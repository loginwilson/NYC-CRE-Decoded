# Acris Synchronization

The synchronization lane of the acris reproduction, as one program: `Acris Synchronization.py`. It keeps the table live at the CRFN edge: one monitor and a crew of walkers behind one entry. While the edge is level the monitor probes a few numbers past it every minute; the moment a filing shows, the crew walks a full bite of numbers in parallel, every document found lands as a new row — the `doc_id` cell, nothing else — and the edge moves to the last document seen. This file is the lane's own authority; the cycle's is `../reproduction/Acris Reproduction.md`.

## Why the CRFN edge

ACRIS sells no date window: the id and CRFN searches have no date field, the type search demands a type and bounces a GET, and the open-data extract is weeks behind. The City Register File Number is one strict citywide counter across both corpora (real property and personal property), essentially gapless, continuous across months. The numbers above the last one we hold are the only live re-readable window the source offers, and one plain GET of the detail page by CRFN answers whether a document sits at a number: the live page carries `DOCUMENT ID`, the stub does not (measured 2026-08-23: 131 KB against 10 KB, no session, no token).

## Launch

    python "Acris Synchronization.py" --edge 2026000247108      the first start names the edge
    python "Acris Synchronization.py"                           afterwards synchronization.edge.json remembers it

Home only: the edge lives on one workstation. `--width` defaults to 20 walkers. `--every 60 --watch 8 --bite 1000` are the cadence knobs. `synchronization.control` takes `width=N` or `stop`. A parked lane refuses to start again until `--unpark`.

## The rules

| rule | what the lane does | origin |
|---|---|---|
| the edge | `synchronization.edge.json` holds the last CRFN whose document the table holds. A start without it needs `--edge`, never a guess. The edge moves only after the documents it passes are in the table, so a crash re-walks the same numbers and loses nothing | the old `_crfn_edge.json`; the 2026-08-28 monitor |
| the monitor stands at the elevator | while level, `--watch` numbers past the edge every `--every` seconds; the crew only walks on a hit | login 2026-08-28: the old loop dispatched a full bite every tick and spent ~36 req/s to land nothing |
| behind | a document within `--watch` numbers of the end of the probed window means more beyond: walk a `--bite` at once and keep walking until a window ends in blanks | the same monitor |
| a blank is an answer | the source said no document is at that number. Blanks past the last document are unissued numbers and are asked again next time | the counter is forward-only |
| an error is not an absence | a failed request is asked again, never read as blank. Three failed asks make a hole: recorded in `synchronization.holes.jsonl`, passed, and left to the audit — one bad number never freezes the edge | acris_edge.quick_crfn, 2026-08-23: a broad except once printed "quiet" after eight instant failures |
| personal-property runs | UCC filings take numbers in the same counter and answer blank here (about a sixth of the sequence). After `--widen-after` empty watches one wider look of `--widen` numbers is taken, so a run of them can never hide a document from a narrow watch | live_delta's CRFN measurements; a stall the old monitor could not rule out |
| a live page is a full page | a detail parsed from fewer than 20 KB is suspect truncation and is asked again, never reported live | acris_edge, `_MIN_DETAIL` |
| the cell | the `doc_id` only. The page fetched is the registry page, and registration will fetch it again for the recorded details: one more request per new document. The cell rule is worth it | login 2026-09-03: each lane fills its own cell and nothing else |
| the counters | a new row moves `needed` for the phase and every lane, and synchronization's `landed`, in the same transaction as the insert | the counting rule |
| one entry, one door, refusal, hang-up, wall, width | shared with every lane; see Acris Documentation.md | lane.py |
| one machine | the edge is local state; the lane runs at home | SCHEMA.md |

## Calibrations

| knob | value | how it was measured, how it fails |
|---|---|---|
| width | 20 | the crew of walkers behind one entry; the counter moves about 1,300 documents a day, in bursts |
| every | 60 s | a watch of 8 requests a minute while level; a filing is seen within a minute |
| watch | 8 | the old monitor's number; also the trailing-blank rule that decides behind or level |
| bite | 1,000 | walked by 20 walkers in about a minute; a bite of 131 KB pages is about 130 MB |
| widen, widen-after | 64 after 5 empty watches | a run of personal-property numbers longer than a watch is rare but not impossible; the wider look costs 64 requests every five quiet minutes at most |
| timeout | 45 s | the old probe's |
| holes | 3 asks | then recorded and passed |

## The blind spot, written down

A forward-only counter inherits every gap it already has and reports clean forever: it cannot see a document withdrawn or re-keyed, and it cannot see a hole it passed. The audit (enumeration: the source census against the table) is the ground truth on a slower schedule. This lane never claims otherwise.

## Working files

Beside this file, never in git: `synchronization.edge.json`, `synchronization.holes.jsonl`, `synchronization.lock`, `synchronization.control`, `synchronization.parked`, `synchronization.fails.jsonl`, `Reproduction/Acris/refusals/`. Exit codes: 0 stopped · 2 refused · 3 redials exhausted · 4 wall · 5 crash.

## History

2026-09-03 — written from the sync floor of `acris_reproduction.py` (monitor, crew, land, edge) and `acris_edge.py` (the probe), every line read. Proven offline (the probe URL, the id from a live page, the stub, the truncation guard, the edge file's fail-closed start) and by a simulated walk against the live cloud with throwaway numbers and no ACRIS request: a burst behind the edge walked in bites, personal-property blanks passed, a failing number recorded as a hole and passed, the edge moved only after the rows were in, the level watch and the wider look. Not yet proven: a real probe, which waits for the data move. The old edge file's last movement was 2026-08-31; the table has been behind since, which the audit will show.
