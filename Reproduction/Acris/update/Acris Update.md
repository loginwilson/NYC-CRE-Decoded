# Acris Update

The board of the acris reproduction, as one program: `Acris Update.py`. It always runs and only reads: every minute it takes the counters that the lanes keep exact, subtracts them from its own readings a minute and five minutes back, and writes rate, increase, eta, percentage, status and the as-of stamp back into `machinery.updates`. What a person opens is `reproduction.acris_update`: three blocks of four rows (below). The shared rules live in `Reproduction/rulebook/rulebook.py` (its board part) - the same file the richmond board runs on, so both boards say the same thing the same way; this file is the lane's own authority.

## Launch

    python "Acris Update.py"                 the board, a tick every 60 s
    python "Acris Update.py" --once          one tick, written
    python "Acris Update.py" show            read and print every row, nothing written
    python "Acris Update.py" reconcile       recount the counters from the table's indexes and overwrite them
    python "Acris Update.py" --every 30      a tick every 30 s instead of 60
    python "Acris Update.py" --host Office2  this workstation's name in the cloud (default: the machine name); --fresh 180 = a heartbeat older than this is not alive

One board per source, on one machine; its `as_of` stamp is its pulse, and a stale stamp is the signal the board died. `update.lock` refuses a second board on the same machine.

## The board

What a person opens is `reproduction.acris_update` (0017, 0018, 0019): three blocks of four rows, a blank spacer row before each workstation block. The Table Editor does not show a view in the view's own order - it sorts by the first column - so every row, the spacers too, carries the source in that column and the order comes through as written (measured 2026-09-07 13:40).

| block | rows | landed | needed |
|---|---|---|---|
| the totals | reproduction total · identification total · registration total · documentation total | reproduction: rows with all three cells filled (identifier, registry, document); a lane: that lane's cells that are not empty (a fill, `pending` or `absent` - a determination counts) | rows in the table |
| workstation 1 | reproduction 1 · identification 1 · registration 1 · documentation 1 | what this workstation landed (its completions on the reproduction row); its number is the order of its first sight | the lane's |
| workstation 2 | the same four, numbered 2 | the same; until the workstation first reports the block reads `pending` with its labels alone (login: "might as well have the second one pending in case we ever had to") | the lane's |

Columns, in reading order: `source`, `lane`, `status`, `as_of_et` (Eastern), the minute kit (`rate_60s`, `increase_60s`, `eta_60s`), the window kit (`rate_5m`, `increase_5m`, `eta_5m`), `landed`, `needed`, `pct`. A workstation row's percentage is its count over the lane's needed, its eta the lane's remaining at this workstation's rate, and it reads `complete` when the lane is level. Every column of the view is text, the as-of is written to the second, and a blank cell is one space - the Table Editor prints EMPTY for an empty string and NULL for a null, so this is the only way a spacer row shows as nothing (0019); nothing in the code reads the view. The table behind the view, `machinery.updates`, also keeps each row's `workers`, `last_seen` and `last_word` (the lane's heartbeat); the board folds them into the status and never shows them.

## The rules

| rule | what the board does | origin |
|---|---|---|
| the counters are the lanes' | `land()` adds exactly what was new to a lane's landed and to the phase's landed (rows whose other cell was already filled); `insert_ids()` adds new rows to every needed and to identification's landed. The board never counts the table | `Reproduction/rulebook/Rulebook.md`, the counting rule |
| one subtraction | rate and increase come from the same subtraction of landed between the board's own readings, nearest to 60 s and to 5 min back; the readings ring lives in `update.state.json` and survives a restart | "5.42/s with +0" on the old board, 2026-08-23 |
| the denominator | every percentage is over needed | login 2026-08-23 |
| four statuses, computed | complete: landed >= needed, needed > 0 · stalled: the lane's last word is a refusal or a wall · active: the counters moved in the last window · pending: everything else. The phase row is stalled if any lane's last word is a rejection | login 2026-08-23 (four and only four); `Reproduction/rulebook/Rulebook.md` 2026-09-03 (the status follows the lane) |
| measured movement outranks every proxy | a row whose counters moved is active whatever the heartbeats' freshness says - unless its last word is a rejection: stalled outranks active (the row above) | `../workflow/reproduction/Acris Reproduction.md` §4 |
| eta follows status | complete -> "complete"; pending or stalled -> "paused"; active -> from the rate and what remains, on both bases | `../workflow/reproduction/Acris Reproduction.md` §4 |
| never clamp | landed outside 0..needed publishes no metrics: the row says OUT OF BOUNDS and names `reconcile` | the anchor that published landed = -20,721,031, 2026-08-23 |
| reconcile on demand | `reconcile` recounts from the primary key and the four partial indexes (index-only) and overwrites the counters, printing the drift; after the data move and after a hand edit, never on the tick | login 2026-09-03: "why are we counting all rows every hour?" |
| a tick never kills the board | a cloud hiccup logs, keeps the readings, and the next tick continues | the board must always run |
| the heartbeats | a lane alive = a heartbeat fresher than `--fresh` (180 s); each lane heartbeats once a minute from every workstation running it | rulebook.py |

## Reading a row

    UPDATE acris | documentation | 60s   4.80/s     +288  +0.0013%  eta 45.2 days | 5m   4.96/s   +1,488  +0.0069%  eta 43.8 days | 2,912,396 / 21,632,805 = 13.46% | ACTIVE - LOGINSURFACE:40 - last: started 1x40 at 2026-09-04 09:00

The minute kit says what is happening now; the window kit is the performance over time and the eta to trust. Landed over needed is the level. The word at the end is the status, then the workstations alive on the lane and the lane's last word.

## Working files

Beside this file, never in git: `update.state.json` (the readings ring), `update.log`, `update.lock`. Exit codes: 0 stopped · 1 refused to start (a board already runs on this machine: `update.lock`) · 5 crash.

## Open

- **A pulse for the board itself.** `as_of` is the pulse; a person or a monitor reading a stale `as_of` is the alarm. Nothing restarts the board yet; the fleet could host it.

## History

2026-09-03 — written from `routine_update.py` and `board_truth.py` (the five metrics, the two windows, the four statuses, one subtraction, never clamp, no scan on a tick) against the tables and functions of migration 0001, every line read. Proven offline (the rate, increase, percentage and eta math over synthetic readings; the status table; the fold of heartbeats; the out-of-bounds gate) and by a simulation against the live cloud with throwaway counters and heartbeats (the rows written and read back, active on movement, pending without a heartbeat, stalled on a refusal's last word, complete at needed, the fold of two workstations, the ring surviving a restart, reconcile restoring the empty table's zeros). Not yet run beside real lanes: that waits for the data move.

2026-09-05 — the review against the code: stalled outranks active (board.py tests the rejection before the movement); the increase now prints with its sign (`+288`), as this file's example always showed.

2026-09-06 — 0007: THE TWO TABS ARE ONE TABLE. login: "You have a database, and you have an updating table that shows you how
you're progressing on filling in that database." `machinery.updates`, source first: the phase row (`lane = reproduction`),
the three lane rows, and a row per workstation running a lane - its own landed count (moved by `land()` and `insert_ids`),
its rate from the board's own subtraction, its workers, `last_seen` (the heartbeat; fresher than `--fresh` = alive) and its
last word. The heartbeats table is gone into those rows; the claims moved out of sight into the schema `machinery`. The
board reads and writes the one table; `show` prints every row.

2026-09-06 22:38 — what a person opens is `reproduction.acris_update` (0010): this board's rows for acris alone, the phase row first, the lanes in the cycle's order, then the workstation rows, columns in reading order (Supabase.md 0010). This program must run beside the lanes: started 22:34 tonight, four minutes after the document lane - the pace columns were blank until its first tick.

2026-09-07 13:18 — 0017: THE BOARD IN THREE BLOCKS, source before lane (login: "reproduction, identification, registration, documentation. Those four are in a total block, and after that, there is a space, and then it goes into the workstation 1 block and then the workstation 2 block ... all in the one table for each source"). The lane row is `identification`. This program's board part writes the workstation rows' percentage (over the lane's needed), eta (the lane's remaining at the workstation's rate) and `complete` when the lane is level; a workstation's reproduction row follows its lanes' last word as the total's does.

2026-09-07 13:4x — 0018: the Table Editor sorts a view by its first column (login, seeing the rows scrambled: "That doesn't look good"); every row carries the source, the totals read `reproduction total` ... `documentation total`, an unclaimed workstation block reads `pending`.

2026-09-07 14:0x — 0019: the spacer rows blank (login: "can they just be blank to act as a spacer? ... Just an aesthetic thing"): every column text, a blank is one space, the as-of to the second.

2026-09-07 — the audit of the source folder against the code: the origins name `Reproduction/rulebook/Rulebook.md` and `Acris Reproduction.md` (no `SCHEMA.md` exists since 09-05 - it became Rulebook.md's section "The table"); the exit codes written (0 · 1 a board already runs here · 5); the program's docstring names `../../rulebook/rulebook.py`; this history in one order, oldest first.

2026-09-07 14:29 — a workstation row is that machine's total, all time (login, reading the board: "this last part where it shows the landed, the needed, and the percentage is false because it's supposed to show the total for that workstation ... right now, everything should be actually the same between Total and Workstation 1"). Everything before the second workstation was this machine's, so workstation 1 was seeded to the totals (all four rows, both sources; acris 3,779,204 documents, 21,631,885 identifications and registrations); from here `land()` and `insert_ids()` credit each landing to its workstation and the total alike, and the workstation rows sum to the total. The boards restarted on a fresh readings ring so the seed showed no false rate.
