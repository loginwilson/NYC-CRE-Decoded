# Richmond Update

The board of the richmond reproduction, as one program: `Richmond Update.py`. It always runs and only reads: every minute it takes the counters that the lanes keep exact, subtracts them from its own readings a minute and five minutes back, and writes the two tabs in the cloud. Its database is the two tables `reproduction.richmond_update` (tab 1: the phase) and `reproduction.richmond_update_lanes` (tab 2: one row per lane). The shared rules live in `Reproduction/rulebook/board.py` - the same file the acris board runs on, so both boards say the same thing the same way; this file is the lane's own authority.

## Launch

    python "Richmond Update.py"                 the board, a tick every 60 s
    python "Richmond Update.py" --once          one tick, written
    python "Richmond Update.py" show            read and print both tabs, nothing written
    python "Richmond Update.py" reconcile       recount the counters from the table's indexes and overwrite them

One board per source, on one machine; its `as_of` stamp is its pulse, and a stale stamp is the signal the board died. `update.lock` refuses a second board on the same machine.

## The two tabs

| tab | table | landed | needed |
|---|---|---|---|
| 1 the phase | `richmond_update` | rows with all three cells filled (doc_id, registry, document) | rows in the table |
| 2 the lanes | `richmond_update_lanes` | that lane's cells that are not empty (a fill, `pending` or `absent` - a determination counts) | rows in the table |

Both tabs carry the same metrics: `pct` (landed over needed), the minute kit (`rate_60s`, `increase_60s`, `pct_60s`, `eta_60s`), the window kit (`rate_5m`, `increase_5m`, `pct_5m`, `eta_5m`), `status`, `as_of`. Tab 2 adds the folded heartbeats: `hosts` ("HOST:width" of the workstations alive on the lane), `width` across them, `heartbeat_at` (the freshest), `last_event` (the freshest heartbeat's last word). Synchronization's landed equals needed by construction (its cell is the row itself), so its row reads complete while it runs; its hosts and heartbeat say it is alive.

## The rules

The rules are `board.py`'s and are written in full in `../../Acris/update/Acris Update.md`: the counters are the lanes' (`land()` and `insert_ids()` move them by exactly what was new; the board never counts the table); one subtraction for rate and increase, from the board's own readings ring (`update.state.json`); every percentage over needed; four statuses, computed - complete, stalled (the lane's last word is a refusal or a wall; the phase when any lane's is), active (measured movement outranks every proxy), pending; eta follows status; never clamp (out of bounds publishes no metric and names `reconcile`); reconcile on demand only, never on the tick; a tick never kills the board; a lane is alive when its heartbeat is fresher than `--fresh` (180 s).

What is richmond's own on the board: three small crews, so the rates are small numbers (a 1×8 pull measured about 28 docs/s at the courts host; the walkers land ids and registries by the listing page, in bursts every walk rather than a steady stream), and registration's `pending` cells (premature details) cycle back through the walk, so its landed can hold still while its pendings turn into registries.

## Working files

Beside this file, never in git: `update.state.json` (the readings ring), `update.log`, `update.lock`.

## History

2026-09-03 - the acris board's twin: `board.py` with the richmond source and lanes, nothing else. Proven by the board's own offline proof and its live-cloud simulation (run on the acris tables; the richmond tables are the same shape from the same migration) and by `show` against the empty richmond tabs. Not yet run beside real lanes: that waits for the data move.
