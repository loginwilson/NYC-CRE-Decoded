# Acris Update

The board of the acris reproduction, as one program: `Acris Update.py`. It always runs and only reads: every minute it takes the counters that the lanes keep exact, subtracts them from its own readings a minute and five minutes back, and writes the two tabs in the cloud. Its database is the two tables `reproduction.acris_update` (tab 1: the phase) and `reproduction.acris_update_lanes` (tab 2: one row per lane). The shared rules live in `Reproduction/rulebook/board.py`; this file is the lane's own authority.

## Launch

    python "Acris Update.py"                 the board, a tick every 60 s
    python "Acris Update.py" --once          one tick, written
    python "Acris Update.py" show            read and print both tabs, nothing written
    python "Acris Update.py" reconcile       recount the counters from the table's indexes and overwrite them

One board per source, on one machine; its `as_of` stamp is its pulse, and a stale stamp is the signal the board died. `update.lock` refuses a second board on the same machine.

## The two tabs

| tab | table | landed | needed |
|---|---|---|---|
| 1 the phase | `acris_update` | rows with all three cells filled (doc_id, registry, document) | rows in the table |
| 2 the lanes | `acris_update_lanes` | that lane's cells that are not empty (a fill, `pending` or `absent` - a determination counts) | rows in the table |

Both tabs carry the same metrics: `pct` (landed over needed), the minute kit (`rate_60s`, `increase_60s`, `pct_60s`, `eta_60s`), the window kit (`rate_5m`, `increase_5m`, `pct_5m`, `eta_5m`), `status`, `as_of`. Tab 2 adds the folded heartbeats: `hosts` ("HOST:width, HOST2:width" of the workstations alive on the lane), `width` across them, `heartbeat_at` (the freshest), `last_event` (the freshest heartbeat's last word). Synchronization's landed equals needed by construction (its cell is the row itself), so its row reads complete while it runs; its hosts and heartbeat say it is alive.

## The rules

| rule | what the board does | origin |
|---|---|---|
| the counters are the lanes' | `land()` adds exactly what was new to a lane's landed and to the phase's landed (rows whose other cell was already filled); `insert_ids()` adds new rows to every needed and to synchronization's landed. The board never counts the table | SCHEMA.md, the counting rule |
| one subtraction | rate and increase come from the same subtraction of landed between the board's own readings, nearest to 60 s and to 5 min back; the readings ring lives in `update.state.json` and survives a restart | "5.42/s with +0" on the old board, 2026-08-23 |
| the denominator | every percentage is over needed | login 2026-08-23 |
| four statuses, computed | complete: landed >= needed, needed > 0 · stalled: the lane's last word is a refusal or a wall · active: the counters moved in the last window · pending: everything else. The phase row is stalled if any lane's last word is a rejection | login 2026-08-23 (four and only four); SCHEMA.md 2026-09-03 (the status follows the lane) |
| measured movement outranks every proxy | a row whose counters moved is active whatever the heartbeats' freshness says - unless its last word is a rejection: stalled outranks active (the row above) | ACRIS REPRODUCTION.md §4 |
| eta follows status | complete -> "complete"; pending or stalled -> "paused"; active -> from the rate and what remains, on both bases | ACRIS REPRODUCTION.md §4 |
| never clamp | landed outside 0..needed publishes no metrics: the row says OUT OF BOUNDS and names `reconcile` | the anchor that published landed = -20,721,031, 2026-08-23 |
| reconcile on demand | `reconcile` recounts from the primary key and the four partial indexes (index-only) and overwrites the counters, printing the drift; after the data move and after a hand edit, never on the tick | login 2026-09-03: "why are we counting all rows every hour?" |
| a tick never kills the board | a cloud hiccup logs, keeps the readings, and the next tick continues | the board must always run |
| the heartbeats | a lane alive = a heartbeat fresher than `--fresh` (180 s); each lane heartbeats once a minute from every workstation running it | lane.py |

## Reading a row

    UPDATE acris | documentation | 60s   4.80/s     +288  +0.0013%  eta 45.2 days | 5m   4.96/s   +1,488  +0.0069%  eta 43.8 days | 2,912,396 / 21,632,805 = 13.46% | ACTIVE - LOGINSURFACE:40 - last: started 1x40 at 2026-09-04 09:00

The minute kit says what is happening now; the window kit is the performance over time and the eta to trust. Landed over needed is the level. The word at the end is the status, then the workstations alive on the lane and the lane's last word.

## Working files

Beside this file, never in git: `update.state.json` (the readings ring), `update.log`, `update.lock`.

## Open

- **A pulse for the board itself.** `as_of` is the pulse; a person or a monitor reading a stale `as_of` is the alarm. Nothing restarts the board yet; the fleet could host it.
- **Richmond** runs the same `board.py` from `Richmond Update.py` once its lanes exist.

## History

2026-09-05 — the review against the code: stalled outranks active (board.py tests the rejection before the movement); the increase now prints with its sign (`+288`), as this file's example always showed.

2026-09-03 - written from `routine_update.py` and `board_truth.py` (the five metrics, the two windows, the four statuses, one subtraction, never clamp, no scan on a tick) against the tables and functions of migration 0001, every line read. Proven offline (the rate, increase, percentage and eta math over synthetic readings; the status table; the fold of heartbeats; the out-of-bounds gate) and by a simulation against the live cloud with throwaway counters and heartbeats (the rows written and read back, active on movement, pending without a heartbeat, stalled on a refusal's last word, complete at needed, the fold of two workstations, the ring surviving a restart, reconcile restoring the empty table's zeros). Not yet run beside real lanes: that waits for the data move.
