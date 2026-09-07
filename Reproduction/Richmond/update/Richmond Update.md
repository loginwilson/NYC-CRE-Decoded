# Richmond Update

The board of the richmond reproduction, as one program: `Richmond Update.py`. It always runs and only reads: every minute it takes the counters that the lanes keep exact, subtracts them from its own readings a minute and five minutes back, and writes rate, increase, eta, percentage, status and the as-of stamp back into `machinery.updates`. What a person opens is `reproduction.richmond_update`: three blocks of four rows (below). The shared rules live in `Reproduction/rulebook/rulebook.py` (its board part) - the same file the acris board runs on, so both boards say the same thing the same way; this file is the lane's own authority.

## Launch

    python "Richmond Update.py"                 the board, a tick every 60 s
    python "Richmond Update.py" --once          one tick, written
    python "Richmond Update.py" show            read and print every row, nothing written
    python "Richmond Update.py" reconcile       recount the counters from the table's indexes and overwrite them
    python "Richmond Update.py" --every 30      a tick every 30 s instead of 60
    python "Richmond Update.py" --host Office2  this workstation's name in the cloud (default: the machine name); --fresh 180 = a heartbeat older than this is not alive

One board per source, on one machine; its `as_of` stamp is its pulse, and a stale stamp is the signal the board died. `update.lock` refuses a second board on the same machine.

## The board

What a person opens is `reproduction.richmond_update` (0017, 0018, 0019): three blocks of four rows, a blank spacer row before each workstation block. The Table Editor does not show a view in the view's own order - it sorts by the first column - so every row, the spacers too, carries the source in that column and the order comes through as written (measured 2026-09-07 13:40).

| block | rows | landed | needed |
|---|---|---|---|
| the totals | reproduction total · identification total · registration total · documentation total | reproduction: rows with all three cells filled (identifier, registry, document); a lane: that lane's cells that are not empty (a fill, `pending` or `absent` - a determination counts) | rows in the table |
| workstation 1 | reproduction 1 · identification 1 · registration 1 · documentation 1 | what this workstation landed (its completions on the reproduction row); its number is the order of its first sight | the lane's |
| workstation 2 | the same four, numbered 2 | the same; until the workstation first reports the block reads `pending` with its labels alone (login: "might as well have the second one pending in case we ever had to") | the lane's |

Columns, in reading order: `source`, `lane`, `status`, `as_of_et` (Eastern), the minute kit (`rate_60s`, `increase_60s`, `eta_60s`), the window kit (`rate_5m`, `increase_5m`, `eta_5m`), `landed`, `needed`, `pct`. A workstation row's percentage is its count over the lane's needed, its eta the lane's remaining at this workstation's rate, and it reads `complete` when the lane is level. Every column of the view is text, the as-of is written to the second, and a blank cell is one space - the Table Editor prints EMPTY for an empty string and NULL for a null, so this is the only way a spacer row shows as nothing (0019); nothing in the code reads the view. The table behind the view, `machinery.updates`, also keeps each row's `workers`, `last_seen` and `last_word` (the lane's heartbeat); the board folds them into the status and never shows them.

## The rules

The rules are `rulebook.py`'s (its board part) and are written in full in `../../Acris/update/Acris Update.md`: the counters are the lanes' (`land()` and `insert_ids()` move them by exactly what was new; the board never counts the table); one subtraction for rate and increase, from the board's own readings ring (`update.state.json`); every percentage over needed; four statuses, computed - complete, stalled (the lane's last word is a refusal or a wall; the phase when any lane's is), active (measured movement outranks every proxy), pending; eta follows status; never clamp (out of bounds publishes no metric and names `reconcile`); reconcile on demand only, never on the tick; a tick never kills the board; a lane is alive when its heartbeat is fresher than `--fresh` (180 s).

What is richmond's own on the board: three small crews, so the rates are small numbers (a 1×8 pull measured about 28 docs/s at the courts host; the walkers land ids and registries by the listing page, in bursts every walk rather than a steady stream), and registration's `pending` cells (premature details) cycle back through the walk, so its landed can hold still while its pendings turn into registries.

## Working files

Beside this file, never in git: `update.state.json` (the readings ring), `update.log`, `update.lock`.

## History

2026-09-03 - the acris board's twin: `board.py` with the richmond source and lanes, nothing else. Proven by the board's own offline proof and its live-cloud simulation (run on the acris tables; the richmond tables are the same shape from the same migration) and by `show` against the empty richmond tabs. Not yet run beside real lanes: that waits for the data move.

2026-09-06 — 0007: THE TWO TABS ARE ONE TABLE. login: "You have a database, and you have an updating table that shows you how
you're progressing on filling in that database." `machinery.updates`, source first: the phase row (`lane = reproduction`),
the three lane rows, and a row per workstation running a lane - its own landed count (moved by `land()` and `insert_ids`),
its rate from the board's own subtraction, its workers, `last_seen` (the heartbeat; fresher than `--fresh` = alive) and its
last word. The heartbeats table is gone into those rows; the claims moved out of sight into the schema `machinery`. The
board reads and writes the one table; `show` prints every row.

2026-09-07 13:18 — 0017: THE BOARD IN THREE BLOCKS, source before lane (login: "reproduction, identification, registration, documentation. Those four are in a total block, and after that, there is a space, and then it goes into the workstation 1 block and then the workstation 2 block ... all in the one table for each source"). The lane row is `identification`. This program's board part writes the workstation rows' percentage (over the lane's needed), eta (the lane's remaining at the workstation's rate) and `complete` when the lane is level; a workstation's reproduction row follows its lanes' last word as the total's does.

2026-09-07 13:4x — 0018: the Table Editor sorts a view by its first column (login, seeing the rows scrambled: "That doesn't look good"); every row carries the source, the totals read `reproduction total` ... `documentation total`, an unclaimed workstation block reads `pending`.

2026-09-07 14:0x — 0019: the spacer rows blank (login: "can they just be blank to act as a spacer? ... Just an aesthetic thing"): every column text, a blank is one space, the as-of to the second.

2026-09-07 14:29 — a workstation row is that machine's total, all time (login, reading the board: "this last part where it shows the landed, the needed, and the percentage is false because it's supposed to show the total for that workstation ... right now, everything should be actually the same between Total and Workstation 1"). Everything before the second workstation was this machine's, so workstation 1 was seeded to the totals (all four rows, both sources); from here `land()` and `insert_ids()` credit each landing to its workstation and the total alike, and the workstation rows sum to the total. The boards restarted on a fresh readings ring so the seed showed no false rate.
