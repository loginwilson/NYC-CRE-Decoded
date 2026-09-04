# Richmond — registration

One program, `Richmond Registration.py`, beside this file. It fills the **registry** cell of every richmond row that needs one: the recorded details the county publishes on a document's detail page, as JSON. Documentation reads the image in its own pass; this lane never touches the document cell.

```
python "Richmond Registration.py" --edge 2026-08-25     the first start names the last day whose registries were walked
python "Richmond Registration.py"                       afterwards registration.edge.json remembers it
python "Richmond Registration.py" --width 4 --every 900 --days 30 --pace 0.3 --pending-age "1 hour"
```

The cycle's authority is `../reproduction/Richmond Reproduction.md`; the shared machinery (the crew and its staggered births - here every walker keeps its OWN session, the county's grant being per session - the outbox, the heartbeat, the refusal park, the hang-up and wall breakers, the width control, the lock) is `Reproduction/lane.py` and is not repeated here. The hang-up is DORMANT at this county (no session close was ever measured here - the drumroll rule, `RICHMOND REPRODUCTION.md` §3): it fires only when the wire itself dies, and then the cut pages and details are dropped from the queue and forgotten as in flight (`rebatch`: asked again at the next walk, a details item releasing its window's count so the window can close), 60 s of silence, one re-entry with births 0.4 s apart (the county's measured handshake stagger); four refused re-entries in a row park it.

## The rule that shapes this lane: the grant

The county serves a detail page (`/Search/viewDocumentInfo/<internal id>`) only to a session that has just fetched the listing page the id appears on (measured 2026-08-21, the redesigned site). A cold fetch answers **HTTP 200** and a 4,212-byte shell, or the words `INVALID REQUEST: UNAUTHORIZED SEARCH ACCESS` (2,180 bytes). That answer is not a refusal and not an absence: it says *our grant did not take*.

So this lane cannot do what the ACRIS registration lane does — take ids from a claim and go get them. It **walks the listing** and fills what it passes:

1. a worker fetches a listing page (`page`) and answers its rows and the page count;
2. the monitor asks the table which of that page's ids need work — registry empty, or `pending` and last checked longer ago than `--pending-age` — and queues a `details` item for exactly those;
3. a worker fetches **that page again in its own session** (the grant), then each target's detail in order, `--pace` apart, and answers the registries;
4. the monitor lands them through the outbox.

Every worker holds its own keep-alive session (the grant is per session), born staggered by the crew. A detail that comes back as the shell is asked again (three asks), then it is a hole. Nothing here rotates, disguises or retries past the county's word: a captcha, access-denied or block page parks the lane at once (exit 2).

## The walk

- **The trailing window.** Every `--every` seconds (900: the old heal cadence) the lane walks the trailing `--days` (30, the county's silent cap on a date range) — page 1 of the window, then pages 2..N fanned out across the workers, each page's needed ids as a `details` item. A page whose ids the table already holds filled costs the county one listing request and nothing more.
- **The catch-up.** On a start, if the edge is older than the trailing window, the days from the edge + 1 to the day before the window are walked first, in 30-day windows.
- **The edge** (`registration.edge.json`) is the last day whose registries were walked. It moves only after a window's pages have all answered and its details are all landed, never on an empty-looking page, and never past an earlier window still open or holed. The first start must name it (`--edge`); the file refuses an `--edge` that disagrees with it (remove the file if the day is meant to change).
- **The control.** Before the first walk and before every walk the lane asks a window known to hold documents (`richmond.CONTROL`: 2026-08-19..20, 315 rows). If page 1 parses no rows, the parser is broken and no empty page may be believed: the lane parks with `PROBE BROKEN` (exit 3) until the parser is re-proven.
- **Holes.** An item that fails three asks (wire, wall, the shell) is written to `registration.holes.jsonl` and asked again at the next walk. A detail that fails three asks is a hole by id.

## The value

The parser is the one that landed 2.4M details in the old walker (`rc_rd_walk.parse_detail` + `rc_source.image_state`), kept verbatim in `richmond.parse_detail`:

| field | from | trap |
|---|---|---|
| `instrument` | `Document No.:` | the label carries a **period** on modern pages and none on old ones; a plain `Document No:` froze every same-day 2026 document at `''` (2026-08-22) |
| `book`, `page`, `doc_type`, `recorded`, `amount`, `status` | the RECORDED DETAILS labels | a blank field stays blank (the next label never bleeds in); the image link is stripped from the status |
| `parcels` | BLOCKS AND LOTS | `[{"bbl": "5" + block(5) + lot(4)}]` |
| `parties` | the PARTIES table (Name / Company / Party) | the **column** the clerk typed the name in is kept; the party's kind is never inferred |
| `image_state` | the page's two markers + the lag | `present` (View Imaged Document) · `pending` (No Image Available inside `IMAGE_LAG_DAYS` = 7) · `absent` (past it) · `unknown` (neither marker: asked again, never a conclusion) |
| `listing` | the listing row | recorded, type, instrument as the listing printed them |
| `at` | the lane | when the detail was read |

Three outcomes, and the table's cell rule admits only these:

- a **dict** — the detail above;
- **`pending`** — a *premature* detail: no instrument number yet (a document registered the day it was recorded). The table hands it back after `--pending-age` and the lane asks again until it matures (the old `rc_rd_refresh`);
- **`absent`** is not produced by this lane: the listing itself is the proof the document exists. The shell, an unrecognised page and an id the page no longer lists are *asked again*, never concluded.

## One machine

The walk is the work list. Two workstations walking the same window would spend the county's requests twice for the same registries, and claims cannot help because the grant is per listing page. Run this lane on one workstation; the 2.5M historical registries arrive by the data move, not by a walk.

## Exit codes

`0` stopped · `2` refused (parked; `--unpark` after a person decides) · `3` four re-entries in a row refused, or the probe broken (the lane parked itself) · `4` wall · `5` crash.

## Proof (2026-09-03; the review 2026-09-04)

- **2026-09-04 (night)** — the review against the record: `rebatch` added (a dead wire could have left a page or a details item stuck as in flight, and a window that never closes never moves the edge); births set to the county's 0.4 s; the inherited cycle named dormant. Proven offline (`test_richmond_rebatch.py`) and by the simulation again.

- **Offline** (`test_richmond_reg_offline.py`): the parser on a page in the county's shape — both `Document No.` labels, blank book/page, BBLs, the party columns, the four image states, the premature detail, the shell as `None`; the walker's order in one session (page, then details), the shell asked again, three wire failures raising `Transport`, a 503 raising `HTTPStatus`, a block page raising `Refused`; the monitor — control first, the catch-up from the edge, pages 2..N fanned out, a `details` item carrying only the ids the table needs, both a dict and a `pending` landed through the outbox, the outbox holding a landing through a cloud hiccup, the edge moving only when the window is complete, holes after three asks (page, detail, control), the next walk re-asking the holes, the broken control parking with code 3, the fail-closed edge file.
- **Live cloud simulation** (`test_richmond_reg_sim.py`): throwaway `RC_9900000xx` rows with empty / `pending` / filled registries; `cloud.todo` returns the empty and the *due* pendings only; a landing fills the cells and moves the lane's counters; a re-ask after the pending age; cleanup + reconcile. No request to the county.
