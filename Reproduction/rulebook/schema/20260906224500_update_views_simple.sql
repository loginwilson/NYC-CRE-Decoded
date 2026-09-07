-- 0011 THE UPDATE VIEWS MADE SIMPLE (login 2026-09-06 22:4x, reading 0010's views in Supabase: "it makes a 3-row Acris into 6 ...
-- half the workstations are empty ... it's showing numbers for other workstations that I haven't started yet ... a lot of 3.57
-- on an empty workstation ... it should be simple").
--
-- The confusion: the one updates table keeps two kinds of rows - the LANE rows (workstation = '', the whole lane across every
-- station) and the WORKSTATION rows (one per machine running a lane, its own count since it joined).  Listed together, the
-- blank workstation reads as "a station not started" and the station's own count reads as a second, disjointed number.
--
-- So: ACRIS UPDATE / RICHMOND UPDATE = the lane rows only, FOUR rows per source, no workstation column - the phase row
-- (reproduction), then synchronization, registration, documentation, with landed / needed / pct, the 60-second block, the
-- 5-minute block, status, workers alive, the last heartbeat and word, as_of.  The per-station detail lives apart, named for
-- what it is: ACRIS WORKSTATIONS / RICHMOND WORKSTATIONS - one row per machine per lane, its own count labelled as such.
-- Views only, no lock; a view's columns change, so drop and create (create or replace cannot remove a column).
drop view if exists reproduction.acris_update;
drop view if exists reproduction.richmond_update;

create view reproduction.acris_update as
  select lane, landed, needed, pct,
         rate_60s, increase_60s, pct_60s, eta_60s,
         rate_5m, increase_5m, pct_5m, eta_5m,
         status, workers, last_seen, last_word, as_of
  from reproduction.updates
  where source = 'acris' and workstation = ''
  order by case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.acris_update is 'ACRIS UPDATE: four rows - the phase (reproduction) and the three lanes, each the whole lane across every workstation; landed / needed / pct, the 60-second and 5-minute blocks (rate, increase, pct increase, eta), status, workers alive, the last heartbeat and word, as_of = the board''s pulse (Acris Update.py, every minute). Per-station detail: acris_workstations';

create view reproduction.richmond_update as
  select lane, landed, needed, pct,
         rate_60s, increase_60s, pct_60s, eta_60s,
         rate_5m, increase_5m, pct_5m, eta_5m,
         status, workers, last_seen, last_word, as_of
  from reproduction.updates
  where source = 'richmond' and workstation = ''
  order by case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.richmond_update is 'RICHMOND UPDATE: four rows - the phase (reproduction) and the three lanes, each the whole lane across every workstation; landed / needed / pct, the 60-second and 5-minute blocks, status, workers alive, the last heartbeat and word, as_of = the board''s pulse (Richmond Update.py, every minute). Per-station detail: richmond_workstations';

create or replace view reproduction.acris_workstations as
  select workstation, lane,
         landed as landed_by_this_station,
         rate_60s, increase_60s, rate_5m, increase_5m,
         status, workers, last_seen, last_word, as_of
  from reproduction.updates
  where source = 'acris' and workstation <> ''
  order by workstation, case lane when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.acris_workstations is 'ACRIS WORKSTATIONS: one row per machine per lane it has run - that machine''s own count since it joined (landed_by_this_station; the lane''s total is in acris_update), its share of the rate, its workers, its last heartbeat and word';

create or replace view reproduction.richmond_workstations as
  select workstation, lane,
         landed as landed_by_this_station,
         rate_60s, increase_60s, rate_5m, increase_5m,
         status, workers, last_seen, last_word, as_of
  from reproduction.updates
  where source = 'richmond' and workstation <> ''
  order by workstation, case lane when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.richmond_workstations is 'RICHMOND WORKSTATIONS: one row per machine per lane it has run - that machine''s own count since it joined (landed_by_this_station; the lane''s total is in richmond_update), its share of the rate, its workers, its last heartbeat and word';
