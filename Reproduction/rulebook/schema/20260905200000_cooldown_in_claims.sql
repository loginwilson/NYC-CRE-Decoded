-- 0004  the re-check clock leaves the table  (login, 2026-09-05 18:4x)
--
-- "Does it have to be there? Makes the table less clean. I get it for the pending aspect, but can't the pending just
-- be in code by running the status against registry/document date of recording?"
--
-- The table holds what the process produced - source, doc_id, registry, document - and nothing about when.  The
-- wait a pending needs before its next check is a CLAIM: land() writes a pending's claim forward to now() + pending_age
-- instead of deleting it (the row stays held, by the cooldown, in the host's name), and claim() takes the pendings
-- whose claim is gone - due pendings first, in id order off the pending index, then empties as before.  Expired
-- claims are released at the start of every claim() as before, so a cooldown ends the way a dead workstation's
-- claim ends.  The claims table is the schema's only clock and holds only rows in flight or cooling; the 24M-row
-- tables carry no timestamp.
--
-- claim() loses its sixth argument (pending_age); land() gains a fifth (pending_age, default 1 hour).  Both lanes'
-- code changes in the same commit (cloud.py, lane.py, the richmond registration's todo()).

drop trigger acris_touch on reproduction.acris;
drop trigger richmond_touch on reproduction.richmond;
drop function reproduction.touch();

drop index reproduction.acris_registration_pending;
drop index reproduction.acris_documentation_pending;
drop index reproduction.richmond_registration_pending;
drop index reproduction.richmond_documentation_pending;

alter table reproduction.acris    drop column updated_at;
alter table reproduction.richmond drop column updated_at;

create index acris_registration_pending     on reproduction.acris    (doc_id) where registry = '"pending"'::jsonb;
create index acris_documentation_pending    on reproduction.acris    (doc_id) where document = 'pending';
create index richmond_registration_pending  on reproduction.richmond (doc_id) where registry = '"pending"'::jsonb;
create index richmond_documentation_pending on reproduction.richmond (doc_id) where document = 'pending';

comment on table reproduction.acris_claims    is 'rows held: in flight (which workstation holds which document for which lane, until when) or cooling (a pending, held in the name of the host that last checked it, until its next check is due); expired rows go back on the list at the next claim()';
comment on table reproduction.richmond_claims is 'rows held for richmond; see acris_claims';

-- claim(source, lane, host, n, ttl) -> the doc_ids now held by this host.
drop function reproduction.claim(text, text, text, integer, interval, interval);
create function reproduction.claim(
  p_source text, p_lane text, p_host text,
  p_n integer default 500, p_ttl interval default interval '20 minutes')
returns setof text
language plpgsql as $$
declare
  cell   text;
  claims text := p_source || '_claims';
  pend   text;
  need   text := '';
  got    integer := 0;
  r      record;
begin
  if p_source not in ('acris', 'richmond') then
    raise exception 'claim: unknown source %', p_source;
  end if;
  cell := case p_lane when 'registration' then 'registry' when 'documentation' then 'document' end;
  if cell is null then
    raise exception 'claim: unknown lane %', p_lane;
  end if;
  pend := case when cell = 'registry' then '''"pending"''::jsonb' else '''pending''' end;
  if p_lane = 'documentation' then
    need := 'and jsonb_typeof(w.registry) = ''object''';
  end if;

  -- expired claims - a dead workstation's, or a cooldown that has run out - go back on the list
  execute format('delete from reproduction.%I where lane = $1 and until < now()', claims) using p_lane;

  -- 1. pendings due for a re-check: not held (in flight or cooling), in id order off the *_pending index
  for r in execute format($q$
      with take as (
        select w.doc_id
        from reproduction.%1$I w
        where w.%2$I = %4$s
          %5$s
          and not exists (select 1 from reproduction.%3$I c where c.doc_id = w.doc_id and c.lane = $1)
        order by w.doc_id
        limit $3
        for update of w skip locked
      ), ins as (
        insert into reproduction.%3$I (doc_id, lane, host, until)
        select doc_id, $1, $2, now() + $4 from take
        on conflict (doc_id, lane) do nothing
        returning doc_id
      )
      select doc_id from ins
    $q$, p_source, cell, claims, pend, need)
    using p_lane, p_host, p_n, p_ttl
  loop
    got := got + 1;
    return next r.doc_id;
  end loop;

  -- 2. the backfill: empties, in doc_id order straight off the *_empty index
  if got < p_n then
    for r in execute format($q$
        with take as (
          select w.doc_id
          from reproduction.%1$I w
          where w.%2$I is null
            %4$s
            and not exists (select 1 from reproduction.%3$I c where c.doc_id = w.doc_id and c.lane = $1)
          order by w.doc_id
          limit $3
          for update of w skip locked
        ), ins as (
          insert into reproduction.%3$I (doc_id, lane, host, until)
          select doc_id, $1, $2, now() + $4 from take
          on conflict (doc_id, lane) do nothing
          returning doc_id
        )
        select doc_id from ins
      $q$, p_source, cell, claims, need)
      using p_lane, p_host, p_n - got, p_ttl
    loop
      return next r.doc_id;
    end loop;
  end if;
  return;
end $$;
comment on function reproduction.claim is 'take a slice of the to-do list for one lane on one workstation: atomic, no overlap between workstations; pendings whose cooldown has run out first, then empties, both in id order; expired claims released first; documentation only takes rows with a registry object';

-- land(source, lane, host, rows, pending_age) -> cells written.
-- A landed path / object / absent releases the row's claim; a landed pending keeps it as a cooldown until
-- now() + pending_age, in the landing host's name (written whether or not the host held a claim).
drop function reproduction.land(text, text, text, jsonb);
create function reproduction.land(p_source text, p_lane text, p_host text, p_rows jsonb, p_pending_age interval default interval '1 hour')
returns integer
language plpgsql as $$
declare
  cell      text;
  other     text;
  vtype     text;
  pend      text;
  claims    text := p_source || '_claims';
  n         integer;
  newly     bigint;
  completes bigint;
begin
  if p_source not in ('acris', 'richmond') then
    raise exception 'land: unknown source %', p_source;
  end if;
  cell  := case p_lane when 'registration' then 'registry' when 'documentation' then 'document' end;
  other := case p_lane when 'registration' then 'document' when 'documentation' then 'registry' end;
  if cell is null then
    raise exception 'land: unknown lane %', p_lane;
  end if;
  vtype := case when cell = 'registry' then 'jsonb' else 'text' end;
  pend  := case when cell = 'registry' then '''"pending"''::jsonb' else '''pending''' end;

  execute format($q$
      select count(*) filter (where w.%2$I is null),
             count(*) filter (where w.%2$I is null and w.%3$I is not null)
      from reproduction.%1$I w
      join jsonb_to_recordset($1) as r(doc_id text) on r.doc_id = w.doc_id
    $q$, p_source, cell, other)
    into newly, completes
    using p_rows;

  execute format('update reproduction.%1$I w set %2$I = r.value from jsonb_to_recordset($1) as r(doc_id text, value %3$s) where w.doc_id = r.doc_id', p_source, cell, vtype)
    using p_rows;
  get diagnostics n = row_count;

  -- the claims: a filled cell releases its row; a pending cools down
  execute format($q$
      delete from reproduction.%1$I c using jsonb_to_recordset($1) as r(doc_id text, value %2$s)
      where c.doc_id = r.doc_id and c.lane = $2 and c.host = $3 and r.value is distinct from %3$s
    $q$, claims, vtype, pend)
    using p_rows, p_lane, p_host;
  execute format($q$
      insert into reproduction.%1$I as c (doc_id, lane, host, until)
      select r.doc_id, $2, $3, now() + $4 from jsonb_to_recordset($1) as r(doc_id text, value %2$s)
      where r.value = %3$s
      on conflict (doc_id, lane) do update set host = excluded.host, until = excluded.until
    $q$, claims, vtype, pend)
    using p_rows, p_lane, p_host, p_pending_age;

  if newly > 0 then
    execute format('update reproduction.%1$I set landed = landed + $1 where lane = $2', p_source || '_update_lanes') using newly, p_lane;
  end if;
  if completes > 0 then
    execute format('update reproduction.%1$I set landed = landed + $1', p_source || '_update') using completes;
  end if;
  return n;
end $$;
comment on function reproduction.land is 'fill a batch of cells for one lane from one workstation; a filled cell releases its claim, a pending keeps it as a cooldown for pending_age; the counters move by what was new; the cell rule constraints reject any wrong value';
