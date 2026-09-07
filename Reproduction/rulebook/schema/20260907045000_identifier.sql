-- 0015 (GATE 5, 2026-09-07 04:5x: login's rule 'if it blocks, move to gate 5' - the seventeenth notice at 04:41, the lane parked) THE IDENTIFIER: doc_id -> identifier.
-- login 2026-09-06 20:12: gate 5 = the One Touch cleanup + "the doc_id -> identifier rename ... lanes paused 2-3 h".
-- The word `doc_id` is ACRIS's; the column holds every source's document identifier (richmond's too), and the vocabulary
-- of the process (README: identifier, registry, source) already says identifier.  A column rename is metadata in
-- Postgres: the primary keys (acris_pkey, richmond_pkey, claims_pkey) and the twelve indexes follow it by themselves.
-- What must be re-stated by hand is everything that names the column in TEXT: the four field/parcel views (a view's
-- output column cannot be renamed in place - dropped and re-created), and the two functions whose bodies build SQL
-- from the name (claim, land - the live bodies of 2026-09-07, rewritten word for word with `identifier`).  heartbeat,
-- us_date, us_money, whole_number never name it.  Applied migrations 0001-0014 stay as written (history).
-- Code in the same commit: cloud.py (claim rows, the land payload key, registries, insert_ids), the boards, test_schema.py,
-- the lanes' SQL strings, Population.py, README + Rulebook vocabulary.  Python parameter names may keep `doc_id` for now.

-- 1. the columns (pkeys and indexes follow)
alter table reproduction.acris    rename column doc_id to identifier;
alter table reproduction.richmond rename column doc_id to identifier;
alter table machinery.claims      rename column doc_id to identifier;

-- 2. the views: dropped and re-created (their first column is renamed)
drop view if exists reproduction.acris_fields;
drop view if exists reproduction.acris_parcels;
drop view if exists reproduction.richmond_fields;
drop view if exists reproduction.richmond_parcels;

create view reproduction.acris_fields as
  select identifier,
         registry ->> 'type' as type,
         registry ->> 'borough' as borough,
         reproduction.us_date(registry ->> 'recorded') as recorded,
         reproduction.us_date(registry ->> 'doc_date') as doc_date,
         reproduction.whole_number(registry ->> 'pages') as pages,
         reproduction.us_money(registry ->> 'amount') as amount,
         registry ->> 'crfn' as crfn,
         registry ->> 'reel_page' as reel_page,
         registry ->> 'remarks' as remarks,
         registry -> 'parcels' as parcels,
         registry -> 'parties' as parties,
         document
  from reproduction.acris;

create view reproduction.acris_parcels as
  select a.identifier,
         p.value ->> 'bbl' as bbl,
         case substr(p.value ->> 'bbl', 1, 1)
           when '1' then 'MANHATTAN' when '2' then 'BRONX' when '3' then 'BROOKLYN'
           when '4' then 'QUEENS' when '5' then 'STATEN ISLAND' else null end as borough,
         substr(p.value ->> 'bbl', 2, 5) as block,
         substr(p.value ->> 'bbl', 7, 4) as lot,
         p.value ->> 'unit' as unit,
         p.value ->> 'address' as address,
         p.value ->> 'use' as use,
         p.value ->> 'partial' as partial
  from reproduction.acris a,
       lateral jsonb_array_elements(case when jsonb_typeof(a.registry -> 'parcels') = 'array' then a.registry -> 'parcels' else '[]'::jsonb end) p(value);

create view reproduction.richmond_fields as
  select identifier,
         registry ->> 'doc_type' as doc_type,
         reproduction.us_date(registry ->> 'recorded') as recorded,
         registry ->> 'book' as book,
         registry ->> 'page' as page,
         registry ->> 'instrument' as instrument,
         reproduction.us_money(registry ->> 'amount') as amount,
         registry ->> 'status' as status,
         registry -> 'parcels' as parcels,
         registry -> 'parties' as parties,
         document
  from reproduction.richmond;

create view reproduction.richmond_parcels as
  select r.identifier,
         p.value ->> 'bbl' as bbl,
         'STATEN ISLAND' as borough,
         substr(p.value ->> 'bbl', 2, 5) as block,
         substr(p.value ->> 'bbl', 7, 4) as lot
  from reproduction.richmond r,
       lateral jsonb_array_elements(case when jsonb_typeof(r.registry -> 'parcels') = 'array' then r.registry -> 'parcels' else '[]'::jsonb end) p(value);

-- 3. claim(): the live body of 2026-09-07 with `identifier` (the live defaults kept: 500 rows, a 20-minute claim - a replace may not drop a default)
create or replace function reproduction.claim(p_source text, p_lane text, p_host text, p_n integer default 500, p_ttl interval default '20 minutes')
returns setof text language plpgsql as $f$
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
    due := due || ' or (jsonb_typeof(w.registry) = ''object'' and reproduction.us_date(w.registry->>''recorded'') is null and w.identifier >= to_char(now() - interval ''400 days'', ''YYYYMMDD'') and w.identifier < ''3'')';
  end if;

  -- expired claims - a dead workstation's, or a cooldown that has run out - go back on the list
  delete from machinery.claims where source = p_source and lane = p_lane and until < now();

  -- 1. due for a re-check: not held (in flight or cooling), in id order
  for r in execute format($q$
      with take as (
        select w.identifier
        from reproduction.%1$I w
        where (%2$s)
          %3$s
          and not exists (select 1 from machinery.claims c where c.source = $5 and c.identifier = w.identifier and c.lane = $1)
        order by w.identifier
        limit $3
        for update of w skip locked
      ), ins as (
        insert into machinery.claims (source, identifier, lane, workstation, until)
        select $5, identifier, $1, $2, now() + $4 from take
        on conflict (source, identifier, lane) do nothing
        returning identifier
      )
      select identifier from ins
    $q$, p_source, due, need)
    using p_lane, p_host, p_n, p_ttl, p_source
  loop
    got := got + 1;
    return next r.identifier;
  end loop;

  -- 2. the backfill: empties, in identifier order straight off the *_empty index
  if got < p_n then
    for r in execute format($q$
        with take as (
          select w.identifier
          from reproduction.%1$I w
          where w.%2$I is null
            %3$s
            and not exists (select 1 from machinery.claims c where c.source = $5 and c.identifier = w.identifier and c.lane = $1)
          order by w.identifier
          limit $3
          for update of w skip locked
        ), ins as (
          insert into machinery.claims (source, identifier, lane, workstation, until)
          select $5, identifier, $1, $2, now() + $4 from take
          on conflict (source, identifier, lane) do nothing
          returning identifier
        )
        select identifier from ins
      $q$, p_source, cell, need)
      using p_lane, p_host, p_n - got, p_ttl, p_source
    loop
      return next r.identifier;
    end loop;
  end if;
  return;
end
$f$;
comment on function reproduction.claim is 'take a slice of the to-do list for one lane on one workstation: atomic, no overlap between machines; due re-checks first (pendings whose cooldown ran out; for registration also the provisional registries - an object without a recorded date on a modern id), then empties, both in identifier order; expired claims released first; documentation only takes rows with a registry object';

-- 4. land(): the live body of 2026-09-07 with `identifier` (the live default kept: a one-hour cooldown); the payload rows read {"identifier": ..., "value": ...}
create or replace function reproduction.land(p_source text, p_lane text, p_host text, p_rows jsonb, p_pending_age interval default '1 hour')
returns integer language plpgsql as $f$
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
      join jsonb_to_recordset($1) as r(identifier text) on r.identifier = w.identifier
    $q$, p_source, cell, other)
    into newly, completes
    using p_rows;

  execute format('update reproduction.%1$I w set %2$I = r.value from jsonb_to_recordset($1) as r(identifier text, value %3$s) where w.identifier = r.identifier', p_source, cell, vtype)
    using p_rows;
  get diagnostics n = row_count;

  -- the claims: a filled cell releases its row; a pending - or a provisional registry - cools down
  execute format($q$
      delete from machinery.claims c using jsonb_to_recordset($1) as r(identifier text, value %1$s)
      where c.source = $4 and c.identifier = r.identifier and c.lane = $2 and c.workstation = $3 and not (%2$s)
    $q$, vtype, cools)
    using p_rows, p_lane, p_host, p_source;
  execute format($q$
      insert into machinery.claims as c (source, identifier, lane, workstation, until)
      select $5, r.identifier, $2, $3, now() + $4 from jsonb_to_recordset($1) as r(identifier text, value %1$s)
      where (%2$s)
      on conflict (source, identifier, lane) do update set workstation = excluded.workstation, until = excluded.until
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
end
$f$;
comment on function reproduction.land is 'fill a batch of cells for one lane from one workstation; a filled cell releases its claim; a pending - or a registry landed without a recorded date (provisional) - keeps it as a cooldown for pending_age; the lane''s row and the workstation''s own row move by what was new, the phase row by rows completed; the cell rule constraints reject any wrong value';

-- 5. the proof after applying (test_schema.py, rewritten for identifier): claim -> land -> the cell, the claim released,
--    the updates rows moved; the four views select; \d shows the pkeys and indexes on identifier.
