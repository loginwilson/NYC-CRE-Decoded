-- 0010 ACRIS UPDATE and RICHMOND UPDATE as two things a person opens (login 2026-09-06 22:3x: "It should be as simple as going
-- to Acris update, and I should see source Acris, the lane - the full phase, reproduction, or synchronization, registration,
-- documentation - and all those metrics for the 60-second update ... the 5-minute metrics ... landed, needed, the percentage of
-- needed ... the as-of, so I can see it updating minute by minute").
--
-- reproduction.updates is ONE table for both sources (0007): the phase row (lane = 'reproduction'), the three lane rows, and a
-- row per workstation running a lane.  These two views are that table cut per source and laid out in reading order: the
-- phase first, then the lanes in the cycle's order, then the workstation rows; the columns in login's order.  Nothing is
-- computed here - the board program (Acris Update.py / Richmond Update.py) writes the metrics onto the table every minute
-- and the view only reads them.  Views take no lock on the table: safe while lanes land.
create or replace view reproduction.acris_update as
  select lane, workstation, landed, needed, pct,
         rate_60s, increase_60s, pct_60s, eta_60s,
         rate_5m, increase_5m, pct_5m, eta_5m,
         status, workers, last_seen, last_word, as_of
  from reproduction.updates
  where source = 'acris'
  order by workstation <> '',
           case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end,
           workstation;
comment on view reproduction.acris_update is 'ACRIS UPDATE: the board for acris - the phase row (reproduction), the three lanes, then each workstation''s own row; the 60-second and 5-minute metrics, landed / needed / pct, status, workers, the last heartbeat and word, as_of = the board''s pulse (written every minute by Acris Update.py)';

create or replace view reproduction.richmond_update as
  select lane, workstation, landed, needed, pct,
         rate_60s, increase_60s, pct_60s, eta_60s,
         rate_5m, increase_5m, pct_5m, eta_5m,
         status, workers, last_seen, last_word, as_of
  from reproduction.updates
  where source = 'richmond'
  order by workstation <> '',
           case lane when 'reproduction' then 0 when 'synchronization' then 1 when 'registration' then 2 when 'documentation' then 3 else 9 end,
           workstation;
comment on view reproduction.richmond_update is 'RICHMOND UPDATE: the board for richmond - the phase row (reproduction), the three lanes, then each workstation''s own row; the 60-second and 5-minute metrics, landed / needed / pct, status, workers, the last heartbeat and word, as_of = the board''s pulse (written every minute by Richmond Update.py)';
