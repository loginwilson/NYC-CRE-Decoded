-- 0014 THE INTERVAL PERCENT COLUMNS LEAVE THE SOURCE VIEWS (login 2026-09-07 01:1x: "pct increase for the 60 second and 5 min
-- interval isn't as necessary since I never really read it and usually only look at the main overall numbers then the
-- interval rates, increases, and eta").  The board still computes and stores pct_60s / pct_5m in reproduction.updates (nothing
-- lost); the two source views now read: lane | landed | needed | pct | rate_60s | increase_60s | eta_60s | rate_5m |
-- increase_5m | eta_5m | status | as_of_et.  Views only, no lock; dropped and re-created because a column is removed.
drop view if exists reproduction.acris_update;
drop view if exists reproduction.richmond_update;

create view reproduction.acris_update as
  select lane, landed, needed, pct,
         rate_60s, increase_60s, eta_60s,
         rate_5m, increase_5m, eta_5m,
         status, (as_of at time zone 'America/New_York') as as_of_et
  from reproduction.updates
  where source = 'acris' and workstation = ''
  order by case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.acris_update is 'ACRIS UPDATE: four rows - the phase (reproduction) and the three lanes: landed / needed / pct, the 60-second block (rate, increase, eta), the 5-minute block, status, as_of_et = the board''s pulse in Eastern time (Acris Update.py, every minute). Per machine: acris_workstations';

create view reproduction.richmond_update as
  select lane, landed, needed, pct,
         rate_60s, increase_60s, eta_60s,
         rate_5m, increase_5m, eta_5m,
         status, (as_of at time zone 'America/New_York') as as_of_et
  from reproduction.updates
  where source = 'richmond' and workstation = ''
  order by case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end;
comment on view reproduction.richmond_update is 'RICHMOND UPDATE: four rows - the phase (reproduction) and the three lanes: landed / needed / pct, the 60-second block (rate, increase, eta), the 5-minute block, status, as_of_et = the board''s pulse in Eastern time (Richmond Update.py, every minute). Per machine: richmond_workstations';
