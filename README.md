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
| database | Supabase project **NYC CRE Decoded** (East US); `supabase/Supabase.md` · `supabase/supabase.py` · `supabase/schema.sql` | three schemas: `reproduction` (the record - `acris`, `richmond` - and the two boards a person opens, `acris_update`, `richmond_update`), `machinery` (what the code needs and a person never reads: `claims`, `updates`), `reading` (the reading layer for products); the whole database as it stands is the one file `schema.sql` |
| code | this repo | `supabase/` at the root (the database's pair), then `Reproduction/`: the shared rulebook and one folder per source, each its rulebook, update and workflow (below) |
| documents | the One Touch, `D:\NYC CRE Decoded\Reproduction\` - the same tree as this repo and the database | `<Source>\By Document\<year>\<MM Mon>\<day>\<id>.pdf` - the day folders from the recorded date, else from a digital id's own date (yyyymmdd at its front), else the id split (`FT_4\4100`) with no day folder (`day_folders`, rulebook.py:53-69); a second workstation writes the identical tree under its own drive and records One Touch paths, then transfers |

Credentials live in `C:/dev/nyc-cre-decoded.env` (home), never committed or printed.

## The layout - the same three folders at every level

```
supabase/       Supabase.md · supabase.py · schema.sql   the one database, its one program, and its definition as it stands
Reproduction/                                            the phase
  rulebook/     Rulebook.md · rulebook.py                the rules every lane of every source shares, and the machinery as one module
  Acris/                                                 a source
    rulebook/   Acris.md · acris.py                      the source's authority, and its rules as one module
    update/     Acris Update.md · Acris Update.py        the board: one program; what a person opens is reproduction.acris_update
    workflow/   reproduction/ enumeration/ identification/ registration/ documentation/
                                                         a pair per folder: `Acris <Lane>.md` (its authority) · `Acris <Lane>.py` (its one program)
  Richmond/     the same
```

Two levels, one shape (login 2026-09-05, tightened 2026-09-07): a **lane** is one program in its own folder, run alone from
there - `python "Acris Documentation.py" --drive OneTouch` is the whole command; a **source** is its lanes together,
configured in its fleet program (`Acris Reproduction.py`; `Acris Reproduction.md` beside it is the cycle's authority and
record); the phase is the sources side by side - there is no phase-level
program. Every folder holds one pair and nothing else - the md is that thing's own authority, the py its one program. A
test or a simulation lives outside the repo, and what it proves goes into the existing file (login 2026-09-07: "it should
be actually altering the existing code, not just making new files"). Nothing is loose: a source folder is its three
folders; the phase folder is the shared rulebook and the sources; the root is the phases and the database's own folder,
`supabase/`. The rulebook's authority is `Reproduction/rulebook/Rulebook.md`; the database's is `supabase/Supabase.md`.

## The phase: reproduction

Two sources, `acris` and `richmond`. Per source one workflow table, one row per document: a `source` column in
front (a constant per table, for the cross-source tables of construction) and three cells: `identifier` · `registry` ·
`document`. No URL or key columns: every URL is minted from the id. Each source has four lanes, each its
own code in its own folder, toggled independently and configurable in width; three of them fill the cells.

| lane | job | fills |
|---|---|---|
| enumeration | the audit, not a cycle lane: counts the source (acris: Socrata + CRFN; richmond: census + date/range), compares with the table, difference must be 0 | nothing (no table) |
| identification | keeps the table live: the CRFN edge monitor and walkers for acris, the date walk for richmond | `identifier` |
| registration | the recorded details, by a URL minted from the id stem; no navigation step | `registry` |
| documentation | the document, by minted access; saved to the drive, its full One Touch path recorded | `document` |

**The cell rule.** Each lane fills its own cell and nothing else. A cell holds the fill or one of two words: `pending`
(recorded but not yet served, inside the source's window; it stays in the backfill until it becomes the fill or
`absent`) or `absent` (checked: there is none). Nothing else can go in a cell; the table itself refuses it. Anything
but empty counts as landed.

**Two workstations, no overlap.** The table is the only to-do list. A lane calls `claim()` for a slice of empty cells
with its name and an expiry on them, atomic and skip-locked so two machines never receive the same document; the
pendings due for a re-check come first. It fills them with `land()` once a minute, or as soon as 200 results are
waiting, which drops the claims; expired claims go back on the list. Each running lane writes `heartbeat()` once a
minute. Identification runs at home; registration and documentation on any machine.

**Joining a second workstation (the steps, refreshed 2026-09-07 after gate 4's first night; on login's word).** Nothing
on the second machine needs Claude Code: the batch, rate and session managers are plain Python in `Reproduction/rulebook/`
(`rulebook.py`) and run wherever the lane runs. There is no allocation to hand out: the table is the only
to-do list, `claim()` is atomic and skip-locked with the host's name on every claim, so two machines never receive the same
document, and a claim that expires (20 minutes) goes back on the list. The steps:

1. Python 3.12. `git clone https://github.com/loginwilson/NYC-CRE-Decoded` (or unzip main) into `C:\dev\nyc-cre-decoded`, then
   `pip install requests>=2.31 psycopg2-binary>=2.9 img2pdf>=0.5 Pillow>=10`.
2. The env file `C:\dev\nyc-cre-decoded.env` holding `SUPABASE_DB_URL` (Connect > Session pooler > URI) and
   `SUPABASE_DB_PASSWORD` - typed in by hand, copied from the home machine, never committed, never printed.
   `python supabase/supabase.py check` must print the ledger with every migration applied.
3. The documents drive, named by its **volume label** (case-insensitive): label the second drive `NYCCRED2`. The lane finds
   it by label, writes the file under the drive labelled NYCCRED2 at the same tree, and the cell carries the One Touch path
   `D:\NYC CRE Decoded\Reproduction\Acris\By Document\<year>\<MM Mon>\<day>\<id>.pdf` - the table accepts no other root -
   so a later move into the One Touch changes nothing in the database.
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
   both at once. Station 2's lane feeds it through its heartbeat and its landings: `reproduction.acris_update` shows the totals block,
   then workstation 1's four rows and workstation 2's four (a workstation's number is the order of its first sight). If the home board is down,
   start it on station 2 instead.

Identification stays on one machine; registration and documentation run on any. The code, the rules and the to-do list are
the same everywhere.

**The update.** One program per source, always running, reading only. What a person opens is `reproduction.acris_update` /
`richmond_update`: three blocks of four rows - the totals (reproduction: rows with all three cells filled; identification,
registration, documentation: that cell filled), then workstation 1's four, then workstation 2's four, a blank line before
each workstation block - with source, lane, status, as of (Eastern), the 60-second and 5-minute rate, increase and eta,
landed, needed and percentage. The status follows the lane's own
heartbeat: `active` (landed rose in the last window) · `pending` (not complete, not stalled, nothing landed in the window:
paused, parked, or alive and idle) ·
`stalled` (the lane's last word is a refusal or a wall; a refusal parks at once) · `complete` (100 %).

**The three managers (login 2026-09-04).** On the acris document lane the batch manager is the cycle itself (the exit
pool settled in one block, one entry, a fresh batch); the rate manager enters with one worker and adds one every 5 s
until the docs/s meets the band, then adjusts every window under the request ceiling; the session manager ends the
session at 1,000,000 requests and hands back to the batch manager. Knobs in the fleet program, never code.

## Rules that do not bend

- One entry per client: one pooled session, one connection per worker at birth, births 5 seconds apart, keep-alive after, no further handshakes. Never a handshake burst: forty births in twenty seconds were cut at the door where a 200-second ramp was served (2026-09-04).
- A block is HTTP 200 plus the Bandwidth Notice page, nothing else (on the wire it may come as a 307 to the policy page; the lane follows it and reads that page as the same notice). A redial into a notice is refused; the notice lifts on its own clock. A hang-up (the far side closing the whole width inside a minute) is ACRIS's ordinary session end, not a block: the lane hangs up at once, drops the cut batch, waits 60 seconds with no line open, and re-enters once on a fresh batch with births 5 seconds apart; a refused re-entry doubles the next wait, a served one halves it back; wifi down waits; four tries per incident, then park with the reason. A partial close is redialed worker by worker. A notice page is never re-entered. A fetch error never stops a lane.
- Never kill a lane on a fail count; its own detectors decide. Never edit running code.
- Never repair a number to make a check pass. Report the failure.
- Env files, databases, documents and bulk inputs never enter git. The One Touch is storage only; code lives here.
