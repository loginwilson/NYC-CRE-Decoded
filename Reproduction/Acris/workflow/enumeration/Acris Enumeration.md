# Acris Enumeration

The enumeration lane of the acris reproduction, as one program: `Acris Enumeration.py`. It is the audit, not a cycle lane: it counts the source, compares with the table, and the difference must be 0. It never writes a cell and has no table. What it finds is written beside this file for a person to act on. This file is the lane's own authority; the cycle's is `../reproduction/Acris Reproduction.md`.

## The law

**BULK BASELINE + LIVE TAIL = TOTAL** (login, 2026-08-29, for every source). The baseline is complete but always stale; the tail is live but reaches only so far back. Neither proves anything alone: the audit is the arithmetic that closes them against each other, and their ranges must overlap so no filing can hide in a seam.

For acris the baseline is ACRIS's own published index on NYC Open Data (two Socrata masters, one per corpus, refreshed monthly and weeks behind) and the tail is the CRFN walk of the synchronization lane. The index is read from a different host than the web endpoint, so the audit is never a second door at ACRIS. And the index can silently omit real records: it dropped 201 live documents in 2016 alone, found only by the per-year CRFN census. So acris needs three checks, not two.

## Launch

    python "Acris Enumeration.py"                       the newest 3 months of the index against the table, and the tail
    python "Acris Enumeration.py" --all                 every band: film FT_ and BK_, every digital month, the odd ids (a long run)
    python "Acris Enumeration.py" --shard 202408        one shard: a month YYYYMM, FT_<borough><digit> or BK_<yy>; repeatable
    python "Acris Enumeration.py" --census              per year: the index's CRFN list and the holes named (no ACRIS request)
    python "Acris Enumeration.py" --probe --acris       the named holes and each year's top asked of ACRIS itself

Any workstation can run the diff and the census (they read the index and the table). The probe asks ACRIS itself and runs on login's word only: `--acris` is that word, and the program refuses to start while any lane's heartbeat is fresh, because an enumeration sweep of the web endpoint never runs beside the cycle. Exit codes: 0 the difference is 0 · 1 a difference · 7 unproven · 2 refused · 3 hang-up · 5 crash.

## The three checks

| check | what it proves | what it cannot see |
|---|---|---|
| **the diff** — every id the index holds must be in the table, shard by shard (a month of digital ids; a film prefix `FT_<borough><digit>` or `BK_<yy>`; the odd ids outside every band) | the baseline: film completeness rests on this alone, since film has no counter | what the index itself omits, and everything after its `good_through_date` |
| **the census** — per year, the index's CRFN list; holes = numbers in 1..top the index does not hold | an upper bound on documents missed in the digital era, named number by number | which holes are void and which are documents: that needs the probe |
| **the probe** — each named hole asked of ACRIS by CRFN: void (the stub), held (its document is in the table) or MISSING; each year's top confirmed by a gallop past the index's highest number | the identity per year: index + held + missing + void = issued, closed only when nothing is unknown | the tail: the current year is capped at the index's own top, everything above it is the walk's |
| **the tail** — reported, not proven here | the edge file's number and age, whether synchronization is alive | anything past the edge |

Ids the table holds that the index does not are classified, never counted against the table: **tail** (dated after the index closed), **seam** (dated inside the last 92 days before it closed: recorded after), **omitted** (older: the index dropped it, the walk found it), **odd** (no date to judge by). They are listed with their class in `enumeration.extra.txt`.

## The rules

| rule | what the program does | origin |
|---|---|---|
| an empty denominator is never a pass | the index's own count is read before any zero is believed; a shard the index answers empty where the table holds rows is UNPROVEN, never a pass | a 45-day richmond window returned a silent zero and printed `held 0/0 · MISSING 0` (ACRIS REPRODUCTION.md §5) |
| every pull is held to its own count | a throttled index call answers HTTP 200 and `[]`; each shard is pulled after a `count(distinct document_id)` for the same range and a short pull is Void, asked twice more, then UNPROVEN | acris_bulk_rd.py, 2026-08-31: one run returned 0/322 and would have read as "every id is missing" |
| `$order=:id` on every page | without an order, `$offset` paging silently drops and duplicates rows while the count stays right | bulk.py, measured 2026-08-06 |
| distinct ids | the index repeats rows (15,348 duplicate rows in the real master) | measured 2026-09-04 |
| 5xx retried, 4xx never | a 5xx or a dropped wire is the server's moment; a 4xx is this client's query and is raised at once | bulk.py |
| the shard list is the index's own | prefixes come from the index and the table, never assumed; the range form of the query, not `starts_with` | measured 2026-09-04: the range form answered a 50,000-row page in 2.5 s against 8 s |
| never repair a number | a difference is reported, listed and left; nothing here inserts. Missing ids are for a person: landing them is a decision, not the audit's act | the security rules; the index is an audit, not a discovery source |
| the seed is the control | the gallop for a year's top starts at the index's own highest number, which must resolve first, or the probe is broken and the top is UNPROVEN | live_delta.resolve_holes: a malformed request returns the same empty page as a real negative |
| a hole is not the edge | after the gallop and bisect, a Fibonacci spread (1, 2, 3, 5, 8, 13, 21, 34, 55, 89) is asked; a hit resumes the climb from there | acris_census.year_edge, 2009: a gallop from 1 stopped at 122 with 430,881 documents held |
| an error is not a void | a number that fails three asks is UNKNOWN and leaves the year's identity OPEN; a blank answer (the stub) is a void | live_delta, 2026-08-23 |
| the probe is a door | one pooled session, `--width` connections born `--stagger` apart, no pacer; HTTP 200 + the notice page is a refusal: stop, no retry, no rotation, `enumeration.parked` until `--unpark`; every line dropped at once is a hang-up: stop with exit 3, the journal resumes | the lanes' access shape (Acris Documentation.md) |
| never beside the cycle | the probe refuses to start while any lane's heartbeat in the cloud is fresher than 3 minutes. The heartbeat cannot see a lane that does not heartbeat (the old lane at home): that is what login's word is for | ACRIS REPRODUCTION.md §5 |
| the current year is capped | holes are named only up to the index's own top for the running year; everything above it was walked number by number by synchronization | acris_void_walk.py |
| resumable | `enumeration.holes.json` is written after every year, `enumeration.probe.json` every 30 seconds; a rerun classifies only what is still unknown | the void walk's journal |

## Calibrations

| knob | value | how it was measured, how it fails |
|---|---|---|
| the index | real `bnx9-e6tj` 17,049,742 distinct ids; personal `sv7x-dduq` 4,544,590; both good through 2026-07-31 | measured 2026-09-04. Both masters hold every band: FT_ (a borough digit 1–4 then a digit; no FT_5: Staten Island's film lives at Richmond County), BK_ (a two-digit year 66–81), digital (2002-12 on). One garbage id in the personal master (`--51e9…--`) and two rows without a recorded date |
| page | 50,000 | honoured (measured 2026-08-05); a page shorter than this ends a walk |
| shards | 284 digital months of at most 57,941 rows; 40 FT_ prefixes of at most 231,241; 16 BK_ of at most 124,810 | the index's own prefix census; a month is one or two pages, a film prefix up to five |
| default scope | the newest 3 months of the index, plus every table month past it (the tail, not asked of the index) | the cheap daily run; `--all` is the full history |
| seam | 92 days | an id is minted before it is recorded; an id dated inside the index's last three months may have been recorded after the extract closed |
| probe width | 10 connections, births 0.5 s apart | the void walk's number (2026-08-21: 10 workers, one session each, no refusal); the meter is rate per connection, and the probe is a small run |
| asks per number | 3 | then UNKNOWN; the gallop's numbers likewise |
| hang-up | 3 × width transport errors with nothing answered for 60 s | the lanes' breaker |
| guard | a heartbeat fresher than 3 minutes | lanes heartbeat every minute |
| the old census, for scale | 2003–2026: issued 11,585,922, held 11,578,284, 7,638 holes named; 7,010 classified: 6,808 void, 201 real documents the index dropped (all 2016), 1 already held | acris_census.py + acris_void_walk.py, 2026-08-21 |

## Working files

Beside this file, never in git: `enumeration.report.txt` (the last run's report, also printed), `enumeration.log` (every run appended), `enumeration.missing.txt` (index ids the table lacks), `enumeration.extra.txt` (table ids the index lacks, with their class), `enumeration.holes.json` (the census: per year the index count, the top, the holes), `enumeration.probe.json` (the probe's journal: every number's verdict, every year's top), `enumeration.probe-missing.txt` (documents the probe found that the table lacks), `enumeration.lock`, `enumeration.parked`, `Reproduction/Acris/rulebook/refusals/`. The board never shows enumeration: its report is the file, and its verdict is the exit code.

## Open

- **Landing what the audit finds.** Missing ids (the diff) and missing documents (the probe) are listed, never inserted. The synchronization lane's insert is the one door for new rows; a small script over the two lists, on login's word, is the likely shape.
- **The census against the table's own CRFNs.** The holes are named from the index alone; the table's registries carry `crfn` too, but reading them per year is a scan of every registry (no expression index yet). When the schema grows an index on the registry's CRFN, the census can name holes against the table directly and the probe shrinks to what neither holds.
- **The 322 ids whose detail page fails** (registration's open decision): 318 are in the real master and 4 in the personal master, so the diff will always find them present and say nothing; their registry is registration's question, not the audit's.

## History

2026-09-04 — written from ACRIS REPRODUCTION.md §5 (the law and the three checks), `acris_census.py` (the per-year top: seed, gallop, bisect, Fibonacci confirm), `acris_void_walk.py` (the index's CRFN list per year, the holes named, the walk's verdicts, the identity), `live_delta.py` (the control before any hole is believed; an error is never a void), `acris_bulk_rd.py` (the throttle answers `[]`; controls in every batch) and `bulk.py` (`$order=:id`, 50,000 a page, 5xx retried and 4xx never), every line read. The index was measured live the same day (both masters, every band, the shard sizes, the range form). Proven offline (the fake index: paging, the count control, Void; the fake counter: the gallop, the seed as control, a hole past the top, three failed asks; the identity math), by a simulation against the live cloud with throwaway rows and a fake index and counter (the difference found and listed; the pass with omitted, seam and tail classified; Void and an empty denominator both UNPROVEN; the heartbeat guard; holes classified void, held and MISSING; the top galloped; the identity closed; a rerun that asks nothing; a refusal that parks and holds; a hang-up), and live against the real index: the diff of one shard (2002-12, 155 ids) against the still-empty table fails as it must (155 missing, listed), and the census of 2026 names 216,588 index CRFNs, top 216,616, 28 holes: the same 28 numbers the old census named on 2026-08-21 from the same July extract. No ACRIS request made.

Flags not named above: `--months` (the newest months diffed by default, 3), `--years` (narrow the census or the probe), `--retop` (re-gallop a year's top), `--host`. The probe's journal is written through `enumeration.probe.tmp`. A refusal to start (`--probe` without `--acris`, a fresh lane heartbeat, a parked probe) leaves with 5 like a crash.
