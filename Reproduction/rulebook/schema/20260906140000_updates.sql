-- 0007  the updates table, and the claims out of sight  (login, 2026-09-06 13:1x)
--
-- "You have a database, and you have an updating table that shows you how you're progressing on filling in that
-- database ... the update table shows how workstations are performing and how we're progressing on reproducing.
-- That's important, but in terms of actually building our own tables for it, it's probably unnecessary ... build it
-- behind the scenes so you don't see it."
--
-- What a person sees in the reproduction schema: acris and richmond (the record, untouched) and UPDATES - one table,
-- source first: a row per source for the phase (lane = reproduction), a row per lane, and a row per workstation
-- running a lane - that machine's own landed count, its rate, its workers, when it was last seen and its last word.
-- The heartbeat is that row's last_seen; the heartbeats tables are gone.  What the code needs and a person does not
-- read: the claims - which doc_ids each workstation holds for which lane, until when.  Two machines can only avoid
-- taking the same document through a list both can see, so the list stays in the cloud, but it moves out of sight
-- into the schema MACHINERY, the code's own drawer; a landed pending's wait lives there as before (0004).  The four
-- functions keep their signatures and point at the new places; the counters move as before, and land() now moves the
-- workstation's own row as well as the lane's.  The old rows are carried over, then the eight old tables are dropped.
-- One transaction: all or nothing.
set statement_timeout = 0;
create schema if not exists machinery;
comment on schema machinery is 'the code''s own drawer: what the lanes need to share between workstations and a person never reads';

create table reproduction.updates (
  source        text not null check (source in ('acris', 'richmond')),
  lane          text not null check (lane in ('reproduction', 'synchronization', 'registration', 'documentation')),
  workstation   text not null default '',
  landed        bigint not null default 0,
  needed        bigint not null default 0,
  pct           numeric(6, 2),
  status        reproduction.lane_status,
  rate_60s      numeric(9, 2),
  increase_60s  bigint,
  pct_60s       numeric(9, 4),
  eta_60s       text,
  rate_5m       numeric(9, 2),
  increase_5m   bigint,
  pct_5m        numeric(9, 4),
  eta_5m        text,
  workers       integer,
  last_seen     timestamptz,
  last_word     text,
  as_of         timestamptz,
  primary key (source, lane, workstation)
);
comment on table  reproduction.updates             is 'how the record is being filled, source first. A row per source for the phase (lane = reproduction: rows with every cell filled), a row per lane (its cells filled), and a row per workstation running a lane (workstation named: that machine''s own landed count, rate, workers, last seen, last word). landed and needed are kept exact by land() and insert_ids and recounted by reconcile(); the rates, eta and status are computed and written every minute by the update program, never set by hand.';
comment on column reproduction.updates.workstation is 'empty on the phase and lane rows (the totals); a machine''s name on its own row';
comment on column reproduction.updates.landed      is 'a lane row: cells of this lane that are not empty; the phase row: rows with every cell filled; a workstation row: what that machine landed';
comment on column reproduction.updates.needed      is 'rows in the table - the ruler for every percentage; 0 on a workstation row';
comment on column reproduction.updates.status      is 'computed: complete (landed >= needed) / stalled (the last word is a refusal or a wall) / active (moved in the last window) / pending (everything else)';
comment on column reproduction.updates.workers     is 'a workstation row: its workers; a lane row: the sum across its workstations alive';
comment on column reproduction.updates.last_seen   is 'a workstation row: its last heartbeat (every minute while it runs; stale = paused or parked); a lane row: the freshest';
comment on column reproduction.updates.last_word   is 'the lane''s last word from that machine: started, REFUSED at <id>, a hang-up, a park, a stop';
comment on column reproduction.updates.as_of       is 'the update program''s pulse, stamped every tick; stale = the update program is not running';

create table machinery.claims (
  source       text        not null check (source in ('acris', 'richmond')),
  doc_id       text        collate "C" not null,
  lane         text        not null check (lane in ('registration', 'documentation')),
  workstation  text        not null,
  until        timestamptz not null,
  primary key (source, doc_id, lane)
);
create index claims_expiry on machinery.claims (source, lane, until);
comment on table machinery.claims is 'the work allocation, out of a person''s sight: which doc_ids each workstation holds for which lane, until when. claim() takes a slice of the to-do list here (no overlap between machines), land() releases a row as its cell fills, a landed pending keeps its row as its cooldown, and an expired row - a dead machine''s, or a cooldown run out - goes back on the list.';

-- the rows carried over: the phase and lane totals, the heartbeats as workstation rows, the claims
insert into reproduction.updates (source, lane, workstation, landed, needed, pct, status, rate_60s, increase_60s, pct_60s, eta_60s, rate_5m, increase_5m, pct_5m, eta_5m, as_of)
select 'acris', 'reproduction', '', landed, needed, pct, status, rate_60s, increase_60s, pct_60s, eta_60s, rate_5m, increase_5m, pct_5m, eta_5m, as_of from reproduction.acris_update
union all
select 'richmond', 'reproduction', '', landed, needed, pct, status, rate_60s, increase_60s, pct_60s, eta_60s, rate_5m, increase_5m, pct_5m, eta_5m, as_of from reproduction.richmond_update;

insert into reproduction.updates (source, lane, workstation, landed, needed, pct, status, rate_60s, increase_60s, pct_60s, eta_60s, rate_5m, increase_5m, pct_5m, eta_5m, workers, last_seen, last_word, as_of)
select 'acris', lane, '', landed, needed, pct, status, rate_60s, increase_60s, pct_60s, eta_60s, rate_5m, increase_5m, pct_5m, eta_5m, width, heartbeat_at, last_event, as_of from reproduction.acris_update_lanes
union all
select 'richmond', lane, '', landed, needed, pct, status, rate_60s, increase_60s, pct_60s, eta_60s, rate_5m, increase_5m, pct_5m, eta_5m, width, heartbeat_at, last_event, as_of from reproduction.richmond_update_lanes;

insert into reproduction.updates (source, lane, workstation, workers, last_seen, last_word)
select 'acris', lane, host, width, heartbeat_at, last_event from reproduction.acris_heartbeats
union all
select 'richmond', lane, host, width, heartbeat_at, last_event from reproduction.richmond_heartbeats;

insert into machinery.claims (source, doc_id, lane, workstation, until)
select 'acris', doc_id, lane, host, until from reproduction.acris_claims
union all
select 'richmond', doc_id, lane, host, until from reproduction.richmond_claims;

-- claim(source, lane, host, n, ttl) -> the doc_ids now held by this workstation.  Unchanged in what it does (0004):
-- expired claims released first; pendings whose cooldown has run out first, in id order off the *_pending index; then
-- empties off the *_empty index; atomic (row locks, skip locked, the claims key).  It reads and writes machinery.claims.
create or replace function reproduction.claim(
  p_source text, p_lane text, p_host text,
  p_n integer default 500, p_ttl interval default interval '20 minutes')
returns setof text
language plpgsql as $$
declare
  cell   text;
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
  delete from machinery.claims where source = p_source and lane = p_lane and until < now();

  -- 1. pendings due for a re-check: not held (in flight or cooling), in id order off the *_pending index
  for r in execute format($q$
      with take as (
        select w.doc_id
        from reproduction.%1$I w
        where w.%2$I = %3$s
          %4$s
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
    $q$, p_source, cell, pend, need)
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
comment on function reproduction.claim is 'take a slice of the to-do list for one lane on one workstation: atomic, no overlap between machines; pendings whose cooldown has run out first, then empties, both in id order; expired claims released first; documentation only takes rows with a registry object';

-- land(source, lane, host, rows, pending_age) -> cells written.  As in 0004, and the counters now move on two rows:
-- the lane's totals row and the landing workstation's own row (made on its first landing if the heartbeat has not
-- made it yet); a row completed moves the phase row.
create or replace function reproduction.land(p_source text, p_lane text, p_host text, p_rows jsonb, p_pending_age interval default interval '1 hour')
returns integer
language plpgsql as $$
declare
  cell      text;
  other     text;
  vtype     text;
  pend      text;
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
      delete from machinery.claims c using jsonb_to_recordset($1) as r(doc_id text, value %1$s)
      where c.source = $4 and c.doc_id = r.doc_id and c.lane = $2 and c.workstation = $3 and r.value is distinct from %2$s
    $q$, vtype, pend)
    using p_rows, p_lane, p_host, p_source;
  execute format($q$
      insert into machinery.claims as c (source, doc_id, lane, workstation, until)
      select $5, r.doc_id, $2, $3, now() + $4 from jsonb_to_recordset($1) as r(doc_id text, value %1$s)
      where r.value = %2$s
      on conflict (source, doc_id, lane) do update set workstation = excluded.workstation, until = excluded.until
    $q$, vtype, pend)
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
comment on function reproduction.land is 'fill a batch of cells for one lane from one workstation; a filled cell releases its claim, a pending keeps it as a cooldown for pending_age; the lane''s row and the workstation''s own row move by what was new, the phase row by rows completed; the cell rule constraints reject any wrong value';

-- heartbeat(source, lane, host, width, last_event) -> the workstation's own row in updates: alive now, this wide,
-- this last word.
create or replace function reproduction.heartbeat(p_source text, p_lane text, p_host text, p_width integer, p_last_event text default null)
returns void
language plpgsql as $$
begin
  if p_source not in ('acris', 'richmond') then
    raise exception 'heartbeat: unknown source %', p_source;
  end if;
  insert into reproduction.updates as u (source, lane, workstation, workers, last_seen, last_word)
  values (p_source, p_lane, p_host, p_width, now(), p_last_event)
  on conflict (source, lane, workstation) do update
    set workers = excluded.workers, last_seen = now(), last_word = coalesce(excluded.last_word, u.last_word);
end $$;
comment on function reproduction.heartbeat is 'a running lane''s sign of life from one workstation, on that machine''s own updates row; stale = paused or parked; last_word carries a refusal, a hang-up, a park';

-- reconcile(source) -> recount landed and needed from the table itself and overwrite the totals rows (the phase and
-- the three lanes); the workstation rows are each machine's own count and are left alone.  Index-only counts; on demand.
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

  update reproduction.updates u
     set landed = case u.lane when 'reproduction' then n_rows - n_either
                              when 'synchronization' then n_rows
                              when 'registration' then n_rows - n_reg
                              else n_rows - n_doc end,
         needed = n_rows
   where u.source = p_source and u.workstation = '';

  return query select 'phase'::text, n_rows - n_either, n_rows
    union all select 'synchronization', n_rows, n_rows
    union all select 'registration', n_rows - n_reg, n_rows
    union all select 'documentation', n_rows - n_doc, n_rows;
end $$;
comment on function reproduction.reconcile is 'recount landed and needed for the phase and the three lanes from the indexes and overwrite the totals rows; on demand - after loads and hand edits, never on the tick';

-- the eight old tables, their rows carried over above; the schema shows acris, richmond, updates
drop table reproduction.acris_heartbeats, reproduction.richmond_heartbeats,
           reproduction.acris_claims,     reproduction.richmond_claims,
           reproduction.acris_update_lanes, reproduction.richmond_update_lanes,
           reproduction.acris_update,     reproduction.richmond_update;
