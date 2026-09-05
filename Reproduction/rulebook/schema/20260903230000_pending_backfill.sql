-- 0002  pending goes back to the backfill  (login, 2026-09-03 23:5x)
--
-- "pending should go back to the backfill so if it is up to date and that lane is running, it should be constantly
-- checking so a pending is automatically filled the moment it becomes absent or the moment it gets a path."
--
-- claim() now takes pendings FIRST - the ones checked longest ago, once their last check is older than
-- pending_age - and fills the rest of the slice with empties.  While the backfill still has empties, pendings
-- ride ahead of it every pending_age; once the lane is up to date every claim is pendings, cycling through them
-- oldest-checked first, so a scan that appears is recorded on the next pass and a document that ages past the
-- window becomes absent on the next pass.  The pending indexes now carry updated_at (the re-check clock) instead
-- of doc_id; the touch trigger bumps updated_at on every land, including a pending landed as pending again.
--
-- documentation claims only rows whose registry is an object: without the recorded details a document cannot be
-- placed (borough, year, month) or judged fresh, so it waits for registration without spending a request.

drop index reproduction.acris_registration_pending;
drop index reproduction.acris_documentation_pending;
drop index reproduction.richmond_registration_pending;
drop index reproduction.richmond_documentation_pending;
create index acris_registration_pending     on reproduction.acris    (updated_at) where registry = '"pending"'::jsonb;
create index acris_documentation_pending    on reproduction.acris    (updated_at) where document = 'pending';
create index richmond_registration_pending  on reproduction.richmond (updated_at) where registry = '"pending"'::jsonb;
create index richmond_documentation_pending on reproduction.richmond (updated_at) where document = 'pending';

create or replace function reproduction.claim(
  p_source text, p_lane text, p_host text,
  p_n integer default 500, p_ttl interval default interval '20 minutes', p_pending_age interval default interval '1 hour')
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

  execute format('delete from reproduction.%I where lane = $1 and until < now()', claims) using p_lane;

  -- 1. pendings due for a re-check, the longest-waiting first
  for r in execute format($q$
      with take as (
        select w.doc_id
        from reproduction.%1$I w
        where w.%2$I = %4$s
          and w.updated_at < now() - $5
          %5$s
          and not exists (select 1 from reproduction.%3$I c where c.doc_id = w.doc_id and c.lane = $1)
        order by w.updated_at
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
    using p_lane, p_host, p_n, p_ttl, p_pending_age
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
comment on function reproduction.claim is 'take a slice of the to-do list for one lane on one workstation: atomic, no overlap between workstations; pendings due for a re-check first (longest-waiting first), then empties; expired claims released first; documentation only takes rows with a registry object';
