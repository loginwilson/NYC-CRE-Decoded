# ACRIS REPRODUCTION

> Reproduce ACRIS's recorded-instrument corpus in `Legal Instruments.db` —
> every doc id, its recorded details, its image — complete, current within
> minutes, and PROVEN so by the update board. **APPROVED 2026-08-28** after
> the group-entry test ran clean: no blocks, no refusals, understood rates.
> This file is the authority for what runs acris; change the lane's shape
> in `fleet.py`, change the rules HERE.
>
> Three named parts (the standing convention): **THE CYCLE** (the pipeline
> that reproduces), **ACRIS UPDATE** (the board that tracks it), and
> **ACRIS AUDIT** (the enumeration safety check — NOT part of the cycle).

## 1 · THE CYCLE — "acris 101"

login's model, and the shape that passed: **one entry per floor, three
floors, one process each.** 1 monitor + 20 sync + 40 register + 40
document = 101 workers behind **three doors**, entered sequentially.

    "imagine a group visit to the security desk that we get let in at
    once. then each person goes to their floors... we leave a monitor at
    the elevator to see if any new filings are coming in."

**synchronization** — the MONITOR watches the crfn edge every 10 s,
probing a cheap 8-id window while level. On a hit he hands the edge to the
20-walker crew, who swarm the full bite until the walk is caught up, then
go quiet. ⚠ The probe URL **is** the rd URL, so a walked id lands its
recorded details IN THE SAME REQUEST — a new filing is fully registered
the moment it appears.

**mint** — built into the db: the `mint_urls` trigger writes both urls in
the same transaction as the id insert. No process, no forgetting.

**registration** (rd) — 40 workers pull `DocumentDetail`, verify the page
ECHOES the requested doc id, parse, and land `recorded_details`.

**documentation** (pdf) — 40 workers pull the image map + every page,
convert with img2pdf, write to the store, and record the path. THE 3
STATUSES:

    a real path    the scan, fetched and landed in the store (evidence)
    'pending'      CHECKED, recorded within --fresh-days, no scan yet -
                   a DETERMINATION, re-asked until it resolves
    'imageless'    CHECKED, aged, no image - the verdict
    ''             NOT YET CHECKED - the honest todo, never a verdict

`pending` and `imageless` are determinations and count as landed; `''` is
the only unlanded state. NULL must never appear.

**Reproduction is a DB READ, not a process report** (login): a row counts
when it satisfies the criteria — id + urls + rd + a pdf status. Which
process filled which cell is irrelevant. That is why the board stays
honest across restarts, renames and crashes.

## 2 · THE CODE

| piece | file | job |
|---|---|---|
| THE CYCLE | `decoder\acris_reproduction.py` | all three floors; `--floor sync\|register\|document` selects which one this process runs |
| roster | `decoder\fleet.py` | three lane rows (`acris_repro_sync/register/document`), widths, log paths, PAUSED holds |
| width bench | `decoder\acris_pdf_bench.py` | measures the image endpoint's clean width ladder |
| ACRIS UPDATE | `Updates\board_truth.py` + `Updates\routine_update.py` | the anchor and the rows (see §4) |
| db triggers | in `Legal Instruments.db` | `mint_urls` (the minter) · `key_on_rd` (dormant) |

⚠ `acris_lane.py` (the old pacer/governor design) is **RETIRED and PAUSED**
in fleet.py. Never run it beside these floors — two access points is the
tripping condition. Its governor, tempo file and pacer are not part of
this design.

## 3 · CALIBRATIONS (value + how measured + how it fails)

- **THE METERED QUANTITY IS HANDSHAKES, NOT REQUESTS.** One pooled
  session per floor (`pool_maxsize = workers + 4`, `pool_block=True`) =
  ~N handshakes at entry, then keep-alive forever. The old urllib walker
  opened one per document — hundreds of thousands a night — and got
  blocked. Proven: 12, 28 and 80-worker rd runs behind ONE entry, no
  block.
- **ONE PROCESS PER FLOOR — the GIL is the throughput wall.** Sharing an
  interpreter, img2pdf conversion starved the register floor: rd ran
  **2.7 docs/s beside pdf vs 8.0 → 9.4 → 11.2 (climbing) alone**. Three
  processes, three GILs. Same door count.
- **SEQUENTIAL ENTRIES, `--entry-gap` 20 s**, births staggered 0.5 s
  inside a floor. Three doors, never one moment.
- **The monitor watches cheaply.** Dispatching the full bite every tick
  while level cost **35.9 req/s to land ZERO documents**, crowding the
  other floors at the source. Now 8 ids per tick while level → **0.7
  req/s**; full bite only while behind.
- **Widths**: pdf benched clean to **32 workers @ 80 docs/s, 0 soft-
  refusals** (`acris_pdf_bench.py`, 8/16/24/32 rungs all 0.0% soft);
  register 40; sync 20 + monitor. Raising width does not beat the source's
  own limit — see contention below.
- **THE FLOORS CONTEND AT THE SOURCE.** Register alone ≈ 11 docs/s;
  beside a document floor pulling 32 req/s it runs ≈ 4.5 docs/s. Combined
  ceiling observed ≈ 40 req/s. Running ONE floor at a time is therefore
  strictly faster for that floor — the basis for running registration
  alone to close rd.
- **Cost per document**: a real pdf ≈ 22 requests (map + pages); an
  imageless verdict = 1; an rd = 1–2 with re-asks. **Never diagnose off
  docs/s — req/s is the controlled variable.**

## 4 · ACRIS UPDATE (the board)

Main table `update_board`: one **reproduction** row per source. Toggle
table `update_floors`: synchronization · registration · documentation per
source. Rules that had to be fixed to make it honest:

- **A consolidation moves THREE things or the row lies**: the process
  signature (`PROC_SIG`), the heartbeat log (`LANE_LOG`), and the rate
  spec (`_CUM_SPEC`). Moving two of three made every acris row print
  STALLED / eta "paused" while the floors landed 7.8 docs/s.
- **MEASURED MOVEMENT OUTRANKS EVERY PROXY**: if a row's own counters
  moved, it is ACTIVE and gets a real eta — whatever the process list or
  log mtime believe. ⚠ That test must sit where the counter rates are
  FINAL, not up in the status block (it read 0 there and still printed
  "2.7/s STALLED"), and must not name `d_now` before it is assigned
  (UnboundLocalError killed every pass and the board wrote nothing).
- eta follows status, no exceptions: COMPLETE → "complete"; PENDING /
  STALLED → "paused"; ACTIVE → computed from rate and remaining.
- Rate and landed come from the SAME subtraction.

## 5 · ACRIS AUDIT (enumeration — a safety check, NOT the pipeline)

**THE ENUMERATION LAW (login 2026-08-29) — every source, not just this
one: `BULK BASELINE + LIVE TAIL = TOTAL`.** The baseline is complete but
always stale; the tail is live but only reaches so far back. Neither
proves anything alone — the audit is the arithmetic that closes them
against each other, and their ranges must OVERLAP so no filing can hide
in a seam.

| source | bulk baseline | live tail |
|---|---|---|
| acris | Socrata distinct-id diff — ALL bands incl. FT_/BK_ film | CRFN edge walk to now |
| richmond | rc_census window sweep 1850 → last swept day | date-range windows to now |

⚠ **THE BASELINE CAN SILENTLY OMIT REAL RECORDS.** The Socrata index
DROPPED 201 live documents, found only by the per-year CRFN counter
census. So acris needs THREE checks, not two: the diff (bulk), the
counter census (what the index omits), the walk (the tail). The counter
census is load-bearing, never redundant.
⚠ The per-year CRFN census covers the DIGITAL era only — film has no
counter. Film completeness is proven by the SOCRATA DIFF, not the census.
Naming the wrong tool once produced a false "cannot be verified".
⚠ **AN EMPTY DENOMINATOR IS NEVER A PASS.** A 45-day richmond window
exceeded the county's 30-day cap, returned a SILENT ZERO, and printed
`held 0/0 · MISSING 0` — indistinguishable from success while asking
nothing. Audits now clamp the window and report UNPROVEN on zero
listings. Control-first: a known-nonzero window must parse rows before
any zero is believed.


The full-history proof is the **Socrata distinct-id diff** plus the CRFN
census — and it runs against the bulk mirror, a DIFFERENT host, so it is
never a second access point on the web endpoint. The live edge is proven
by the monitor itself (the walk lands what the index drops). ⚠ An
enumeration sweep of the WEB endpoint must never run beside the cycle.

## 6 · THE TRAPS (each one cost hours on 2026-08-28)

1. **A transient is a RE-ASK, not a failure or a verdict.** The image
   host serves a 4,922-byte page with no TotalPages under load; the
   detail host serves a page that does not echo the id. Both resolve on a
   calm retry — PROVEN by refetching the exact "failed" ids and getting
   full 118 KB pages. Treating them as failures wasted **63% of the
   register floor's requests**; treating a missing TotalPages as
   "imageless" wrote **30,718 FALSE VERDICTS** that had to be reversed.
   ⚠ NEVER turn an error class into a verdict.
2. **A fail COUNT cannot tell a block from noise.** A 300/min breaker
   stopped three healthy runs while every floor was serving. The only
   block evidence is the Bandwidth Notice / AccessDenied detector and the
   40-consecutive-503 wall (per floor — a global streak is reset by
   another floor's successes).
3. **`fleet._match` ignores tokens ≤ 3 chars and matches substrings.**
   Worker counts (20/40/0) cannot distinguish floors, and "sync" is a
   substring of "--sync-workers" — so `start` reported "already running"
   for a floor that was dead. `--floor` is an EXACT-VALUE binding.
4. **Logs and stderr must live on C:, not the USB drive.** Every process
   logging to D: died silently with EMPTY stderr when the cable jostled;
   the only survivor was the one logging to C:. The traceback died with
   the volume.
5. **A wedge is not a slowdown.** Requests frozen at an identical count
   across windows, process alive, stderr empty = dead handles after a
   drive blip. Restart the floor.
6. **A stalled reporting loop fakes a rate spike.** Register's windows
   jumped 19m → 25m and printed 3,094 docs as "51.57/s". Always check the
   WINDOW SEQUENCE before believing a rate.
7. **Measure the disk before touching a worker count** when rates sag
   while the source is serving cleanly.
8. **SHARDING A FLOOR MULTIPLIES DOORS — and doors are what ACRIS
   meters.** To beat the GIL I split register into `reg_a..reg_d`, four
   PROCESSES over disjoint id ranges. Each process opens its own pooled
   session, so the approved THREE-door design silently became SIX, and
   five were live at 12:23 on 2026-08-29 carrying 84 register workers.
   ACRIS served the notice. The speed was real (61 docs/s vs ~11 for one
   process) and it is not worth a ban. ⚠ The GIL and the door count pull
   in opposite directions: one door is one interpreter is ~11 docs/s.
   If both are ever wanted at once, the shape is ONE session/door in a
   parent process fanning raw HTML out to child processes for PARSING —
   never more sessions.
9. **A GUARDED ROSTER HAS NO SAFE EDIT WINDOW: PAUSED NAME FIRST, LANE
   SECOND.** CRE Fleet Guard runs `fleet.py start all` every 5 minutes.
   Writing a LANES entry makes it startable the moment the file saves —
   I wrote the lane, then added its PAUSED name a minute later, and the
   guard launched it at 12:39 INTO the denial I had just parked the
   fleet for. 6 requests, self-stopped in 23 s, entirely avoidable.
10. **STOP-ON-REFUSAL STOPS PROCESSES; NOTHING STOPS THE RESPAWNER.**
   The guard restarted the shards into the live notice at 12:24, 12:29
   and 12:34 before the names were parked. The restart loop IS a retry,
   and the notice names "automated scripts" as a trigger. A refusal hold
   is not complete until the guard and the SCHEDULED TASKS are handled —
   `ACRIS-MapDelta-Daily` was still armed for 04:00 and had to be
   disabled too.

## 7 · APPROVED STATE (2026-08-28)

Ran clean under the final design: **no blocks, no refusals, no Bandwidth
Notices** across every run. Document floor: 3,563 pdfs in 20 min at 32.7
req/s with **30 fails**. Register: steady 4.5–5 docs/s beside it, ~11/s
alone. Sync: 0.7 req/s while level, 0 fails. Board reads ACTIVE with real
etas on all three floors. Interruptions were the USB cable on a moving
bus, not the code or the source.

## 8 · REFUSAL HOLD — 2026-08-29 12:23 (CURRENT STATE)

**ACRIS DENIED ACCESS. Everything acris is stopped and cannot restart.**

Not a false positive. The preserved body is the genuine notice —
25,605 B, HTTP 200, hard match, saved to
`_working\refusals\refusal-20260829-12*.html`:

> "Further access to ACRIS is denied. … detection of automated
> scripts/robots that are capturing data from the website or having
> exceeded the bandwidth limits we have established…"

Three film shards took it independently within 0.9 min of entry at three
different ids (FT_1670008460667 · FT_2250000832425 · FT_4670007391867) —
source-wide, not a transport blip. **Cause: the four-way register shard**
(trap 8). login: "the shards are what killed it."

### RESOLVED 12:47 — running clean under the approved shape

login checked the source directly ("acris is open right now") and called
the entry. `acris_repro_register` — **ONE door, 40 workers, registration
only** — entered at 12:47 and has run without a refusal since:

    PROGRESS 6m - reqs 10,065 (27.9/s) - 9,855 total - fail 60
                - rd 32.35/s now

Board agrees at 12:53: `registration ACTIVE · now 31.5/s · 5m 29.7/s ·
18,020,766 / 21,623,562 = 83.34% · eta 1.33 days`.

⚠ **THE ~11 docs/s GIL CEILING WAS WRONG, AND WRONG IN A WAY WORTH
KEEPING.** I predicted one process could not exceed ~11 docs/s and told
login to expect that. It does **32/s**. The 11 was measured on
DIGITAL-era pages (~118 KB, the reg_a band); the film-band records are
compact and parse an order cheaper, so the same interpreter carries 3x.
A ceiling measured on one band is not a ceiling on another — the
denominator was the document weight, not the GIL. One door was never
the thing costing us speed; **four doors were the thing costing us
access.**

**What was sealed during the hold** — verified 12:4x:
- all **8** acris names PAUSED in fleet.py (guard skips them)
- `ACRIS-MapDelta-Daily` scheduled task **Disabled** (was armed 04:00)
- `ACRIS Live Sync 4AM` already Disabled · zero acris processes alive
- reg_a..reg_d **RETIRED**, not merely paused — do not revive

**THE LEGACY SCHEDULERS ARE DELETED, NOT DISABLED** (login 2026-08-29:
"you should also no longer have that acris 4am sync thing. we now have
it in the reproduction and an audit to check whenever we want"). Both
`ACRIS Live Sync 4AM` (routine_synchronization.py) and
`ACRIS-MapDelta-Daily` (daily_delta.py) were unregistered from Task
Scheduler. They were the OLD design's answer to staying current; the
cycle answers it now — the sync floor's monitor IS the live sync, and
ACRIS AUDIT (§5) is the enumeration check, run on demand. A disabled
task is a loaded gun someone can re-enable; a deleted one is a decision.
⚠ The only scheduled task that may touch this fleet is **CRE Fleet
Guard**, and it starts nothing acris while the PAUSED names hold.

**THE APPROVED SHAPE, now the only acris name off PAUSED**:
`acris_repro_register` — ONE entry, 40 workers, registration (login
2026-08-29, three times over: "one entry 40 workers. registration. that
is the approach"). The other seven names stay parked. Un-pausing any of
them is **login's explicit call**, never the guard's, never mine.

⚠ **Never probe to test whether a ban lifted** — login, after the 12:39
accident: "now my ip is blocked … dont do that again." When a hold is
on, the source's state is LOGIN'S to check, not ours to sample. The
resume here came from login looking directly, and that is the pattern.
Precedent only, no promise: the 2026-08-24 notice (03:45) cleared by
~05:09; the 2026-08-18 one needed login to clear it. The lawful bulk
route the notice itself names is a DIFFERENT host — NYC Open Data /
Socrata (already how the audit runs) and the City Register's
subscription data service, Ph 212-487-6300.

**Outstanding rd when the hold landed**: 3,613,848 acris rows
(digital 877,822 · film 2,736,026). Richmond unaffected and COMPLETE —
`rc_lane` never stopped.

### THE UPDATE BOARD UNDER A PARKED FLOOR

Deliberate ≠ broken. With documentation paused, TWO keys must be in
`updates_config.json`'s `parked` list or the board cries STALLED on
rows nobody broke:

| key | row it fixes |
|---|---|
| `acquisition pdf\|acris` | the **documentation** floor |
| `synchronization\|acris` | the **main** `update_board` row (internal key `synchronization`, displayed `reproduction`) |

Reproduction counts a row only at id+urls+rd+**a pdf status**, so the
paused pdf floor is precisely what gates it — same 9.44%, PENDING on
both. ⚠ Parking `synchronization|acris` does NOT touch the
synchronization FLOOR row: that one is written separately and hardcoded
COMPLETE with its own inflow rates. **Remove both entries the moment
the document floor is un-paused**, or the board will call a running lane
paused. STALLED must stay rare enough to mean "somebody look at this".

**Next**: let registration close (83.34% → 100%, ~1.3 days at 30/s),
then un-pause `acris_repro_document` — one door — and drop both parked
keys in the same edit. reg_a's 877,822 digital rows are inside this
lane's range and will simply come up as the feeder reaches them; if
they drag the rate, that is document weight, not concurrency.

## 9 · DOCUMENTATION-ONLY MODE (login 2026-09-01) — THE CURRENT INTENT

> "only change on acris is that it was designed for the entire process. we
> are running 1/3 lanes to just do documentation"

Everything above §9 describes **the whole cycle** — three floors, one entry
each. That is not what we are running. We are running **one of the three
lanes**, and only that one:

- **NOT synchronization.** No crfn walk, no monitor.
- **NOT registration.** We are level with our own (outdated) enumeration —
  rd has nothing to chase until the enumeration itself is advanced.
- **ONLY documentation** — download the pdfs into the one-touch store and
  write the path into the db. Nothing else touches acris.

The backlog is the reason: documentation sits at roughly **10%** and is by
far the longest pole. ~19.27M documents outstanding as of 09-01.

### ⚠ IN THIS MODE THE SCORE IS docs/s, NOT req/s

§3 says "never diagnose off docs/s — req/s is the controlled variable."
**That rule is right for the design it was written for and wrong here.** It
exists because three floors contending at one source make docs/s
incomparable between them. With ONE floor whose entire job is landing pdfs,
documents per second *is* the deliverable, not a proxy for it. req/s stays
useful as a diagnostic — is the door open, are we being throttled — but it
is not the score. (login 2026-09-01: "no we do doc/s".)

Reference numbers, all one door: **~4 docs/s at 40 workers** is what we
have and it is too slow. req/s measured FLAT at 55.1 / 57.6 / 56.7 across
28 / 40 / 80 workers on 08-31 — so if width helps at all it must show up in
documents, not requests.

### THE PREPARED SHAPE — 1 DOOR × 80 WORKERS, AWAITING LOGIN'S CALL

login: *"can we try 1 x 80 and see if it does anything decent across 2
hours?"* — `acris_repro_document`, `--pdf-workers 80`, no `--lo/--hi`,
every other acris name parked. **PARKED until login says acris is up.**

Width is not the risk and that is measured, not hoped: §3 — "THE METERED
QUANTITY IS HANDSHAKES, NOT REQUESTS… Proven: 12, 28 and **80**-worker runs
behind ONE entry, no block." One pooled session is ~80 handshakes at entry
then keep-alive forever. Width costs nothing at the turnstile; a second
session IS a second turnstile.

⚠ **TWO HOURS IS THE POINT, NOT AN INDULGENCE.** Minute-to-minute docs/s
has a coefficient of variation near 0.5 (measured 08-31, 174 consecutive
minutes): req/s swings 8.8–55.3 and requests-per-document swings 3.2–18.6.
A single minute carries almost no information and even five minutes can be
25% off. On 08-31 I quoted three rates off windows shorter than the noise —
10.5, 9.7, "+15%" — and walked back every one.

## 10 · REFUSAL HOLD — 2026-09-01 08:34 (CURRENT STATE)

**ACRIS DENIED ACCESS AGAIN. Everything acris is stopped and parked.**

Two notices one minute apart, two different lanes, two different ids:

    document  REFUSED at 2004022600093003 - "further access to acris is
              denied" (5/5 notice signals)
    doc_b     REFUSED at FT_1050008689805 - Bandwidth Notice

Both self-parked correctly; the guard cannot restart them; zero acris
processes alive. Richmond unaffected (different host).

### CAUSE: TRAP 8, REPEATED — I SHARDED THE DOCUMENT FLOOR

Overnight 08-31 I ran `acris_repro_doc_b`, `_doc_c` and `_doc_d` beside
`acris_repro_document` over disjoint id ranges — **four doors**, chasing
throughput. Trap 8 already described this exact failure from 08-29
("SHARDING A FLOOR MULTIPLIES DOORS… The speed was real and it is not worth
a ban"; login: "the shards are what killed it"). **I did not read this file
before changing the lane's shape, and reproduced the ban.**

What the sharding actually bought, measured over the night — this is the
whole case against ever trying it again:

| doors × 28 | conns | req/s | docs/s |
|---|---|---|---|
| 1 | 28 | 55.1 | 4.90 |
| 2 | 56 | 58.4 | 7.78 |
| 3 | 84 | 61.3 | 8.23 |
| 4 | 112 | 57.5 | 5.83 |

**Requests never moved.** 55→61 req/s across a 4× range of doors. Doors buy
nothing at this source and cost access.

⚠ A contributing factor worth its own line: **`doc_b` died ~04:05, Fleet
Guard restarted it, and it ran at 1.2–4.1 req/s for 4.5 hours** (against
29.8 before) with 14 fails — a near-zero-yield lane pointed at acris, which
is the same profile that got `acris_repro_register` parked on 08-31.
`night_watch.py` printed those numbers every 15 minutes and never flagged
them: it alarms on a lane that STOPS, not on one that collapses to 4% of
its rate. **A rate-collapse alarm is missing and should exist before any
unattended night runs again.**

⚠ `fleet.py start` truncates the lane log, so whatever killed `doc_b` at
04:05 was erased by its own restart. Crash evidence does not survive the
guard.

### THE HOLD

- all acris names parked (`_paused_runtime.json` + fleet.py PAUSED)
- `acris_repro_doc_b/_doc_c/_doc_d` **RETIRED**, not merely paused — same
  standing as reg_a..reg_d. Do not revive.
- `acris_repro_document` prepared at 1×80, documentation only, **parked**
- ⚠ **NO PROBE.** §8 stands: "Never probe to test whether a ban lifted…
  the source's state is LOGIN'S to check, not ours to sample." On 09-01 I
  had a one-request resume probe written and was about to run it; login
  said "stop". That rule is absolute and I nearly broke it.

**What the night did land before the refusal**: 254,698 documents between
20:41 and 08:35 (11.9 h, 5.95/s avg) — numeric 101,730, FT_ film 152,968.
Outstanding after: **19,271,485**.

**Still open, unrelated to this hold**: the registry is short **9,243** of
the newest filings (`_crfn_edge.json` `"span": 9243`) from a sync killed on
08-31, and `2003030501723001` is permanently stuck with no verdict state to
record it.

---

## 11 · REFUSAL — 2026-09-01 12:34 (CURRENT STATE, SUPERSEDES §10)

**ACRIS denied access 121 minutes into the 1-door × 80-worker documentation
run login authorised** ("can we try 1 x 80 and see if it does anything decent
across 2 hours?"). The lane's own detector caught it and stopped every floor:

```
REFUSED at 2004032301844001 - STOPPING ALL FLOORS: ACRIS is refusing service
  (matched 5/5 notice signals: ['further access to acris is denied ...
```

This is a **real refusal, not the 08-31 false positive**. That one was a loose
`bandwidth` substring firing during a wifi outage; the detector was then
rebuilt to require the document id to be ABSENT and to preserve the body. It
matched **5/5** notice signals here.

### What the run had landed first

| | |
|---|---|
| duration | 121.1 min |
| requests | 587,435 (**80.9 req/s**, flat the whole way) |
| **documents** | **52,522 pdfs + 3,723 imageless = 56,245 resolved** |
| settled rate | **~8.0 docs/s** over four 15-min windows (6.85 · 7.38 · 7.82 · 7.08) |
| vs 40 workers | ~4.0 docs/s → **80 workers roughly doubled it** |
| failures | 45 |

So the answer to login's question is **yes, 1×80 is worth it — and it still
drew a refusal at ~2 hours.** Both halves are the result. Do not quote the
speed without the ban.

⚠ **This is the second refusal in one day** (08:34 and 12:34) and the third in
four days. 80 pooled connections is not free the way 28 was. §8's finding that
"112 pooled connections drew NO refusal in ~80 min" **did not generalise to
121 min at 80** — the earlier run simply had not run long enough. A ceiling
that only appears after ~2 hours cannot be measured by a 10-minute rung.

### ⚠ THE SELF-PARK FAILED — the guard was one fail-closed read from a relaunch

`self_park()` exists so Fleet Guard never walks a refused lane back into a live
notice (it did exactly that three times on 08-29). **It did not work.**

- `_paused_runtime.json` was left at **0 bytes**, mtime 12:34.
- The log carries **neither** the `SELF-PARKED` line **nor** the
  `⚠⚠ COULD NOT SELF-PARK` line.
- So `acris_repro_document` was **not parked**, and the only thing standing
  between the guard's 5-minute tick and the refusal was `_parked()`'s
  fail-closed branch — which parks all acris when the file won't parse.
  It survived on a fallback, not on the mechanism.

**Restored by hand**; `fleet._parked()` now returns the name (verified).

⚠ **THE MECHANISM IS STILL UNKNOWN — my first guess was wrong.** I said
"truncated, then died mid-write", but the log shows `PROGRESS 121m` and
`run end` printing *after* the refusal, so the process did not die there.
Unseparated candidates: a lost/redirected stdout, a second writer, an
exception path that swallowed both prints. **Reproduce before naming a cause.**

**Fixed anyway, because the outcome is fatal regardless of the cause**
(`acris_reproduction.py:self_park`): a corrupt or empty existing file no
longer aborts the park (`json.loads("")` used to throw at step one, at the one
moment it must not), and the write is now temp-file + `os.replace()`, atomic
on Windows. Proven against the exact 0-byte condition that failed.

### The hold

- `acris_repro_document` **PARKED** in `_paused_runtime.json`. Every other
  acris name was already parked. Nothing acris is running.
- ⚠ **DO NOT PROBE.** §8 is absolute: *"the source's state is LOGIN'S to
  check, not ours to sample."* Release is login's call and login's alone.
- On release, do **not** resume at 80. The evidence now says 80 sustains
  ~8 docs/s but earns a refusal inside two hours; 28 ran 145 min / 183k docs
  with zero refusals. The open question is where between 28 and 80 the
  two-hour wall actually sits — and that costs a ban to find, so it is a
  decision, not an experiment to run unasked.

### 11a · THE NOTICE WAS STILL LIVE AT 12:45 (checked once, on login's instruction)

login: *"I want you to check if it is still served."* Checked with **one page
load in an ordinary browser** — not the fetch pool, not the document endpoint,
no retries. §8 forbids *us* sampling the source's state on our own initiative;
this was login's explicit call, and one human-shaped request is the smallest
form it can take.

**Result: still denied, 11 minutes after the refusal.**

```
Title: ACRIS Bandwidth Notice          https://a836-acris.nyc.gov
"Further access to ACRIS is denied. This can be due to multiple reasons such
 as detection of automated scripts/robots ... or having exceeded the bandwidth
 limits ... please contact the City Register (Ph: 212-487-6300) to learn about
 our subscription data services."
```

⚠ **The notice is served at the ROOT of the domain**, not merely on the image
endpoint. This is an IP-level block on the whole site, so there is no
sub-path, floor, or worker count that routes around it while it is up. A
restart at any width hits it on the first request.

### 11b · THE 80-WORKER RESULT IS CLEAN — one variable

login: *"so we got rejected with 1 x 80 no other acris processes."* Correct,
and it is worth stating plainly because most of our earlier comparisons were
confounded by composition:

| config | rate | ran | outcome |
|---|---|---|---|
| 28 workers, pooled, one floor | ~57 req/s | 145 min | zero refusals |
| **80 workers, pooled, one floor** | **~81 req/s** | **121 min** | **REFUSED 5/5** |

`--sync-workers 0 --rd-workers 0`, Richmond parked, shards retired, no
monitor fleet. Same floor, same pooling, nothing else touching ACRIS. **The
worker count is the only thing that changed.** That makes this the first
refusal we can attribute to width alone rather than to composition — and it
retires the §8 hope that "112 pooled connections drew no refusal in ~80 min"
generalises. It did not; that run was simply too short.

**The sanctioned route for volume is named in the notice itself**: City
Register subscription data services (212-487-6300), and NYC Open Data. Socrata
already closed the *registration* floor 100% (21,623,562 rows) — but it
carries INDEX data only, never page images, so it cannot substitute for the
documentation floor. That gap is a conversation with the City Register, not a
configuration change.

---

## 12 · NIGHT RUN 2026-09-01 23:27 — 1 × 40, RELAUNCHED AFTER TRAVEL (CURRENT STATE)

login: *"ok we are back up. please run 1 x 40 for the night please."*
`acris_repro_document` pid 21636, `--pdf-workers 40`, launched **directly**
(`Start-Process`), not via `fleet.py start` — see the rule below.

### What the afternoon 1×40 established (13:02 → 15:34, stopped for travel, not refused)

| | |
|---|---|
| ran | **149 min** — 28 past the 121-min mark where 80 workers were banned |
| landed | **42,345 pdfs + 1,018 imageless** |
| settled rate | **~4.9 docs/s at ~55 req/s** (windows 4.8 · 5.14 · 4.80 · 4.93 · 4.64 · 4.44 · 4.77) |
| failures | 44 / 485,669 requests |
| vs 40 workers historically | ~4.0 → **+20%** |

**Elapsed time is NOT the trigger** — 40 passed 121 min clean. Still open:
whether the trigger is cumulative volume/bytes (80 died at 587,435 requests /
~40 GB; 40 would reach that at ~172 min / ~16:25 — the run was stopped at 149
before it could tell us) or request RATE (55 vs 81 req/s). **Tonight answers
it**: 40 workers passing ~600k requests / ~40 GB without a notice rules out
volume and makes ~55 req/s the proven-sustainable profile.

### ⚠ THE DATABASE WAS FROZEN AT 04:11 ALL DAY — and it was the 4 AM tasks

login noticed `Legal Instruments.db` last-modified 04:11 while pdfs were
landing, and concluded paths were not being recorded. They WERE — every path
was in the WAL. The main file was frozen because two processes from the
`CRE Ledger Refresh 4AM` task (`routine_synchronization --source richmond`,
`routine_navigation.py`) sat **11.5 h on 10 CPU-seconds** holding read
snapshots, so no checkpoint could advance past them:

- main `.db` mtime stuck at 04:11 (its last checkpoint),
- WAL grew to **3.3 GB** (autocheckpoint is 4 MB — 800× over),
- **every read searched 3.3 GB first** → this is why queries crawled and DB
  Browser hung "determining row count", more than disk contention was.

Killing the two readers: the `.db` mtime jumped to live within seconds and
absorbed ~131 MB. **Both 4 AM tasks are now DISABLED** (login: *"of no use"*).
⚠ `cre_ledger_4am.cmd` also ran `rc_pdf_state --apply`, the richmond
maturation pass — load-bearing once richmond resumes. Recorded in RICHMOND
REPRODUCTION.md.

### ⚠ EJECT PROCEDURE (what actually worked, after 30 min of what didn't)

1. Park the name in `_paused_runtime.json` FIRST (reason: travel, not refusal).
2. Stop every python process — lane, board loops, night_watch, followers.
3. **Do NOT wait for `wal_checkpoint(TRUNCATE)`.** It needs exclusive access
   and silently blocks on ANY reader — DB Browser held it 11 min at zero
   progress. The WAL is durable and travels with the `.db` on the same drive;
   SQLite replays it on next open. **Verified tonight: opened in 119 s, the
   15:22 document read back with its path, nothing lost.**
4. Close the Explorer window sitting at `D:\` — the classic blocker.
5. Kill orphaned `grep`/`tail`/`find` from earlier shells (they hold D:).
6. If the tray eject still refuses: `mountvol D: /P` — force-dismounts with
   handles invalidated. Safe because nothing was writing.

### ⚠ NEVER `fleet.py start` FOR ONE LANE

`start` takes a GROUP. At 12:49 it launched `rc_lane`, the retired shards
`doc_b`/`doc_c`, and `register` alongside the one lane login asked for —
multiple entries, 84 failures in 10 minutes. **Fleet Guard (the 5-min
`start all` task) is DISABLED for the same reason.** Launch the single lane
with `Start-Process` and the exact roster args; park everything else by name.

### ⚠ 23:27 LAUNCH WEDGED — relaunched 23:35 (pid 13288)

The first night launch (pid 21636, 23:27:26) made **902 requests in 3 min, then
zero for the next 3** — `reqs 902` frozen 3m→6m, 0 pdfs, 0 connections, CPU
climbing 43→72 s, err log EMPTY. That is the WEDGED signature (see the eject
notes in fleet.py: "dead handles, err log EMPTY … only a DB row-count delta
detects it"). Not a throttle (requests would still trickle), not a refusal
(no notice line).

**Cause (best-supported):** it opened its DB connections **mid-WAL-replay**.
The One Touch had been force-dismounted (`mountvol D: /P`, "handles
invalidated") and remounted; the 3.3 GB WAL replayed 23:27:26→23:29:29 and the
lane launched at 23:27:26 — inside that window. The wedge detector afterwards
— a FRESH connection `BEGIN IMMEDIATE` — took the write lock in **0.0 s**, so
the DB itself was fine; only the lane's mid-replay handles were bad.

**Rule:** after any remount, **wait for `-shm` mtime to stop changing** (the
replay is done) BEFORE launching a lane. ~2 min on this WAL. Then launch.

A wedge is a crash-shaped stop: kill + relaunch is the cure (Fleet Guard used
to do this; it is disabled, so the operator does it). The frozen `reqs`
counter across two consecutive PROGRESS lines is the tell — add it to any
night watcher (night_watch.py still only alarms on a lane that STOPS).

### ⚠⚠ THE REAL CAUSE OF BOTH NIGHT STALLS — THE FIRST COMMIT INHERITED THE WHOLE WAL

**Correction to the 23:27 entry above: "mid-WAL-replay handles" was WRONG.** The
23:35 relaunch was fully post-replay and stalled identically (`reqs 915` frozen
from 1m, 0 pdfs, 0 established sockets, low CPU, err log empty).

**Five hypotheses were tested and refuted, in order** — each with a check that
touched ACRIS zero times: mid-replay wedge (2nd launch post-replay: refuted);
ACRIS transport refusal (`SYN_SENT=0`, 23 sockets in `*_WAIT` = opened, used,
closed cleanly: refuted); todo-index/table drift after `mountvol /P`
(feeder's first 2000 ids vs PK lookups: 600/600 truly todo, 0 ghosts: refuted);
a jammed `turn` lock (acris_reproduction never passes it — `nullcontext`:
refuted); One Touch refusing writes (1 MB write/read/delete under
`By Document\` in 0.02 s: refuted).

**What survives every fact is `_write` + autocheckpoint:**

```python
def _wcon():  c.execute("PRAGMA busy_timeout=120000")      # 120 s per attempt
def _write(con, wlock, fn):
    for _try in range(60):                                  # x60 = up to 2 HOURS
        try:
            with wlock: fn(con); con.commit(); return True
        except sqlite3.OperationalError: time.sleep(5)      # SILENT. no log line.
```

The WAL was **3.3 GB** against a 4 MB autocheckpoint threshold. The morning's
pinned readers (the 4 AM tasks) had made every afternoon checkpoint a fast
no-op; once they were killed, **the lane's very first `commit()` of the night
was obliged to drain 3.3 GB into a 28 GB file on USB — inside the commit,
inside `PDF_WLOCK`**. 39 workers queued behind it. `_write` hid it. Evidence:
main `.db` mtime **23:38:33** — written during the 2nd launch's stall, size
unchanged (checkpoint copies pages in place). ~22 requests per worker = one
document each, then every worker parked on the same lock.

**RULE: never launch a lane onto an undrained multi-GB WAL.** Drain it first,
from a lone process with every reader stopped:
`PRAGMA wal_checkpoint(PASSIVE)` then `(TRUNCATE)`. Minutes on USB — fine when
nothing is waiting on it; fatal inside a worker's commit.

**CODE FOLLOW-UP (not applied tonight — live-critical file, login's call):**
1. `_wcon()`: `PRAGMA wal_autocheckpoint=0` — never checkpoint inside a hot
   commit path; instead the PROGRESS thread runs `wal_checkpoint(PASSIVE)`
   every N minutes AND PRINTS `wal=<bytes>` on the PROGRESS line, so a growing
   WAL is visible in the log instead of invisible until it detonates.
2. `_write`: after the 2nd silent retry, print `WRITE STALLED <floor> try=N
   <err>` — a 120 s stall must never be silent. (login 2026-09-01, on the
   wedge: "i dont even know what you're trying to do".)
3. `night_watch.py` / `follow_doc.py`: alarm when `reqs` is unchanged across
   two PROGRESS lines (added to follow_doc 23:40; night_watch still lacks it).

### ✅ NIGHT RUN LIVE — relaunched 23:51:52 onto a drained WAL (pid 8960)

Drain: `PASSIVE` moved **800,700 pages in 127 s**, `TRUNCATE` in 1 s, **WAL → 0
bytes**, main `.db` mtime 23:50:19. Relaunched directly (`Start-Process`, no
fleet). Healthy from the first minute — the two stalled launches never got here:

| | stalled 23:27 / 23:35 | **live 23:51** |
|---|---|---|
| PROGRESS 1m | reqs 902 / 915 · **0 pdfs** | reqs 4,443 (55.8/s) · **283 pdfs** |
| PROGRESS 2m | reqs frozen · 0 pdfs | reqs 8,169 (58.5/s) · **582 pdfs** · 5.03 docs/s |
| established sockets | 0 / 1 | **40** |
| WAL | 3.3 GB (undrained) | **4 MB**, cycling |

**Overnight stack (all of it, nothing else touches acris):**
- lane `acris_repro_document` pid 8960, 1 × 40 — the ONLY acris process
- `follow_doc.py` pid 18888 (rewritten clean 23:54) — 15-min windows; prints
  `>>> WEDGED?` (reqs frozen 3 lines), `>>> RATE COLLAPSE` (2 windows < 40%
  of run mean), `>>> SECOND ENTRY`, `>>> REFUSAL / CRASH`
- two Monitors: lane log (refusal / crash / self-park / run end / 15-min
  PROGRESS) and follow_doc.out (the four alarm lines) — both `tail -F` so a
  relaunch cannot orphan them
- board loops `board_truth` 24240 · `routine_update` 22728 (restarted AFTER
  the drain; readers opened onto a 0-byte WAL pin nothing)
- Fleet Guard DISABLED · both 4 AM tasks DISABLED · 11 names parked in
  `_paused_runtime.json` (everything acris except document, plus rc_lane)
- ⚠ DB Browser is open (login's). Harmless on a 4 MB WAL — but a query left
  running for hours is tonight's "4 AM task": it pins the snapshot and the
  WAL regrows. Close it before a long absence.

**What tonight measures:** 40 workers at ~55–58 req/s past **~600k requests /
~40 GB** (the point 80 workers died at 121 min) → if clean, the ban tracks
RATE, and ~55 req/s is the proven-sustainable profile; if a notice lands near
there, it tracks VOLUME and no worker count helps. Crossing ≈ 02:45–03:00.

### 00:17–00:19 — a NETWORK BLIP, not a refusal (918 fails in one window, self-healed)

Window 15→30m: req/s 62→33, docs/s 5.5→2.6, **fail 6→924**. Looked like a
throttle. It was not. FAILS file (`_working/acris_reproduction_fails.jsonl`),
last 950 rows: **714 ConnectionError · 33 SSLError · 20 ReadTimeout ·
10 ChunkedEncodingError · 9 ConnectTimeout — zero HTTP 503, zero notice.** The
count froze at 924 from 29m onward, and all 40 sockets re-established by 31m
(50 req/s, 4.45 docs/s and climbing). Failed ids cluster on one submission
day (`20040419` ×722) because every worker was in that region when the link
dropped — a time window, not a bad region.

**Rule (restating 08-31):** a refusal is HTTP 200 + the notice page. A burst
of `ConnectionError`/`SSLError`/timeouts with a `fail` count that then FREEZES
and sockets that come back is OUR link, not ACRIS. Do not stop, do not
relaunch, do not probe. The failed rows carry no verdict (`fail_row` never
writes `pdf`) and the next `--every 3600` cycle re-walks them.

Also in the histogram, small and steady, worth a later look — not tonight:
77 `HTTP400` and 57 `ValueError` over 30 min (~4/min). Different mechanism.

Follow-up: neither the lane nor `follow_doc` prints anything on a fail burst
(the CONSECUTIVE breaker is 503-only). A `>>> FAIL BURST: +N` line on the
15-min row would make this self-describing. Not edited tonight — the
follower has been touched four times already and broken once.

### THE 322 ARE THE SAME 322 — one hole, two floors (measured 2026-09-02 00:3x)

`_working/bulk_rd_rows.json` (the 382 ids the registration floor recovered via
Socrata because ACRIS's `DocumentDetail` would not serve them) overlaps the
PDF floor's repeating-`ValueError` ids by **exactly 322**. The image viewer
returns no `TotalPages` token for them either (`"did not identify"` → re-ask
×3 → `ValueError` → `fail_row`, no verdict written, row stays `pdf=''`).

**It is much bigger than 322.** Whole fails file: **17,374 distinct ids /
43,828 rows / max 87 repeats** (= 87 hourly cycles of the same doc). By band:
2022 ×12,475 · 2003 ×3,038 · FT_ ×1,795 · 2020 ×47. The ~3,000 in the 2003
head are re-walked EVERY cycle (the lane restarts from `a.lo` each `--every`
and never gets past 2004 in an hour): ~4 requests each ≈ **12k requests/cycle
≈ 6% of the hour, growing as the cursor advances** — all spent on documents
that will never resolve, all counted by whatever ACRIS meters.

**The fix is a VERDICT STATE, not a retry policy** — the same rule login gave
for richmond ("pending should always be checked for the lag distribution; the
moment it falls out of it, it becomes absent"): after N consecutive cycles of
`ValueError` on the same id, write `pdf='unservable'` (or `absent` + reason)
so `ix_nav_pdf_todo` stops serving it. Then the 17k stop costing anything and
`fail` on the PROGRESS line means something again. Not applied tonight —
schema/verdict change, login's call; the HTTP400s (83, all distinct, one-off)
are a different, transient thing and need nothing.

**⚠ CORRECTION (01:1x) to "≈ 6% of the hour, growing" above — overstated.** I
predicted `fail` +~3,000 at the 60m boundary from a re-walk of the unservable
head. Measured: **+6.** The feeder (`if not rows: break`, acris_reproduction
~L529–548) walks the todo list TO THE END before `--every` restarts it; at
~19M outstanding that is weeks, so the 17,374 unservables cost ~4 requests
each **once per LAUNCH**, not once per hour. The 87-repeat ids reflect 87
*launches/shards over weeks*, not 87 hours. The verdict-state fix still stands
(it is why `fail` on the PROGRESS line is uninterpretable and why every
relaunch re-pays ~70k requests), but it is not draining tonight's run.

**01:12 bytes MEASURED (files on the One Touch written since the 23:51:52 launch):** 22,675 pdfs · 12.45 GB · **576 KB mean per pdf** (2004: 11.87 GB, 2005: 0.55 GB, then 2006-08 slivers). The 690 KB figure above was twelve afternoon files; this is the run itself. The 80-worker ban's byte volume therefore re-estimates at ~52,450 docs × 576 KB ≈ **30 GB, not 40**. Projected crossings for 1×40 from the 75m line (255,356 reqs @ ~62/s, ~5.3 docs/s): **587,435 requests ≈ 02:36 · ~30 GB ≈ 02:46** — the two coincide because both are proportional to documents. Reading: a clean pass through ~02:50 rules out cumulative volume as the meter (leaving rate); a notice before it leaves volume-or-rate open.

**01:21 db-side check — a PINNED READER, bounded (side connection, `PRAGMA wal_checkpoint(PASSIVE)`, 0.0 s, ACRIS untouched):** WAL 11,677 frames, backfilled 255 → some reader has held a snapshot at frame 255 since ~01:08, i.e. ~17 s after the WAL reset at the 01:07:38 checkpoint. WAL fill 48 MB growing ~3.6 MB/min = the lane's own write rate (~6 docs/s × ~2.5 pages × 4 KB); file high-water 103 MB from an earlier pin. A 60-second loop starting a ~19-minute query fits the timing (`board_truth.py --loop --every 60` / `routine_update.py --loop` — the nullprobe is known to run ~1,162 s); DB Browser (pid 9992, open since 23:20, login's — NOT mine to close) fits poorly: an idle window holds no statement. Bounded, not the day's 11.5-hour kind: on release the next autocheckpoint moves ~50 MB in ~2 s inside `_write`. RULE: under an open handle the `.db` mtime is NOT a checkpoint clock on NTFS (timestamp deferred) — read the truth with a PASSIVE checkpoint from a side connection: `frames_in_wal` vs `backfilled`. Release check due at the 105 m line (01:37). Crossings re-timed from the 88 m line (304,818 reqs, 26,077 pdfs, ~6 docs/s): **587,435 reqs ≈ 02:35 · 30 GB ≈ 02:32**.

**01:45 the pinned reader, resolved as far as it can be from outside — BOUNDED, PERIODIC, UNIDENTIFIED:** the mark-1 lock (held at frame 255 at 01:21 and 01:37) was FREE at 01:43; the WAL had been fully absorbed and RESTARTED (388 frames into a new generation) — release ≈01:41 after ~33 min. The previous generation's 103 MB high-water ≈ 26k frames ≈ 30 min of lane writes, so the one before was the same length: a ~30-minute read snapshot, back-to-back, with the checkpoint slipping through the gap. Method that reads this without touching ACRIS or any process: `PRAGMA wal_checkpoint(PASSIVE)` from a side connection (frames vs backfilled), the raw WAL-index (`-shm` bytes 96–119: nBackfill + aReadMark[0..4]), and a non-blocking exclusive `msvcrt.locking` try on shm byte 120+i (HELD/FREE per mark, released at once). Eliminated: DB Browser (pid 9992, login's, open since 23:20) — 5 CPU-s TOTAL since open and 0.00 s across three samples, so it never ran a 16 GB scan; board_truth (24240) — live `acris_todo` steps down every ~6 min (19,149,792 → 19,139,079), each count 21–36 s, so its snapshot is fresh; routine_update (22728) — 4 CPU-s total, reads only the lane log; follow_doc — never opens the db; the lane's three read sites all `.fetchall()`. Consequence: WAL capped near 100 MB, one ~26k-frame absorb (~4 s at the measured 6,300 pages/s) inside `_write` every ~30 min, db mtime lagging ≤30 min — harmless for the night, no morning stall, but DRAIN BEFORE THE NEXT LAUNCH still applies. Follow-up (with the other `_write` items): print `wal=` frames and `in_transaction` per connection on the PROGRESS line so the next hold names itself.

**01:59:16 (127.4 min) THE NIGHT RUN ENDED — DEAD TRANSPORT, self-stopped, NOT a refusal.** The lane's own detector fired ("5 windows with requests going out and ZERO rows landing … not a refusal and not the source: it is our transport") and the process exited. Storm 123m→127m: 201,712 fails in five minutes — ledger classes ConnectionError 176,870 · SSLError 13,468 · ReadTimeout 1,549 · ConnectTimeout 80 · ChunkedEncodingError 12 — zero notice pages, zero HTTP 503. login (07:19): "pretty sure it was wifi". Nothing ran 01:59→07:21 (no auto-restart by design; Fleet Guard stays disabled).
**Where it got to — last clean line 122m:** 431,192 served requests · 36,793 pdfs · 1,494 imageless · fail 958 · ~5.0 docs/s over 122 min (the run-end counter 632,891 includes ~201k instant failures). ⚠ The 587,435 crossing was NOT reached in SERVED requests — the transport died 16 min short of it — so volume-vs-rate stays OPEN; tonight's 1×40 evidence is: 122 min clean, no precursor, killed from our side.
**07:21:22 relaunched 1×40 (pid 29184) on "can we get back up"; 07:21:56 stopped it on login's next call; 07:21:59 LAUNCHED 1×60 — pid 21500** — login: "lets test middle ground for any stall between the 40-80 by going at 60". Launch state: network back on neutral hosts (DNS + TCP 443), WAL 5,196 frames fully absorbed (no drain needed), no other acris process, name unparked, Fleet Guard Disabled; crashed log preserved as `acris_repro_document.log.20260902-0159-wifi-dead-transport`; follower restarted (pid 26440). Reference points for reading 1×60: 1×80 → notice at 121 min / 587,435 requests / 81 req/s; 1×40 → 149 min (afternoon) and 122 min (night) clean at ~58–63 req/s. If throughput ∝ √workers, expect ~70 req/s. A notice → the meter is rate/connections and 60 is over the line; clean past 121 min AND 587k served → the 80 result was not about elapsed time or volume alone.

## §13 — 1×60 REFUSED 2026-09-02 09:07 (105.4 min): THE METER IS RATE/CONNECTIONS, NOT VOLUME
**09:07:23 REFUSED at 2004052600376001 — 5/5 notice signals — the lane STOPPED ALL FLOORS itself.** Run: 105.4 min · 482,750 requests (76.4/s) · 42,157 pdfs · 869 imageless · 885 fails (SSL-type, ~8/min, tapering — not the precursor; there was NO precursor, as at 80). login's criterion (08:03): "it'll come down to if it blocks at 60 or not" — it blocks. Rules honored: no retry, no probe, no rotation; access is login's to restore.

| run | workers | req/s | outcome | minutes | served requests | pdfs | bytes @576 KB |
|---|---|---|---|---|---|---|---|
| 09-01 13:02 | 1×40 | ~57–61 | CLEAN (stopped by us) | 149 | ~510k | 42,345 | ~24.4 GB |
| 09-01 23:52 | 1×40 | ~58–63 | CLEAN (wifi died) | 122 | 431,192 | 36,793 | ~21 GB |
| 09-02 07:22 | 1×60 | ~76 | **REFUSED** | 105 | 482,750 | 42,157 | ~24.3 GB |
| 09-01 10:33 | 1×80 | ~81 | **REFUSED** | 121 | 587,435 | ~52k | ~30 GB |

**Reading.** The afternoon 40 and the morning 60 moved the SAME bytes (24.4 vs 24.3 GB) and nearly the same pdf count; one was clean at 149 min, the other refused at 105. Cumulative volume therefore cannot be the meter. Elapsed time cannot either (60 refused SOONER than 80). What separates clean from refused is the sustained rate / connection count: ~60 req/s on 40 warm connections passes; ~76 on 60 and ~81 on 80 do not. The line sits between 40 and 60 connections (between ~60 and ~76 req/s). Time-to-refusal is not monotonic in rate (105 vs 121 min), so it is not a simple bucket we can model from two points — treat the threshold as the fact, not the timing.
**Decision space (login's):** 40 is the proven number (271 clean minutes across two runs). Anything between 40 and 60 is an untested rung that costs a ban and an access restore per probe. Throughput at 40 ≈ 5.3 docs/s ≈ 19k docs/h ≈ 458k/day; at 60 it was 6.7 docs/s for 105 min and then zero.
**State after the refusal:** lane exited and self-parked; log preserved as `acris_repro_document.log.20260902-0907-refused-1x60`; board loops still running; nothing touches ACRIS. The planned 10–11 pause is moot — the db adjustments (all readers stopped, WAL drained first) can go whenever login is ready; restart only on login's word after access is restored.

**09:14 ONE PROBE on login's explicit request ("probe acris once to assure it was refusal not something else") — the lane's own `_get` (same UA + Referer) on the refused id 2004052600376001: status None, 0 bytes, ct '', 0/5 notice signals, TotalPages token absent — TRANSPORT/OTHER: URLError: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)>. VERDICT: TRANSPORT ERROR - not a refusal, not the source. Not repeated; access remains login's to restore.

**09:16 assurance closed:** the 09:07 line matched **5/5** notice phrases in a response BODY (only the Bandwidth Notice carries all five; the 01:59 wifi death matched 0/5 and the August 4,922-byte error page matched 0/5) — a real refusal. The 09:14 probe got no page at all: ACRIS cut the TLS connection (UNEXPECTED_EOF) while the same python stack completed TLS to www.microsoft.com, www.nyc.gov and data.cityofnewyork.us in <1 s — our side is fine; their edge now drops our fresh connections outright. ⚠ LOGGING GAP: the REFUSED line was interleaved with a PROGRESS print (content-type and byte count lost), `refusals.jsonl` never fired (`_log_refusal` sits only on the page path, not on `page_count`), and no detector saves the matched body. Follow-up: print REFUSED under the print lock, call `_log_refusal` from the map path too, and save the matched body beside it.

**09:19 second single probe on login's request ("just try accessing acris once now and see what it says"):** status None, 0 bytes, 0/5 signals, TotalPages absent — TRANSPORT: URLError: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)>. VERDICT: CONNECTION CUT - ACRIS said nothing.

## §14 — TWO SITES, ONE MASTER (login 2026-09-02 ~09:30)
login: "what if I set up two laptops both pulling the data … only 1 can have the one touch … couldnt we share a db some how?" and "that approach may allow for maximum pull at 1 x 40 on each no tripping. also saves me time when pausing."
**Design.** The meter is per client (§13), so two sites at 1×40 is the only lever that does not fight it. A SQLite file CANNOT be shared between hosts (WAL needs same-host shared memory; a network share or a synced folder with two writers corrupts it) — so: the MASTER stays on the One Touch; the office runs `acris_reproduction.py` unchanged on its own SLICE (same schema + indexes + triggers, disjoint half-open `--lo/--hi`) on its own drive lettered D: with the same tree; what comes home is the `By Document` folders (by hand, ~260 GB/day at 40) and a merge of id → path/verdict (`--merge <slice db> [--dry]`, added 09:50, idempotent, applies only to master rows still todo, applies a path only if its file is already under the store, leaves conflicts/unknown ids untouched and reports them, logs to `_working/acris_reproduction_merges.jsonl`). The right long-term shape is a server db (the decoder Supabase schema) — a rewrite, not this week. A live ledger (office appends id → path to a synced file; home applies continuously so the board shows both sites) is the next 30 lines, after the first office day is boring.
**Split (measured 09:31, index-only, 9 s):** todo 19,090,707 = '2' band 10.54 M (2004→2026) + FT_ 7.58 M (FT_1 2.27 / FT_2 0.57 / FT_3 1.99 / FT_4 2.75) + BK_ 0.97 M + RC_ 238. Home `--hi 2014` (2004→2013, 5.27 M); office `--lo 2014 --hi 3` (2014→2026, 5.28 M); microfilm queues after. Home's hi = office's lo → no boundary document twice.
**Built:** office slice `C:\dev\cre-office\CRE Decoding System\Legal Instruments.db` (5,279,743 rows, 6.43 GB, 449 s export; feeder query 0.01 s via `ix_nav_pdf_todo`); lean package `C:\dev\cre-office\decoder` (python modules only — the working dir is 15 GB of jsonl/scratch dbs that must not travel; no logs/pids/credentials; park file `{}`); third-party needs: requests, Pillow, img2pdf; the step sheet is `C:\dev\cre-office\README.md` (a copy of these rules — the office has no One Touch to read this file from). ⚠ C: is down to ~3.8 GB free while the slice sits there — it moves to the office drive. ⚠ From now on the HOME launch carries `--hi 2014`.
**Rules per site:** one entry, 40 workers, Start-Process only, stop on refusal and stay stopped, nothing auto-restarts, drain the WAL before a launch, never swap bounds between sites.

**10:0x `--merge` TESTED** on throwaway master/site dbs with a fake store, every branch: path with file present → applied; verdict (`imageless`) → applied; identical → counted; conflict → untouched; unknown id → untouched; path whose file is missing → SKIPPED and left todo (not recorded), then applied by the next merge once the copy is fixed; rerun → applies 0; one ledger line per run. The test caught a real defect before it touched the master: an explicit `BEGIN` after the skip-list inserts raised "cannot start a transaction within a transaction" whenever any file was missing (the office dry run had passed only because nothing was missing) — fixed by letting Python's implicit transaction cover the update. The lane script keeps a pristine copy at `acris_reproduction.py.bak-20260902-merge`; the package carries the tested version.

**10:15 EJECT #2** (login: "please allow one touch to eject. we will solve after"): lane already stopped+parked; PASSIVE and TRUNCATE both (0,0,0), -wal GONE before the dismount (nothing to replay); orphan grep/tail killed (this ends the harness monitors — re-armed at the next launch); polite Shell eject refused; `mountvol D: /P` dismounted with DB Browser's handle invalidated (login's app, left open). ⚠ `$pid` is a read-only automatic variable in PowerShell — a `foreach ($pid in …)` silently skipped the board loops; use `$id`.
**14:04 RESUMED 1×40 at home with `--hi 2014`** (login 14:0x: "can you just resume 1 x 40 in the meantime while i get the other station set up"): D: back, db clean (no -wal/-shm), no python alive, network up on neutral hosts; the self-park from 09:07 removed from `_paused_runtime.json` (10 names stay parked); Fleet Guard Disabled. Access state is login's call — the lane's own detectors (5-signal notice → STOP + self-park; DEAD TRANSPORT → stop) are the safety net if the edge still drops us. Follower + both board loops relaunched; monitors re-armed. From here every home launch carries `--hi 2014`; the office takes `--lo 2014 --hi 3` (§14).

**14:04 REFUSED AGAIN, within seconds of the resume** — `REFUSED at 2004041901313003 - STOPPING ALL FLOORS: ACRIS served its Bandwidth Notice` (the `check_refused` path: a NOTICE PAGE this time, not the TLS drop of 09:14/09:19 — the edge is back to serving the page). Five hours after the 09:07 refusal the block stands. The lane stopped and self-parked; nothing runs at home; no retry. Access remains login's to restore (yesterday it came back only after login acted). Lesson for the record: "resume" is not evidence of access — the lane's first request is the check, and it costs one launch.

**14:07:31 SERVED — 1×40 `--hi 2014`, pid 9596, public address 104.243.245.238 (recorded for the two-site comparison).** login: "should be good as long as you make a new batch of workers under current ip … try now". First minute: 4,281 requests (53.7/s), 187 pdfs, 1 fail, 40 established connections. The 14:04 batch (same code, same shape) was refused on its first 5 requests three minutes earlier — the variable between the two launches was the CONNECTION, not the batch (every launch is a new process and a new pooled session; nothing survives an exit). Access restore = login's connection change, as on 09-01. Follower pid 16156; board loops 26008/29724; monitors armed.

**14:4x §14 addendum — WORKSTATION 2 IS A MACBOOK AIR (login pasted a bash prompt).** The Windows kit assumed drive letters and PowerShell; the package now takes every drive path from ONE environment variable, `CRE_SYS_ROOT` (the "CRE Decoding System" folder): corpus_paths SYS/NAV/NAV_DB/DOC_STORE, acris_pdf STORE, acris_reproduction LEDGER_DB, live_delta's refusal folder — default unchanged (D:/CRE Decoding System), verified by an import test under a fake root and by the default. ⚠ The HOME copy still hard-codes D: — port the same override at a pause (identical default, zero behaviour change). Transfer route: OneDrive on the home PC, folder `CRE Office/` — `decoder.zip` (modules + `run_office.sh` launcher with the guards + `README-mac.md`) and `Legal Instruments.db.gz` (825 MB, from 6.43 GB). Office drive must be exFAT (Mac read/write, Windows read for the merge; NTFS is read-only on a Mac, APFS invisible to Windows). Mac launch: `run_office.sh` = `caffeinate -i nohup python3 -u acris_reproduction.py … --lo 2014 --hi 3`; a MacBook still sleeps on lid close. No credentials needed for the documentation floor. Sizing: ~260 GB/day of PDFs at 40 — a few-hour TEST fits a local disk with ≥60 GB free; a sustained run needs the external drive.

## §15 — NYC CRE DECODES: THE TABLE MOVES TO THE CLOUD (login, 2026-09-02 14:5x–15:1x, from the office Mac)
login: "can the db in the one touch be stored in supabase, yes or no?" → yes. "make a NEW supabase … NYC CRE Decodes → reproduction → acris | Richmond → rebuild the db for each based on changes we would like to make since our current system is messy"; "remove the key type and key columns"; "I like the mint, but … build the automation into the python code and remove those columns too"; "do better with how we are pathing the pdf instead of just starting by document".
Cost answered: Pro is $25/mo per ORG with ~$10/mo compute credits; a second project adds ~$10/mo compute + disk over 8 GB at ~$0.125/GB (the table is ~30 GB in Postgres — the SQLite is 27 GB for the same JSON) → ~$13–15/mo extra. The existing decoder project is NOT idle (41/71 tables populated: parcel_geometry 1.7 M, residential_leases 1.4 M, parcels 1.2 M, building_bbl 1.1 M, decoder_documents 440k …) — it stays untouched.

**Schema (`nyc_cre_decodes_reproduction.sql`, pasted once; then Settings → API → expose schema `reproduction`):** `reproduction.acris` and `reproduction.richmond` (same shape): id · details jsonb (verbatim) · recorded_on date · doc_type · borough smallint · pages int · pdf ('' | pending | imageless | unservable | path) · site · landed_at. NO rd_url/pdf_url (python mints them: `urls(id)`), NO keyed_by/key. Indexes: partial todo on id, recorded_on, doc_type, borough, pages, landed. `reproduction.landings` (id, pdf, site, landed_at, applied_at) with trigger `apply_landing` routing by id prefix and updating only rows still todo (never repairs a value). View `board`; function `search_acris(year, type, borough, min_pages, has_pdf, limit)` = the six knobs. RLS on, service role only.

**The lane in cloud mode (`NAV_CLOUD=1`, `NAV_SITE=office|home`, `NAV_SUPABASE_URL` / `NAV_SUPABASE_SERVICE_KEY`):** the feeder reads `acris` where pdf = '' and details not null, lo < id < hi, id order (PostgREST `eq.` empty-string, `not.like`, `gt` + `order` all verified HTTP 200 on a populated table); the pending recheck reads pdf = 'pending'; the landing write is a DURABLE LOCAL QUEUE (`landings_outbox.db` under NAV_WORK) drained by one sender thread every 5 s to `landings` — a worker never waits on the network; a blip or a crash loses nothing. Tested with a stubbed cloud. Modes added: `--cloud-load` (one-time resumable copy of the SQLite into the source tables, typed columns parsed at load, disjoint --lo/--hi ranges in parallel), `--outbox SITE` (home transition: SQLite trigger → cloud landings), `--inbox` (home: mirror cloud landings into the SQLite so the board/search/Richmond keep working until they move).

**PDF layout (package only until home switches):** `acris/<borough>/<year>/<MM Mon>/<id>.pdf` (1 Manhattan … 5 Staten Island; microfilm borough = the id's first digit; unknown → `0 Unknown`; undated microfilm → `0000/00 Undated`) and `richmond/<year>/<MM Mon>/<id>.pdf`. The day level is gone (a borough-month ≈ 15–25k files). Existing files keep their `By Document` paths — the pdf cell is the truth, never re-derived. Borough is threaded from the rd JSON through `fetch_pdf(…, borough=)` into `doc_store_dir`.

**Package:** `C:/dev/cre-office/decoder` (+ `decoder.zip`; `run_office.sh` = cloud mode, office bounds, guards; `mac_storage.sh`; `README-mac.md`; snippets + `_build_cloud_package.py`, rerunnable). The slice transfer is MOOT in cloud mode — the OneDrive / Storage uploads earlier today are dead ends. ⚠ HOME still runs the SQLite lane (pid 9596, `--hi 2014`); it switches to cloud mode at a pause, after the load.

**Next (login owns the first three):** create the project → paste the SQL → expose `reproduction` → put NAV_SUPABASE_URL / NAV_SUPABASE_SERVICE_KEY into acris-decoder.env at home (for the loader) and into run_office.sh on the Mac. Then: `--cloud-load` from home in 4 disjoint ranges (hours), the Mac launches, home switches, the board and the search move to `reproduction.board` / `search_acris`.

**15:03:13 HOME 1x40 PAUSED for the restructure** (login: pause any reproduction lanes given the massive restructure): 55 min, 16,134 pdfs, 260 imageless, 21 fails, 57.2 req/s; log preserved as acris_repro_document.log.20260902-1503-paused-for-restructure; name parked. Dead ends cleaned: the office-transfer bucket in the OLD project and the OneDrive CRE Office folder. Next: login walks the restructure step by step - db, then the four lanes (enumeration=audit, synchronization, registration, documentation) with the status rules built into their code, then the monitor with a tab per lane.

**15:2x THE DATA DECODER PROJECT BECOMES THE HOME BASE (login: "literally make it blank", then rename to NYC CRE Decoded).** Decision: NO new project (Pro is per org; a second instance costs compute for nothing; a schema is its own clean namespace). The app runs on a DIFFERENT project (verified from both app repos' env), and nothing in the workload reads this one. Blank = drop schema public cascade + recreate with grants (SQL editor; REST cannot run DDL). Pro keeps 7 days of backups. Inventory dropped (78 relations, 42 with rows, 7,141,050 rows), largest first: parcel_geometry 1,714,708; residential_leases 1,442,605; parcels 1,192,472; building_bbl 1,082,984; decoder_documents 439,717; condo_sales 374,466; document_without_claim 174,142; source_document 174,142; document 149,005; decoder_parcels 135,610; decoder_entitlements 114,143; decoder_parcel_entitlements 66,547; building_parcel_keys 41,765; decoder_facts 18,264; lot_lineage 8,563; decoder_parcel_source 3,108; decoder_parcel_coverage 3,080; decoder_lpc_parcels 2,117; decoder_runs 1,069; decoder_bsa_parcels 991; decoder_bbl_spine 317; decoder_posting 270; decoder_v_parcel_timeline 270; decoder_v_function_summary 227; decoder_v_envelope_adjustment 119; decoder_lifecycle_link 83; decoder_v_zoning_lot_membership 71; decoder_workflow 44; decoder_consent 29; slot 27; decoder_document 15; vocabulary 15; decoder_v_envelope_balance_check 12; decoder_v_price_tape 11; decoder_source_registry 10; decoder_document_coverage 9; decoder_pipeline 6; decoder_stage 6; parcel_document 5; decoder_v_active_restrictions 4; parcel_ready 1; runs 1. Full list: C:/dev/cre-office/_public_inventory_20260902.json. Home-base structure: one schema per phase (reproduction now; organization, extraction, decoded later); lanes are roles over reproduction.acris/richmond; code to move into a small private repo (nyc-cre-decodes: reproduction/acris/<lane>.py + shared modules; each workstation clones; large files never in it).

## §16 — THE OLD PROJECT IS GONE; NYC CRE DECODED IS BLANK AND REACHABLE (login, 2026-09-02 15:12–15:58)
login: "I want this all empty as if a new project. no memory of anything" → not a wipe, a replacement. Data Decoder (ref trljekig) was DELETED by login after the check that every table in it was a COPY of files still on disk in the decoder folder (parcels ← spine/spine.jsonl 1,192,472 lines exact; parcel_geometry ← spine/geometry 4 files = 856,614 + 858,094; building_bbl ← _footprints.jsonl + _bin_bbl.json; residential_leases ← leases_raw 2 files 505 MB; decoder_documents/facts/runs ← C:/dev/decoder-sink; condo_sales ← sales_archive 66 DOF spreadsheets; source_document/document ← the old acquisition ledger, superseded by Legal Instruments.db). Nothing running read it (follow_doc / board_truth / routine_update never touch Supabase); the app is on its own project (ghjkjxfx, 15 tables of its own, none shared). Cost: a replacement is covered by the org's compute credit; a new project also starts on the included 8 GB disk (the old disk never shrinks).
NEW project **NYC CRE Decoded**: first made in West US Oregon by mistake, deleted, REMADE in **East US (N. Virginia), us-east-1** — ref **bhyputyffmuxxhapvhsz**, https://bhyputyffmuxxhapvhsz.supabase.co, Micro, PostgreSQL 17.6. Verified from home at 15:58: public schema 0 tables / 0 views; only Supabase's own schemas exist (auth, storage, realtime, vault, extensions, graphql, pgbouncer). REST root with the new `sb_secret_` key: HTTP 200, 0 relations (works with `apikey` alone and with `apikey` + Bearer).
**Access from here:** `C:/dev/nyc-cre-decoded.env` → SUPABASE_URL, SUPABASE_SERVICE_KEY (sb_secret_…), SUPABASE_DB_URL (SESSION POOLER, aws-0-us-east-1.pooler.supabase.com:5432 — the direct `db.` host is IPv6-only and does not resolve from home), SUPABASE_DB_PASSWORD on its own line (the executor substitutes + percent-encodes it). Executor: `python C:/dev/cre-office/decoded_sql.py --check | -c "sql" | -f file.sql [--dry]`, every statement appended to `_decoded_sql.log` → the schema has a written history. ⚠ NO SCHEMA YET: login dictates the structure step by step ("I want a blank project that I tell you how to build"); the earlier draft SQL is shelved.
