# Richmond Enumeration

The enumeration lane of the richmond reproduction, as one program: `Richmond Enumeration.py`. It is the audit, not a cycle lane: it counts the source, compares with the table, and the difference must be 0. It never writes a cell and has no table in the cloud. This file is the lane's own authority; the cycle's is `../reproduction/Richmond Reproduction.md`; the source's shared rules are in `Reproduction/Richmond/rulebook/richmond.py` (its document is `Richmond.md` beside it).

## The law

**BULK BASELINE + LIVE TAIL = TOTAL** (login, 2026-08-29, for every source). For richmond the baseline is the census window sweep (1850 to the last swept day) and the tail is the trailing date window. The county's date-range listing is the one surface it answers unconditionally: a detail unlocks only after its listing page in the same session, so a cold per-id probe can classify nothing, and the listing gives every internal id directly. The two ranges overlap, the trailing window reaching weeks back past the census's last swept day, so no filing hides in a seam.

## Launch

    python "Richmond Enumeration.py"                                   the trailing 30 days of the county's listing against the table
    python "Richmond Enumeration.py" --days 7
    python "Richmond Enumeration.py" --from 2026-06-01 --to 2026-08-31  a date range, in windows of at most 30 days
    python "Richmond Enumeration.py" --all                             the census: every window from 1850 to today, resumable
    python "Richmond Enumeration.py" report                            the census ledger against the table: listed / held / MISSED / void

Any workstation can run it; the ledger of a census lives beside the file on the workstation that swept it. Exit codes: 0 the difference is 0 · 1 a difference · 7 unproven · 2 refused · 3 the probe is broken or the wire died · 5 crash.

## The three checks

| check | what it proves | what it cannot see |
|---|---|---|
| **the trailing window** (default) — the county's listing for the last 30 days, every internal id checked against the table | the tail: `held N/N · MISSING 0`, or the missing ids named | anything older than the window |
| **the census** (`--all`) — every window of 30 days from 1850, each listed id checked, the ids and the window recorded in `enumeration.census.db`; resumable; the window covering today re-opened every run | the baseline: listed − held = MISSED; held − listed = never listed (until the sweep completes); range − listed = void by the county's own testimony; held + missed + void = range is the 100 % identity | a document the county lists in no window at all |
| **the report** — the ledger against the table without a request | the identity from the last sweep | that the sweep is current: its last swept day is printed |

## The rules

| rule | what the program does | origin |
|---|---|---|
| windows are 30 days or shorter | every window is clamped to the county's cap; `--days 45` is clamped and says so | a 45-day ask answered a silent zero and printed `held 0/0 · MISSING 0` on a window that held hundreds (richmond_audit.py, 2026-08-28) |
| control first, every run | page 1 of a window known to hold documents (2026-08-19..20, 315 recorded) must parse rows, or the parser is broken and no zero from it is believed: exit 3 | rc_window.control, 2026-08-21: a zero window "verified" by a second zero window through the same broken parser printed level for hours |
| an empty denominator is never a pass | a trailing window the county lists as empty is UNPROVEN; a census window that answers empty is recorded as swept (an old month may be empty) but the trailing window never is | the same |
| the trailing window is re-swept | the window covering today is never done; the census re-opens it every run | rc_census, 2026-08-25: four days were silently omitted and the census said COMPLETE |
| a failed window is left unswept | never marked swept; the next run asks it again. The retry unit is the page (three asks), never the window | rc_rd_walk, 2026-08-21: one mid-walk timeout aborted a whole window every sweep |
| two namespaces | the internal id (the ViewDocumentInfo key) is ours: `RC_<internal>`; the instrument number repeats across eras and is never a key | measured 2026-08-21 |
| the sweep is polite | `--workers` 10 at `--pace` 0.3 s between pages, first handshakes 0.4 s apart, keep-alive, one pooled session | the concurrency the county served 2.4M requests at without one trip |
| identify honestly | the user-agent names this project; the county does not gate the listing on it | measured 2026-08-18; naming yourself truthfully is not working around bot detection |
| refusal | a captcha, access-denied or block page stops the run: no retry, no rotation, `enumeration.parked` until `--unpark` | the standing rule |
| never repair a number | a difference is reported, listed and left; nothing here inserts | the security rules |

## Calibrations

| knob | value | how it was measured, how it fails |
|---|---|---|
| window cap | 30 days | the county's measured cap; longer answers a silent zero |
| the history | 1850 to today, about 2,150 windows | 1940 was too late: the first census windows returned 200+ rows a month in 1940; empty 1850s windows cost one request each and prove the start is early enough |
| rows a page | about 18 | "Page 1 of 18" for a two-day window of 315 rows |
| the census | 2,501,708 listings across 2,156 windows in the old ledger (`Richmond Census.db`, 2026-08-21..25) | the new ledger is rebuilt by `--all`; the old one is not read |
| workers, pace | 10, 0.3 s | rc_census: 143k pages, no trip |
| control | 2026-08-19..20, 315 rows | rc_window.control |

## Working files

Beside this file, never in git: `enumeration.report.txt`, `enumeration.log`, `enumeration.missing.txt` (the trailing window's or the sweep's), `enumeration.missed.txt` (the report's), `enumeration.census.db` (the ledger: `listing` and `window`), `enumeration.parked`. The ledger is a working file, rebuildable by sweeping again; the database is the cloud.

## Open

- **Landing what the audit finds.** Missing ids are listed, never inserted; the synchronization lane's insert is the door for new rows.
- **The old ledger.** `Richmond Census.db` on the drive holds the 2026-08 sweep; a fresh `--all` will take about the same time as it did (days at the polite pace). Whether to seed the new ledger from the old one is a decision, not a default: a sweep is the proof, a copy is a claim.

## History

2026-09-05 — the review against the code: the trailing window is `--days` inclusive days (today-29 .. today for 30; it was 31, one more than the module's own `windows()` and both walkers count); a window cut by a stop (a refusal elsewhere, Ctrl+C) returned its PARTIAL rows and was recorded as swept - it is left unswept now; the census's exit code on a wire death is 7, not 3.

2026-09-04 (night) — reviewed against the record (the drumroll rule): the sweep keeps its 0.4-s first handshakes, its 0.3-s pace and no cycle - in the census a wire death leaves that window unswept and the run goes on, leaving with 7 (the ledger asks the window again next run); in the trailing window it ends the run with exit 3 - restarts the record calls free. Nothing changed.

2026-09-04 — written from `rc_window.py` (the listing route, the row pattern, the pager, the control), `rc_census.py` (the windows from 1850, the resumable sweep, the re-opened trailing window, the identity) and `richmond_audit.py` (the trailing window, the clamp, the empty denominator, the verdict), every line read. Proven offline against a fake county and a fake cloud (the parser on the county's markup shape, the pager, the namespace, the refusal shapes, the window arithmetic, the trailing window's three verdicts, the census with a failed window left unswept and resumed, the identity with a phantom, a refusal stopping the sweep) and live against the county's own listing with the still-empty table, where the trailing window must fail and does.
