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

**Joining a second workstation (the steps, refreshed 2026-09-07 after gate 4's first night; on login's word).** Nothing
on the second machine needs Claude Code: the batch, rate and session managers are plain Python in `Reproduction/rulebook/`
(`lane.py`, `rate_manager.py`) and run wherever the lane runs. There is no allocation to hand out: the table is the only
to-do list, `claim()` is atomic and skip-locked with the host's name on every claim, so two machines never receive the same
document, and a claim that expires (20 minutes) goes back on the list. The steps:

1. Python 3.12. `git clone https://github.com/loginwilson/NYC-CRE-Decoded` (or unzip main) into `C:\dev\nyc-cre-decoded`, then
   `pip install -r Reproduction/rulebook/requirements.txt` (requests, psycopg2-binary, img2pdf, Pillow).
2. The env file `C:\dev\nyc-cre-decoded.env` holding `SUPABASE_DB_URL` (Connect > Session pooler > URI) and
   `SUPABASE_DB_PASSWORD` - typed in by hand, copied from the home machine, never committed, never printed.
   `python supabase/supabase.py check` must print the ledger with every migration applied.
3. The documents drive, named by its **volume label** (case-insensitive): label the second drive `NYCCRED2`. The lane finds
   it by label, creates `NYCCRED2:\NYC CRE Decoded\Reproduction\Acris\By Document\<year>\<MM Mon>\<day>\<id>.pdf` itself,
   and every cell it lands carries that same tree path - so the files can later be moved into the One Touch with no change
   to the database.
4. **ACRIS from the office line, VPN OFF** (2026-09-07: the VPN provider's exits are throttled per block; the office IP is the
   resident address). Richmond documentation also runs without the VPN. The lane's own gate draws the exit five times and
   enters only when all five are one block.
5. Launch the lane through the fleet program so the three managers' knobs (`MANAGE` in `Acris Reproduction.py`: the band and
   the width ceiling) apply - a lane launched alone runs with the managers off - from its folder, with the drive label and
   this machine's name:
   `cd Reproduction\Acris\workflow\reproduction`
   `python "Acris Reproduction.py" --drive NYCCRED2 --host Office2 --lanes documentation:40 --stagger 5`
   It enters once, one worker in and one more every 5 s until the band (floor 4 / goal 5 / ceiling 6 docs/s under 60
   requests/s; when BOTH workstations run ACRIS, the goal per station is 4-5), holds, hangs up when every line is cut, waits
   60 s, claims a fresh batch and re-enters once; a notice page parks it (`documentation.parked` in the lane folder) and a
   person clears it (`--unpark`). Stop with `python "Acris Reproduction.py" stop`.
6. **The board runs on ONE machine per source** - at home (`python "Acris Update.py"` in `Reproduction/Acris/update`), never on
   both at once. Station 2's lane feeds it through its heartbeat: `reproduction.acris_workstations` shows the station's own row
   (landed by this station, rate, workers, last seen) and `reproduction.acris_update` the totals. If the home board is down,
   start it on station 2 instead.

Synchronization stays on one machine; registration and documentation run on any. The code, the rules and the to-do list are
the same everywhere.

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
