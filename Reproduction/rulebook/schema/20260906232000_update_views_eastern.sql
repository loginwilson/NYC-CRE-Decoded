-- 0013 as_of AND last_seen IN EASTERN TIME (login 2026-09-06 23:1x: "make the as_of timestamp always Eastern - North American
-- Eastern, Toronto or New York - that's where most people view it from").  The board writes as_of and last_seen as `now()`,
-- a timestamptz stored in UTC; Supabase's table editor renders a timestamptz in UTC (the screenshot read 03:14 while it was
-- 23:14 in New York).  `<ts> at time zone 'America/New_York'` turns the stored instant into the wall-clock timestamp in New York
-- (DST handled by the zone), so the column reads 23:14 for every viewer, no client setting.  Views only, no lock; dropped and
-- re-created so the two columns change type (timestamptz -> timestamp in ET).
drop view if exists reproduction.acris_update;
drop view if exists reproduction.richmond_update;
drop view if exists reproduction.acris_workstations;
drop view if exists reproduction.richmond_workstations;

create view reproduction.acris_update as
  select lane, landed, needed, pct,
         rate_60s, increase_60s, pct_60s, eta_60s,
         rate_5m, increase_5m, pct_5m, eta_5m,
         status, (as_of at time zone 'America/New_York') as as_of_et
  from reproduction.updates
  where source = 'acris' and workstation = ''
  order by case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.acris_update is 'ACRIS UPDATE: four rows - the phase (reproduction) and the three lanes: landed / needed / pct, the 60-second block (rate, increase, pct increase, eta), the 5-minute block, status, as_of_et = the board''s pulse in Eastern time (Acris Update.py, every minute). Per machine: acris_workstations';

create view reproduction.richmond_update as
  select lane, landed, needed, pct,
         rate_60s, increase_60s, pct_60s, eta_60s,
         rate_5m, increase_5m, pct_5m, eta_5m,
         status, (as_of at time zone 'America/New_York') as as_of_et
  from reproduction.updates
  where source = 'richmond' and workstation = ''
  order by case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.richmond_update is 'RICHMOND UPDATE: four rows - the phase (reproduction) and the three lanes: landed / needed / pct, the 60-second block, the 5-minute block, status, as_of_et = the board''s pulse in Eastern time (Richmond Update.py, every minute). Per machine: richmond_workstations';

create view reproduction.acris_workstations as
  select workstation, lane,
         landed as landed_by_this_station,
         rate_60s, increase_60s, rate_5m, increase_5m,
         workers, status, last_word,
         (last_seen at time zone 'America/New_York') as last_seen_et,
         (as_of at time zone 'America/New_York') as as_of_et
  from reproduction.updates
  where source = 'acris' and workstation <> ''
  order by workstation, case lane when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.acris_workstations is 'ACRIS WORKSTATIONS: one row per machine per lane - that machine''s own count (the lane total is in acris_update), its 60-second and 5-minute rate and increase, workers, status, last word, last_seen_et and as_of_et in Eastern time';

create view reproduction.richmond_workstations as
  select workstation, lane,
         landed as landed_by_this_station,
         rate_60s, increase_60s, rate_5m, increase_5m,
         workers, status, last_word,
         (last_seen at time zone 'America/New_York') as last_seen_et,
         (as_of at time zone 'America/New_York') as as_of_et
  from reproduction.updates
  where source = 'richmond' and workstation <> ''
  order by workstation, case lane when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.richmond_workstations is 'RICHMOND WORKSTATIONS: one row per machine per lane - that machine''s own count (the lane total is in richmond_update), its 60-second and 5-minute rate and increase, workers, status, last word, last_seen_et and as_of_et in Eastern time';
