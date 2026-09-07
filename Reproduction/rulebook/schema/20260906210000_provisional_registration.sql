-- 0009 THE PROVISIONAL REGISTRATION (login 2026-09-06 20:4x: "if something is filed and has a CRFN and it doesn't have a
-- recording yet, we catch it ... make sure we're not missing the recording date because we're working ahead").
--
-- ACRIS issues a document id and a CRFN when a document is indexed and records it later; the detail page shows
-- "RECORDED / FILED: N/A" until then and the parser keeps no `recorded` key (never a made-up date).  A registration taken
-- before recording is PROVISIONAL.  8,876 acris registries stood without a recorded date on 2026-09-06 (ids 2025-10-29 ..
-- 2026-08-19, the old lane's), most of them recorded since - the city's index lists them with dates.
--
-- The rule, the same shape as a pending document:
--   claim()  for registration offers, before the empties, every registry that is an object WITHOUT a readable recorded
--            date whose id is younger than 400 days (the id's first eight digits are its date; ACRIS records within that -
--            older and still undated stays as filed, the registration's `absent`), not held; off the *_recorded index (its
--            null entries) and the primary key
--   land()   a registry landed WITHOUT a readable recorded date keeps its claim as a COOLDOWN for pending_age (the lane's
--            --pending-age; a day for a batch that levels), exactly as a landed 'pending' does; a registry with a recorded
--            date releases the claim.  The counters do not move for a registry over a registry (as before).
-- One transaction; the two functions replaced; nothing else touched.
create or replace function reproduction.claim(
  p_source text, p_lane text, p_host text,
  p_n integer default 500, p_ttl interval default interval '20 minutes')
returns setof text
language plpgsql as $$
declare
  cell   text;
  pend   text;
  need   text := '';
  due    text;
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
  -- what is due for a re-check: the pendings; and, for registration, the PROVISIONAL registries - an object without a
  -- readable recorded date on a modern id (the *_recorded index answers "is null")
  due := format('w.%I = %s', cell, pend);
  if p_lane = 'registration' then
    due := due || ' or (jsonb_typeof(w.registry) = ''object'' and reproduction.us_date(w.registry->>''recorded'') is null and w.doc_id >= to_char(now() - interval ''400 days'', ''YYYYMMDD'') and w.doc_id < ''3'')';
  end if;

  -- expired claims - a dead workstation's, or a cooldown that has run out - go back on the list
  delete from machinery.claims where source = p_source and lane = p_lane and until < now();

  -- 1. due for a re-check: not held (in flight or cooling), in id order
  for r in execute format($q$
      with take as (
        select w.doc_id
        from reproduction.%1$I w
        where (%2$s)
          %3$s
          and not exists (select 1 from machinery.claims c where c.source = $5 and c.doc_id = w.doc_id and c.lane = $1)
        order by w.doc_id
        limit $3
        for update of w skip locked
      ), ins as (
        insert into machinery.claims (source, doc_id, lane, workstation, until)
        select $5, doc_id, $1, $2, now() + $4 from take
        on conflict (source, doc_id, lane) do nothing
        returning doc_id
      )
      select doc_id from ins
    $q$, p_source, due, need)
    using p_lane, p_host, p_n, p_ttl, p_source
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
            %3$s
            and not exists (select 1 from machinery.claims c where c.source = $5 and c.doc_id = w.doc_id and c.lane = $1)
          order by w.doc_id
          limit $3
          for update of w skip locked
        ), ins as (
          insert into machinery.claims (source, doc_id, lane, workstation, until)
          select $5, doc_id, $1, $2, now() + $4 from take
          on conflict (source, doc_id, lane) do nothing
          returning doc_id
        )
        select doc_id from ins
      $q$, p_source, cell, need)
      using p_lane, p_host, p_n - got, p_ttl, p_source
    loop
      return next r.doc_id;
    end loop;
  end if;
  return;
end $$;
comment on function reproduction.claim is 'take a slice of the to-do list for one lane on one workstation: atomic, no overlap between machines; due re-checks first (pendings whose cooldown ran out; for registration also the provisional registries - an object without a recorded date on a modern id), then empties, both in id order; expired claims released first; documentation only takes rows with a registry object';

create or replace function reproduction.land(p_source text, p_lane text, p_host text, p_rows jsonb, p_pending_age interval default interval '1 hour')
returns integer
language plpgsql as $$
declare
  cell      text;
  other     text;
  vtype     text;
  pend      text;
  cools     text;
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
  -- what keeps its claim as a cooldown: a pending; and, for registration, a provisional registry (an object without a
  -- readable recorded date)
  cools := format('r.value = %s', pend);
  if p_lane = 'registration' then
    cools := cools || ' or (jsonb_typeof(r.value) = ''object'' and reproduction.us_date(r.value->>''recorded'') is null)';
  end if;

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

  -- the claims: a filled cell releases its row; a pending - or a provisional registry - cools down
  execute format($q$
      delete from machinery.claims c using jsonb_to_recordset($1) as r(doc_id text, value %1$s)
      where c.source = $4 and c.doc_id = r.doc_id and c.lane = $2 and c.workstation = $3 and not (%2$s)
    $q$, vtype, cools)
    using p_rows, p_lane, p_host, p_source;
  execute format($q$
      insert into machinery.claims as c (source, doc_id, lane, workstation, until)
      select $5, r.doc_id, $2, $3, now() + $4 from jsonb_to_recordset($1) as r(doc_id text, value %1$s)
      where (%2$s)
      on conflict (source, doc_id, lane) do update set workstation = excluded.workstation, until = excluded.until
    $q$, vtype, cools)
    using p_rows, p_lane, p_host, p_pending_age, p_source;

  if newly > 0 then
    update reproduction.updates set landed = landed + newly where source = p_source and lane = p_lane and workstation = '';
    insert into reproduction.updates as u (source, lane, workstation, landed) values (p_source, p_lane, p_host, newly)
      on conflict (source, lane, workstation) do update set landed = u.landed + excluded.landed;
  end if;
  if completes > 0 then
    update reproduction.updates set landed = landed + completes where source = p_source and lane = 'reproduction' and workstation = '';
  end if;
  return n;
end $$;
comment on function reproduction.land is 'fill a batch of cells for one lane from one workstation; a filled cell releases its claim; a pending - or a registry landed without a recorded date (provisional) - keeps it as a cooldown for pending_age; the lane''s row and the workstation''s own row move by what was new, the phase row by rows completed; the cell rule constraints reject any wrong value';
