-- 0012 THE UPDATE VIEWS WITH ONLY THE COLUMNS A PERSON READS (login 2026-09-06 22:5x: "Acris: its reproduction, synchronization,
-- registration, and its documentation ... a separate table for the same exact thing for workstations ... you probably don't
-- need to see all those counts ... the last word ... the manager should be in the background").
--
-- ACRIS UPDATE / RICHMOND UPDATE: four rows (the phase, then the three lanes), and per row: landed, needed, pct, the 60-second
-- block (rate, increase, pct increase, eta), the 5-minute block (the same four), status, as_of.  Nothing else.  Workers, the
-- last heartbeat and the last word stay on the storage table for the programs and for the WORKSTATIONS views.
-- ACRIS WORKSTATIONS / RICHMOND WORKSTATIONS: one row per machine per lane - the same reading, for that machine alone:
-- landed by that station, its 60-second and 5-minute rate and increase, its workers, its status, its last word, as_of.
-- Views only, no lock; dropped and re-created (a view cannot lose a column through create or replace).
drop view if exists reproduction.acris_update;
drop view if exists reproduction.richmond_update;
drop view if exists reproduction.acris_workstations;
drop view if exists reproduction.richmond_workstations;

create view reproduction.acris_update as
  select lane, landed, needed, pct,
         rate_60s, increase_60s, pct_60s, eta_60s,
         rate_5m, increase_5m, pct_5m, eta_5m,
         status, as_of
  from reproduction.updates
  where source = 'acris' and workstation = ''
  order by case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.acris_update is 'ACRIS UPDATE: four rows - the phase (reproduction) and the three lanes, the whole lane across every workstation: landed / needed / pct, the 60-second block (rate, increase, pct increase, eta), the 5-minute block, status, as_of = the board''s pulse (Acris Update.py, every minute). Per machine: acris_workstations';

create view reproduction.richmond_update as
  select lane, landed, needed, pct,
         rate_60s, increase_60s, pct_60s, eta_60s,
         rate_5m, increase_5m, pct_5m, eta_5m,
         status, as_of
  from reproduction.updates
  where source = 'richmond' and workstation = ''
  order by case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.richmond_update is 'RICHMOND UPDATE: four rows - the phase (reproduction) and the three lanes, the whole lane across every workstation: landed / needed / pct, the 60-second block, the 5-minute block, status, as_of = the board''s pulse (Richmond Update.py, every minute). Per machine: richmond_workstations';

create view reproduction.acris_workstations as
  select workstation, lane,
         landed as landed_by_this_station,
         rate_60s, increase_60s, rate_5m, increase_5m,
         workers, status, last_word, as_of
  from reproduction.updates
  where source = 'acris' and workstation <> ''
  order by workstation, case lane when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.acris_workstations is 'ACRIS WORKSTATIONS: one row per machine per lane it has run - that machine''s own count since it joined (the lane''s total is in acris_update), its 60-second and 5-minute rate and increase, its workers alive, its status and last word, as_of';

create view reproduction.richmond_workstations as
  select workstation, lane,
         landed as landed_by_this_station,
         rate_60s, increase_60s, rate_5m, increase_5m,
         workers, status, last_word, as_of
  from reproduction.updates
  where source = 'richmond' and workstation <> ''
  order by workstation, case lane when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.richmond_workstations is 'RICHMOND WORKSTATIONS: one row per machine per lane it has run - that machine''s own count since it joined (the lane''s total is in richmond_update), its 60-second and 5-minute rate and increase, its workers alive, its status and last word, as_of';
