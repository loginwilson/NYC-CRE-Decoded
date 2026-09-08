-- THE SCHEMA as it stands, written from the project itself by `python supabase/supabase.py baseline` on 2026-09-08 18:20 ET.
-- Idempotent: a fresh project builds from it (push applies it first); an existing project is unchanged by it.
-- In building order: schemas, the extension, types, functions, tables, views, materialized views, indexes.
-- A change is a numbered <version>_<name>.sql beside this file, applied once with `push`, folded in with `baseline`,
-- and removed in the same commit - so this folder holds one file between changes.

create schema if not exists reproduction;
comment on schema reproduction is 'the record: one table per source, a row per document (source | identifier | registry | document), and the two boards a person opens (acris_update, richmond_update); nothing else belongs here (0016)';
create schema if not exists machinery;
comment on schema machinery is 'the code''s own drawer: what the lanes need to share between workstations and a person never reads';
create schema if not exists reading;
comment on schema reading is 'the reading layer for products: what a document says, spelled out - fields, parcels, keys, profiles; read only, never written by a lane';

create extension if not exists pg_trgm with schema extensions;
set check_function_bodies = off;                 -- a SQL function may name one written after it

do $$ begin create type reproduction.lane_status as enum ('active', 'pending', 'stalled', 'complete'); exception when duplicate_object then null; end $$;
comment on type reproduction.lane_status is 'a board row''s status, computed by the board every minute: active (landed rose in the last window) / pending (not complete, not stalled, nothing landed in the window) / stalled (the lane''s last word is a refusal or a wall) / complete (landed = needed)';

CREATE OR REPLACE FUNCTION reproduction.bbl(borough text, block integer, lot integer)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE PARALLEL SAFE STRICT
AS $function$
  select reproduction.borough_digit(borough) || lpad(block::text, 5, '0') || lpad(lot::text, 4, '0')
$function$;
comment on function reproduction.bbl(borough text, block integer, lot integer) is 'a person''s helper: borough + block + lot as the ten-digit bbl (borough digit, block padded to five, lot padded to four)';

CREATE OR REPLACE FUNCTION reproduction.block_key(borough text, block integer)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE PARALLEL SAFE STRICT
AS $function$
  select reproduction.borough_digit(borough) || '-' || lpad(block::text, 5, '0')
$function$;
comment on function reproduction.block_key(borough text, block integer) is 'a person''s helper: borough + block as the block key block_keys() writes, for a containment filter on acris_blocks / richmond_blocks';

CREATE OR REPLACE FUNCTION reproduction.block_keys(r jsonb)
 RETURNS text[]
 LANGUAGE plpgsql
 IMMUTABLE PARALLEL SAFE STRICT
AS $function$
declare
  keys text[] := '{}';
  p jsonb;
  b text;
begin
  if jsonb_typeof(r->'parcels') <> 'array' then
    return keys;
  end if;
  for p in select * from jsonb_array_elements(r->'parcels') loop
    b := p->>'bbl';
    if b is not null and length(b) = 10 and translate(b, '0123456789', '') = '' then
      keys := array_append(keys, substr(b, 1, 1) || '-' || substr(b, 2, 5));
    end if;
  end loop;
  return keys;
end $function$;
comment on function reproduction.block_keys(r jsonb) is 'a registry''s parcels as block keys, "<borough digit>-<block, five digits>", one per valid ten-digit bbl - the text array behind the GIN indexes acris_blocks and richmond_blocks';

CREATE OR REPLACE FUNCTION reproduction.borough_digit(borough text)
 RETURNS text
 LANGUAGE plpgsql
 IMMUTABLE PARALLEL SAFE STRICT
AS $function$
begin
  return case upper(trim(borough))
    when 'MANHATTAN' then '1' when 'BRONX' then '2' when 'BROOKLYN' then '3' when 'QUEENS' then '4' when 'STATEN ISLAND' then '5'
    when '1' then '1' when '2' then '2' when '3' then '3' when '4' then '4' when '5' then '5' end;
end $function$;
comment on function reproduction.borough_digit(borough text) is 'the borough as ACRIS prints it (MANHATTAN .. STATEN ISLAND, or the digit itself) as its digit 1..5; null otherwise';

CREATE OR REPLACE FUNCTION reproduction.claim(p_source text, p_lane text, p_host text, p_n integer DEFAULT 500, p_ttl interval DEFAULT '00:20:00'::interval)
 RETURNS SETOF text
 LANGUAGE plpgsql
AS $function$
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
$function$;
comment on function reproduction.claim(p_source text, p_lane text, p_host text, p_n integer, p_ttl interval) is 'take a slice of the to-do list for one lane on one workstation: atomic, no overlap between machines; due re-checks first (pendings whose cooldown ran out; for registration also the provisional registries - an object without a recorded date on a modern id), then empties, both in identifier order; expired claims released first; documentation only takes rows with a registry object';

CREATE OR REPLACE FUNCTION reproduction.heartbeat(p_source text, p_lane text, p_host text, p_width integer, p_last_event text DEFAULT NULL::text)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
begin
  if p_source not in ('acris', 'richmond') then
    raise exception 'heartbeat: unknown source %', p_source;
  end if;
  insert into machinery.updates as u (source, lane, workstation, workers, last_seen, last_word)
  values (p_source, p_lane, p_host, p_width, now(), p_last_event)
  on conflict (source, lane, workstation) do update
    set workers = excluded.workers, last_seen = now(), last_word = coalesce(excluded.last_word, u.last_word);
end $function$;
comment on function reproduction.heartbeat(p_source text, p_lane text, p_host text, p_width integer, p_last_event text) is 'a running lane''s sign of life from one workstation, on that machine''s own updates row; stale = paused or parked; last_word carries a refusal, a hang-up, a park';

CREATE OR REPLACE FUNCTION reproduction.land(p_source text, p_lane text, p_host text, p_rows jsonb, p_pending_age interval DEFAULT '01:00:00'::interval)
 RETURNS integer
 LANGUAGE plpgsql
AS $function$
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
    update machinery.updates set landed = landed + newly where source = p_source and lane = p_lane and workstation = '';
    insert into machinery.updates as u (source, lane, workstation, landed) values (p_source, p_lane, p_host, newly)
      on conflict (source, lane, workstation) do update set landed = u.landed + excluded.landed;
  end if;
  if completes > 0 then
    update machinery.updates set landed = landed + completes where source = p_source and lane = 'reproduction' and workstation = '';
    insert into machinery.updates as u (source, lane, workstation, landed) values (p_source, 'reproduction', p_host, completes)
      on conflict (source, lane, workstation) do update set landed = u.landed + excluded.landed;
  end if;
  return n;
end
$function$;
comment on function reproduction.land(p_source text, p_lane text, p_host text, p_rows jsonb, p_pending_age interval) is 'a lane''s landing: the cells in one statement, the claims released (a pending keeps its claim for p_pending_age), the counters credited - the lane''s total and this workstation''s, and a completion (every cell filled) to the reproduction rows of both';

CREATE OR REPLACE FUNCTION reproduction.parcel(borough text, block integer, lot integer)
 RETURNS jsonb
 LANGUAGE sql
 IMMUTABLE PARALLEL SAFE STRICT
AS $function$
  select jsonb_build_object('parcels', jsonb_build_array(jsonb_build_object('bbl', reproduction.bbl(borough, block, lot))))
$function$;
comment on function reproduction.parcel(borough text, block integer, lot integer) is 'a person''s helper: borough + block + lot as the registry fragment {"parcels": [{"bbl": ...}]} for a containment filter on the registry index';

CREATE OR REPLACE FUNCTION reproduction.party_names(r jsonb)
 RETURNS text
 LANGUAGE plpgsql
 IMMUTABLE PARALLEL SAFE STRICT
AS $function$
declare
  names text := '';
  p jsonb;
begin
  if jsonb_typeof(r->'parties') <> 'array' then
    return null;
  end if;
  for p in select * from jsonb_array_elements(r->'parties') loop
    names := names || coalesce(p->>'name', '') || ' | ';
  end loop;
  return nullif(names, '');
end $function$;
comment on function reproduction.party_names(r jsonb) is 'a registry''s party names joined with " | " into one text - behind the trigram GIN indexes acris_party_names and richmond_party_names; null when there are no parties';

CREATE OR REPLACE FUNCTION reproduction.reconcile(p_source text)
 RETURNS TABLE(what text, landed bigint, needed bigint)
 LANGUAGE plpgsql
AS $function$
declare
  n_rows   bigint;
  n_reg    bigint;
  n_doc    bigint;
  n_both   bigint;
  n_either bigint;
begin
  if p_source not in ('acris', 'richmond') then
    raise exception 'reconcile: unknown source %', p_source;
  end if;
  execute format('select count(*) from reproduction.%I', p_source) into n_rows;
  execute format('select count(*) from reproduction.%I where registry is null', p_source) into n_reg;
  execute format('select count(*) from reproduction.%I where document is null', p_source) into n_doc;
  execute format('select count(*) from reproduction.%I where registry is null and document is null', p_source) into n_both;
  n_either := n_reg + n_doc - n_both;

  update machinery.updates u
     set landed = case u.lane when 'reproduction' then n_rows - n_either
                              when 'identification' then n_rows
                              when 'registration' then n_rows - n_reg
                              else n_rows - n_doc end,
         needed = n_rows
   where u.source = p_source and u.workstation = '';

  return query select 'phase'::text, n_rows - n_either, n_rows
    union all select 'identification', n_rows, n_rows
    union all select 'registration', n_rows - n_reg, n_rows
    union all select 'documentation', n_rows - n_doc, n_rows;
end
$function$;
comment on function reproduction.reconcile(p_source text) is 'recount landed and needed for the phase and the three lanes from the primary key and the partial indexes (three index-only counts and a subtraction: rows with no registry, rows with no document, rows with neither) and overwrite the totals rows; on demand - after loads and hand edits, never on the tick; run it on a connection without the statement timeout';

CREATE OR REPLACE FUNCTION reproduction.us_date(t text)
 RETURNS date
 LANGUAGE plpgsql
 IMMUTABLE PARALLEL SAFE STRICT
AS $function$
begin
  -- '1/23/2003 9:26:58 AM' or '8/23/1993' -> 2003-01-23 / 1993-08-23; anything else, or an impossible day, -> null
  return make_date(split_part(split_part(t, ' ', 1), '/', 3)::int,
                   split_part(t, '/', 1)::int,
                   split_part(split_part(t, ' ', 1), '/', 2)::int);
exception when others then
  return null;
end $function$;
comment on function reproduction.us_date(t text) is 'a date as the source prints it (M/D/YYYY, with or without a time) read as a date; null when it is not one - behind the recorded, doc_date and expiration indexes and the reading views; plpgsql without a regular expression on purpose (see us_money)';

CREATE OR REPLACE FUNCTION reproduction.us_money(t text)
 RETURNS numeric
 LANGUAGE plpgsql
 IMMUTABLE PARALLEL SAFE STRICT
AS $function$
begin
  -- '$1,250,000.00' -> 1250000.00; anything else -> null.  plpgsql, no regular expression: the instance restarted
  -- three times under an index built on a SQL function with a per-row regular expression (2026-09-06 12:13, 12:36, 13:18)
  return replace(replace(t, '$', ''), ',', '')::numeric;
exception when others then
  return null;
end $function$;
comment on function reproduction.us_money(t text) is 'an amount as the source prints it ($1,250,000.00) read as numeric; null when it is not one - behind the amount indexes and the reading views; plpgsql without a regular expression: an index built on a SQL function with a per-row regular expression restarted the instance three times (2026-09-06)';

CREATE OR REPLACE FUNCTION reproduction.whole_number(t text)
 RETURNS integer
 LANGUAGE plpgsql
 IMMUTABLE PARALLEL SAFE STRICT
AS $function$
begin
  -- '4' -> 4; anything but one to nine digits -> null; no regular expression (see us_money)
  if t = '' or length(t) > 9 or translate(t, '0123456789', '') <> '' then
    return null;
  end if;
  return t::integer;
end $function$;
comment on function reproduction.whole_number(t text) is 'a printed count of up to nine digits read as an integer; null otherwise - behind the pages index and the profile';

create table if not exists machinery.claims (
  source         text not null,
  identifier     text collate "C" not null,
  lane           text not null,
  workstation    text not null,
  until          timestamp with time zone not null,
  constraint claims_pkey PRIMARY KEY (source, identifier, lane),
  constraint claims_lane_check CHECK ((lane = ANY (ARRAY['registration'::text, 'documentation'::text]))),
  constraint claims_source_check CHECK ((source = ANY (ARRAY['acris'::text, 'richmond'::text])))
);
comment on table machinery.claims is 'the work allocation, out of a person''s sight: which identifiers each workstation holds for which lane, until when. claim() takes a slice of the to-do list here (no overlap between machines), land() releases a row as its cell fills, a landed pending keeps its row as its cooldown, and an expired row - a dead machine''s, or a cooldown run out - goes back on the list.';
comment on column machinery.claims.source is 'acris or richmond: the table the identifier belongs to';
comment on column machinery.claims.identifier is 'the document held';
comment on column machinery.claims.lane is 'registration or documentation: the cell being filled';
comment on column machinery.claims.workstation is 'the machine that holds it';
comment on column machinery.claims.until is 'when the hold expires: a claim''s ttl (20 minutes), or a landed pending''s cooldown (an hour) - past it the row goes back on the list';

create table if not exists machinery.updates (
  source         text not null,
  lane           text not null,
  workstation    text not null default ''::text,
  landed         bigint not null default 0,
  needed         bigint not null default 0,
  pct            numeric(6,2),
  status         reproduction.lane_status,
  rate_60s       numeric(9,2),
  increase_60s   bigint,
  pct_60s        numeric(9,4),
  eta_60s        text,
  rate_5m        numeric(9,2),
  increase_5m    bigint,
  pct_5m         numeric(9,4),
  eta_5m         text,
  workers        integer,
  last_seen      timestamp with time zone,
  last_word      text,
  as_of          timestamp with time zone,
  first_seen     timestamp with time zone not null default now(),
  constraint updates_pkey PRIMARY KEY (source, lane, workstation),
  constraint updates_lane_check CHECK ((lane = ANY (ARRAY['reproduction'::text, 'identification'::text, 'registration'::text, 'documentation'::text]))),
  constraint updates_source_check CHECK ((source = ANY (ARRAY['acris'::text, 'richmond'::text])))
);
comment on table machinery.updates is 'how the record is being filled, source first: a row per source for the phase (lane = reproduction), one per lane, one per workstation running a lane - the counters land() and insert_ids() keep exact and the rates, eta, status and as-of the board writes every minute; a person reads reproduction.acris_update / richmond_update, never this table';
comment on column machinery.updates.source is 'acris or richmond';
comment on column machinery.updates.lane is 'reproduction (the phase: every cell filled), identification, registration or documentation';
comment on column machinery.updates.workstation is 'empty on the phase and lane rows (the totals); a machine''s name on its own row';
comment on column machinery.updates.landed is 'a lane row: cells of this lane that are not empty; the phase row: rows with every cell filled; a workstation row: what that machine landed';
comment on column machinery.updates.needed is 'rows in the table - the ruler for every percentage; 0 on a workstation row';
comment on column machinery.updates.pct is 'landed over needed, in percent, written by the board every minute';
comment on column machinery.updates.status is 'computed: complete (landed >= needed) / stalled (the last word is a refusal or a wall) / active (moved in the last window) / pending (everything else)';
comment on column machinery.updates.rate_60s is 'documents a second over the last minute, from the board''s own two readings';
comment on column machinery.updates.increase_60s is 'landed now minus landed a minute ago';
comment on column machinery.updates.pct_60s is 'the minute''s increase over needed, in percent (kept here, off the board since 0014)';
comment on column machinery.updates.eta_60s is 'what remains at the minute''s rate: "3.2 days", "complete", or "paused"';
comment on column machinery.updates.rate_5m is 'documents a second over the last five minutes';
comment on column machinery.updates.increase_5m is 'landed now minus landed five minutes ago';
comment on column machinery.updates.pct_5m is 'the five minutes'' increase over needed, in percent (off the board since 0014)';
comment on column machinery.updates.eta_5m is 'what remains at the five-minute rate - the eta to trust';
comment on column machinery.updates.workers is 'a workstation row: its workers; a lane row: the sum across its workstations alive';
comment on column machinery.updates.last_seen is 'a workstation row: its last heartbeat (every minute while it runs; stale = paused or parked); a lane row: the freshest';
comment on column machinery.updates.last_word is 'the lane''s last word from that machine: started, REFUSED at <id>, a hang-up, a park, a stop';
comment on column machinery.updates.as_of is 'the update program''s pulse, stamped every tick; stale = the update program is not running';
comment on column machinery.updates.first_seen is 'when this row first appeared; a workstation''s number on the board is the order of its first sight';

create table if not exists reproduction.acris (
  source         text not null default 'acris'::text,
  identifier     text collate "C" not null,
  registry       jsonb,
  document       text,
  constraint acris_pkey PRIMARY KEY (identifier),
  constraint acris_document_cell CHECK (((document IS NULL) OR (document = ANY (ARRAY['pending'::text, 'absent'::text])) OR starts_with(document, 'D:\'::text))),
  constraint acris_registry_cell CHECK (((registry IS NULL) OR (jsonb_typeof(registry) = 'object'::text) OR (registry <@ '["pending", "absent"]'::jsonb))),
  constraint acris_source CHECK ((source = 'acris'::text))
);
comment on table reproduction.acris is 'acris reproduction: one row per document; each lane fills its own cell';
comment on column reproduction.acris.source is 'the source, a constant per table (acris): every cross-source table or view carries it without a join';
comment on column reproduction.acris.identifier is 'filled by identification (the ACRIS document id; every URL is minted from it)';
comment on column reproduction.acris.registry is 'filled by registration: the recorded details as a JSON object, or the verdict word when the source has none: pending | absent';
comment on column reproduction.acris.document is 'filled by documentation: the full One Touch path of the saved document, or the verdict word: pending (still being checked, stays in the backfill) | absent (checked: there is none)';

create table if not exists reproduction.richmond (
  source         text not null default 'richmond'::text,
  identifier     text collate "C" not null,
  registry       jsonb,
  document       text,
  constraint richmond_pkey PRIMARY KEY (identifier),
  constraint richmond_document_cell CHECK (((document IS NULL) OR (document = ANY (ARRAY['pending'::text, 'absent'::text])) OR starts_with(document, 'D:\'::text))),
  constraint richmond_registry_cell CHECK (((registry IS NULL) OR (jsonb_typeof(registry) = 'object'::text) OR (registry <@ '["pending", "absent"]'::jsonb))),
  constraint richmond_source CHECK ((source = 'richmond'::text))
);
comment on table reproduction.richmond is 'richmond reproduction: one row per document; each lane fills its own cell';
comment on column reproduction.richmond.source is 'the source, a constant per table (richmond): every cross-source table or view carries it without a join';
comment on column reproduction.richmond.identifier is 'filled by identification (the Richmond County internal id; every URL is minted from it)';
comment on column reproduction.richmond.registry is 'filled by registration: the recorded details as a JSON object, or the verdict word when the source has none: pending | absent';
comment on column reproduction.richmond.document is 'filled by documentation: the full One Touch path of the saved document, or the verdict word: pending (still being checked, stays in the backfill) | absent (checked: there is none)';

create or replace view reading.acris_fields as
 SELECT identifier,
    registry ->> 'type'::text AS type,
    registry ->> 'borough'::text AS borough,
    reproduction.us_date(registry ->> 'recorded'::text) AS recorded,
    reproduction.us_date(registry ->> 'doc_date'::text) AS doc_date,
    reproduction.whole_number(registry ->> 'pages'::text) AS pages,
    reproduction.us_money(registry ->> 'amount'::text) AS amount,
    registry ->> 'crfn'::text AS crfn,
    registry ->> 'reel_page'::text AS reel_page,
    registry ->> 'remarks'::text AS remarks,
    registry -> 'parcels'::text AS parcels,
    registry -> 'parties'::text AS parties,
    document
   FROM reproduction.acris;
comment on view reading.acris_fields is 'the acris registry spelled out as typed columns, one row per document: type, borough, recorded and doc_date as dates, pages as an integer, amount as numeric, crfn, reel_page, remarks, the parcel and party counts, and the document path; a person filters here';

create or replace view reading.acris_parcels as
 SELECT a.identifier,
    p.value ->> 'bbl'::text AS bbl,
        CASE substr(p.value ->> 'bbl'::text, 1, 1)
            WHEN '1'::text THEN 'MANHATTAN'::text
            WHEN '2'::text THEN 'BRONX'::text
            WHEN '3'::text THEN 'BROOKLYN'::text
            WHEN '4'::text THEN 'QUEENS'::text
            WHEN '5'::text THEN 'STATEN ISLAND'::text
            ELSE NULL::text
        END AS borough,
    substr(p.value ->> 'bbl'::text, 2, 5) AS block,
    substr(p.value ->> 'bbl'::text, 7, 4) AS lot,
    p.value ->> 'unit'::text AS unit,
    p.value ->> 'address'::text AS address,
    p.value ->> 'use'::text AS use,
    p.value ->> 'partial'::text AS partial
   FROM reproduction.acris a,
    LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(a.registry -> 'parcels'::text) = 'array'::text THEN a.registry -> 'parcels'::text
            ELSE '[]'::jsonb
        END) p(value);
comment on view reading.acris_parcels is 'one row per parcel of every acris registry: the bbl and its borough, block, lot, unit, address, use and the partial flag';

create or replace view reading.richmond_fields as
 SELECT identifier,
    registry ->> 'doc_type'::text AS doc_type,
    reproduction.us_date(registry ->> 'recorded'::text) AS recorded,
    registry ->> 'book'::text AS book,
    registry ->> 'page'::text AS page,
    registry ->> 'instrument'::text AS instrument,
    reproduction.us_money(registry ->> 'amount'::text) AS amount,
    registry ->> 'status'::text AS status,
    registry -> 'parcels'::text AS parcels,
    registry -> 'parties'::text AS parties,
    document
   FROM reproduction.richmond;
comment on view reading.richmond_fields is 'the richmond registry spelled out as typed columns, one row per document: doc_type, recorded as a date, book and page, instrument, amount as numeric, status, the parcel and party counts, and the document path';

create or replace view reading.richmond_parcels as
 SELECT r.identifier,
    p.value ->> 'bbl'::text AS bbl,
    'STATEN ISLAND'::text AS borough,
    substr(p.value ->> 'bbl'::text, 2, 5) AS block,
    substr(p.value ->> 'bbl'::text, 7, 4) AS lot
   FROM reproduction.richmond r,
    LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(r.registry -> 'parcels'::text) = 'array'::text THEN r.registry -> 'parcels'::text
            ELSE '[]'::jsonb
        END) p(value);
comment on view reading.richmond_parcels is 'one row per parcel of every richmond registry: the bbl and its borough, block, lot';

create or replace view reproduction.acris_update as
 WITH lanes(lane, ord) AS (
         VALUES ('reproduction'::text,1), ('identification'::text,2), ('registration'::text,3), ('documentation'::text,4)
        ), stations AS (
         SELECT updates.workstation,
            row_number() OVER (ORDER BY (min(updates.first_seen)), updates.workstation) AS n
           FROM machinery.updates
          WHERE updates.source = 'acris'::text AND updates.workstation <> ''::text
          GROUP BY updates.workstation
        ), blocks AS (
         SELECT n.n
           FROM generate_series(1::bigint, GREATEST(2::bigint, ( SELECT count(*) AS count
                   FROM stations))) n(n)
        ), total AS (
         SELECT updates.lane,
            updates.needed
           FROM machinery.updates
          WHERE updates.source = 'acris'::text AND updates.workstation = ''::text
        ), board AS (
         SELECT 0 AS block,
            l.ord,
            u.source,
            u.lane || ' total'::text AS lane,
            u.status::text AS status,
            to_char((u.as_of AT TIME ZONE 'America/New_York'::text), 'YYYY-MM-DD HH24:MI:SS'::text) AS as_of_et,
            u.rate_60s::text AS rate_60s,
            u.increase_60s::text AS increase_60s,
            u.eta_60s,
            u.rate_5m::text AS rate_5m,
            u.increase_5m::text AS increase_5m,
            u.eta_5m,
            u.landed::text AS landed,
            u.needed::text AS needed,
            u.pct::text AS pct
           FROM lanes l
             JOIN machinery.updates u ON u.source = 'acris'::text AND u.workstation = ''::text AND u.lane = l.lane
        UNION ALL
         SELECT b.n,
            0,
            'acris'::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text
           FROM blocks b
        UNION ALL
         SELECT b.n,
            l.ord,
            'acris'::text AS text,
            (l.lane || ' '::text) || COALESCE(s.workstation, b.n::text),
            COALESCE(u.status::text, 'pending'::text) AS "coalesce",
            to_char((u.as_of AT TIME ZONE 'America/New_York'::text), 'YYYY-MM-DD HH24:MI:SS'::text) AS to_char,
            u.rate_60s::text AS rate_60s,
            u.increase_60s::text AS increase_60s,
            u.eta_60s,
            u.rate_5m::text AS rate_5m,
            u.increase_5m::text AS increase_5m,
            u.eta_5m,
            u.landed::text AS landed,
                CASE
                    WHEN s.workstation IS NOT NULL THEN t.needed
                    ELSE NULL::bigint
                END::text AS text,
            u.pct::text AS pct
           FROM blocks b
             CROSS JOIN lanes l
             LEFT JOIN stations s ON s.n = b.n
             LEFT JOIN machinery.updates u ON u.source = 'acris'::text AND u.workstation = s.workstation AND u.lane = l.lane
             LEFT JOIN total t ON t.lane = l.lane
        )
 SELECT source,
    lane,
    status,
    COALESCE(as_of_et, ' '::text) AS as_of_et,
    COALESCE(rate_60s, ' '::text) AS rate_60s,
    COALESCE(increase_60s, ' '::text) AS increase_60s,
    COALESCE(NULLIF(eta_60s, ''::text), ' '::text) AS eta_60s,
    COALESCE(rate_5m, ' '::text) AS rate_5m,
    COALESCE(increase_5m, ' '::text) AS increase_5m,
    COALESCE(NULLIF(eta_5m, ''::text), ' '::text) AS eta_5m,
    COALESCE(landed, ' '::text) AS landed,
    COALESCE(needed, ' '::text) AS needed,
    COALESCE(pct, ' '::text) AS pct
   FROM board
  ORDER BY block, ord;
comment on view reproduction.acris_update is 'ACRIS UPDATE: three blocks of four rows - the totals (reproduction total, identification total, registration total, documentation total), a blank spacer row, workstation 1''s four (reproduction 1 ...), a blank spacer row, workstation 2''s four (pending until it first reports); source, lane, status, as of (Eastern, to the second), the 60-second block (rate, increase, eta), the 5-minute block, landed, needed, percentage. Every column is text and a blank is one space, so the Table Editor shows a spacer as nothing; every row carries the source because the Editor sorts a view by its first column';
comment on column reproduction.acris_update.source is 'acris, on every row';
comment on column reproduction.acris_update.lane is 'reproduction total, identification total, registration total, documentation total; then one block per station, each row named <lane> <station> - the provider''s own name (DigitalOcean, Vultr, ExpressVPN); a block no station has claimed yet keeps its number';
comment on column reproduction.acris_update.status is 'active / pending / stalled / complete, computed by the board; pending on a workstation block nobody has claimed';
comment on column reproduction.acris_update.as_of_et is 'the board''s last tick, Eastern, to the second; stale = the board is not running';
comment on column reproduction.acris_update.rate_60s is 'documents a second over the last minute';
comment on column reproduction.acris_update.increase_60s is 'landed now minus landed a minute ago';
comment on column reproduction.acris_update.eta_60s is 'what remains at the minute''s rate, or complete / paused';
comment on column reproduction.acris_update.rate_5m is 'documents a second over the last five minutes';
comment on column reproduction.acris_update.increase_5m is 'landed now minus landed five minutes ago';
comment on column reproduction.acris_update.eta_5m is 'what remains at the five-minute rate - the eta to trust';
comment on column reproduction.acris_update.landed is 'a total row: cells of that lane that are not empty (reproduction: rows with every cell filled); a workstation row: what that machine landed';
comment on column reproduction.acris_update.needed is 'rows in the table - the ruler for every percentage; a workstation row shows the lane''s';
comment on column reproduction.acris_update.pct is 'landed over needed, in percent';

create or replace view reproduction.richmond_update as
 WITH lanes(lane, ord) AS (
         VALUES ('reproduction'::text,1), ('identification'::text,2), ('registration'::text,3), ('documentation'::text,4)
        ), stations AS (
         SELECT updates.workstation,
            row_number() OVER (ORDER BY (min(updates.first_seen)), updates.workstation) AS n
           FROM machinery.updates
          WHERE updates.source = 'richmond'::text AND updates.workstation <> ''::text
          GROUP BY updates.workstation
        ), blocks AS (
         SELECT n.n
           FROM generate_series(1::bigint, GREATEST(2::bigint, ( SELECT count(*) AS count
                   FROM stations))) n(n)
        ), total AS (
         SELECT updates.lane,
            updates.needed
           FROM machinery.updates
          WHERE updates.source = 'richmond'::text AND updates.workstation = ''::text
        ), board AS (
         SELECT 0 AS block,
            l.ord,
            u.source,
            u.lane || ' total'::text AS lane,
            u.status::text AS status,
            to_char((u.as_of AT TIME ZONE 'America/New_York'::text), 'YYYY-MM-DD HH24:MI:SS'::text) AS as_of_et,
            u.rate_60s::text AS rate_60s,
            u.increase_60s::text AS increase_60s,
            u.eta_60s,
            u.rate_5m::text AS rate_5m,
            u.increase_5m::text AS increase_5m,
            u.eta_5m,
            u.landed::text AS landed,
            u.needed::text AS needed,
            u.pct::text AS pct
           FROM lanes l
             JOIN machinery.updates u ON u.source = 'richmond'::text AND u.workstation = ''::text AND u.lane = l.lane
        UNION ALL
         SELECT b.n,
            0,
            'richmond'::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text,
            ' '::text AS text
           FROM blocks b
        UNION ALL
         SELECT b.n,
            l.ord,
            'richmond'::text AS text,
            (l.lane || ' '::text) || COALESCE(s.workstation, b.n::text),
            COALESCE(u.status::text, 'pending'::text) AS "coalesce",
            to_char((u.as_of AT TIME ZONE 'America/New_York'::text), 'YYYY-MM-DD HH24:MI:SS'::text) AS to_char,
            u.rate_60s::text AS rate_60s,
            u.increase_60s::text AS increase_60s,
            u.eta_60s,
            u.rate_5m::text AS rate_5m,
            u.increase_5m::text AS increase_5m,
            u.eta_5m,
            u.landed::text AS landed,
                CASE
                    WHEN s.workstation IS NOT NULL THEN t.needed
                    ELSE NULL::bigint
                END::text AS text,
            u.pct::text AS pct
           FROM blocks b
             CROSS JOIN lanes l
             LEFT JOIN stations s ON s.n = b.n
             LEFT JOIN machinery.updates u ON u.source = 'richmond'::text AND u.workstation = s.workstation AND u.lane = l.lane
             LEFT JOIN total t ON t.lane = l.lane
        )
 SELECT source,
    lane,
    status,
    COALESCE(as_of_et, ' '::text) AS as_of_et,
    COALESCE(rate_60s, ' '::text) AS rate_60s,
    COALESCE(increase_60s, ' '::text) AS increase_60s,
    COALESCE(NULLIF(eta_60s, ''::text), ' '::text) AS eta_60s,
    COALESCE(rate_5m, ' '::text) AS rate_5m,
    COALESCE(increase_5m, ' '::text) AS increase_5m,
    COALESCE(NULLIF(eta_5m, ''::text), ' '::text) AS eta_5m,
    COALESCE(landed, ' '::text) AS landed,
    COALESCE(needed, ' '::text) AS needed,
    COALESCE(pct, ' '::text) AS pct
   FROM board
  ORDER BY block, ord;
comment on view reproduction.richmond_update is 'RICHMOND UPDATE: three blocks of four rows - the totals (reproduction total, identification total, registration total, documentation total), a blank spacer row, workstation 1''s four (reproduction 1 ...), a blank spacer row, workstation 2''s four (pending until it first reports); source, lane, status, as of (Eastern, to the second), the 60-second block (rate, increase, eta), the 5-minute block, landed, needed, percentage. Every column is text and a blank is one space, so the Table Editor shows a spacer as nothing; every row carries the source because the Editor sorts a view by its first column';
comment on column reproduction.richmond_update.source is 'richmond, on every row';
comment on column reproduction.richmond_update.lane is 'reproduction total, identification total, registration total, documentation total; then one block per station, each row named <lane> <station> - the provider''s own name; a block no station has claimed yet keeps its number';
comment on column reproduction.richmond_update.status is 'active / pending / stalled / complete, computed by the board; pending on a workstation block nobody has claimed';
comment on column reproduction.richmond_update.as_of_et is 'the board''s last tick, Eastern, to the second; stale = the board is not running';
comment on column reproduction.richmond_update.rate_60s is 'documents a second over the last minute';
comment on column reproduction.richmond_update.increase_60s is 'landed now minus landed a minute ago';
comment on column reproduction.richmond_update.eta_60s is 'what remains at the minute''s rate, or complete / paused';
comment on column reproduction.richmond_update.rate_5m is 'documents a second over the last five minutes';
comment on column reproduction.richmond_update.increase_5m is 'landed now minus landed five minutes ago';
comment on column reproduction.richmond_update.eta_5m is 'what remains at the five-minute rate - the eta to trust';
comment on column reproduction.richmond_update.landed is 'a total row: cells of that lane that are not empty (reproduction: rows with every cell filled); a workstation row: what that machine landed';
comment on column reproduction.richmond_update.needed is 'rows in the table - the ruler for every percentage; a workstation row shows the lane''s';
comment on column reproduction.richmond_update.pct is 'landed over needed, in percent';

create materialized view if not exists reading.acris_keys as
 SELECT 'registry'::text AS level,
    k.k AS key,
    count(*) AS documents
   FROM reproduction.acris,
    LATERAL jsonb_object_keys(
        CASE
            WHEN jsonb_typeof(acris.registry) = 'object'::text THEN acris.registry
            ELSE '{}'::jsonb
        END) k(k)
  GROUP BY k.k
UNION ALL
 SELECT 'parcel'::text AS level,
    k.k AS key,
    count(*) AS documents
   FROM reproduction.acris,
    LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(acris.registry -> 'parcels'::text) = 'array'::text THEN acris.registry -> 'parcels'::text
            ELSE '[]'::jsonb
        END) p(value),
    LATERAL jsonb_object_keys(
        CASE
            WHEN jsonb_typeof(p.value) = 'object'::text THEN p.value
            ELSE '{}'::jsonb
        END) k(k)
  GROUP BY k.k
UNION ALL
 SELECT 'party'::text AS level,
    k.k AS key,
    count(*) AS documents
   FROM reproduction.acris,
    LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(acris.registry -> 'parties'::text) = 'array'::text THEN acris.registry -> 'parties'::text
            ELSE '[]'::jsonb
        END) p(value),
    LATERAL jsonb_object_keys(
        CASE
            WHEN jsonb_typeof(p.value) = 'object'::text THEN p.value
            ELSE '{}'::jsonb
        END) k(k)
  GROUP BY k.k;
comment on materialized view reading.acris_keys is 'the key census of the acris registry: every key at every level and how many documents carry it; refreshed by hand after a large landing';

create materialized view if not exists reading.acris_profile as
 WITH d AS (
         SELECT acris.registry ->> 'type'::text AS type,
            acris.registry ->> 'borough'::text AS borough,
            EXTRACT(year FROM reproduction.us_date(acris.registry ->> 'recorded'::text))::integer AS year,
            jsonb_array_length(
                CASE
                    WHEN jsonb_typeof(acris.registry -> 'parcels'::text) = 'array'::text THEN acris.registry -> 'parcels'::text
                    ELSE '[]'::jsonb
                END) AS parcels,
            jsonb_array_length(
                CASE
                    WHEN jsonb_typeof(acris.registry -> 'parties'::text) = 'array'::text THEN acris.registry -> 'parties'::text
                    ELSE '[]'::jsonb
                END) AS parties,
            reproduction.whole_number(acris.registry ->> 'pages'::text) AS pages,
            acris.registry ? 'recorded'::text AND reproduction.us_date(acris.registry ->> 'recorded'::text) IS NULL AS recorded_unparsed,
            acris.registry ? 'amount'::text AND reproduction.us_money(acris.registry ->> 'amount'::text) IS NULL AS amount_unparsed,
            acris.registry ? 'pages'::text AND reproduction.whole_number(acris.registry ->> 'pages'::text) IS NULL AS pages_unparsed,
            acris.document IS NOT NULL AND acris.document <> 'pending'::text AND acris.document <> 'absent'::text AS with_document
           FROM reproduction.acris
          WHERE jsonb_typeof(acris.registry) = 'object'::text
        )
 SELECT
        CASE GROUPING(type, borough, year, parcels, parties, pages)
            WHEN 7 THEN 'type, borough, year'::text
            WHEN 31 THEN 'type'::text
            WHEN 47 THEN 'borough'::text
            WHEN 55 THEN 'year'::text
            WHEN 59 THEN 'parcels'::text
            WHEN 61 THEN 'parties'::text
            WHEN 62 THEN 'pages'::text
            ELSE 'all'::text
        END AS facet,
    type,
    borough,
    year,
    parcels,
    parties,
    pages,
    count(*) AS documents,
    count(*) FILTER (WHERE with_document) AS with_document,
    count(*) FILTER (WHERE recorded_unparsed) AS recorded_unparsed,
    count(*) FILTER (WHERE amount_unparsed) AS amount_unparsed,
    count(*) FILTER (WHERE pages_unparsed) AS pages_unparsed
   FROM d
  GROUP BY GROUPING SETS ((type, borough, year), (type), (borough), (year), (parcels), (parties), (pages), ());
comment on materialized view reading.acris_profile is 'the acris record profiled by facet - type, borough, year, parcel count, party count, pages - with documents, how many have a document, and how many carry a recorded date, amount or page count the readers could not parse; refreshed by hand';

create materialized view if not exists reading.richmond_keys as
 SELECT 'registry'::text AS level,
    k.k AS key,
    count(*) AS documents
   FROM reproduction.richmond,
    LATERAL jsonb_object_keys(
        CASE
            WHEN jsonb_typeof(richmond.registry) = 'object'::text THEN richmond.registry
            ELSE '{}'::jsonb
        END) k(k)
  GROUP BY k.k
UNION ALL
 SELECT 'parcel'::text AS level,
    k.k AS key,
    count(*) AS documents
   FROM reproduction.richmond,
    LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(richmond.registry -> 'parcels'::text) = 'array'::text THEN richmond.registry -> 'parcels'::text
            ELSE '[]'::jsonb
        END) p(value),
    LATERAL jsonb_object_keys(
        CASE
            WHEN jsonb_typeof(p.value) = 'object'::text THEN p.value
            ELSE '{}'::jsonb
        END) k(k)
  GROUP BY k.k
UNION ALL
 SELECT 'party'::text AS level,
    k.k AS key,
    count(*) AS documents
   FROM reproduction.richmond,
    LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(richmond.registry -> 'parties'::text) = 'array'::text THEN richmond.registry -> 'parties'::text
            ELSE '[]'::jsonb
        END) p(value),
    LATERAL jsonb_object_keys(
        CASE
            WHEN jsonb_typeof(p.value) = 'object'::text THEN p.value
            ELSE '{}'::jsonb
        END) k(k)
  GROUP BY k.k;
comment on materialized view reading.richmond_keys is 'the key census of the richmond registry: every key at every level and how many documents carry it; refreshed by hand';

create materialized view if not exists reading.richmond_profile as
 WITH d AS (
         SELECT richmond.registry ->> 'doc_type'::text AS doc_type,
            EXTRACT(year FROM reproduction.us_date(richmond.registry ->> 'recorded'::text))::integer AS year,
            jsonb_array_length(
                CASE
                    WHEN jsonb_typeof(richmond.registry -> 'parcels'::text) = 'array'::text THEN richmond.registry -> 'parcels'::text
                    ELSE '[]'::jsonb
                END) AS parcels,
            jsonb_array_length(
                CASE
                    WHEN jsonb_typeof(richmond.registry -> 'parties'::text) = 'array'::text THEN richmond.registry -> 'parties'::text
                    ELSE '[]'::jsonb
                END) AS parties,
            richmond.registry ? 'recorded'::text AND reproduction.us_date(richmond.registry ->> 'recorded'::text) IS NULL AS recorded_unparsed,
            richmond.registry ? 'amount'::text AND reproduction.us_money(richmond.registry ->> 'amount'::text) IS NULL AS amount_unparsed,
            richmond.document IS NOT NULL AND richmond.document <> 'pending'::text AND richmond.document <> 'absent'::text AS with_document
           FROM reproduction.richmond
          WHERE jsonb_typeof(richmond.registry) = 'object'::text
        )
 SELECT
        CASE GROUPING(doc_type, year, parcels, parties)
            WHEN 3 THEN 'doc_type, year'::text
            WHEN 7 THEN 'doc_type'::text
            WHEN 11 THEN 'year'::text
            WHEN 13 THEN 'parcels'::text
            WHEN 14 THEN 'parties'::text
            ELSE 'all'::text
        END AS facet,
    doc_type,
    year,
    parcels,
    parties,
    count(*) AS documents,
    count(*) FILTER (WHERE with_document) AS with_document,
    count(*) FILTER (WHERE recorded_unparsed) AS recorded_unparsed,
    count(*) FILTER (WHERE amount_unparsed) AS amount_unparsed
   FROM d
  GROUP BY GROUPING SETS ((doc_type, year), (doc_type), (year), (parcels), (parties), ());
comment on materialized view reading.richmond_profile is 'the richmond record profiled by facet - doc_type, year, parcel count, party count - with documents, how many have a document, and how many carry a recorded date or amount the readers could not parse; refreshed by hand';

CREATE INDEX IF NOT EXISTS claims_expiry ON machinery.claims USING btree (source, lane, until);
CREATE UNIQUE INDEX IF NOT EXISTS acris_keys_key ON reading.acris_keys USING btree (level, key);
CREATE UNIQUE INDEX IF NOT EXISTS acris_profile_key ON reading.acris_profile USING btree (facet, type, borough, year, parcels, parties, pages) NULLS NOT DISTINCT;
CREATE UNIQUE INDEX IF NOT EXISTS richmond_keys_key ON reading.richmond_keys USING btree (level, key);
CREATE UNIQUE INDEX IF NOT EXISTS richmond_profile_key ON reading.richmond_profile USING btree (facet, doc_type, year, parcels, parties) NULLS NOT DISTINCT;
CREATE INDEX IF NOT EXISTS acris_amount ON reproduction.acris USING btree (reproduction.us_money((registry ->> 'amount'::text)));
CREATE INDEX IF NOT EXISTS acris_blocks ON reproduction.acris USING gin (reproduction.block_keys(registry));
CREATE INDEX IF NOT EXISTS acris_borough ON reproduction.acris USING btree (((registry ->> 'borough'::text)));
CREATE INDEX IF NOT EXISTS acris_crfn ON reproduction.acris USING btree (((registry ->> 'crfn'::text)));
CREATE INDEX IF NOT EXISTS acris_doc_date ON reproduction.acris USING btree (reproduction.us_date((registry ->> 'doc_date'::text)));
CREATE INDEX IF NOT EXISTS acris_document ON reproduction.acris USING btree (document text_pattern_ops) WHERE (document IS NOT NULL);
CREATE INDEX IF NOT EXISTS acris_documentation_empty ON reproduction.acris USING btree (identifier) WHERE (document IS NULL);
CREATE INDEX IF NOT EXISTS acris_documentation_pending ON reproduction.acris USING btree (identifier) WHERE (document = 'pending'::text);
CREATE INDEX IF NOT EXISTS acris_expiration ON reproduction.acris USING btree (reproduction.us_date((registry ->> 'expiration'::text)));
CREATE INDEX IF NOT EXISTS acris_pages ON reproduction.acris USING btree (reproduction.whole_number((registry ->> 'pages'::text)));
CREATE INDEX IF NOT EXISTS acris_party_names ON reproduction.acris USING gin (reproduction.party_names(registry) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS acris_recorded ON reproduction.acris USING btree (reproduction.us_date((registry ->> 'recorded'::text)));
CREATE INDEX IF NOT EXISTS acris_registration_empty ON reproduction.acris USING btree (identifier) WHERE (registry IS NULL);
CREATE INDEX IF NOT EXISTS acris_registration_pending ON reproduction.acris USING btree (identifier) WHERE (registry = '"pending"'::jsonb);
CREATE INDEX IF NOT EXISTS acris_registry ON reproduction.acris USING gin (registry jsonb_path_ops);
CREATE INDEX IF NOT EXISTS acris_type ON reproduction.acris USING btree (((registry ->> 'type'::text)));
CREATE INDEX IF NOT EXISTS richmond_amount ON reproduction.richmond USING btree (reproduction.us_money((registry ->> 'amount'::text)));
CREATE INDEX IF NOT EXISTS richmond_blocks ON reproduction.richmond USING gin (reproduction.block_keys(registry));
CREATE INDEX IF NOT EXISTS richmond_book_page ON reproduction.richmond USING btree (((registry ->> 'book'::text)), ((registry ->> 'page'::text)));
CREATE INDEX IF NOT EXISTS richmond_doc_type ON reproduction.richmond USING btree (((registry ->> 'doc_type'::text)));
CREATE INDEX IF NOT EXISTS richmond_document ON reproduction.richmond USING btree (document text_pattern_ops) WHERE (document IS NOT NULL);
CREATE INDEX IF NOT EXISTS richmond_documentation_empty ON reproduction.richmond USING btree (identifier) WHERE (document IS NULL);
CREATE INDEX IF NOT EXISTS richmond_documentation_pending ON reproduction.richmond USING btree (identifier) WHERE (document = 'pending'::text);
CREATE INDEX IF NOT EXISTS richmond_instrument ON reproduction.richmond USING btree (((registry ->> 'instrument'::text)));
CREATE INDEX IF NOT EXISTS richmond_party_names ON reproduction.richmond USING gin (reproduction.party_names(registry) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS richmond_recorded ON reproduction.richmond USING btree (reproduction.us_date((registry ->> 'recorded'::text)));
CREATE INDEX IF NOT EXISTS richmond_registration_empty ON reproduction.richmond USING btree (identifier) WHERE (registry IS NULL);
CREATE INDEX IF NOT EXISTS richmond_registration_pending ON reproduction.richmond USING btree (identifier) WHERE (registry = '"pending"'::jsonb);
CREATE INDEX IF NOT EXISTS richmond_registry ON reproduction.richmond USING gin (registry jsonb_path_ops);
