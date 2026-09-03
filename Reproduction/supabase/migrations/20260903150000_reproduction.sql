-- 0001  reproduction  (dictated by login, 2026-09-03; see Reproduction/SCHEMA.md)
--
-- Supabase gives one level of folder above tables, so: the PHASE is the schema and the SOURCE is in the
-- table name.  Per source, the things the lanes feed and the board reads:
--   <source>              "<source> reproduction"   one row per document: doc_id | registry | document
--   <source>_update       "<source> updates" tab 1  the whole phase: rows complete against rows, rates, eta, status
--   <source>_update_lanes "<source> updates" tab 2  one row per lane: that lane's cells landed against rows
--   <source>_claims       rows in flight: which workstation holds which document for which lane, until when
--   <source>_heartbeats   one row per running lane per workstation: width, last sign of life, last word
-- Enumeration has NO table: it counts the source and compares with count(*) here; the difference must be 0.
--
-- THE CELL RULE: each lane fills its own cell and leaves nothing else.  synchronization fills doc_id.
-- registration fills registry (the recorded details as a JSON object) or, when the source has none, the
-- verdict word for it.  documentation fills document (the FULL One Touch path, pasteable into the file bar)
-- or the verdict word: pending (recorded in the last days, not yet served; it stays in the backfill until it
-- becomes a path or absent), absent (checked: there is none).  Two words, nothing else.  No URL columns
-- anywhere: every URL is minted by the code from the doc_id stem.  Anything but empty counts as landed.
--
-- THE STATUS RULE (login): the board's status follows the LANE.  active = heartbeat fresh and landed rising ·
-- pending = no fresh heartbeat and not complete (the lane is paused or parked by a person) · stalled = the
-- lane's last word is a refusal (fully rejected) · complete = landed equals needed.  A fetch error is never a
-- stop; only the notice page is.
--
-- THE COUNTING RULE (speed): the board never counts 21.6M rows once a minute.  land() adds what it landed to
-- the lane's and the phase's `landed` as it lands (exact, a few rows per minute); reconcile() recounts from the
-- partial indexes on demand (hourly, and after every load) and overwrites, so the counters can never drift for
-- long.  The 60-second and 5-minute rates are the board's subtraction of `landed` between its own ticks.
--
-- The path is always labelled as the One Touch (D:\...).  A second workstation mounts its drive under the same
-- letter, writes the same layout and records the same label; when its files are transferred, nothing here changes.
--
-- doc_id carries COLLATE "C": byte order, so index order is id order, comparisons are cheapest, and range seeks
-- such as doc_id >= '2017' and doc_id < '2018' walk the primary key directly.

create schema if not exists reproduction;

create type reproduction.lane_status as enum ('active', 'pending', 'stalled', 'complete');

create or replace function reproduction.touch() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- ───────────────────────────────────────────────────────────────────────────── acris

create table reproduction.acris (
  doc_id      text        collate "C" primary key,
  registry    jsonb,
  document    text,
  updated_at  timestamptz not null default now(),
  constraint acris_registry_cell check (
    registry is null
    or jsonb_typeof(registry) = 'object'
    or registry <@ '["pending", "absent"]'::jsonb
  ),
  constraint acris_document_cell check (
    document is null
    or document in ('pending', 'absent')
    or starts_with(document, 'D:\')
  )
);
comment on table  reproduction.acris            is 'acris reproduction: one row per document; each lane fills its own cell';
comment on column reproduction.acris.doc_id     is 'filled by synchronization (the ACRIS document id; every URL is minted from it)';
comment on column reproduction.acris.registry   is 'filled by registration: the recorded details as a JSON object, or the verdict word when the source has none: pending | absent';
comment on column reproduction.acris.document   is 'filled by documentation: the full One Touch path of the saved document, or the verdict word: pending (still being checked, stays in the backfill) | absent (checked: there is none)';
comment on column reproduction.acris.updated_at is 'touched on every change of the row (any cell); the pending recheck age is measured from it';

-- the to-do list, as four small partial indexes: a claim takes empties first (index order = doc_id order,
-- no sort), then aged pendings; reconcile() counts the same four indexes
create index acris_registration_empty    on reproduction.acris (doc_id) where registry is null;
create index acris_registration_pending  on reproduction.acris (doc_id) where registry = '"pending"'::jsonb;
create index acris_documentation_empty   on reproduction.acris (doc_id) where document is null;
create index acris_documentation_pending on reproduction.acris (doc_id) where document = 'pending';
create trigger acris_touch before update on reproduction.acris for each row execute function reproduction.touch();

create table reproduction.acris_update (
  phase         text primary key default 'reproduction' check (phase = 'reproduction'),
  landed        bigint not null default 0,
  needed        bigint not null default 0,
  pct           numeric(6, 2),
  rate_60s      numeric(9, 2),
  increase_60s  bigint,
  pct_60s       numeric(9, 4),
  eta_60s       text,
  rate_5m       numeric(9, 2),
  increase_5m   bigint,
  pct_5m        numeric(9, 4),
  eta_5m        text,
  status        reproduction.lane_status,
  as_of         timestamptz
);
comment on table  reproduction.acris_update        is 'acris updates, tab 1: the whole phase - rows complete (all three cells filled) against rows, 60 s and 5 min rates, eta, status, as of';
comment on column reproduction.acris_update.landed is 'rows with all three cells filled; kept current by land(), recounted by reconcile()';
comment on column reproduction.acris_update.needed is 'rows in the table; recounted by reconcile()';

create table reproduction.acris_update_lanes (
  lane          text primary key check (lane in ('synchronization', 'registration', 'documentation')),
  landed        bigint not null default 0,
  needed        bigint not null default 0,
  pct           numeric(6, 2),
  rate_60s      numeric(9, 2),
  increase_60s  bigint,
  pct_60s       numeric(9, 4),
  eta_60s       text,
  rate_5m       numeric(9, 2),
  increase_5m   bigint,
  pct_5m        numeric(9, 4),
  eta_5m        text,
  status        reproduction.lane_status,
  as_of         timestamptz,
  hosts         text,
  width         integer,
  heartbeat_at  timestamptz,
  last_event    text
);
comment on table  reproduction.acris_update_lanes              is 'acris updates, tab 2: one row per lane - that lane''s cells landed (anything but empty) against rows, rates, eta, status, as of; the last four columns are folded from acris_heartbeats';
comment on column reproduction.acris_update_lanes.landed       is 'cells of this lane that are not empty; kept current by land(), recounted by reconcile()';
comment on column reproduction.acris_update_lanes.hosts        is 'the workstations running the lane, e.g. LOGINSURFACE:40, MAC-1:40 (folded from the heartbeats)';
comment on column reproduction.acris_update_lanes.width        is 'workers across all workstations on this lane';
comment on column reproduction.acris_update_lanes.heartbeat_at is 'the freshest heartbeat on this lane; stale = paused or parked';
comment on column reproduction.acris_update_lanes.last_event   is 'the latest last word on this lane: a refusal (REFUSED at <id>), a hang-up, a park by a person';

insert into reproduction.acris_update (phase) values ('reproduction');
insert into reproduction.acris_update_lanes (lane) values ('synchronization'), ('registration'), ('documentation');

-- ───────────────────────────────────────────────────────────────────────────── richmond

create table reproduction.richmond (
  doc_id      text        collate "C" primary key,
  registry    jsonb,
  document    text,
  updated_at  timestamptz not null default now(),
  constraint richmond_registry_cell check (
    registry is null
    or jsonb_typeof(registry) = 'object'
    or registry <@ '["pending", "absent"]'::jsonb
  ),
  constraint richmond_document_cell check (
    document is null
    or document in ('pending', 'absent')
    or starts_with(document, 'D:\')
  )
);
comment on table  reproduction.richmond            is 'richmond reproduction: one row per document; each lane fills its own cell';
comment on column reproduction.richmond.doc_id     is 'filled by synchronization (the Richmond County internal id; every URL is minted from it)';
comment on column reproduction.richmond.registry   is 'filled by registration: the recorded details as a JSON object, or the verdict word when the source has none: pending | absent';
comment on column reproduction.richmond.document   is 'filled by documentation: the full One Touch path of the saved document, or the verdict word: pending (still being checked, stays in the backfill) | absent (checked: there is none)';

create index richmond_registration_empty    on reproduction.richmond (doc_id) where registry is null;
create index richmond_registration_pending  on reproduction.richmond (doc_id) where registry = '"pending"'::jsonb;
create index richmond_documentation_empty   on reproduction.richmond (doc_id) where document is null;
create index richmond_documentation_pending on reproduction.richmond (doc_id) where document = 'pending';
create trigger richmond_touch before update on reproduction.richmond for each row execute function reproduction.touch();

create table reproduction.richmond_update (like reproduction.acris_update including all);
comment on table reproduction.richmond_update is 'richmond updates, tab 1: the whole phase';
create table reproduction.richmond_update_lanes (like reproduction.acris_update_lanes including all);
comment on table reproduction.richmond_update_lanes is 'richmond updates, tab 2: one row per lane';

insert into reproduction.richmond_update (phase) values ('reproduction');
insert into reproduction.richmond_update_lanes (lane) values ('synchronization'), ('registration'), ('documentation');

-- ───────────────────────────────────────────────────────────────────────────── cooperation between workstations
--
-- login 2026-09-03: "what do we do to assure there's no overlap in what they're pulling?"  The table is the ONLY
-- to-do list.  A lane never picks its own work: it calls claim(), which hands out a slice of empty cells with the
-- workstation's name and an expiry written on it, atomically, skipping anything another workstation holds
-- (FOR UPDATE SKIP LOCKED + the claims key).  Two machines asking in the same second get two different slices.
-- The lane fills the cells with land() in batches, which also drops the claims and moves the counters; a
-- machine that dies leaves claims that expire and go back on the list.  Each running lane writes heartbeat()
-- once a minute; the update program folds the heartbeats into the lane row (hosts, width, freshest, last word).

create table reproduction.acris_claims (
  doc_id  text        collate "C" not null references reproduction.acris (doc_id) on delete cascade,
  lane    text        not null check (lane in ('registration', 'documentation')),
  host    text        not null,
  until   timestamptz not null,
  primary key (doc_id, lane)
);
create index acris_claims_expiry on reproduction.acris_claims (lane, until);
comment on table reproduction.acris_claims is 'rows in flight: which workstation holds which document for which lane, until when; expired claims go back on the list; rows are deleted as cells land';

create table reproduction.richmond_claims (
  doc_id  text        collate "C" not null references reproduction.richmond (doc_id) on delete cascade,
  lane    text        not null check (lane in ('registration', 'documentation')),
  host    text        not null,
  until   timestamptz not null,
  primary key (doc_id, lane)
);
create index richmond_claims_expiry on reproduction.richmond_claims (lane, until);
comment on table reproduction.richmond_claims is 'rows in flight for richmond; see acris_claims';

create table reproduction.acris_heartbeats (
  lane          text        not null check (lane in ('synchronization', 'registration', 'documentation')),
  host          text        not null,
  width         integer,
  heartbeat_at  timestamptz not null default now(),
  last_event    text,
  primary key (lane, host)
);
comment on table reproduction.acris_heartbeats is 'one row per running lane per workstation: width, last sign of life (every minute), last word; the update program folds these into acris_update_lanes';
create table reproduction.richmond_heartbeats (like reproduction.acris_heartbeats including all);
comment on table reproduction.richmond_heartbeats is 'heartbeats for richmond; see acris_heartbeats';

-- claim(source, lane, host, n, ttl, pending_age) -> the doc_ids now held by this host.
-- Empties first, in doc_id order straight off the *_empty index (no sort); then pendings older than
-- pending_age off the *_pending index.  Expired claims for the lane are released first.  One round trip, atomic:
-- the workflow rows are row-locked for the duration of the call, other callers skip them, and the claims key
-- (doc_id, lane) makes a double claim impossible.
create or replace function reproduction.claim(
  p_source text, p_lane text, p_host text,
  p_n integer default 500, p_ttl interval default interval '20 minutes', p_pending_age interval default interval '1 day')
returns setof text
language plpgsql as $$
declare
  cell   text;
  claims text := p_source || '_claims';
  pend   text;
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

  execute format('delete from reproduction.%I where lane = $1 and until < now()', claims) using p_lane;

  for r in execute format($q$
      with take as (
        select w.doc_id
        from reproduction.%1$I w
        where w.%2$I is null
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
    $q$, p_source, cell, claims)
    using p_lane, p_host, p_n, p_ttl
  loop
    got := got + 1;
    return next r.doc_id;
  end loop;

  if got < p_n then
    for r in execute format($q$
        with take as (
          select w.doc_id
          from reproduction.%1$I w
          where w.%2$I = %4$s
            and w.updated_at < now() - $5
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
      $q$, p_source, cell, claims, pend)
      using p_lane, p_host, p_n - got, p_ttl, p_pending_age
    loop
      return next r.doc_id;
    end loop;
  end if;
  return;
end $$;
comment on function reproduction.claim is 'take a slice of the to-do list for one lane on one workstation: atomic, no overlap between workstations, empties before aged pendings, expired claims released first';

-- land(source, lane, host, rows) -> number of cells written.  rows = [{"doc_id": "...", "value": ...}, ...]
-- value: for documentation a text (the full One Touch path, or "pending" / "absent");
--        for registration a JSON object (the recorded details), or "pending" / "absent".
-- One statement fills the cells (the cell rule rejects any wrong value); this host's claims on them are dropped;
-- the counters move by exactly what was NEW: cells that were empty add to the lane's landed, and rows whose
-- other cell was already filled add to the phase's landed.  A pending that becomes a path or absent was already
-- counted as landed and adds nothing.
create or replace function reproduction.land(p_source text, p_lane text, p_host text, p_rows jsonb)
returns integer
language plpgsql as $$
declare
  cell      text;
  other     text;
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

  execute format($q$
      select count(*) filter (where w.%2$I is null),
             count(*) filter (where w.%2$I is null and w.%3$I is not null)
      from reproduction.%1$I w
      join jsonb_to_recordset($1) as r(doc_id text) on r.doc_id = w.doc_id
    $q$, p_source, cell, other)
    into newly, completes
    using p_rows;

  if cell = 'registry' then
    execute format('update reproduction.%1$I w set registry = r.value from jsonb_to_recordset($1) as r(doc_id text, value jsonb) where w.doc_id = r.doc_id', p_source)
      using p_rows;
  else
    execute format('update reproduction.%1$I w set document = r.value from jsonb_to_recordset($1) as r(doc_id text, value text) where w.doc_id = r.doc_id', p_source)
      using p_rows;
  end if;
  get diagnostics n = row_count;

  execute format('delete from reproduction.%1$I c using jsonb_to_recordset($1) as r(doc_id text) where c.doc_id = r.doc_id and c.lane = $2 and c.host = $3', p_source || '_claims')
    using p_rows, p_lane, p_host;

  if newly > 0 then
    execute format('update reproduction.%1$I set landed = landed + $1 where lane = $2', p_source || '_update_lanes') using newly, p_lane;
  end if;
  if completes > 0 then
    execute format('update reproduction.%1$I set landed = landed + $1', p_source || '_update') using completes;
  end if;
  return n;
end $$;
comment on function reproduction.land is 'fill a batch of cells for one lane from one workstation, release their claims, move the counters by what was new; the cell rule constraints reject any wrong value';

-- heartbeat(source, lane, host, width, last_event) -> the lane's sign of life, once a minute.
create or replace function reproduction.heartbeat(p_source text, p_lane text, p_host text, p_width integer, p_last_event text default null)
returns void
language plpgsql as $$
begin
  if p_source not in ('acris', 'richmond') then
    raise exception 'heartbeat: unknown source %', p_source;
  end if;
  execute format($q$
      insert into reproduction.%1$I as h (lane, host, width, heartbeat_at, last_event)
      values ($1, $2, $3, now(), $4)
      on conflict (lane, host) do update
        set width = excluded.width, heartbeat_at = now(), last_event = coalesce(excluded.last_event, h.last_event)
    $q$, p_source || '_heartbeats')
    using p_lane, p_host, p_width, p_last_event;
end $$;
comment on function reproduction.heartbeat is 'a running lane''s sign of life from one workstation; stale = paused or parked; last_event carries a refusal, a hang-up, a park';

-- reconcile(source) -> recount landed and needed from the table itself and overwrite the counters.
-- Uses the primary key and the four partial indexes only (index-only scans), so it costs seconds on the full
-- table and nothing on the lanes.  The board calls it hourly and after every load; land() keeps the counters
-- current between calls.  Never repairs a number: it measures.
create or replace function reproduction.reconcile(p_source text)
returns table (what text, landed bigint, needed bigint)
language plpgsql as $$
declare
  n_rows   bigint;
  n_reg    bigint;
  n_doc    bigint;
  n_either bigint;
begin
  if p_source not in ('acris', 'richmond') then
    raise exception 'reconcile: unknown source %', p_source;
  end if;
  execute format('select count(*) from reproduction.%I', p_source) into n_rows;
  execute format('select count(*) from reproduction.%I where registry is null', p_source) into n_reg;
  execute format('select count(*) from reproduction.%I where document is null', p_source) into n_doc;
  execute format('select count(*) from reproduction.%I where registry is null or document is null', p_source) into n_either;

  execute format('update reproduction.%I set landed = $1, needed = $2', p_source || '_update') using n_rows - n_either, n_rows;
  execute format('update reproduction.%I set landed = case lane when ''synchronization'' then $1 when ''registration'' then $2 else $3 end, needed = $1', p_source || '_update_lanes')
    using n_rows, n_rows - n_reg, n_rows - n_doc;

  return query select 'phase'::text, n_rows - n_either, n_rows
    union all select 'synchronization', n_rows, n_rows
    union all select 'registration', n_rows - n_reg, n_rows
    union all select 'documentation', n_rows - n_doc, n_rows;
end $$;
comment on function reproduction.reconcile is 'recount landed and needed for the phase and the three lanes from the indexes and overwrite the counters; hourly and after loads';
