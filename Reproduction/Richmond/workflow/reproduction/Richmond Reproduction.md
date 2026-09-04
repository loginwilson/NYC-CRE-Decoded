# RICHMOND REPRODUCTION

> Reproduce Richmond County's recorded-instrument corpus in
> `Legal Instruments.db` — every doc id, its recorded details, its image —
> complete, current within minutes, and PROVEN so by the update board.
> Closed COMPLETE and week-audited 2026-08-28. This file is the authority
> for what runs richmond and what "right" looks like; change the lane's
> shape in `fleet.py`, change the rules HERE.
>
> Three named parts (login 2026-08-28): **THE CYCLE** (the pipeline that
> reproduces), **RICHMOND UPDATE** (the board that tracks it), and
> **RICHMOND AUDIT** (the enumeration safety check — NOT part of the
> cycle; run it whenever you want a proof).

> **Reading order (2026-09-03).** Section 0 is the fleet program that runs this source in the NYC-CRE-Decoded tree; the lane mds under `workflow/` and `SCHEMA.md` are the authorities for the running code. Sections 1 onward are the pre-repo authority - the decoder era, `Legal Instruments.db`, the old lane files - kept whole as the record of what was measured. Where they contradict a lane's md or `SCHEMA.md`, the lane md and `SCHEMA.md` win. Translations: an empty cell is NULL (the old `''`); the two verdict words are `pending` and `absent` (the old `imageless` / `unservable` are `absent`); the to-do list is the cloud table (`claim`), not a local db; the old `fleet.py` roster is `Reproduction/fleet.py` + `<Source> Reproduction.py`; the old lane files (`acris_reproduction.py`, `rc_lane.py`) are the lane programs under `workflow/`.

## 0 · THE FLEET PROGRAM — `Richmond Reproduction.py` (2026-09-03)

The cycle's lanes as one launch: `Reproduction/Richmond/workflow/reproduction/Richmond Reproduction.py`
in the NYC-CRE-Decoded tree, a thin site over the shared `Reproduction/fleet.py` (the same machinery
runs the acris fleet). Each lane is its own program with its own lock, park, control file and log; the
fleet launches them in the cycle's order, one door at a time, and watches them. It relaunches what a
relaunch can cure and never relaunches what a person must decide.

    python "Richmond Reproduction.py" --drive NYCCRED1 --edge 2026-08-25     home: synchronization x4, registration x4, documentation x8 - one process per lane, 20 s apart; --edge on the FIRST start only
    python "Richmond Reproduction.py" --drive NYCCRED2 --lanes documentation:8
                                                                           workstation 2: documentation only (see "one station" below)
    python "Richmond Reproduction.py" status                                 this machine's lanes, and every workstation's heartbeats in the cloud
    python "Richmond Reproduction.py" stop [lane]                            `stop` into the control file(s), a 90 s grace, then force
    python "Richmond Reproduction.py" width documentation=24                 into the lane's control file (read within a minute)

| rule | what the fleet does | origin |
|---|---|---|
| one process per lane | the default; `--mega` is the exception | the GIL is the throughput wall (acris §3) |
| one door per lane, `--entry-gap` apart | lanes launched 20 s apart; births inside a lane 0.4 s apart (`--stagger`, set in each richmond lane: the county's measured handshake stagger) | three doors, never one moment; 160 cold TLS opens in one instant = SSLError across the board (§3) |
| the cycle, dormant | every lane carries the shared cycle (`lane.py`: one entry, staggered births, a hang-up when the whole width dies with nothing landing, a 60-s wait, one re-entry, the cut batch dropped) and at this county it is DORMANT: no session close was ever measured here - the drumroll rule stands, no pacer, latency is the governor, restarts are free, stop-on-refusal is the only safety. It fires only when the wire itself dies (wifi, a dead host), the right thing then; the walkers drop their cut windows and pages and ask them again at the next heal or walk | §3 calibrations; login 2026-09-04: "richmond can just enter and hammer" - the record agrees |
| maturation | inside the documentation lane: a `pending` comes back from the claim after `--pending-age` and is minted again; past the 7-day lag it lands `absent` - the old 4 AM `rc_pdf_state --apply` pass cannot be separated from the lane any more | the 4 AM tasks section below |
| one station for the walkers | synchronization and registration WALK the county's listing (the grant is per listing page, so no claim can split that work); two walkers of the same window would spend the county's requests twice. Workstation 2 runs documentation only, which claims its slice from the table | Richmond Registration.md, "one machine" |
| the edge is a date | `--edge YYYY-MM-DD` goes to synchronization and registration on a first start (each keeps its own `*.edge.json` afterwards); a later `--edge` that disagrees with the file is refused | the two walkers' edge files |
| widths | 4 / 4 / 8: the county has no metronome, latency is its backpressure; 8 pullers measured 28.23 docs/s against 18.76 at 16 (rc_bench 2026-08-25, one variable) | §3 calibrations |
| pending window | documentation's `--fresh-days` defaults to the measured 7-day scan lag | rc_source IMAGE_LAG_DAYS |
| what each exit means | 0 done · 1 refused to start: left alone · 2 REFUSED: every lane told to stop, exit 2, a person decides · 3 four re-entries in a row refused, or the probe broken: the lane parked itself, never relaunched, a person decides · 4 wall: parked by the lane, left · 5 crash: relaunch after 60 s · 6 drive gone: wait for the drive, relaunch with `--unpark` | fleet.py |
| the relaunch cap | more than `--relaunch-cap` (3) launches of one lane in an hour parks it with the reason | every start is a stampede of handshakes |
| a parked lane is never relaunched | the drive's return is the one exception, because the fleet can verify it | the park is the lane's word, or a person's |
| logs appended, never truncated | `<lane>/<lane>.log` with a fleet banner at every launch | 2026-09-03 |
| one fleet per machine | `reproduction.lock`; the lanes' own locks refuse a double, so a lane running by hand is left alone | trap 8 |
| cross-station | `status` reads `reproduction.richmond_heartbeats` | SCHEMA.md |

Proven 2026-09-03 by the fleet simulation over fake `Richmond <Lane>.py` programs (the same
simulation that proved the acris fleet, pointed at this site): the order and the gap; crashes
relaunched and the cap; a refusal stilling every lane; the drive's return; a lane already running
refused and left; the mega lane; width, stop and status. Not yet run on the real lanes: that waits
for the data move. Re-proven 2026-09-04 (night) after the review.

## 1 · THE CYCLE (login's words — this IS richmond reproduction)

**synchronization** — doc ids flow into the db, with the MONITOR (the
probe, every 10 s) live-tracking doc inflow on the day window: a new
filing's id lands within seconds of the county listing it.

**mint** — built into the db logic: the `mint_urls` trigger forms both
urls from the doc id in the same transaction as the insert. The urls are
how rd and pdf navigate. No process, no forgetting.

**rd** — acquires the recorded details and populates them into the row's
cells. In-session only, after the listing page (the grant rule below);
the heal (every 15 min, 30-day window) catches any filing whose detail
lagged its listing. A failed fetch is a RETRY next cycle, never a verdict
(measured 2026-08-28: failed 4 → landed 4 on the following pass).

**pdf** — acquires the image, sends it to the right folder in the store,
and copies the path into the db, with the path / pending / absent logic:

    a real path    the scan, fetched and landed in the store (evidence)
    'pending'      CHECKED - the source itself says the scan is not up
                   yet ("No Image Available At This Time") - re-asked
                   every 5 min until it uploads
    'absent'       CHECKED - determined no image (the url does not show)
    ''             NOT YET CHECKED - the honest todo, never a verdict

`pending` and `absent` are DETERMINATIONS and count as landed; `''` is
the only unlanded state; NULL must never appear.

**keying** — RETIRED 2026-08-27. Columns physically present, nothing
writes them. ⚠ NAMING (login): "richmond sync" the lane IS richmond
reproduction now — the rename (rc_lane → richmond_reproduction) is
DEFERRED to the key-column removal, because renaming a lane with docs
inflowing risks more than it buys. Never reproduce and delete/rename at
the same time.

## 2 · THE CODE (the roster — what richmond reproduction IS)

| piece | file | job |
|---|---|---|
| THE CYCLE | `decoder\rc_lane.py` | the ONLY richmond process: monitor/probe every 10 s (day pages, sync landings) · rd heal every 15 min over a 30-day window · 24 miners (mint asks) · 8 pullers (image fetch + land) · pending recheck every 5 min. Launch: `python fleet.py start sync`. |
| RICHMOND AUDIT | `decoder\richmond_audit.py` | the enumeration safety check, one command (see §5). |
| census sweeper | `decoder\rc_census.py` | the audit's historical baseline: `--run` sweeps the county's whole listed history (resumable); `--report` prints listed/held/void. |
| RICHMOND UPDATE | `Updates\board_truth.py` + `Updates\routine_update.py` | the anchor (landed = total − todo, richmond counted live 60 s) and the row renderer (see §4). |
| roster | `decoder\fleet.py` | the lane's args (`--apply --miners 24 --workers 8`), PAUSED mechanism, singleton guard; Fleet Guard restarts crashed lanes within 5 min. |
| db triggers | in `Legal Instruments.db` | `mint_urls` (the minter) · `key_on_rd` (dormant). |

Retired, never to run beside the lane: rc_live, rc_feed, rc_pdf_pull,
rc_pdf_land, rc_rd_walk (`_archive/richmond_preconsolidation/`). Two
minters double-serve ids — served_ids is per-process.

## 3 · CALIBRATIONS (values + the conditions they were measured under)

- **DRUMROLL RULE**: no pacer, no governor — latency is the only
  governor. Proven 160 concurrent connections, 26 h clean. The ONLY
  safety is stop-on-refusal, and the rd heal stopping says nothing about
  the pdf host (different host, self-authenticating tokens).
- **Pullers = 8** (rc_bench 2026-08-25, single variable: 8 → 28.23
  docs/s · 16 → 18.76 — past the pipe, self-contending). Richmond is
  BANDWIDTH-shaped (~5 MB docs); acris is latency-shaped. Never read one
  lane's rate as evidence about the other.
- **First handshakes staggered** 0.4 s/worker; keep-alive removes every
  later handshake. 160 cold TLS opens in one instant = SSLError across
  the board.
- **THE GRANT RULE** (2026-08-21): a detail unlocks only after THIS
  session fetched the LISTING PAGE the id appears on. A cold detail
  fetch returns HTTP 200 and a 4,212-byte lie. Window → pages →
  details, same session, always.
- **TWO NUMBER NAMESPACES**: internal id (RC_<n>, ours) ≠ instrument
  number (repeats!). Probes must pin the internal id.
- **30-day heal window** = the absent-verdict line: inside it, absent/
  pending are scan-lag, re-asked; outside it we stop asking and an
  un-minted row keeps `''`. 10/10 Friday docs read "absent" and were
  "present" by Monday — first readings are never verdicts.
- **The eject/wifi hold**: park rc_lane + routine_update + board_truth
  in fleet.py PAUSED before pulling D: or losing the network (a lane on
  a dead drive WEDGES silently). Resume = remove the names; the guard
  restarts them.
- Lane restarts are free (drumroll) — richmond stops/starts at full
  speed, unlike acris.

## 4 · RICHMOND UPDATE (the board, fine-tuned to track the cycle)

One row `synchronization | richmond`, proven live 2026-08-28:

- `needed` moves with the filings — board_truth counts richmond's total
  LIVE every 60 s (0.17 s warm) + the ledger delta. The 2026-08-23
  "read the ledger" calibration EXPIRED when rc_lane made the PK's RC_
  range hot; conditions changed, value re-taken.
- `landed` = total − unassigned (index-only, ix_nav_pdf_todo; pending
  counts landed — an assignment is a determination).
- **rate and increase come from THE SAME SUBTRACTION** as landed:
  sync|richmond is deliberately NOT in routine_update's `_CUM_SPEC`
  (removed 2026-08-28 — the `db N` download counter is blind to
  assignment-landings; measured landed +83 while downloads sat flat,
  board printed 0.0/s on a climbing row).
- Kits: 60 s (`now`) + 5 m (`window`); after a flat stretch the window
  re-arms and needs ~4-5 min of movement before a rate prints — honest,
  not a defect.
- Statuses: ACTIVE (a process is pulling) · COMPLETE (landed == needed
  EXACTLY) · STALLED (an error blocks progress) · PENDING (we paused
  ourselves — wifi, eject; `parked` in updates_config.json). Only
  ACTIVE earns an eta.
- Acceptance (seen live at the 16:45 close): landed +1 ticks · eta
  "4 min" → "complete" · ACTIVE → COMPLETE at exact equality. A new
  filing must walk needed+1 → ACTIVE → rd → pending → landed+1 →
  COMPLETE with no hand touching anything.

## 5 · RICHMOND AUDIT (enumeration — a safety check, NOT the pipeline)

login: "enumeration is an audit that isn't part of the cycle, but exists
to check whenever we want to as a match of total doc id in our db vs the
live source."

**THE ENUMERATION LAW (login 2026-08-29), the same at every source:
`BULK BASELINE + LIVE TAIL = TOTAL`.** For richmond the baseline is the
census window sweep (1850 → last swept day) and the tail is the
date-range window to now; for acris it is the Socrata diff plus the CRFN
edge walk. The baseline is complete but stale, the tail live but shallow,
and the ranges must OVERLAP so nothing hides in a seam — richmond's
30-day window deliberately reaches back weeks past the census's last
swept day.
⚠ **AN EMPTY DENOMINATOR IS NEVER A PASS.** `--days 45` exceeded the
county's 30-day window cap, returned a SILENT ZERO, and printed
`county lists 0 ... held 0/0 · MISSING 0` — a "pass" on a window we KNEW
held hundreds of filings. The tool now clamps to 30 days and reports
UNPROVEN when the listing is empty. Re-run at 30 days: county 2,633,
held 2,633/2,633, MISSING 0 — a real PASS.

    python richmond_audit.py [--days 30]

What it proves, in one command, all read-only:
1. **our totals** — RC row count + the zero-states (`rd=''`, `pdf=''`,
   NULL) — sub-second, index-only.
2. **live membership** — fetches the county's OWN listing for the
   trailing window and PK-checks every internal id: `held N/N ·
   MISSING 0` or the missing ids named.
3. **historical baseline** — `rc_census.py --report` accounting
   (listed / held / MISSED / void). The census closed history through
   2026-08-25; the trailing window overlaps it by weeks, so there is no
   seam between baseline and live edge.

PASS = MISSING 0 · MISSED 0 · zero-states 0 (except an honest pdf=''
just-landed tail). PROVEN 2026-08-28: week 08/21..08/28 → county 745,
held 745/745, MISSING 0 (login's independent count: 745 ✓); census
MISSED 0; inflow chain since 08/21 reconciled to zero remainder
(+75,001 backfill close · +105 · +169 · +170 · +112 · +85 live).

## 6 · CLOSED STATE (2026-08-28)

2,502,230 rows · COMPLETE 16:45 · week audit 745/745 · census MISSED 0 ·
~85 fresh filings pending on the recheck · heal residue self-closed
(failed 4 → landed 4). Keying columns dormant, rename deferred to their
removal. Next: the same three names for acris — `acris_reproduction.py`
(the group-entry design, untested) · acris update (the shared board's
acris rows) · acris audit (formalize on close) — then DOB per the
roadmap.

---

## ⚠ THE 4 AM TASKS WERE REMOVED 2026-09-01 — ONE OF THEM IS LOAD-BEARING

login: *"the 4 am tasks should be completely removed. they are of no use."*
Disabled: **`CRE Ledger Refresh 4AM`** and **`Legal Instruments Navigation
Audit`** (Windows Scheduled Tasks; disabled, not deleted, so re-enabling is
one command).

**Why they were removed** — not because they were idle, but because they were
**freezing the database**. Both started ~04:00, then sat for **11.5 hours on
10 CPU-seconds**, holding open read connections. In WAL mode a checkpoint
cannot advance past the oldest reader, so:

- the main `.db` last-modified froze at **04:11** (its last checkpoint),
- every write since went into the WAL, which reached **3.3 GB**,
- and every read had to search that WAL first — which is why queries crawled
  and DB Browser hung.

Killing the two processes released the snapshot and the timestamp jumped to
live within seconds, the main file absorbing ~131 MB immediately.

⚠ **BUT `cre_ledger_4am.cmd` ALSO RAN `rc_pdf_state.py --apply`, AND THAT ONE
MATTERS.** Its own comment: *"pending should always be checked for the lag
distribution. the moment it falls out of it, it becomes absent … Without it a
doc silently stops being refreshed and sits at pdf='' forever - which is
exactly how 6,699 rows accumulated and why richmond stalled at 99.60%."*

**Harmless while richmond is parked** (login 2026-09-01: all hands on acris
documentation). **NOT harmless once richmond resumes** — without the
maturation pass, `pending` rows never mature to `path`/`absent` and richmond
stalls again exactly as it did before.

**SO: when richmond resumes, restore the maturation pass** — either re-enable
the task, or better, fold `rc_pdf_state --apply` into `rc_lane` so it cannot
be separated from the lane it serves. Do NOT simply re-enable the old 4 AM
task while a long acris run is live: that is what created this deadlock.
