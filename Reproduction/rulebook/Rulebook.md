# Rulebook

The phase's shared rules and machinery: a rule is written once here and every lane of every source on every workstation gets it.
A source's own rules - its URLs minted from the id, its one user-agent, its refusal detector, where its documents file
- live in `<Source>/rulebook/` (`acris.py` · `Acris.md`, `richmond.py` · `Richmond.md`); nothing about one source is
in here. This file is the authority; the module's docstring points here. It says what this folder holds and what it
leans on, how a program reaches it, the table as dictated, the flags, and what the lane, the fleet and the board do,
with the code's numbers and the line each number is on.

What this folder holds and what it leans on:

| what | job |
|---|---|
| `rulebook.py` | THE MACHINERY, one file, six parts in dependency order - storage (where a document lives: the drive by its label, the One Touch tree, the day folders), the rate manager (the Governor; the batch and session managers are the lane's own cycle, in the lane part), cloud (claim, land, heartbeat, the outbox: one round trip each), lane (THE ENTRY every cycle lane shares: one pooled session, staggered births, hang-up, rebatch, re-entry, the park), fleet (the source's lanes together as one program), board (the update board: the counters read once a minute, rates / eta / status written back). A lane does `import rulebook` |
| the README's pip line | the one install a workstation needs: `pip install requests>=2.31 psycopg2-binary>=2.9 img2pdf>=0.5 Pillow>=10` |
| `supabase/schema.sql` at the root | THE TABLE's definition beside the database program: the whole database as it stands, one file, written from the project itself by `python supabase/supabase.py baseline`; a change is a numbered `supabase/<version>_<name>.sql` applied once with `push`, folded in with `baseline`, removed in the same commit |

## How a program reaches it

Every lane, fleet and board program carries one path line and imports by name. A lane or fleet program sits two
folders under the phase (`workflow/`), a board one (`update/`):

    PHASE = HERE.parents[2]                           # <lane> -> workflow -> <Source> -> Reproduction   (a lane, the fleet)
    PHASE = HERE.parents[1]                           # update -> <Source> -> Reproduction               (the board)
    sys.path.insert(0, str(PHASE / "rulebook"))       # the phase's rulebook: rulebook.py, the machinery as one module
    sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
    import rulebook, acris

A second workstation clones the repo and runs the same file; there is no install step beyond the README's pip line and
the env file (`C:/dev/nyc-cre-decoded.env` at home, `~/nyc-cre-decoded.env` on a Mac, or `NYC_CRE_DECODED_ENV`),
which is never committed or printed.

## The table — as dictated (2026-09-03)

login's organization concept for NYC CRE Decoded, in the words it was given, followed by the mapping onto Supabase, git
and the drive. The one file `supabase/schema.sql` at the root implements it one dictated decision at a time; nothing is
created that was not dictated. The database as a whole - one project, one schema per phase, the program that applies
the file and its changes - is `../../supabase/Supabase.md`.

### The concept

**Supabase** is the database the lane codes feed. A phase (`reproduction`) holds source folders (`acris`, `richmond`). Each source has a *workflow* database that its lanes fill and an *update* database that reads the workflow's progress.

**The four lanes per source.** Enumeration, identification, registration, documentation. Each is its own code, toggled on and off independently, and configurable in width: 1x40, 1x20, 1x80; identification 1x20 beside documentation 1x40; or one entry of 100 split 20 identification, 40 registration, 40 documentation.

- **Enumeration is not part of the reproduction cycle.** It is the first step to get reproduction up, and afterwards an audit: it counts the source (acris: Socrata + CRFN; richmond: census + date/range), compares with the database total, and the difference must be 0. It never writes the cloud database and has no table; it reads the table's counts and ids to compare (`Cloud.count` / `ids` / `prefixes` / `held` / `max_id`, rulebook.py:539-585).
- **Identification** keeps the database live: for acris it sits at the CRFN edge and any CRFN movement triggers an edge walk that populates new ids; for richmond it walks from the last recorded id by date range. One monitor on the lane's main thread (the feed and the landing, not a connection), `--width` walkers.
- **Registration** acquires the registry information (the recorded details) for each id, using the source rules and a URL minted by the code from the id stem. No navigation step, no URL column.
- **Documentation** does the same for the document itself: minted access, save to the drive, record the path.

**The workflow row** is as simple as `doc id | registry | document`: identification fills the id, registration the registry, documentation the document. (2026-09-05: a `source` column stands in front of the three cells - `source | identifier | registry | document`; the id cell was `doc_id` until 0015, 2026-09-07 - a constant the table enforces, so a cross-source table or view carries the source in every row without a join; login: "knowing acris, richmond, dob now, dof, bis web, etc. is helpful as we expand and link datasets". The two sources keep their own tables.)

**The cell rule.** A lane's outcome lives in the cell that lane fills, and there are exactly two words a cell may hold instead of its fill: `pending` (still being checked; it stays in the backfill until it becomes the fill or `absent`) and `absent` (checked: there is none). Anything but empty counts as landed. The rules for when a cell becomes pending or absent are part of the lane code.

**The path.** Recorded as something that pastes into the file bar and opens the document: the full One Touch path. (2026-09-05, superseding the layout dictated here on 09-03: the One Touch mirrors GitHub and Supabase - `D:\NYC CRE Decoded\Reproduction\<Source>\By Document\<year>\<MM Mon>\<day>\<id>.pdf`, the day folder from the RECORDED date; login: "NYC CRE Decoded -> reproduction -> source -> by document -> by year -> by month -> by day ... the PDFs stay in the OneTouch because Supabase is just for storing the data table". No borough folder.) The day folders, in three steps (`day_folders`, rulebook.py:53-69): the recorded date; else a digital id's own date, yyyymmdd at its front; else the id split (`FT_4\4100`) with no day folder. The cell always carries the `D:\` address (`canonical`, 72-76; the table accepts no other root) and the file is written under the drive the lane found by its label (`find_drive`, `local`, 119-131, 79-82). Two workstations: the second names its drive by label; the lane writes the same tree under it and records the One Touch path, which opens the file once the documents are moved in; its documents are transferred into the One Touch before it continues, and nothing in the database changes on transfer. A click-to-open link is not possible for a file on a drive; it would require the PDFs served from the cloud (the corpus is on the order of 20 TB at full size, so that is a real cost, not a schema change).

**The update database** is the board, built cleaner: 60-second and 5-minute rate, increase and eta (the window percentages stay in `machinery.updates`, off the board since 0014), plus landed, needed, percentage of total, the status and the as-of stamp. Three blocks of four rows (17, 2026-09-07): the totals - reproduction as rows with all three cells filled against rows, each lane as the cells of that lane landed against rows - then workstation 1's four and workstation 2's four, a blank line before each workstation block, source before lane (10 rows, 5 documented = 50 % on documentation). The update code is one program per source that always runs and only reads.

**Two workstations, no overlap (dictated 2026-09-03 16:xx).** "What do we do to assure there's no overlap in what they're pulling?" The table is the only to-do list. A lane never picks its own work: it calls `claim(source, lane, host, n, ttl)`, which hands out a slice of empty cells with the workstation's name and an expiry written on it, atomically (`FOR UPDATE SKIP LOCKED` plus the claims key), skipping anything another workstation holds; two machines asking in the same second get two different slices. Pendings whose cooldown has run out are taken first, then empties, both in id order straight off the partial indexes (no sort) - migrations 0002 and 0004; a landed pending keeps its claim as a cooldown for `pending_age` (`land()`'s fifth argument), so the claims table is the only clock and the workflow tables carry no timestamp. The lane fills its cells with `land()` in batches once a minute, or as soon as 200 results are waiting, which also drops its claims; a machine that dies leaves claims that expire and go back on the list. Each running lane writes `heartbeat()` once a minute into its own workstation row of `machinery.updates`; the update program folds those into the lane row (hosts, width, freshest heartbeat, last word). Identification runs on one machine only (two monitors at the CRFN edge would find the same ids); registration and documentation can run anywhere.

**The status follows the lane.** Each lane writes a heartbeat once a minute into its own row of `machinery.updates` (workstation, workers, last seen, its last word) and the board folds it into the lane's update row, so the board can say: `active` = landed rose in the last window · `pending` = not complete, not stalled, nothing landed in the window (the lane is paused or parked by a person, or alive and idle) · `stalled` = the lane's last word is a refusal or a wall (rejected by the source) · `complete` = 100 %. A fetch error never stops a lane; only its own detectors do - the notice page, the wall, `--tries` refused re-entries in a row, the drive gone ("The lane" below) - and a hang-up is redialed.

### The mapping

| concept | Supabase | git | drive |
|---|---|---|---|
| phase | schema `reproduction` | `Reproduction/` (its tables defined in `supabase/`, explained here) | `D:\NYC CRE Decoded\Reproduction\` |
| source | the table `acris` / `richmond` and its `source` column; `acris_` / `richmond_` on the boards and the reading views | `Reproduction/Acris/`, `Reproduction/Richmond/` (each with its rulebook: `Acris.md` / `Richmond.md`, the source's authority) | `Acris\` / `Richmond\` under the phase folder |
| workflow database | `reproduction.acris` (source, identifier, registry, document) | `Reproduction/Acris/workflow/{reproduction,enumeration,identification,registration,documentation}/` (reproduction/ is the fleet program and `Acris Reproduction.md`, the cycle's authority and record) | documents land here: `By Document\<year>\<MM Mon>\<day>\<id>.pdf` |
| update database | `reproduction.acris_update` (three blocks of four rows: the totals, workstation 1, workstation 2) over `machinery.updates` | `Reproduction/Acris/update/` | |
| enumeration | no table | `…/workflow/enumeration/` | |

Postgres has one level of folder above tables, so the phase is the schema and the source sits in the table name; in the Table Editor, choose the schema `reproduction` and the four things a person reads: `acris`, `acris_update`, `richmond`, `richmond_update` (16, 2026-09-07; the machinery and the reading layer live in their own schemas, `machinery` and `reading`).

### The decisions in the schema

Each was a numbered file, applied once; since 0016 (2026-09-07) they are folded into the one file `supabase/schema.sql` and the ledger keeps the versions - twenty applied. One line per version, from `supabase/Supabase.md`'s log:

| version | decision |
|---|---|
| 0001 (2026-09-03 17:01) | the phase schema `reproduction`; `acris` / `richmond` (doc_id `collate "C"` so index order is id order and range seeks walk the key) with the cell rule as check constraints (JSON or path, `pending`, `absent`); four partial to-do indexes per source (`*_registration_empty/_pending`, `*_documentation_empty/_pending`); `*_claims`; `*_heartbeats`; the functions `claim()`, `land()`, `heartbeat()`, `reconcile()`; `*_update` and `*_update_lanes`; the lane-status enum; `updated_at` touch trigger |
| 0002 (2026-09-05 15:55) | pendings first: `claim()`'s `pending_age` (its default 1 hour, was 1 day) offers the pendings due for a re-check before the empties, and documentation claims only rows whose registry is a JSON object (login 2026-09-03 23:5x, "pending goes back to the backfill") |
| 0003 (2026-09-05 17:0x) | the `source` column first in `acris` and `richmond` (a constant per table, `check (source = 'acris')`, default filled so every insert that names only the id still works); the empty tables rebuilt in the dictated order with every rule, index, trigger and comment kept (login 2026-09-05 16:5x: "source, id, registry, document ... separating acris and richmond given they each have their own table") |
| 0004 (2026-09-05 22:04) | the re-check clock leaves the table: `updated_at` and its touch trigger dropped, so a row is `source \| doc_id \| registry \| document` and nothing about when; a pending's wait between two checks is its CLAIM - `land()` keeps a landed pending's claim as a cooldown until now() + `pending_age` (its fifth argument, default 1 hour) and `claim()` offers the pendings whose claim is gone, then empties, both in id order off the partial indexes; the claims table is the schema's only clock (login 2026-09-05 18:4x: "Does it have to be there? Makes the table less clean") |
| 0005 (2026-09-06 15:36) | the lookup: an expression index on each field a person filters by, one GIN over the whole registry, an index on the document cell, the `*_fields` views and the functions `us_date` / `us_money` / `whole_number` ("Filtering the table" below) |
| 0006 (2026-09-06 17:07) | the profile: `*_profile` and `*_keys`, materialized, refreshed on demand ("The profile" below) |
| 0007 (2026-09-06 17:08) | the two tabs and the heartbeats of both sources become one `updates` table (source, lane, workstation); the claims out of a person's sight in the schema `machinery` ("What a person sees" below) |
| 0008 (2026-09-06 19:29) | the lookup, more: the block keys with their own GIN and the helpers `block_key` / `bbl` / `parcel` / `block_keys`; every party name as one text (`party_names`) with a trigram GIN; a typed expiration index; the `*_parcels` views with borough, block and lot spelled out ("Filtering the table" below) |
| 0009 (2026-09-06 20:35) | the provisional registration: `claim()` for registration offers, before the empties, a registry that is an object without a readable recorded date on an id younger than 400 days; `land()` keeps it as a cooldown for `pending_age` until a recorded date lands; the counters move only for a new registration (login: "if something is filed and has a CRFN and it doesn't have a recording yet, we catch it") |
| 0010 (2026-09-06 22:38) | the two update views, `acris_update` / `richmond_update`: the one updates table cut per source in reading order |
| 0011 (2026-09-06 22:45) | the update views made simple: four rows per source, no workstation column; the per-station rows apart in `*_workstations` |
| 0012 (2026-09-06 22:5x) | the update views with only the columns a person reads: landed, needed, pct, the two blocks, status, as_of |
| 0013 (2026-09-06 23:1x) | `as_of` / `last_seen` rendered in Eastern (`as_of_et`, `last_seen_et`) |
| 0014 (2026-09-07 01:10) | pct_60s / pct_5m dropped from the two source update views (kept in the table) |
| 0015 (2026-09-07 04:56) | `doc_id` -> `identifier` in `acris`, `richmond` and `machinery.claims`; the keys, the eleven indexes and the four views follow; `claim()` / `land()` re-stated with `identifier` |
| 0016 (2026-09-07 12:49) | THE ORGANIZATION, three schemas: `reproduction` holds the record and the two boards a person opens (`acris`, `acris_update`, `richmond`, `richmond_update`) and nothing else; `machinery` holds `claims` and `updates`; `reading` holds the reading layer (`*_fields`, `*_parcels`, `*_keys`, `*_profile`); the `*_workstations` views gone |
| 0017 (2026-09-07 13:18) | the lane row is `identification`; `machinery.updates.first_seen` numbers the workstations by their first sight; a workstation's `reproduction` row holds its completions (`land()` credits them); the boards in three blocks of four rows, source before lane |
| 0018 (2026-09-07 13:4x) | the board's order as the Table Editor shows it: every row carries the source (the Editor sorts a view by its first column), the totals named `<lane> total`, an unclaimed workstation block reads `pending` |
| 0019 (2026-09-07 14:0x) | the spacer rows blank: every column of the two boards is text, a blank is one space, the as-of to the second |
| 0020 (2026-09-07 15:0x) | the audit: `reconcile()` from the partial indexes - three index-only counts and a subtraction; no PUBLIC execute on the four process functions (`claim`, `land`, `heartbeat`, `reconcile`); a comment on every schema, type, table, column, function, view and materialized view |

**The counting rule (speed).** The board never counts 21.6M rows once a minute. `land()` adds exactly what was new to the lane's `landed` (cells that were empty) and to the phase's `landed` (rows whose other cell was already filled); a pending that becomes a path was already counted and adds nothing. `reconcile(source)` recounts from the primary key and the partial indexes - three index-only counts and a subtraction (rows with no registry, rows with no document, rows with neither; 0020, 2026-09-07 - before it the fourth count was a scan of the whole table), seconds on the full table, run on a connection without the two-minute statement timeout - and overwrites the counters; the update program runs it on demand only (`reconcile`): after the data move, after a hand edit, never on the tick. The 60-second and 5-minute rates are the board's subtraction of `landed` between its own ticks.

Apply a change with the project's program: `python supabase/supabase.py push --dry` shows what would be applied, `push` applies it and records it in the project's ledger; then `baseline` folds it into `schema.sql` and the change file leaves in the same commit. A version already applied is never edited - a new decision is a new change file.

## The proofs

A proof or a simulation lives outside the repo (login 2026-09-07: "all your tests need to go, every single one ... even if you're doing a test, it should wait and then go in once approved that it works"); what it proves goes into the existing file it proves, dated, and the code it approves alters the existing program - never a new file for a small adjustment. The live cloud table is never a proof's fixture: a simulation that must touch the cloud uses throwaway rows and says so in its first line.

## The shared flags

Every cycle lane takes these (they are `add_common_args` in `rulebook.py`; this table is written from its own help text, 2026-09-07). A lane's own flags are in its md; the fleet's own flags are `build_parser`, the next table; the board's four are below it.

| flag | default | what it does |
|---|---|---|
| `--width` | 40 | workers = connections (default 40; a lane may set its own: acris identification 20; richmond documentation 8, identification 4, registration 4) |
| `--host` |  | this station's name in the cloud (default: the machine name). STATIONS ARE PROVIDERS (2026-09-08): a station is the provider its doors come from - `ExpressVPN`, `DigitalOcean`, the next provider the next name - and every process on that provider reports under the one name: the cloud ADDS landings per (source, lane, workstation) and `claim` skips every claimed row whoever holds it, so processes under one name never overlap and their landings sum (`heartbeat` is last-writer: workers and last_word are one process's). The board numbers stations by their first sighting, so a retired name must leave `machinery.updates` before a new one can take a block |
| `--slot` | (none) | one lane process per CORE (2026-09-08): this process's number. Its lock, control and parked files become `<lane>.N.lock` / `.control` / `.parked` (`lane_tag`, 707-714, 742, 1109, 1141, 1467, 1492, 1478), so slots never collide on disk - and since 12:0x the same for the crew's outbox and fails files, `<lane>.N.outbox.jsonl` / `.fails.jsonl` (927-929): nine slots on ONE `documentation.outbox.jsonl` collided on its rewrite (slot 1 crashed on `documentation.outbox.tmp`, PermissionError, 12:06) and a slot's drain could drop a row another slot had just appended, leaving that document to its claim's expiry; pair it with `--host <station>-N` (its own cloud rows and claims) and its own `--door` set, disjoint across slots, the VPN's `direct` in exactly one slot. Why: one lane process pushes ~100 requests/s through its interpreter lock whatever its door count (10:06 - eight doors in one process = one door's throughput, the process at 98% of one core; the home line at 45 Mbit/s and the drive idle). The launcher outside the repo: `C:\dev\cre-office\slots_lane.ps1` |
| `--pooler` | session | which Supabase pooler this process's crews connect through (`POOLER_PORT`, `dsn`: 389, 395-408, 739, 1480). `session` = the URI's own port 5432: 15 clients in all for the whole project - each crew is one, the boards ~6, so one lane process per core hit "cloud unreachable" at the ninth (10:39). `transaction` = 6543, hundreds of clients; the lane's use is autocommit, one statement at a time, each a SQL function (claim / land / heartbeat), which is what transaction mode serves. The slot launcher passes `--pooler transaction`; the boards keep 5432 |
| `--stagger` | 5.0 | seconds between worker births (default 5.0; the richmond lanes set 0.4): a ramp of about 200 s at width 40 (2026-09-04: 0.5-s entries were cut, 5-s and 20-s entries served on the same door) |
| `--claim` | 0 | documents taken per claim (default 12 x width) |
| `--ttl` | 20 minutes | how long a claim is ours before it goes back on the list |
| `--pending-age` | 1 hour | re-check a pending once its last check is this old (its claim stays as a cooldown that long); pendings ride ahead of the backfill, and when the lane is up to date every claim is pendings (one request per pending per interval) |
| `--redial-wait` | 60 | seconds of silence after the session closes before the fresh-batch re-entry; a refused re-entry doubles the next wait (cap 4,800 s), a served one halves it back to this base |
| `--tries` | 4 | re-entries per incident before parking (the wait doubles each time: 1, 2, 4, 8 minutes at the base) |
| `--no-pool-check` | off | skip the exit-pool check at entry (tests only) |
| `--door` | none: the machine's own line | a door: a proxy this crew's lines go through, e.g. socks5h://127.0.0.1:1080 (an `ssh -N -D 1080` tunnel to a rented address); repeatable - one crew per door, each with its own exit check, session and rate manager; `direct` = the machine's own line (the VPN's exit). A notice on one door retires that door's crew; the lane parks when every door has been refused (2026-09-07: a door is a block, ACRIS keeps its standing per address range). A door can also join the running lane later through the control file, `door=URL` (2026-09-08) |
| `--entry-gap` | 20.0 | seconds between one crew's entry and the next (--also) |
| `--also` | none | host another lane's crew too, e.g. registration:40 |
| `--one-batch` | off | ONE BATCH (login 2026-09-06, the acris rule): every --also crew rides this crew's entry - one ramp across the crews (each crew's births start when the previous crew's ramp ends, --stagger apart, no --entry-gap), one exit-pool check, one hang-up for the whole batch and one re-entry from the top (this crew first), no rate manager; each crew keeps its own pooled session (08-28 run 3: mixed floors on one session served empty viewer pages) |
| `--limit` | 0 | stop after this many documents (a test run) |
| `--log` |  | also append the printed lines to this file |
| `--unpark` | off | start although the lane parked itself (a person has decided) |
| `--manage` | 0 | 1 = the rate and session managers run this lane (default 0: fixed --width, the cycle only) |
| `--ramp-to-rate` | 1 | managed: 1 = enter with ONE worker and add one every --stagger s until the band; 0 = ramp to --width |
| `--rate-floor` | 5.0 | managed: docs/s under this = a full step up |
| `--rate-ideal-lo` | 6.0 | managed: the band's lower edge (login: around 6) |
| `--rate-ideal-hi` | 7.0 | managed: the band's upper edge |
| `--dps-ceiling` | 8.0 | managed: the hard line - a full step down at once (login: no more than 8 ever) |
| `--rps-ceiling` | 60.0 | managed: REQUESTS/s ceiling, the record's meter (notices at 58-81 held for hours; the golden day ~57); 0 = off |
| `--width-min` | 20 | managed: the manager never retires below this |
| `--width-max` | 120 | managed: the manager never grows above this (the pool's ceiling is 128) |
| `--adjust-every` | 120 | managed: seconds per window |
| `--adjust-step` | 10 | managed: workers per full step |
| `--ramp-window` | 60.0 | managed: the ramp reads its docs/s and requests/s over this many seconds (read at the current width) |
| `--session-max-requests` | 0 | managed: end the session at this many requests and re-enter on a fresh batch (login: 1,0,0); 0 = off |

### The fleet's flags

`build_parser` in `rulebook.py` (2085-2113), from its own help text. The commands: `run` (the default), `status`, `stop [lane]`, `width LANE=N`.

| flag | default | what it does |
|---|---|---|
| `--lanes` | the site's cycle: acris `identification:5,registration:5,documentation:5`, richmond `identification:4,registration:4,documentation:8` | LANE:WIDTH,... in launch order |
| `--mega` | off; the acris site says it by itself | every crew in one process through the first lane's --also (on acris: this site's default, ONE BATCH) |
| `--separate` | off | one process per lane even on a ONE BATCH site (tests only) |
| `--drive` |  | documentation's drive label (the volume label: OneTouch at home, workstation 2's own) |
| `--fresh-days` | acris 30, richmond 7 | documentation: a document recorded within this many days with no image is pending, not absent |
| `--edge` | none (acris 0, richmond empty) | identification's first start - acris: the last CRFN whose document the table holds; richmond: the last day (YYYY-MM-DD) identification and registration walked; passed on a lane's FIRST launch only |
| `--entry-gap` | 20 | seconds between lane launches (and between crews inside a mega lane) |
| `--stagger` | the lane's own | seconds between worker births inside a lane (default: the lane's own) |
| `--pending-age` | 1 hour | handed to every lane |
| `--redial-wait` | the lane's own | seconds of silence before a re-entry (default: the lane's own, 60 s with the backoff) |
| `--tries` | the lane's own | re-entries per incident before a lane parks (default: the lane's own, 4) |
| `--limit` | 0 | each lane stops after this many documents (a test run) |
| `--unpark` | off | start parked lanes too (a person has decided) |
| `--no-pool-check` | off | the lanes skip the exit-pool check at entry (tests only) |
| `--door` | none | a door for every lane launched: a proxy its lines go through (socks5h://127.0.0.1:1080, an ssh tunnel to a rented address); repeatable - one crew per door; `direct` = the machine's own line; not with ONE BATCH |
| `--relaunch-wait` | 0 | seconds before relaunching a crashed lane (0 = the fleet's own 60 s) |
| `--relaunch-cap` | 3 | relaunches per lane per hour before the fleet parks it |
| `--stop-wait` | 180 | seconds for the lanes to leave after `stop` (a lane reads its control file on the minute, then joins its workers) before terminating them |
| `--within` | 10 minutes | status: heartbeats this recent |
| `--host` |  | this station's name in the cloud (default: the machine name). STATIONS ARE PROVIDERS (2026-09-08): a station is the provider its doors come from - `ExpressVPN`, `DigitalOcean`, the next provider the next name - and every process on that provider reports under the one name: the cloud ADDS landings per (source, lane, workstation) and `claim` skips every claimed row whoever holds it, so processes under one name never overlap and their landings sum (`heartbeat` is last-writer: workers and last_word are one process's). The board numbers stations by their first sighting, so a retired name must leave `machinery.updates` before a new one can take a block |

The board takes four of its own - `--every` (60), `--once`, `--fresh` (180), `--host` - and the commands `run` / `show` / `reconcile`: `<Source>/update/<Source> Update.md`.

## The lane

The cycle lane is `run(roles, args, here)` in the lane part of `rulebook.py` (658-1627): a lane file defines a ROLE - what one
worker does with one document - and hands it to `run()`, which owns the rest. The numbers are the code's; the line is in
parentheses.

| rule | what the lane does |
|---|---|
| one door | `<lane>.lock` holds the pid: a second start on this machine is refused while the first lives, a stale lock is taken (716-732, 1492-1493). A parked lane (`<lane>.parked`, the reason inside) refuses to start until `--unpark`, which removes the file (1483-1488). A crew has 1 to MAX_WIDTH 128 workers (847, 1489-1491). The cloud must answer before anything is entered (1526-1531); the outbox left from last time lands first (1532) |
| one entry | one pooled session per crew (`make_session`: a pool of MAX_WIDTH + 4 connections, no retries, 890-901), workers born `--stagger` apart on their own thread, one connection each at its birth, keep-alive after (1036-1067); a crew enters when no other crew ON THE SAME DOOR is ramping (a burst of handshakes on one address is the ban condition; crews with no door share the machine's own line and still take turns) and the last crew on any door started its ramp `--entry-gap` ago (`entered_at`, 939, 1024; the gate 1417-1425) - so DIFFERENT doors, being different addresses, enter `--entry-gap` apart and ramp CONCURRENTLY (2026-09-08: eight doors all ramping within a minute, where the old one-ramp-at-a-time rule took ~5 min per door). The wire must be up: no answer from a neutral host = wait a minute, no try spent (830-841, 1427-1430). `--door`, repeatable, makes one crew per role per door (1512-1516), each crew's session through its own proxy (890-901, 909-912), named `<lane>@doorN` in the log; ONE BATCH and doors together are refused at start |
| the exit-pool check | before every entry, on its own thread so the other crews keep feeding and landing (1431-1439): five draws of the public exit (api.ipify.org, one fresh connection each, 1 s apart, 850-869); five answers in one /24 = enter, else wait 30 s and draw again, the heartbeat saying "waiting for a settled exit pool" (872-887); a verdict older than 120 s is drawn again (1442). `--no-pool-check` skips it. No owner lookup, no spent list: the block is the whole check. Through a door the draws go through the crew's tunnel and answer the rented address, one block by construction (850-869) |
| the batch | the feed keeps the queue a batch ahead: `claim()` for `--claim` (default 12 x the width) with `--ttl`, the registries fetched with the ids (1225-1248); the fresh batch is claimed right before the ramp, never before a wait (1444). An empty list = ask again in 60 s; a failed claim = 30 s (1244, 1214) |
| landing | results go to `<lane>.outbox.jsonl` first and to `land()` second, in chunks of 500, so a cloud hiccup loses nothing (595-656, 1251-1265). The flush: as soon as 200 results wait (1557-1560) and on the minute tick (1582) |
| the minute tick | every 60 s (1574): the control file (1576), the role's check - documentation: the drive is still there, or park with exit 6 (1581) - the landing, the PROGRESS line (1583, 1268-1285), the session manager, the quiet counter, the heartbeat with the live worker count (1584-1604) |
| a worker's failures | a fetch error never stops the lane: the document is written to `<lane>.fails.jsonl` and left for a later pass (964-973); a transport error is re-asked once, then failed, and the cut worker pauses HANGUP_PAUSE_S 5 s before it dials again (999-1009); a `Retry` (a short document, an unknown page shape) is a fail, not a verdict (1010-1014); a worker above the width leaves after its document (1018-1019) |
| the hang-up | the session closed: every worker cut inside HANGUP_WINDOW_S 60 s and nothing landed for HANGUP_QUIET_S 10 s (844-845, 1021-1034; during a ramp the whole width is the workers born). Then at once: leave, land what the crew holds, drop the cut batch (its claims expire on their own), wait `--redial-wait` with no line open, re-enter once on a fresh batch (1338-1367) |
| served or refused | the last re-entry was SERVED when it landed SERVED_LANDINGS 300 or lived SERVED_S 300 s (846, 1322): the incident closes and the wait halves back toward the base (1350-1351); otherwise it was REFUSED and the next wait doubles, cap 4,800 s (1353); `--tries` refused in a row = park, exit 3 (1354-1355). The try is spent at the re-entry itself, never while the wire is down (1445-1448) |
| dead transport | 3 x width transport errors in a row and nothing landed for 60 s = the same hang-up (1568-1570); five minute ticks asking with nothing landing = "our wire", the same hang-up (1594-1599) |
| the wall | 40 consecutive 503/429 (the wall counts these two only) = park, exit 4, not retrying, not rotating (996-997, 1562-1564) |
| the refusal | the source's notice page (`Refused`, raised by the source module's detector) = park at once, exit 2 (991-992). With more than one `--door`, the notice on one door retires that door's crew alone - its lines close, what it fetched lands, its claims expire (1103-1112, 1543-1552) - and the lane parks when the last open door is refused |
| the park | `<lane>.parked` with the reason; the process stops; the heartbeat carries the reason on the way out (1114-1125, 1613-1626). Exit codes: 0 stopped (the control file, `--limit`, Ctrl+C, a signal) · 2 refused · 3 `--tries` re-entries refused · 4 wall · 5 crash · 6 drive gone |
| the control file | `<lane>.control`, read on the minute (1138-1172): `width=N` for the lane's own crew, `<lane>=N` for a hosted crew (N capped at 128), `stop` (acted on once, then the file is emptied; a stale `stop` is cleared at start, 1494-1500). Workers above the new width leave after their document, missing ones are born staggered (1083-1089). `door=URL` or `door=direct` (2026-09-08, HOT-ADD A DOOR) gives the running lane one more crew per role on that door, born the way a launched crew is born - cloud row, outbox landed, a batch claimed, then the ordinary entry with its own exit-pool check, ramp and rate manager - so the VPN walk swaps blocks and rented addresses join without a relaunch; a door already open is not opened twice, a retired door is never re-entered by it, the line is consumed once acted on (1180-1222) |
| the mega lane | `--also LANE:WIDTH` hosts another lane's crew in this process on its own session (790-827); one ramp at a time, `--entry-gap` apart. ONE BATCH (`--one-batch`, 1377-1403, 1308-1335): the hosted crews ride the host's entry - each crew's births start right after the previous crew's ramp, `--stagger` apart, no `--entry-gap`; what closes one crew closes the batch and the batch re-enters from the top, the host first; no rate manager on the batch (1452-1453) |
| the managers | `--manage 1` on a lane alone: the rate manager (the Governor, 156-359) enters with one worker and adds one every `--stagger` s until the band, then adjusts every `--adjust-every` s under `--rps-ceiling` (1052-1053, 1454-1470); the session manager ends the session on purpose at `--session-max-requests` and the cycle re-enters on a fresh batch, no try spent, the wait at the base (1584-1593, 1346-1348). Off by default |
| the heartbeat | `heartbeat()` at the start ("started 1x40", 1529), every minute with the live worker count (1602), with 0 workers and the reason while it waits for the pool, at a hang-up and on the way out (884, 1338, 1618) |

## The fleet

`<Source> Reproduction.py` is a `Site` - the name, the lanes in the cycle's order, their widths, where the lane programs
live, which lanes take `--edge`, the managers' knobs per lane, `one_batch`, `mega_default` (1639-1683) - handed to `main()`
in the fleet part of `rulebook.py` (1631-2126).

| rule | what the fleet does |
|---|---|
| one fleet per machine | `reproduction.lock` in the fleet's folder; its words in `reproduction.log` beside it (1693, 1729) |
| the launch | one process per lane, in the cycle's order, `--entry-gap` (20 s) apart (1782-1791); each lane's `<lane>/<lane>.log` is appended, never truncated, with a fleet banner at every launch (1745-1754). The lane's command line (1711-1743): `--width`, `--host`, `--entry-gap`, `--pending-age` always; `--stagger` / `--redial-wait` / `--tries` only when given, so the lane's own defaults are the cycle's; `--drive` and `--fresh-days` for a documentation crew; `--edge` on a lane's FIRST launch only - afterwards its edge file is the truth (1723-1724); `--limit`, `--unpark`, `--no-pool-check`; the site's manager knobs for a lane run alone (1740-1742) |
| the mega lane | `--mega`, or a site whose `mega_default` says so (acris): the first lane of `--lanes` hosts the rest as `--also` crews in one process (1692, 1782-1784); on a `one_batch` site the hosted crews get `--one-batch` and no manager knobs (1727-1742); `--separate` launches one process per lane even there (tests) |
| the watch | the children are polled every 3 s, a status line every 60 s, and the fleet is done when every lane has left (1794-1802) |
| what each exit means | 0 stopped cleanly and 1 refused to start: left alone · 2 REFUSED by the source: every lane told to stop, the fleet leaves with 2, a person decides · 3 parked itself (`--tries` re-entries refused) and 4 the wall: never relaunched, a person decides · 5 crash: relaunched · 6 drive gone: relaunched with `--unpark` once the drive is back (1634-1636, 1847-1882, 1884-1905) |
| the relaunch | WAIT_AFTER 60 s (1598; `--relaunch-wait` when not 0, 1880) while the lane's launches in the last hour are within `--relaunch-cap` 3 (1870-1872); past the cap the fleet writes `<lane>.parked` itself and leaves the lane alone (1872-1879); a lane parked meanwhile is not relaunched (1898-1901) |
| `stop` | `stop` into each running lane's control file, up to `--stop-wait` 180 s for the lanes to leave - a lane reads its control file on the minute, then joins its workers - then terminate (1916-1939, 2018-2049); the fleet's own end (a signal, Ctrl+C, a crash) does the same (1804-1814) |
| `status` | this machine's lanes by their locks - RUNNING pid, PARKED with the reason, the control file's word, the log's last line - the fleet's own lock, and every workstation's heartbeat in the cloud within `--within` (1983-2015) |
| `width LANE=N` | `width=N` into the lane's control file, read within a minute; 1 to 128 (2052-2067) |
| `door LANE=URL` | `door=URL` (or `LANE=direct`) into the lane's control file, read within a minute: one more door for the RUNNING lane, its crew born and entered on its own ramp, nothing relaunched (2070-2082; the lane side 1180-1222) |
| a hosted crew | on a mega run a hosted crew takes no lock of its own and reads only its host's control file, so `stop`, `width` and `status` resolve it to its host - the first lane of `--lanes` while that one's lock is alive (`host_of`, 1970-1980): `width registration=20` writes `registration=20` into the host's control file, `stop registration` stops the host's process (every crew leaves), `status` reads the host's lock |

## The board

`<Source> Update.py` hands its source, its lanes and its four flags to `Board` in the board part of `rulebook.py`
(2130-2477); the words are `<Source> Update.md`.

| rule | what the board does |
|---|---|
| the tick | every `--every` 60 s (`--once`: one tick, 2414, 2395): read `machinery.updates` - the totals rows (landed, needed) and every workstation row (workers, last seen, last word, its own landed) - compute, write, remember (2221-2231, 2385-2398). It never counts the workflow table |
| the readings ring | its own memory of the counters, `update.state.json` beside it, KEEP 8 minutes of readings; a restart reads it back (2140, 2136, 2190-2205) |
| one subtraction | rate and increase for 60 s and 5 min come from the reading nearest to that far back and at least three-quarters of the way there (`_then`, 2207-2218): increase = landed now - landed then, rate = increase over the real seconds between, eta = the remaining at that rate (2273-2286); a window with no reading that old stays blank |
| the four statuses | `complete` when needed > 0 and landed >= needed · `stalled` when the lane's last word from its freshest workstation starts with REFUSED or wall (for the phase row: any lane's) · `active` when landed rose in either window · `pending` otherwise (2239-2258, 2287-2294); a workstation row the same from its own word and its own count (2303-2341). eta follows the status: `complete`, `paused` (pending, stalled), or the number (2296-2299) |
| the heartbeats | a workstation is alive when its heartbeat is fresher than `--fresh` 180 s; the lane row's workers is the sum across its workstations alive, its last seen the freshest (2171, 2244-2258). Freshness feeds hosts and width, never the status |
| never clamp | landed outside 0..needed publishes no metrics: the row says OUT OF BOUNDS and names `reconcile` (2266-2269) |
| the write | pct, the two windows, status and as_of = now() onto the row of `machinery.updates`; the totals rows also take the fold - workers, last_seen, last_word (2345-2359) |
| a tick never kills the board | a failed tick logs, keeps the readings, closes the connection and the next tick continues (2425-2430); `update.lock` refuses a second board on the machine (2402). Exit codes: 0 stopped · 5 crash |
| `show` / `reconcile` | `show` reads and prints every row, nothing written (2451-2462); `reconcile` runs `reproduction.reconcile(source)` and prints each counter with its drift, on demand only (2464-2477) |

## Filtering the table (0005 and 0008, 2026-09-06)

login: "say i wanted to look up deeds, or page numbers, or boroughs" - "assure filtering works on any row and column if
its possible, without causing massive load issues." The registry stays jsonb: text would take the same space and could
only be searched by LIKE, a scan of 21.6 million rows every time; jsonb can be filtered by field and indexed by field.
Migration 0005 puts beside the table, without changing a row: an expression index on each field a person filters by
(acris: type, borough, recorded, doc_date, pages, amount, crfn; richmond: doc_type, recorded, book + page, instrument,
amount), so equality, ranges and ORDER BY on those fields read the index; one GIN index per table over the whole registry
(`jsonb_path_ops`), so a containment test on any key and value at any depth reads the index -
`registry @> '{"parcels":[{"bbl":"4001230001"}]}'`, `registry @> '{"parties":[{"name":"CITY OF NEW YORK"}]}'`; an
index on the document cell for a prefix (one day folder: `document like 'D:\...\23\%' escape ''`) or one path; and
two views, `acris_fields` and `richmond_fields`, that show the registry's fields as typed columns (the dates as dates, the
amount as a number, pages as an integer) - a filter on a view column is the very expression its index was built on, so
the Table Editor's filters and sorts on the views use the indexes. Three immutable functions (`us_date`, `us_money`,
`whole_number`) read the fields as the lanes wrote them and give null for anything else. Load: the indexes are ~8-12 GB
(the GIN the largest), built while no lane lands, statement by statement - each index its own transaction with the
instance's default build memory and no parallel worker, after the one-transaction build of 11:36 brought the 1 GB
instance down at 11:48 (a crash now costs one index; a re-run skips what exists; a plain CREATE INDEX holds the
table against writes for its build); afterwards a landing maintains them at a cost no lane will notice at its rate, and an indexed filter answers
in milliseconds. A filter on something not indexed still scans, and the dashboard's two-minute statement timeout cuts
it off - so a stray query costs at most two minutes, never a runaway. The disk is a dashboard setting, raised by hand
before a build needs the room: 40 GB on the record (Supabase.md's state table, 2026-09-05), the database 32 GB after
the builds (2026-09-06 19:29).

Migration 0008 (2026-09-06 19:29) adds the lookups the key census named: the block keys with their own GIN
(`acris_blocks`, `richmond_blocks` over `block_keys(registry)`) and the helpers `block_key(borough, block)`,
`bbl(borough, block, lot)` and `parcel(borough, block, lot)` that build a key from words ("Manhattan block 573 lot 24"
without assembling ten digits); every party name as one text (`party_names(registry)`) with a trigram GIN
(`acris_party_names`, `richmond_party_names`); a typed expiration index (`acris_expiration`); and the views
`reading.acris_parcels` / `richmond_parcels`, one row per parcel with borough, block and lot spelled out (schema.sql: the
indexes, the functions, the views). Two limits, measured: a party by PART of a name reads the trigram index but a common
name takes 30-45 s cold on the Small instance (the exact full name through the registry GIN stays at about 300 ms); the
parcels views are for reading a document's parcels and for joins by identifier - a filter by bbl on them is a full scan,
so finding a parcel goes through containment or the block keys.

### The proven filters (2026-09-06 15:37, every plan an index scan)

Write filters against the views `reading.acris_fields` and `reading.richmond_fields` (typed columns: type,
borough, recorded, doc_date, pages, amount, crfn / doc_type, recorded, book, page, instrument, amount) - a filter on a
view column IS the indexed expression - and against the registry itself with containment (`@>`) for anything else: a
parcel, a party, a unit, any key at any depth; a block or a lot from words through `block_keys` / `parcel` (8). The
document cell answers a prefix (`like 'D:\...\2003\01 Jan\23\%' escape ''`, the day folder). The parcels views
(`reading.acris_parcels`, `richmond_parcels`) read a document's parcels spelled out; they are not where a parcel is
found. Measured on the pooled connection, a Small instance, the table larger than memory:

| filter | query | ms |
|---|---|---|
| deeds in Queens, newest first | `select identifier, recorded, pages, document from reading.acris_fields where type = 'DEED' and borough = 'QUEENS' order by identifier desc limit 20` | 207 |
| a year of deeds by recorded date | `select count(*) from reading.acris_fields where type = 'DEED' and recorded between '1995-01-01' and '1995-12-31'` (54,581 rows) | 13,282 beside a running profile build; two indexes ANDed |
| long documents | `select identifier, type, pages from reading.acris_fields where pages >= 50 order by pages desc limit 20` | 199 |
| amount above ten million | `select identifier, type, amount from reading.acris_fields where amount >= 10000000 order by amount desc limit 20` | 200 |
| one crfn | `select identifier from reading.acris_fields where crfn = '2003000003997'` | 181 |
| a parcel by bbl | `select identifier, registry->>'type' from reproduction.acris where registry @> '{"parcels":[{"bbl":"1015131008"}]}' limit 20` | 191 |
| a party by name | `select identifier, registry->>'type' from reproduction.acris where registry @> '{"parties":[{"name":"CITY OF NEW YORK"}]}' limit 20` | 311 |
| one day folder | `select identifier, document from reproduction.acris where document like 'D:\NYC CRE Decoded\Reproduction\Acris\By Document\2003\01 Jan\23\%' escape '' limit 20` | 180 |
| richmond book and page | `select identifier, doc_type, recorded, document from reading.richmond_fields where book = '8770' and page = '221'` | 180 |
| one instrument | `select identifier, doc_type from reading.richmond_fields where instrument = '48402'` | 182 |
| richmond deeds in 2020 | `select count(*) from reading.richmond_fields where doc_type = 'Deed' and recorded between '2020-01-01' and '2020-12-31'` (7,118 rows) | 553 |
| a richmond parcel | `select identifier from reproduction.richmond where registry @> '{"parcels":[{"bbl":"5001570097"}]}' limit 20` | 184 |

The dynamic proof, the same run: one throwaway row landed with a registry and a document path was found by five of these
shapes within 2.0 s of landing, each by an index scan, then deleted. The indexes are maintained on every insert and update
(the GIN batches new entries in a pending list that queries also search); the lanes' landings are filterable the moment
they land. Only 0006's profile is a snapshot, refreshed on command.

## The profile (6, 2026-09-06)

login: "the things we'd want to filter on ... are the things found in the registry realistically ... when training a
rounded framework, we need to look at all types of registry scenarios." Two summary tables per source, materialized,
built by scanning the rows once and refreshed on demand: `acris_profile` / `richmond_profile` count documents by type,
borough and year (facet `type, borough, year`), and by each alone, by how many parcels and parties a document carries,
and by its page count, with `with_document` and the fields 0005's functions could not read (`recorded_unparsed`,
`amount_unparsed`, `pages_unparsed`) counted alongside; the `all` row is the whole table. `acris_keys` / `richmond_keys`
count which keys appear at the registry's top level, inside a parcel and inside a party, so an unusual field shows with
its frequency. A model reads the profile first (a few thousand rows) to see the whole variety, then pulls examples of any
shape through 0005's indexes: `select * from reading.acris_fields where type = 'DEED' and borough = 'QUEENS' and
recorded between '1995-01-01' and '1995-12-31' and jsonb_array_length(parcels) >= 3 limit 20`. Refresh after a lane has
landed a lot: `refresh materialized view concurrently reading.acris_profile` (the unique index on each allows
`concurrently`, so readers are never blocked); a refresh is one scan of the table.

## What a person sees (7, 2026-09-06; 16-19, 2026-09-07)

login: "You have a database, and you have an updating table that shows you how you're progressing on filling in that
database ... the update table shows how workstations are performing and how we're progressing on reproducing. That's
important, but in terms of actually building our own tables for it, it's probably unnecessary ... build it behind the
scenes so you don't see it." The schema `reproduction` holds the record, `acris` and `richmond`, and the two boards a
person opens, `acris_update` and `richmond_update`; the schema `machinery` holds `updates` and `claims` (0016; 0007
first put `updates` beside the record). `updates` is source first, then lane, then workstation: a row per source for
the phase (`lane = reproduction`, rows with every cell filled), a row per lane (its cells filled), and a row per
workstation running a lane, that machine's own landed count, rate, workers, `last_seen` (its heartbeat, every minute
while it runs) and `last_word`. The heartbeats tables are gone into those rows. What the code needs and a person never
reads - which identifiers each workstation holds for which lane, until when - is `machinery.claims`: two machines can
only avoid taking the same document through a list both can see, so the list stays in the cloud, and a landed pending's
wait lives there as before (4). The functions `claim`, `land`, `heartbeat`, `reconcile` keep their signatures:
`land()` moves the lane's row and the landing machine's own row; `heartbeat()` is the machine's row; `reconcile()`
recounts the totals rows and leaves each machine's count alone. A way to have no list at all - a fixed share of the ids
per machine, by a rule in the code, each machine remembering its own re-check times - is the follow-up if wanted; its
cost is that adding or losing a machine means restarting the others with the new count, where the list rebalances by
itself.

## Access: how the tunnel works and how each source answers it

login, 2026-09-07 06:1x: "We need to figure out the correspondence between how the vpn works and acris access. This is key. Richmond
also had some issues with the vpn." This file is that correspondence, from measurements, in one place. It changes only when a
measurement changes it.

### 1. The tunnel, as measured on the home workstation

| fact | measured |
|---|---|
| where the tunnel sits | in the app on the workstation, below the socket layer: the app keeps a /32 host route to its Lightway server (2.57.171.151 via the Wi-Fi gateway while on 'Brazil'), no virtual adapter is Up, the default route stays the Wi-Fi's, and the lane's sockets bind to the LAN address (192.168.1.168) - yet every byte leaves from the server's block. (First read as a router tunnel; the host route settled it: the app's Lightway driver carries the whole machine, invisibly to netstat.) The server the app connects to and the block the traffic exits from are one block, so the app's server list is the exit list |
| the app's settings, read from settings.json | `automaticTransport = True` (the app may change protocol on its own = a reconnect mid-run), `protocol = udp`, `lightwayTurboEnabled = True` with `lightwayTurboNumberOfTunnels = 1` (turbo on, but one tunnel = one block), split tunnel off. For the lane: Automatic OFF, Lightway UDP fixed, one tunnel |
| every exit the app knows | `C:\Program Files\ExpressVPN\data\data.json` -> `cachedModernRegionsList`: 215 locations, 1,036 server addresses. `python C:\dev\cre-office\exits_map.py` (a person's tool, outside the repo) groups them by block, looks every block's owner up (no ACRIS request) and writes exits_map.md: label -> country -> blocks -> owner -> refused / candidate |
| one connection, one address | a new TCP connection is NATed to a random address of the exit's /24: 20 draws in a row gave 11 distinct addresses of 2.57.171.0/24. The lane's 40-80 lines sit on many addresses of ONE block; the block is the unit we can see |
| the app's location name | a label. "Bolivia" exited from Phoenix (GSL Networks). "Bosnia" from Lelystad, Netherlands (Clouvider). "Brazil" from Sao Paulo (Latitude.sh). "Singapore" from GSL Networks, Singapore. The owner of the range, not the city, is what a source sees |
| few owners behind many labels | GSL Networks AS137409 (Singapore, Phoenix, Dallas, Amsterdam, Frankfurt), Datacamp AS212238 (Vienna), Delta Telecom AS29049 (Baku), Clouvider AS62240 (Netherlands), Latitude.sh AS262287 (Sao Paulo) - five owners across nine blocks on the ledger |
| every exit is a known proxy | ip-api flags all nine blocks `proxy: true`, served and refused alike. A public proxy flag is therefore NOT the gate ACRIS uses; ACRIS keeps its own standing per range |
| a switch | re-keys the app's tunnel: every open connection on the machine dies at once (the lane's "dead transport"); the next connections come from the new block |
| a pool that spans blocks | five draws in two blocks = the tunnel mid-switch, or a multi-tunnel mode: the lane's lines would go out on two exits. Never launch on it; wait for one block (the exit-pool gate) |
| protocol modes | single Lightway holds one tunnel = one block. "Automatic" may change protocol or server on its own (a reconnect mid-run = dead transport). A dual / turbo mode opens more than one tunnel = lines spread over exits (the spread pool). The lane wants ONE tunnel, held: single Lightway, not Automatic, not dual |

Two checks; only the one-block check is the lane's (`exit_pool` / `wait_for_pool`, rulebook.py:850-887): five draws,
one /24, or wait 30 s and draw again - no owner lookup, no spent list. The owner and the standing are a person's step
before the entry, with a tool outside the repo, no source touched:

    python C:\dev\cre-office\doc_lane.py exit      five draws -> the block -> the owner -> FRESH / SPENT (spent_providers.json)

### 2. ACRIS

Two mechanisms, seen apart on 2026-09-07 (the whole night in `Acris Reproduction.md`):

| mechanism | what it looks like | keyed on |
|---|---|---|
| standing | the Bandwidth Notice at request 1 (HTTP 307 to `/BandwidthPolicy/ACRIS-BW-POL.html`, or the 25,103-byte page) | the exit range's standing with ACRIS - from our spend (Phoenix after Singapore's 415k, both GSL) or none of ours (Clouvider, never used, refused at once) |
| allowance | served at the exit's speed (~45 requests/s whatever the width), then the notice after a cumulative count | the range: 24k, 26k, 49k, 60k, 157k, 415k, 1.35M, 2.3M requests on different ranges at the same rates |

Not the client. The identical binary, TLS stack, Chrome/128 UA, Referer and cookie handling served 415,321 requests on 140.99.118, was
refused at request 1 on 147.90.160 and 200.162.147, and served again on 2.57.171. On 147.90.160 a curl with a different TLS stack got the
same redirect. The client was constant; only the exit changed. A cookie cannot be the trigger: the refusal comes on the first request,
before any cookie exists. (The one client rule that stands: the honest UA is answered 503, the Chrome UA is served - `Acris.md`.)

ACRIS's notice page, in its words: access is denied for "detection of automated scripts/robots that are capturing data" or "having
exceeded the bandwidth limits"; for large amounts of data, the City Register's subscription data services, 212-496-6300.

What the allowance buys: ~10.7 requests per numeric-id document, ~5.4 per microfilm (FT_/BK_) document; 415k requests = ~39k numeric
documents in 2.5 h on one exit. Unknown: whether a spent range renews (one request after a rest, on login's word), and a range's
allowance before it is spent (only running shows it).

### 3. Richmond

The clerk's registry pages serve through the tunnel. The courts host that serves the document images sits behind Cloudflare, which
challenges the tunnel's exits (the 403 challenge page; `is_challenge` parks the lane at once). 2026-09-06 21:57: the same code with the
VPN OFF served 536 pdfs in 2 minutes. Richmond documentation runs on a line without the tunnel; a challenge is never solved by code.

### 4. The rules that follow

1. Before an entry, a person reads the exit: `doc_lane.py exit` (the tool outside the repo). A provider on `spent_providers.json` is
   not entered - the person's list; the lane's own gate checks one block, not the owner. A fresh one gets ONE entry; the first
   request is the test (a refusal there costs one request; log the owner).
2. One tunnel, one block, held: single Lightway; never launch on a spread pool; never switch under a running lane.
3. A notice parks the lane; the range is never re-entered by a lane. Whether it lifts is one request after a rest, on login's word;
   a lift removes the provider from the list.
4. The survey (login's question "how would we know which work"): walk the app's list once, `exit` at each stop, one request where the
   owner is new; the table of label -> owner -> served / refused is the map for the day. Owners repeat, so the map is shorter than the list.
5. A residential line is outside both gates by construction (no proxy standing, no Cloudflare challenge): the office line on station 2 is
   the strongest door for ACRIS and the only door for Richmond documents.
6. The calendar is doors x allowance: 17.9M documents remaining, ~147M requests; one exit's day at 415k is ~39k documents. More doors and
   larger-standing ranges are the levers; the client is not.

## UPDATE — the boards

There is no phase-level board (login 2026-09-07: "we're not doing a master reproduction file"; "I don't even think we
need an update yet" for the phase). Each source has its own - `<Source>/update/<Source> Update.py`, one program that
always runs and only reads, writing rate, increase, eta, percentage, status and the as-of stamp into `machinery.updates`
every minute (the board part of `rulebook.py`: one subtraction, every percentage over needed, the four statuses, never a
clamp, never a scan on a tick). What a person opens is `reproduction.acris_update` / `richmond_update`: three blocks of
four rows - the totals, workstation 1, workstation 2 - a blank spacer before each workstation block, source before lane
(17-19). The words are in `<Source>/update/<Source> Update.md`.

## History

2026-09-04/05 — `rate_manager.py` added: the three managers as knobs, live on the home workstation since 2026-09-04
19:37 (the night's record: `D:/CRE Decoding System/Reproduction/Acris Reproduction/ACRIS DOCUMENTATION NIGHT
2026-09-04.md`).

2026-09-05 — The database came home (login: "Isn't that a bit confusing? I have no idea how this works compared to how
we've set up the acris and Richmond folders" · "supabase shouldn't even be in reproduction … the project gets a supabase
folder"): the two SQL files moved from `Reproduction/supabase/migrations/` to `schema/` here, `test_claims.py` became
`test_schema.py`, the dictated schema (`SCHEMA.md`) became the section "The table" above; the push script, the SQL tool
and the Supabase CLI's config were retired for the project's one program, `supabase/supabase.py` at the root
(`Supabase.md` beside it; the folder was named `rulebook/` for an hour, then for what it holds). 0001's header still names `Reproduction/SCHEMA.md`, its home when it was applied: an applied
file is never edited.

2026-09-05 — the review of every module against its own words (three reviewers, then each finding read in the code): lane.py - the exit-pool check and the fresh batch's claim moved off the main thread and after the wait (a mega lane's crews no longer stall while one waits for the VPN); a retire during a grow now ends the grow; a `stop` in the control file is cleared when acted on and at start; failed ids leave `held`; HTTPStatus keeps its url; the Governor's grow/retire are relative to the live count it reads; `urllib.error` imported; the help strings show each lane's own defaults. fleet.py - exit 3 is a park, never relaunched; `--edge` on a lane's first launch only; a lane the fleet terminates is logged as such; `--stop-wait` 180; the drive help names the real label. board.py - the increase prints with its sign. cloud.py - `pending_age` defaults to 1 hour (migration 0002); one lock per connection. rate_manager.py - a dead attribute removed. The proofs that had lived only in the scratchpad now sit here (`test_fleet_sim.py`, `test_lane_sim.py`, `test_lane_policies.py`, `test_mega_sim.py`, `test_board_offline.py`, `test_board_sim.py`) and all pass.

2026-09-05 — The six modules and their proof moved here from loose files at the phase level (login: "I don't think
they should be loose folders. I don't like that"), so the phase has the same three folders a source has. Nothing in
the modules changed with the move; the twelve programs' path line changed from `PHASE` to `PHASE / "rulebook"`.

2026-09-05 — The phase's update folder (its md folded into this file 2026-09-07): created as the phase's third folder
(login: "rulebook workflow update ... and then you have all the sources underneath"). The master view is the Supabase
step's business, after the GitHub tree is complete.

2026-09-05 — 0004, the re-check clock leaves the table. login on the example row (18:4x): "Updated at? ... Does it have to be there?
Makes the table less clean. I get it for the pending aspect, but can't the pending just be in code by running the status
against registry/document date of recording?" The column and its trigger are dropped; the wait a pending needs before
its next check is its claim (`land()` writes it forward by `pending_age` instead of deleting it; `claim()` hands out
pendings whose claim is gone). The richmond registration's `todo()` asks the claims table the same question. Written
during the load, applied after it (a column drop takes the table's lock, and the load's COPY must not wait on it);
`test_schema.py` rewritten for the populated table: it inserts its own pendings and claims exactly those, proves the
cooldown, and lands the counters' proof on empty test rows directly.

2026-09-05 19:2x — THE SIMS AND THE POPULATED TABLE. Running the proofs after the 0004 code change, three of them
(`test_lane_sim.py`, `test_lane_policies.py`, `test_mega_sim.py`) turned out to prove the lane loop against the LIVE
cloud with SIM rows - and `claim()` hands out the first empties of the whole table in id order, so on the populated
table they claimed 28 real acris documents (2003030501723001 .. 2005080202430001) in the test host's name. Checked
before anything else: every document cell in the table is a real path or a verdict word (0 odd cells), the counters
never moved (0), no outbox or parked file was left; the 28 claims were deleted (they would have expired by 19:42
anyway). Each of the three now refuses a table that holds anything but SIM rows, before it inserts a row. `test_schema.py`
is the one proof written for the populated table: it inserts its own pendings and claims exactly those.

2026-09-05 20:1x — THE NUL ESCAPE IN A LANDING. The population load met 8,710+ old registries whose JSON carries `\u0000` (a NUL from the source page inside a party name); PostgreSQL's jsonb refuses it (`unsupported Unicode escape sequence`). The new lanes would meet the same character in a fresh registry, and a landing jsonb refuses would fail `land()` forever and sit in the outbox - so `cloud.py` `land()` strips that six-character escape from the landing's JSON before it goes to the table; nothing else is touched. Proven offline on a value carrying a real NUL.

2026-09-05 22:04 — 0004 APPLIED on the populated tables, after the load and its verify (MATCH on both sources, 21:52). The table is `source | doc_id | registry | document`. test_schema.py ALL OK on the populated table (22:13, its connections without the statement timeout; the first run's recount was cut at two minutes): its own pendings claimed and nothing real, the cooldown held in the landing host's name for about an hour, an expired cooldown handed out again and the rows still held skipped, the counters moved by what was new, the cell rule and the heartbeats as before.

2026-09-06 14:3x — ONE BATCH (login: "with Acris you can only have one batch that enters ... of those 30 workers, 10 are syncs
and 20 are registrations"). lane.py `--one-batch`: the hosted crews (`--also`) ride the host crew's entry - the host's exit-pool
check, try and wait are the batch's; each next crew's births start right after the previous crew's ramp, `--stagger` apart (one
ramp from the first worker to the last, no `--entry-gap` between crews); what closes one crew closes the batch (`_hangup_batch`:
every crew leaves, lands what it holds, drops its cut batch, waits the one wait) and the batch re-enters from the top, the host
first; the rate manager is ignored on the batch (login: "you don't need a rate manager, just stay low and be patient"); each crew
keeps its own pooled session (run 3 of 08-28: mixed floors on one session served empty viewer pages; the wire pattern is a
connection per worker either way). fleet.py: a `Site` says `one_batch` and `mega_default`; the acris site says both, so its
default run is the mega lane and the hosted crews get `--one-batch` and no manager knobs; a lane run alone keeps its managers
(a lane alone is maximized); `--separate` (tests) launches one process per lane. The richmond site is unchanged: any number of
batches at any width (login: "for Richmond you could do max"). Widths on acris 5/5/5 by login's word, set by `--lanes`
(Gate 3: `--lanes identification:10,registration:20`). Proven offline: `test_one_batch_offline.py` ALL OK (12 checks),
`test_fleet_sim.py` ALL OK on both sites. Not run live: Gate 3, on login's word after the exit reset. The ten live sims
(`test_*_sim.py` under rulebook/ and the sources' rulebooks, `test_lane_policies.py`) still name the tables 0007 replaces
(`<source>_update`, `_update_lanes`, `_heartbeats`, `_claims`): they stay guarded and unrun until reworked for
`reproduction.updates` / `machinery.claims`. The schema `reproduction` holds the record and its two boards - `acris`, `acris_update`, `richmond`, `richmond_update` - and nothing else (16, 2026-09-07); `machinery` holds what the code needs and a person never reads (`claims`, `updates`); `reading` holds the reading layer for products (`acris_fields`, `acris_parcels`, `acris_keys`, `acris_profile` and the richmond four).

2026-09-06 17:1x — GATE 2's THREE MIGRATIONS DONE: 0005 (15:36, proven 15:37: twelve filters every plan an index scan, a landed
row found within 2 s), 0006 (17:07, proven 17:08: four populated profile views, a facet in about 200 ms), 0007 (17:08, proven
17:10: test_schema.py ALL OK on the live table - two workstations claiming at once, the cooldown, the counters on the lane row
and the workstation's own row). The key census against the index: every key answers by containment, ranges on the typed
fields; two gaps named and written as 0008 (`schema/20260906150000_lookup_more.sql`): block keys with their own GIN and the
helpers block_key / bbl / parcel that build the key from words ("Manhattan block 573 lot 24" without assembling ten digits),
party names as one text with a trigram GIN (a name by part of it), a typed expiration date, and the parcels views with borough,
block and lot derived. Its functions proven in a rolled-back transaction; the build follows the audit. The proof of 0008 after
the build: `prove_0008_filters` (plans and timings of a block, a lot from words, a partial name, an expiration range, the
parcels view, and a landed row found by block and by part of a name).

2026-09-06 19:4x — GATE 2 CLOSED. 0008 built (the trigram over party names 37 min, 1.9 GB) and proven: a block from words
(`reproduction.block_keys(registry) @> array[reproduction.block_key('MANHATTAN', 582)]`, 522 ms), a lot from words
(`registry @> reproduction.parcel('MANHATTAN', 582, 24)`, 320 ms), an expiration range (1.4 s), a landed row found by all of
them. The honest limits, recorded in Supabase.md: a party by PART of a name reads its index but a common name takes 30-45 s
cold on the Small instance (the exact full name stays at 300 ms; a word-level index is the candidate 0009); the parcels views
read a document's parcels with borough / block / lot spelled out - finding a parcel goes through containment or the block
keys. Gate 1 closed the same hour (Population.md). Next: gate 3 on login's word - the acris phase lane as ONE BATCH,
`--lanes identification:10,registration:20 --unpark --edge 2026000245705` (the highest CRFN the table holds, read from the
table 18:5x; the lane's old state file said 2026000247108 and does not exist any more - the number comes from the table, never
a guess), the richmond phase lane `--lanes identification:10,registration:20 --mega`.

2026-09-06 20:3x — A PROVISIONAL REGISTRATION (found while checking the cleaned CRFNs against the city's index). The open-data
master datasets (real and personal property together - a check against the real one alone reads federal liens, RFLs and PATs
as "missing") are complete through 2026-07-31 (good_through) with nothing for August; every document of ours they hold agrees
with ours, 0 disagreements. What they do NOT hold, besides August: documents ACRIS has indexed (a document id and a CRFN issued)
but not yet RECORDED - our registry for those has an empty `recorded` because the detail page had none when the lane read it.
8,876 acris rows have no readable recorded date (via the recorded index), most of them the newest. A registration taken before
recording is PROVISIONAL: the recorded date (and whatever else recording fills) arrives later, and our rule "a registry over a
registry adds nothing" means nobody goes back. THE RULE TO ADD (gate 3 or the first window after): a registry without a recorded
date older than N days is claimed again by the registration lane and re-read; the counters do not move; the re-read that still
finds no recorded date waits again. The same shape as a pending document. Not tonight's change; written here so it is not lost.

2026-09-06 20:3x — 0009 THE PROVISIONAL REGISTRATION, APPLIED AND PROVEN (applied 20:35–20:40, before the batch) (login: "if something is filed and has a CRFN and it
doesn't have a recording yet, we catch it ... fix those before we even go into gate 3"). claim() for registration now offers,
before the empties, every registry that is an object without a readable recorded date on an id younger than 400 days (the id's
first eight digits are its date; older and still undated stays as filed - the registration's `absent`); land() keeps a
registry landed without a recorded date as a cooldown for `--pending-age` (a day for the leveling batch), like a pending
document, and releases it when a recorded date lands; the counters move only for a new registration. The parser already refuses
"RECORDED / FILED: N/A" (no made-up date), so a re-read before recording lands the same shape and cools again. Proven by
`test_provisional.py` on throwaway rows in a rolled-back transaction, before the push and again after: ALL OK (8 checks); the due
query reads the recorded index and lists 500 in 425 ms. 8,876 real registries are due tonight - gate 3's registration crew
takes them first, then the new documents the sync finds. `--pending-age "1 day"` on the batch.

2026-09-06 21:21 — GATE 3 LEVEL ON BOTH SOURCES (identification + registration). ACRIS: one batch of 30 (sync 10 + registration 20) entered 20:44:28, level 20:54:03 (edge 2026000254029, 8,323 new documents), the 8,876 provisional registries re-read by 21:02 (0 left), one session close 20:57 → the batch-wide hang-up and a re-entry served 20:58:36, registration 21,640,885 / 21,640,885 at 21:21 (Acris Reproduction.md §18). Richmond: level in two minutes (0 new, 0 to register). Richmond documentation (499 pages) parked on CLOUDFLARE'S CHALLENGE in front of the courts host - proven not the code's (the request is the old lane's byte for byte; three UA strings, a bound socket, curl.exe, and a fetcher on a datacenter network with no VPN were all challenged on tokens the clerk had just minted) and not one exit's (login: the VPN was on for the whole 2.5M-page week): the courts host's own posture, on record flipping before (Richmond Documentation.md 21:2x); `richmond.is_challenge()` now parks the lane at once, named. Gate 4 (ACRIS documentation on two workstations) may start on login's word; the 499 richmond pages wait on the courts host - one `--unpark` pull tells when.

2026-09-06 22:00 — RICHMOND DOCUMENTATION LEVEL: 2,511,936 / 2,511,936 (137 pending = scan lag). login's theory proven: every lane stopped at 21:43 (both fleets exit 0), the VPN off, the same documentation code entered on the home line 69.204.251 at 21:57:19 and pulled 536 pdfs in two minutes, 0 fails - Cloudflare in front of the courts host challenges the VPN's exits and serves the residential line; the 21:21 entry's "not one exit" is refuted. THE RULE: richmond documentation on a line WITHOUT the VPN, ACRIS ON it, never both through one machine's tunnel → workstation 2 (the office IP) takes richmond documentation (README, Richmond Documentation.md). GATE 3 IS CLOSED on every lane but ACRIS documentation, which is Gate 4. ACRIS is not relaunched until the VPN is back on (ACRIS never on the home address).

2026-09-06 22:38 — 0010 THE TWO UPDATE VIEWS (`reproduction.acris_update`, `reproduction.richmond_update`): the one updates table cut per source in reading order, for login to open in Supabase (Supabase.md 0010). Gate 4's first document lane: 1x40 entered 22:30:46 on the fresh block 94.20.154 (the tenth notice at 22:15 refused the first request on 45.95.243), 40/40 workers at minute 4, 1,212 pdfs by minute 7 at 3.6-4.1 docs/s, both boards ticking.

2026-09-06 22:45 — 0011: `acris_update` / `richmond_update` are four rows per source (the phase and the three lanes, no workstation column); the per-station rows moved to `acris_workstations` / `richmond_workstations` (Supabase.md 0011). 22:41:48 THE ELEVENTH NOTICE: the 1x40 document lane refused after 11.2 minutes and ~23k requests at 35 req/s on the fresh block 94.20.154 - parked, the board stalled, a person decides (Acris Reproduction.md §18).

2026-09-06 22:5x — 0012: the update views trimmed to what a person reads (four rows; landed / needed / pct, the two blocks, status, as_of); the per-station views carry the machine's own count, rates, workers, status and last word (Supabase.md 0012).

2026-09-06 23:1x — 0013: `as_of`/`last_seen` render in Eastern (`as_of_et`, `last_seen_et`) in the four update views (login's word). 23:11:48 THE TWELFTH NOTICE: the managed 1x40 (band 4-5, held exactly) refused after 11.2 min on the fresh block 135.136.69 - the SAME ~11 min as the eleventh on a different fresh block at a different rate → a per-exit allowance on this VPN provider, not the code/rate/UA (all verified against the proven decoder). The office line (workstation 2) is the discriminator and the path forward; relaunching into fresh VPN blocks stopped.

2026-09-07 00:11 — the fourteenth notice; the A/B is closed. The proven OneTouch lane (1x40 pinned, no manager) served 6.8 min / 26,279 requests / 2,422 pdfs on a fresh VPN block, then the notice. Three fresh blocks tonight fell at 24k / 28.5k / 26.3k requests (2.0-2.7k documents) at 35 / 43 / 64 req/s, in 11.2 / 11.2 / 6.8 min: the meter tonight is a per-exit REQUEST BUDGET on this provider's ranges, not a rate and not the code (old and new meet the same wall). Gate 4 waits on an address, not a change: workstation 2's own line or another provider. See Acris Reproduction.md.

2026-09-07 01:10 — 0014 applied: pct_60s / pct_5m dropped from the two source update views (kept in the table); the views read landed / needed / pct, then rate · increase · eta for 60 s and 5 min, status, as_of_et. Known wart, not fixed yet: the lane flushes landings once a minute or at 200 results and the board ticks once a minute, so the 60-second cell sometimes reads 0 and then double; the 5-minute block is smooth. The fix is a shorter lane flush (15 s / 50 results) at the next natural exit.

2026-09-07 01:18 — the fifteenth notice. The golden-band GitHub run on 89.106.14 was cut at 22.5 min / ~49k requests / ~4,600 pdfs: double the earlier fresh blocks after a longer cooldown, still nowhere near the golden runs. The VPN's exits are throttled for us tonight regardless of code/rate/ramp/band; the sustain test moves to the office line (workstation 2) or to a block held still for hours. Documentation parked; the fleet stilled every lane.

2026-09-07 21:5x — the door flag (login: "go, write the door flag"). The survey of every owner in the app (24 stops, one request each, the ledger `C:\dev\cre-office\doors.md`) and the held run that followed showed the unit ACRIS meters is the address range, not the owner: one Latitude.sh block refused the lane at request 1 while another served it minutes later, and a rented address at DigitalOcean served on its first request. So a door is a block, and a station can hold several at once through tunnels. `--door URL`, repeatable, on every cycle lane and passed through by the fleet: one crew per role per door, each with its own exit check (the draws through the tunnel), its own session (the proxy on it) and its own rate manager; a notice on one door retires that crew alone and the lane parks when every door has been refused; one door is the lane as before. ONE BATCH and doors together are refused. The log names the crews `<lane>@doorN`; the cloud, the outbox and the claims keep the lane name, and the heartbeat carries every door's workers.

2026-09-08 08:1x — HOT-ADD A DOOR (login: "go ahead and write the hot-add door change"). The night walk showed the shape of the work: one VPN block at a time on a station, each block run to its notice, the next served block found by one request each, rented addresses meant to run beside it. The door list was fixed at launch, so bringing the next VPN block in meant relaunching the whole lane and re-entering every other door. Now `door=URL` or `door=direct` in the control file (the fleet command `door LANE=URL`, 2070-2082) gives the running lane one more crew per role on that door, born the way a launched crew is born - cloud row, outbox landed, a batch claimed, then the ordinary entry: wire up, exit pool settled, one ramp, its own rate manager (1180-1222). A door already open is not opened twice; a retired door is never re-entered by it (the walk moves the VPN to a served block first, then writes `door=direct` again, and the new crew takes the next door number); the word is consumed once acted on; ONE BATCH takes no doors. A crew added this way keeps its own PROGRESS count from the minute it joins.

2026-09-08 10:0x - CONCURRENT DOOR ENTRY (login: "why not just ramp them the moment they are launched? if you have to wait for door 1 to reach perfection before launching door 2 it will take forever ... each door can just ramp up to its max throughput and sprint to its allowance before a new one comes in"). The entry gate serialized EVERY crew: no crew entered while any other was ramping, and only `--entry-gap` after the last ramp ENDED. With eight doors in sprint (each ramp to width_max) that was ~5 min per door, ~40 min to a full house - the first doors could burn before the last entered. The burst rule is per ADDRESS, so the gate is now per DOOR: a crew waits only for a crew on the SAME door (same proxy; the no-door crews share the empty door and still take turns, the cycle unchanged), and enters `--entry-gap` after the last crew on any door STARTED its ramp (`Crew.entered_at`, set in `enter`). Measured 10:01: door1 10:01:22, door2 :30, door3 :40, door4 :48, door5 :56 - all eight ramping side by side inside a minute. Same session, the SPRINT band on the doors (rps_ceiling 0, dps_ceiling 20, width to 40-60): one address uncapped served ~100 requests/s and 8-10 docs/s (10 workers 43/s, 20: 71/s, 30: 77/s, 50: 100/s) - the 62-67/s "wall" of 09-07 was the golden band's own ceiling, not the source's. Open: whether ~100/s shortens the allowance (requests to the notice) - the running eight-door sprint is the measurement.

2026-09-08 10:1x - ONE LANE PROCESS PER CORE (login: "we need each processor to get its own process, otherwise we are failing to maximize our doors"). The eight-door sprint in ONE process, all doors ramping side by side, gave 93 requests/s and 12.6 docs/s in total - one door alone had given ~100/s. Measured: the lane process at 98%% of one core (the machine at 26%% of eight), the home line at 44.6 Mbit/s, D: writing 8.9 MB/s with an empty queue, RAM fine. The interpreter lock is the ceiling: one Python process = ~100 requests/s whatever its door count. So a machine runs one lane process per core, one door each (a far door needs more workers than a near one to fill the same core; the rate manager finds each slot's width - the door curve stops growth where a step buys nothing). `--slot N` gives each process its own lock/control/parked files (`lane_tag`), `--host <station>-N` its own cloud rows and claims, `--log documentation.N.log` its own log; the lock's rule - two processes on one lane = two doors at the source - holds per slot: the door sets are disjoint. Launched 10:16: eight slots, eight locks, ~1.5 MB per worker, 1 GB RAM to spare. The fleet (`Acris Reproduction.py`) does not drive slots yet - its stop/width/door commands address `<lane>.control`; a slot is addressed by hand: `width=30` into `documentation.N.control`, `stop` likewise.

2026-09-08 11:0x - THE TRANSACTION POOLER, AND WHAT THE SEVEN-DOOR DIRECT RUN SAID (login: "all I care about is figuring out a way to maximize doors from one machine and completely use up the maximum rate"). Eight slot processes on the session pooler could not all connect: 15 clients in all, ~6 of them the boards, so `--pooler transaction` (6544) is now the slots' pooler (`POOLER_PORT`); a `select 1` and a live slot proved it. Then the clean run: every droplet destroyed and refilled (seven fresh blocks: London 161.35.164, Amsterdam 64.227.71, Singapore 159.223.60 + 159.223.68, Bangalore 168.144.69, Sydney 168.144.168, Toronto 165.22.236 - DigitalOcean's fresh blocks run out at seven or eight), seven processes DIRECT with the VPN off (the droplet tunnels never need the VPN - they exit at the droplet; disconnecting it had dropped every tunnel, which proved they had been riding inside it): 86 req/s, 10 docs/s in total - the SAME ceiling as through the VPN, the machine at 85%% of one core in all, Wi-Fi 48 Mbit/s. So neither the VPN nor the machine. The reading that fits every layout since 09:30: ~12 req/s PER TUNNEL DOOR (near 20-24, far 9-10) - an `ssh -D` tunnel is ONE TCP connection multiplexing all sixty workers - and the aggregate is just the sum; the VPN door alone reached 100 because every worker had its own connection. The lever is LINES PER DOOR: a second tunnel to the same droplet (slot 8 on 1087 next to slot 1 on 1080, London), or a SOCKS service on the droplet so every worker owns its connection. Measured next.

2026-09-08 12:0x - THE DOORS ARE INDEPENDENT; EACH ADDRESS HAS ITS OWN PACE; THE OUTBOX WAS SHARED (login: "if you have separate doors that are completely uncorrelated to each other, then ACRIS doesn't throttle" / "something in the code so that we don't keep overlapping and pulling from the same resources"). The 11:08 reading above was wrong: a SOCKS service on the droplet (every worker its own connection, no ssh) ramped to 60 workers at 15.9 req/s = the tunnel's 18.6 - the tunnel was never the choke. Every home-side candidate then measured under load and cleared: 348 Mbit/s spare on the line beside the lanes' 40, 94 ms to Amsterdam under 618 open connections (bare 90), D: 0.5 ms writes, lanes 6-62%% of a core. ON THE DROPLETS (curl, nothing of ours in the path, one session, the lane's UA and referer): a quiet fresh address serves one page image in 4.8-13 s, the SAME serially or 60 wide, under Chrome or Firefox, with or without a session - ACRIS assigns each ADDRESS a pace from its first request (DigitalOcean 64.227.71 ~1.3 s = 45 req/s at 60 workers; 209.38.x / 146.190.x / 165.22.x ~5 s = 12; 159.223.x / 152.42.x ~12 s = 4.5; a VPN exit ~0.5 s = 100), and a door's rate is workers / pace. THE STOP-FOUR TEST: `stop` into four slots' control files removed ~40 req/s of mid-tier doors and the fast door beside them did not rise (42-52 before, 42-52 after) - no shared pool at the source; the ~100 req/s seen in every layout was the SUM of similar doors. So the levers are (1) doors with a FAST pace (the door manager now measures the pace on the droplet before keeping it, `pace.sh` / `do_doors.py pace`, threshold 2,500 ms) and (2) more of them, one process per door. The one overlap that WAS in the code: the crew's outbox and fails files were named by the lane, not the slot - now `lane_tag` (the --slot row). Also measured: a VPN exit's standing today - usa-salt-lake-city refused at request 1, usa-chicago and usa-new-york spread their exits over two blocks (the exit-pool gate holds, never forced); the split tunnel needs admin, so each VPN switch drops every droplet door once (they re-enter on their own).
