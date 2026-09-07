# NYC CRE Decoded

The process that turns New York City's public real-estate record into decoded intelligence, in three phases. Each
phase is a folder at the root of this repo; only the first exists yet.

| phase | what it produces | state |
|---|---|---|
| **REPRODUCTION** | every source's record reproduced into one place - the registered data in one cloud database, the documents on the One Touch, and the code that keeps both current: the document index | running: acris and richmond |
| **CONSTRUCTION** | the event index, built from the reproduced documents (it never existed before - it is constructed, not re-constructed) | not started |
| **PRODUCTION** | the products | not started |

This repo is the process. The data is not in it. The concept of the first phase, in login's words, is the section
"The table" of `Reproduction/rulebook/Rulebook.md`; the database that holds every phase is `supabase/Supabase.md`.

## Three homes

login 2026-09-05: "code = git, database = supabase, document = hard drive." Each home holds one kind of thing and
nothing of the other two; the same tree - phase, source - runs through all three.

| what | where | shape |
|---|---|---|
| database | Supabase project **NYC CRE Decoded** (East US); `supabase/Supabase.md` · `supabase/supabase.py` | one schema per phase: `reproduction`; per source a workflow table (`acris`, `richmond`), two update tables (`*_update`, `*_update_lanes`), a claims table and a heartbeats table; each phase's schema as numbered SQL in `<Phase>/rulebook/schema/` |
| code | this repo | `supabase/` at the root (the database's pair), then `Reproduction/` with the same three folders at every level (below) |
| documents | the One Touch, `D:\NYC CRE Decoded\Reproduction\` - the same tree as this repo and the database | `<Source>\By Document\<year>\<MM Mon>\<day>\<id>.pdf`, the day from the recorded date; a second workstation writes the identical tree under its own drive and records One Touch paths, then transfers |

Credentials live in `C:/dev/nyc-cre-decoded.env` (home), never committed or printed.

## The layout - the same three folders at every level

```
supabase/       Supabase.md · supabase.py       the one database (one project, one schema per phase) and its one program
Reproduction/                                   the phase
  rulebook/     Rulebook.md · lane.py · fleet.py · board.py · cloud.py · storage.py · rate_manager.py · requirements.txt · schema/
                                                the rules every lane of every source shares, written once; schema/ = the phase's tables as numbered SQL
  workflow/     Reproduction.md · Reproduction.py   the phase's authority, and every source's fleet kicked off as configured
  update/       Update.md                       the phase board across sources (a later SQL decision)
  Acris/                                        a source
    rulebook/   acris.py · Acris.md             the source's rules as one module, and its authority
    workflow/   reproduction/ enumeration/ synchronization/ registration/ documentation/
                                                a pair per folder: `Acris <Lane>.md` (its authority) · `Acris <Lane>.py` (its one program)
    update/     Acris Update.md · Acris Update.py   the board: one program, two tabs in Supabase
  Richmond/     the same
```

Three levels, one shape (login 2026-09-05): a **lane** is one program in its own folder, run alone from there -
`python "Acris Documentation.py" --drive OneTouch` is the whole command; a **source** is its lanes together,
configured in its fleet program (`Acris Reproduction.py`); the **phase** is every source's fleet, kicked off as
configured (`Reproduction/workflow/Reproduction.py`). Every folder that holds code holds a pair - the md is that
thing's own authority, the py its one program - and a proof beside it (`test_*.py`) that asks nothing of any source.
Nothing is loose: a source folder is its three folders; the phase folder is its three folders and the sources; the root
is the phases and the database's own folder, `supabase/`. The phase's authority is `Reproduction/workflow/Reproduction.md`;
the rulebook's is `Reproduction/rulebook/Rulebook.md`; the database's is `supabase/Supabase.md`.

## The phase: reproduction

Two sources, `acris` and `richmond`. Per source one workflow table, one row per document: a `source` column in
front (a constant per table, for the cross-source tables of construction) and three cells: `doc_id` · `registry` ·
`document`. No URL or key columns: every URL is minted from the id. Each source has four lanes, each its
own code in its own folder, toggled independently and configurable in width; three of them fill the cells.

| lane | job | fills |
|---|---|---|
| enumeration | the audit, not a cycle lane: counts the source (acris: Socrata + CRFN; richmond: census + date/range), compares with the table, difference must be 0 | nothing (no table) |
| synchronization | keeps the table live: the CRFN edge monitor and walkers for acris, the date walk for richmond | `doc_id` |
| registration | the recorded details, by a URL minted from the id stem; no navigation step | `registry` |
| documentation | the document, by minted access; saved to the drive, its full One Touch path recorded | `document` |

**The cell rule.** Each lane fills its own cell and nothing else. A cell holds the fill or one of two words: `pending`
(recorded but not yet served, inside the source's window; it stays in the backfill until it becomes the fill or
`absent`) or `absent` (checked: there is none). Nothing else can go in a cell; the table itself refuses it. Anything
but empty counts as landed.

**Two workstations, no overlap.** The table is the only to-do list. A lane calls `claim()` for a slice of empty cells
with its name and an expiry on them, atomic and skip-locked so two machines never receive the same document; the
pendings due for a re-check come first. It fills them with `land()` once a minute, which drops the claims; expired
claims go back on the list. Each running lane writes `heartbeat()` once a minute. Synchronization runs at home;
registration and documentation on any machine.

**Joining a second workstation (the steps, 2026-09-05; on login's word).** 1. `git clone https://github.com/loginwilson/NYC-CRE-Decoded`
and `pip install -r Reproduction/rulebook/requirements.txt` (Python 3.12). 2. The env file - `C:\dev\nyc-cre-decoded.env` on
Windows, `~/nyc-cre-decoded.env` on a Mac, or wherever `NYC_CRE_DECODED_ENV` points - with `SUPABASE_DB_URL` (the session
pooler) and `SUPABASE_DB_PASSWORD`, typed in by hand, never committed. 3. `python supabase/supabase.py check` prints the
ledger: every migration applied. 4. A drive for the documents, named by its label; a lane is launched from its own folder
with that label and this machine's name - `python "Acris Documentation.py" --drive <label> --host <name> --width 20` - the
files land under that drive in the same tree, every cell carries the One Touch path (`Reproduction/rulebook/storage.py`),
and the claims (out of sight, `machinery.claims`) hand each machine its own slice; `reproduction.updates` shows every workstation's row - lane, workers, landed, last seen - beside the phase and lane rows (migration 0007, 2026-09-06). 5. Synchronization stays on one machine, and RICHMOND DOCUMENTATION RUNS ON A LINE WITHOUT THE VPN while the ACRIS lanes run on it: Cloudflare in front of the courts host challenges the VPN's exits and serves the residential line (measured 2026-09-06 21:57), and one machine's tunnel is system-wide, so workstation 2 on the office IP takes richmond documentation. Nothing else is
configured: the code, the rules and the to-do list are the same everywhere.

**The update.** One program per source, always running, reading only: tab 1 is the phase (rows with all three cells
filled against rows), tab 2 is the lanes (each cell filled against rows), both with 60-second and 5-minute rate,
increase, percent and eta, landed, needed, percent of total, status and as-of. The status follows the lane's own
heartbeat: `active` (fresh heartbeat, landed rising) · `pending` (no fresh heartbeat, not complete: paused or parked) ·
`stalled` (the lane's last word is a refusal or a wall; a refusal parks at once) · `complete` (100 %).

**The three managers (login 2026-09-04).** On the acris document lane the batch manager is the cycle itself (the exit
pool settled in one block, one entry, a fresh batch); the rate manager enters with one worker and adds one every 5 s
until the docs/s meets the band, then adjusts every window under the request ceiling; the session manager ends the
session at 1,000,000 requests and hands back to the batch manager. Knobs in the fleet program, never code.

## Rules that do not bend

- One entry per client: one pooled session, one connection per worker at birth, births 5 seconds apart, keep-alive after, no further handshakes. Never a handshake burst: forty births in twenty seconds were cut at the door where a 200-second ramp was served (2026-09-04).
- A block is HTTP 200 plus the Bandwidth Notice page, nothing else. A redial into a notice is refused; the notice lifts on its own clock. A hang-up (the far side closing the whole width inside a minute) is ACRIS's ordinary session end, not a block: the lane hangs up at once, drops the cut batch, waits 60 seconds with no line open, and re-enters once on a fresh batch with births 5 seconds apart; a refused re-entry doubles the next wait, a served one halves it back; wifi down waits; four tries per incident, then park with the reason. A partial close is redialed worker by worker. A notice page is never re-entered. A fetch error never stops a lane.
- Never kill a lane on a fail count; its own detectors decide. Never edit running code.
- Never repair a number to make a check pass. Report the failure.
- Env files, databases, documents and bulk inputs never enter git. The One Touch is storage only; code lives here.
