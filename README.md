# NYC CRE Decoded

The reproduction of New York City's public real-estate record sources into one place: the registered data in one cloud database, the documents on the One Touch, and the code that keeps both current. This repo is the process. The data is not in it. The concept, in login's words, is `Reproduction/SCHEMA.md`.

## Three homes

| what | where | shape |
|---|---|---|
| database | Supabase project **NYC CRE Decoded** (East US) | schema `reproduction`; per source a workflow table (`acris`, `richmond`), two update tables (`*_update`, `*_update_lanes`), a claims table and a heartbeats table |
| code | this repo | `Reproduction/<Source>/workflow/<lane>/` and `Reproduction/<Source>/update/` |
| documents | the One Touch, `D:\CRE Decoding System\Documents\` | `source\borough\year\month\id.pdf` (richmond has no borough); a second workstation mounts its drive under the same letter and layout, then transfers |

Credentials live in `C:/dev/nyc-cre-decoded.env` (home), never committed or printed.

## The phase: reproduction

Two sources, `acris` and `richmond`. Per source one workflow table, one row per document, three cells: `doc_id` · `registry` · `document`. No URL or key columns: every URL is minted from the id. Each source has four lanes, each its own code in its own folder, toggled independently and configurable in width (1x40, 1x20, one entry of 100 split 20/40/40); three of them fill the cells.

| lane | job | fills |
|---|---|---|
| enumeration | the audit, not a cycle lane: counts the source (acris: Socrata + CRFN; richmond: census + date/range), compares with the table, difference must be 0 | nothing (no table) |
| synchronization | keeps the table live: the CRFN edge monitor and walkers for acris, the date walk for richmond | `doc_id` |
| registration | the recorded details, by a URL minted from the id stem; no navigation step | `registry` |
| documentation | the document, by minted access; saved to the drive, its full One Touch path recorded | `document` |

**The cell rule.** Each lane fills its own cell and nothing else. A cell holds the fill or one of two words: `pending` (recorded but not yet served, inside the source's window; it stays in the backfill until it becomes the fill or `absent`) or `absent` (checked: there is none). Nothing else can go in a cell; the table itself refuses it. Anything but empty counts as landed.

**Two workstations, no overlap.** The table is the only to-do list. A lane calls `claim()` for a slice of empty cells with its name and an expiry on them, atomic and skip-locked so two machines never receive the same document; it fills them with `land()` once a minute, which drops the claims; expired claims go back on the list. Each running lane writes `heartbeat()` once a minute. Synchronization runs at home; registration and documentation on any machine.

**The update.** One program per source, always running, reading only: tab 1 is the phase (rows with all three cells filled against rows), tab 2 is the lanes (each cell filled against rows), both with 60-second and 5-minute rate, increase, percent and eta, landed, needed, percent of total, status and as-of. The status follows the lane's own heartbeat: `active` (fresh heartbeat, landed rising) · `pending` (no fresh heartbeat, not complete: paused or parked) · `stalled` (the lane's last word is a refusal or a wall; a refusal parks at once) · `complete` (100 %).

## Layout

```
Reproduction/
  SCHEMA.md                       the concept, in login's words
  lane.py · cloud.py · storage.py the pieces every lane shares
  supabase/migrations/            one numbered SQL file per dictated decision; supabase/db_push.ps1 applies them
  Acris/     rulebook/ (acris.py · Acris.md) · workflow/{reproduction,enumeration,synchronization,registration,documentation}/ · update/
  Richmond/  rulebook/ (richmond.py · Richmond.md) · the same
```

In every lane folder a pair named for the source and the lane: `Acris Documentation.md` (that lane's authority) and `Acris Documentation.py` (its one program). `workflow/reproduction/` holds the source's authority and the fleet program that runs the whole cycle; `update/` holds the board pair; `rulebook/` holds the source's rules as one module and that module's authority (`acris.py` · `Acris.md`). A source folder is those three folders and nothing loose. Everything about a source lives in its folder; everything about the phase lives at the phase level. There is nothing else at the top. A lane is launched from its own folder: go to Acris, workflow, documentation, and `python "Acris Documentation.py" --drive NYCCRED1` is the whole command.

## Rules that do not bend

- One entry per client: one pooled session, one connection per worker at birth, births 5 seconds apart, keep-alive after, no further handshakes. Never a handshake burst: forty births in twenty seconds were cut at the door where a 200-second ramp was served (2026-09-04).
- A block is HTTP 200 plus the Bandwidth Notice page, nothing else. A redial into a notice is refused; the notice lifts on its own clock. A hang-up (the far side closing the whole width inside a minute) is ACRIS's ordinary session end, not a block: the lane hangs up at once, waits 60 seconds with no line open, and re-enters once on a fresh batch with births 5 seconds apart; a refused re-entry doubles the next wait, a served one halves it back; wifi down waits; four tries per incident, then park with the reason. A partial close is redialed worker by worker. A notice page is never re-entered. A fetch error never stops a lane.
- Never kill a lane on a fail count; its own detectors decide. Never edit running code.
- Never repair a number to make a check pass. Report the failure.
- Env files, databases, documents and bulk inputs never enter git. The One Touch is storage only; code lives here.
