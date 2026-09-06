# Richmond Synchronization

The synchronization lane of the richmond reproduction, as one program: `Richmond Synchronization.py`. It keeps the table live at the county's date edge: one monitor and a few walkers behind one entry. The monitor reads today's listing every ten seconds and lands every new internal id as a new row, the `doc_id` cell and nothing else, within seconds of the county listing it; every quarter hour it re-reads the trailing thirty days so a filing the county lists late lands too; on a start after downtime it walks the days it missed. This file is the lane's own authority; the cycle's is `../reproduction/Richmond Reproduction.md`; the source's shared rules are in `Reproduction/Richmond/rulebook/richmond.py` (its document is `Richmond.md` beside it).

## Why the date edge

Richmond County lists its recorded instruments by date range, with every row carrying the internal id, and answers that listing unconditionally (a detail unlocks only after its listing page in the same session, which is registration's business). There is no counter to stand at, as at ACRIS; the calendar is the edge, and the county back-dates a late entry to its recorded day, so the live window has to be re-read for a while after each day closes. The old lane's cadence, a probe every ten seconds and a heal every fifteen minutes over thirty days, is kept.

## Launch

    python "Richmond Synchronization.py" --edge 2026-08-25      the first start names the last day walked
    python "Richmond Synchronization.py"                        afterwards synchronization.edge.json remembers it

One machine: the edge is local state. `--width` defaults to 4 walkers (the day window, the heal, a catch-up). `--every 10 --heal-every 900 --heal-days 30 --pace 0.3` are the cadence knobs. `synchronization.control` takes `width=N` or `stop`. A parked lane refuses to start again until `--unpark`.

## The rules

| rule | what the lane does | origin |
|---|---|---|
| the edge | `synchronization.edge.json` holds the last day whose listing was walked. A start without it needs `--edge`, never a guess. The edge moves only over windows whose ids are in the table and never past a window still in flight or holed, so a crash re-walks from the last contiguous day and loses nothing | the acris lane's edge; the census's last swept day |
| the day | today's listing every `--every` seconds; a new filing lands within seconds | rc_lane's probe every 10 s (Richmond Reproduction.md §1) |
| the heal | the trailing `--heal-days` (30, inclusive) every `--heal-every` seconds (15 min); never a window longer than the county's cap | rc_lane's rd heal, 15 min over 30 days; the 30-day cap answers a silent zero beyond it |
| catch-up | on a start, the days between the edge and the heal window are walked first, in windows of at most 30 days | the census's resumable windows |
| control first | a window known to hold documents (2026-08-19..20, 315 rows) is asked at start and before every heal; if it parses nothing, the parser is broken and the lane parks (exit 3) rather than believing empty answers | rc_window.control, 2026-08-21: a sync printed level for hours on a false zero |
| a blank is an answer | the county listed nothing for that day: weekends, holidays, early morning | the listing is the county's own |
| an error is not an absence | a page that fails is asked again (three asks by the monitor; each time a transport error is retried once more by the crew); a window that keeps failing is recorded in `synchronization.holes.jsonl` and the next heal asks it again | rc_rd_walk, 2026-08-21: the retry unit must never be bigger than the failure unit |
| two namespaces | the internal id is ours: `RC_<internal>`; the instrument number repeats across eras and is never a key | measured 2026-08-21 |
| the cell | the `doc_id` only; the counters move with the insert in the same transaction | the cell rule; `insert_ids()` |
| ids landed once | the monitor remembers the ids it has landed for the heal window and sends only new ones to the cloud | ten-second probes must not re-send the day's ids |
| one entry, one door, refusal, hang-up, wall, width | shared with every lane; a county refusal shape (captcha, access denied, block page) is a `lane.Refused`. The hang-up is DORMANT at this county (no session close was ever measured here): it fires only when the wire itself dies - every walker a transport error inside 60 s with nothing answered for 10 s - and then the cut windows are dropped from the queue and forgotten as in flight (`rebatch`: asked again at the next heal, the day window at the next tick, a control before the heal), 60 s of silence, one re-entry with births 0.4 s apart; four refused re-entries in a row park it | lane.py; richmond.py; Richmond Reproduction.md §3 (the drumroll rule) |
| identify honestly | the user-agent names this project | measured 2026-08-18; the standing line on bot detection |

## Calibrations

| knob | value | how it was measured, how it fails |
|---|---|---|
| every | 10 s | the old probe's cadence; today's listing is a few pages, so the cost is under a request a second |
| heal | 900 s over 30 days | the old heal; about 150 pages a quarter hour |
| pace | 0.3 s between pages | the census's pace against this county, 143k pages without a trip |
| width | 4 | the day window, the heal window and a catch-up window are the only work; more walkers buy nothing |
| stagger | 0.4 s | the county's measured handshake stagger (160 cold opens at once = SSLError); keep-alive after |
| control | 2026-08-19..20, 315 rows | rc_window.control |
| memory | the ids of the last 37 days | the heal window plus a week; pruned past 200,000 |

## The blind spot, written down

A date edge sees what the county lists for the dates it re-reads. A document listed more than thirty days late, or one the county re-keys, is invisible to this lane. The audit (`Richmond Enumeration.py`, the census) is the ground truth on a slower schedule. This lane never claims otherwise.

## Working files

Beside this file, never in git: `synchronization.edge.json`, `synchronization.holes.jsonl`, `synchronization.lock`, `synchronization.log` (every launch's output, appended), `synchronization.control`, `synchronization.parked`, `synchronization.fails.jsonl`. Exit codes: 0 stopped · 2 refused · 3 four re-entries in a row refused, or the probe broken (the lane parked itself) · 4 wall · 5 crash.

## History

2026-09-05 — the review against the code: when `insert_ids` failed, the answered windows were already forgotten and their ids neither in `seen` nor re-asked - lost for the run, and the edge could move past them; the answers now stay on the crew for the next minute. The three asks are the monitor's; the crew's own transport retry comes on top.

2026-09-04 (night) — the review against the record: `rebatch` added so a dead wire can never leave a window stuck as in flight (the edge would have frozen behind it); births set to the county's 0.4 s; the inherited cycle named dormant. Proven again offline and by the simulation.

2026-09-03 — written from `rc_lane.py` (the probe and the heal cadence), `rc_window.py` (the listing route, the row pattern, the control) and the richmond audit's window rules, every line read. Proven offline against a fake crew and a fake cloud (the control first, the catch-up from the edge, the heal window inclusive of thirty days, ids landed once, the edge moving only after the rows are in, a hole after three failed asks, a control that fails three asks re-asked, a broken control parking the lane, the fail-closed edge file) and by a simulated walk against the live cloud with throwaway ids and no county request: a catch-up window, a heal window, the day window with a filing appearing mid-run, a window failing every ask recorded as a hole, the edge file at today, the counters moved by exactly the rows inserted. Not yet proven: a real listing read from the lane, which waits for the data move.

2026-09-05 23:54 — THE FIRST REAL RUN, against the cloud with the rows in (login: "spend the night resyncing ... Richmond, you
could do more, but one batch"): `--edge 2026-08-31` (the old rc_lane's last live page was 09/01/2026 page 7 at 12:50; the
cloud's newest recorded date was 2026-09-01), the calibrated width 4. Exit pool one block (173.239.217), entered 23:54:17,
births 0 s apart. The control window parsed; the catch-up (09-01..09-05) and the trailing heal listed 2,625 ids and
inserted 435 new rows by 23:56:09, holes 0, the edge at 2026-09-05; today's listing was empty at midnight (a blank is an
answer). Stopped by `synchronization.control` at 23:57:09 (exit 0) so the registration lane could take the county alone.
