# THE RULEBOOK

The phase's shared modules: a rule is written once here and every lane of every source on every workstation gets it.
A source's own rules - its URLs minted from the id, its one user-agent, its refusal detector, where its documents file
- live in `<Source>/rulebook/` (`acris.py` · `Acris.md`, `richmond.py` · `Richmond.md`); nothing about one source is
in here. Every module's docstring is its own authority: the rules, the numbers and where each was measured. This file
says what each module is for and how a program reaches it.

| module | job | proof |
|---|---|---|
| `lane.py` | THE ENTRY every cycle lane shares. A lane file defines a ROLE (what one worker does with one document) and hands it to `run()`, which owns the rest: one pooled session per crew, births `--stagger` apart (ONE BATCH, `--one-batch`, login 2026-09-06: the hosted crews ride the host's entry - one ramp across the crews, one hang-up, one re-entry, no manager; each crew its own session) with one connection each, claim / land / heartbeat once a minute through the outbox, failures that never stop the lane, the refusal park (HTTP 200 + the notice page), the hang-up and the re-entry on a fresh batch, the wall, the width control file, the mega lane, one door per lane. The three managers as knobs (`--manage`, default off): the ramp from one worker, the rate manager's windows, the session cap | `test_managers.py` (the lane's wiring of the managers through the whole loop) |
| `fleet.py` | THE FLEET every source runs: the source's lanes together as one program - one process per lane, one door per lane `--entry-gap` apart (or, on a site that says so - acris - ONE BATCH: the mega lane by default, the hosted crews with `--one-batch` and no manager knobs), the cycle's order, the watch with the meaning of every exit code, the relaunch cap, a parked lane never relaunched, `status` / `stop` / `width`, one fleet per machine. A source's `<Source> Reproduction.py` is a `Site` (name, lanes, widths, where the programs live, the managers' knobs per lane) and this module | `test_fleet_sim.py` (fake lane programs in a temp tree; ONE BATCH on the acris site, plain on richmond), `test_one_batch_offline.py` (the lane's ONE BATCH with a fake cloud and fake roles) |
| `board.py` | THE BOARD every source's update program shares: the counters and the heartbeats read once a minute, one subtraction for rate and increase, every percentage over needed, the four computed statuses, never a clamp, never a scan on a tick | `test_board_offline.py` (the arithmetic), `test_board_sim.py` (the live tabs with throwaway counters) |
| `cloud.py` | THE CLOUD TABLE from a lane's point of view: `claim`, `land`, `heartbeat` as one round trip each to the functions defined in `schema/`, the registries, and the local outbox so a cloud hiccup loses nothing. One connection per crew, one statement at a time under its lock | `test_lane_sim.py`, `test_lane_policies.py` (throwaway rows on the live table) |
| `storage.py` | WHERE A DOCUMENT LIVES: the drive found by its label on Windows or Mac, the One Touch tree `D:\NYC CRE Decoded\Reproduction\<Source>\By Document\<year>\<MM Mon>\<day>\<id>.pdf` (the day from the recorded date, else a digital id's date, else the id split - the old lane's rule kept), recorded in canonical `D:\` form whichever machine fetched the file | `../Acris/rulebook/test_acris_offline.py` (the drive lookup, the path rule and the acris rules) |
| `rate_manager.py` | THE RATE MANAGER and the session cap: `next_width()` is pure arithmetic (the graduated hand around the docs band, the request ceiling as a projection at the exit's recent speed, the door curve), the `Governor` thread only calls it and the crew's resize | `test_managers.py` (fake exits at 10x speed: the band, the ceiling, the stall, the door curve, the ramp, the session knob) |
| `requirements.txt` | the one install a workstation needs: `pip install -r requirements.txt` | |
| `schema/` | THE TABLE's definition: the phase's schema `reproduction` as numbered SQL files, one per dictated decision, applied once and never edited after (a new decision is a new file) - 0001 the tables, the cell rule as constraints, the to-do indexes, the claims, the heartbeats, the counters and the four functions `claim` / `land` / `heartbeat` / `reconcile`; 0002 pendings first, and documentation claims only where a registry is; 0003 the `source` column first in both tables (a constant per table, for the cross-source tables of construction); 0004 the re-check clock out of the table (a landed pending keeps its claim as its cooldown); 0005 the lookup - an index for each field a person filters by, a GIN over the whole registry, an index on the document cell, and the `acris_fields` / `richmond_fields` views (written 2026-09-06, applied on login's word); 0006 the profile - `<source>_profile` (documents by type, borough, year, parcels, parties, pages) and `<source>_keys` (which keys appear where, how often), materialized, refreshed on demand (written 2026-09-06 12:0x); 0007 the updates table and the claims out of sight - `reproduction.updates` (source, lane, workstation: the phase, lane and workstation rows) replaces the two tabs and the heartbeats of both sources, `machinery.claims` replaces the two claims tables; the four functions keep their signatures (written and proven in a rolled-back run 2026-09-06 13:1x). Applied and recorded by the project's program, `python ../../supabase/supabase.py push` (`--dry` first; `../../supabase/Supabase.md`). The dictated concept is the section "The table" below | `test_schema.py` (claim / land / heartbeat / reconcile on the live project with throwaway TEST- rows; refuses a populated table) |

## How a program reaches it

Every lane, fleet and board program carries one path line and imports by name:

    PHASE = HERE.parents[2]                           # <lane> -> workflow -> <Source> -> Reproduction
    sys.path.insert(0, str(PHASE / "rulebook"))       # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager
    sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
    import cloud, lane, storage, acris

A second workstation clones the repo and runs the same file; there is no install step beyond `requirements.txt` and
the env file (`C:/dev/nyc-cre-decoded.env` at home, `~/nyc-cre-decoded.env` on a Mac, or `NYC_CRE_DECODED_ENV`),
which is never committed or printed.

## The table — as dictated (2026-09-03)

login's organization concept for NYC CRE Decoded, in the words it was given, followed by the mapping onto Supabase, git
and the drive. The SQL files in `schema/` beside this file implement it one dictated decision at a time; nothing is
created that was not dictated. The database as a whole - one project, one schema per phase, the program that applies
these files - is `../../supabase/Supabase.md`.

### The concept

**Supabase** is the database the lane codes feed. A phase (`reproduction`) holds source folders (`acris`, `richmond`). Each source has a *workflow* database that its lanes fill and an *update* database that reads the workflow's progress.

**The four lanes per source.** Enumeration, synchronization, registration, documentation. Each is its own code, toggled on and off independently, and configurable in width: 1x40, 1x20, 1x80; synchronization 1x20 beside documentation 1x40; or one entry of 100 split 20 synchronization, 40 registration, 40 documentation.

- **Enumeration is not part of the reproduction cycle.** It is the first step to get reproduction up, and afterwards an audit: it counts the source (acris: Socrata + CRFN; richmond: census + date/range), compares with the database total, and the difference must be 0. It never touches the cloud database and has no table.
- **Synchronization** keeps the database live: for acris it sits at the CRFN edge and any CRFN movement triggers an edge walk that populates new ids; for richmond it walks from the last recorded id by date range. One monitor worker, the rest walkers.
- **Registration** acquires the registry information (the recorded details) for each id, using the source rules and a URL minted by the code from the id stem. No navigation step, no URL column.
- **Documentation** does the same for the document itself: minted access, save to the drive, record the path.

**The workflow row** is as simple as `doc id | registry | document`: synchronization fills the id, registration the registry, documentation the document. (2026-09-05: a `source` column stands in front of the three cells - `source | doc_id | registry | document` - a constant the table enforces, so a cross-source table or view carries the source in every row without a join; login: "knowing acris, richmond, dob now, dof, bis web, etc. is helpful as we expand and link datasets". The two sources keep their own tables.)

**The cell rule.** A lane's outcome lives in the cell that lane fills, and there are exactly two words a cell may hold instead of its fill: `pending` (still being checked; it stays in the backfill until it becomes the fill or `absent`) and `absent` (checked: there is none). Anything but empty counts as landed. The rules for when a cell becomes pending or absent are part of the lane code.

**The path.** Recorded as something that pastes into the file bar and opens the document: the full One Touch path. (2026-09-05, superseding the layout dictated here on 09-03: the One Touch mirrors GitHub and Supabase - `D:\NYC CRE Decoded\Reproduction\<Source>\By Document\<year>\<MM Mon>\<day>\<id>.pdf`, the day folder from the RECORDED date; login: "NYC CRE Decoded -> reproduction -> source -> by document -> by year -> by month -> by day ... the PDFs stay in the OneTouch because Supabase is just for storing the data table". No borough folder.) Two workstations: the second mounts its own drive under the same letter and writes the same layout, so the recorded path opens the file on whichever machine holds it; its documents are transferred into the One Touch before it continues, and nothing in the database changes on transfer. A click-to-open link is not possible for a file on a drive; it would require the PDFs served from the cloud (the corpus is on the order of 20 TB at full size, so that is a real cost, not a schema change).

**The update database** is the board, built cleaner: 60-second and 5-minute rate, increase, percentage and eta, plus landed, needed, percentage of total, the status and the as-of stamp. Two tabs: tab 1 reads the phase as completion of rows landed against rows (all three cells filled); tab 2 reads each lane as the cells of that lane landed against rows (10 rows, 5 documented = 50 % on documentation). The update code is one program per source that always runs and only reads.

**Two workstations, no overlap (dictated 2026-09-03 16:xx).** "What do we do to assure there's no overlap in what they're pulling?" The table is the only to-do list. A lane never picks its own work: it calls `claim(source, lane, host, n, ttl)`, which hands out a slice of empty cells with the workstation's name and an expiry written on it, atomically (`FOR UPDATE SKIP LOCKED` plus the claims key), skipping anything another workstation holds; two machines asking in the same second get two different slices. Pendings whose cooldown has run out are taken first, then empties, both in id order straight off the partial indexes (no sort) - migrations 0002 and 0004; a landed pending keeps its claim as a cooldown for `pending_age` (`land()`'s fifth argument), so the claims table is the only clock and the workflow tables carry no timestamp. The lane fills its cells with `land()` in batches once a minute, which also drops its claims; a machine that dies leaves claims that expire and go back on the list. Each running lane writes `heartbeat()` once a minute into `*_heartbeats` (one row per lane per workstation); the update program folds those into the lane row (hosts, width, freshest heartbeat, last word). Synchronization runs on one machine only (two monitors at the CRFN edge would find the same ids); registration and documentation can run anywhere. Claims need the rows in the cloud, so the second workstation joins after the row move; until then the only overlap-free split is the fixed id-range split built 2026-09-02.

**The status follows the lane.** Each lane writes a heartbeat once a minute into `*_heartbeats` (host, width, a timestamp, its last word) and the board folds it into the lane's update row, so the board can say: `active` = heartbeat fresh and landed rising · `pending` = no fresh heartbeat and not complete (the lane is paused or parked by a person) · `stalled` = the lane's last word is a refusal or a wall (rejected by the source) · `complete` = 100 %. A fetch error never stops a lane; only the notice page does, and a hang-up is redialed.

### The mapping

| concept | Supabase | git | drive |
|---|---|---|---|
| phase | schema `reproduction` | `Reproduction/` (its tables defined in `rulebook/schema/`, explained here) | |
| source | table-name prefix `acris_`, `richmond_` | `Reproduction/Acris/`, `Reproduction/Richmond/` (each with its reproduction doc) | `acris\…`, `richmond\…` under the store root |
| workflow database | `reproduction.acris` (source, doc_id, registry, document) | `Reproduction/Acris/workflow/{reproduction,enumeration,synchronization,registration,documentation}/` (reproduction/ is the fleet program and the source's authority) | documents land here |
| update database | `reproduction.acris_update` (tab 1), `reproduction.acris_update_lanes` (tab 2) | `Reproduction/Acris/update/` | |
| enumeration | no table | `…/workflow/enumeration/` | |

Postgres has one level of folder above tables, so the phase is the schema and the source sits in the table name; in the Table Editor, choose the schema `reproduction` and the ten tables (five per source: the workflow table, the two update tabs, the claims, the heartbeats) are the whole picture. A non-public schema must be exposed under Project Settings → Data API before the REST layer can read it; direct SQL needs nothing.

### The SQL files

| file | decision |
|---|---|
| `20260903150000_reproduction.sql` | the phase schema; `acris` / `richmond` (doc_id `collate "C"` so index order is id order and range seeks walk the key) with the cell rule as check constraints (JSON or path, `pending`, `absent`); four partial to-do indexes per source (`*_registration_empty/_pending`, `*_documentation_empty/_pending`); `*_claims` (doc_id, lane, host, until; key (doc_id, lane)); `*_heartbeats` (lane, host, width, heartbeat_at, last_event); the functions `claim()`, `land()`, `heartbeat()`, `reconcile()`; `*_update` and `*_update_lanes` (with the folded hosts, width, heartbeat_at, last_event); the lane-status enum; `updated_at` touch trigger |
| `20260903230000_pending_backfill.sql` | pendings first: `claim()`'s sixth argument `pending_age` (its default now 1 hour, was 1 day) offers the pendings due for a re-check before the empties, and documentation claims only rows whose registry is a JSON object; the pending indexes are re-keyed on `updated_at` so the due set is an index range (login 2026-09-03 23:5x, "pending goes back to the backfill") |
| `20260905170000_source_column.sql` | the `source` column first in `acris` and `richmond` (a constant per table, `check (source = 'acris')`, default filled so every insert that names only doc_id still works); the empty tables rebuilt in the dictated order with every rule, index, trigger and comment kept and the claims tables rebuilt for their foreign keys; `doc_id` keeps its name (login 2026-09-05 16:5x: "source, id, registry, document ... separating acris and richmond given they each have their own table") |
| `20260905200000_cooldown_in_claims.sql` | the re-check clock leaves the table: `updated_at` and its touch trigger dropped from `acris` and `richmond`, so a row is `source | doc_id | registry | document` and nothing about when; a pending's wait between two checks is its CLAIM - `land()` keeps a landed pending's claim as a cooldown until now() + `pending_age` (its new fifth argument, default 1 hour) and `claim()` (five arguments now) offers the pendings whose claim is gone, then empties, both in id order off the partial indexes (the pending indexes re-keyed on `doc_id`); the claims table is the schema's only clock and holds only rows in flight or cooling (login 2026-09-05 18:4x: "Does it have to be there? Makes the table less clean") |

**The counting rule (speed).** The board never counts 21.6M rows once a minute. `land()` adds exactly what was new to the lane's `landed` (cells that were empty) and to the phase's `landed` (rows whose other cell was already filled); a pending that becomes a path was already counted and adds nothing. `reconcile(source)` recounts from the primary key and the four partial indexes (index-only scans, seconds on the full table) and overwrites the counters; the update program runs it on demand only (`reconcile`): after the data move, after a hand edit, never on the tick. The 60-second and 5-minute rates are the board's subtraction of `landed` between its own ticks.

Apply with the project's program: `python ../../supabase/supabase.py push --dry` shows what would be applied, `push` applies it and records each file in the project's ledger. A file already applied is never edited - a new decision is a new file (0001's header still names `Reproduction/SCHEMA.md`, its home when it was applied).

## The proofs

`python test_managers.py` runs the managers' proof offline - fake exits, a fake cloud, nothing asked of any source; its
last line is `THREE MANAGERS: ALL OK`. The simulations named above run the shared modules against fake lane programs
or throwaway rows on the live cloud table (never a source); each one says in its first line what it touches.
Each source's proofs live in its own `rulebook/` beside its module - `Acris/rulebook/test_*.py`, `Richmond/rulebook/test_*.py` -
and a lane folder holds the lane and its md, nothing else (login 2026-09-06, on the richmond lanes: "test runs ... that
shouldn't be there"; the thirteen proofs that sat beside the lanes moved that day, each offline one re-run from its new
place, all OK; the live simulations were not run - their first read is a count over the populated table).

## Filtering the table (0005, 2026-09-06)

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
it off - so a stray query costs at most two minutes, never a runaway. The disk goes to 60 GB by hand before the build
(22 GB used of 40 today; the indexes and the lanes' growth need the room).

### The proven filters (2026-09-06 15:37, every plan an index scan)

Write filters against the views `reproduction.acris_fields` and `reproduction.richmond_fields` (typed columns: type,
borough, recorded, doc_date, pages, amount, crfn / doc_type, recorded, book, page, instrument, amount) - a filter on a
view column IS the indexed expression - and against the registry itself with containment (`@>`) for anything else: a
parcel, a party, a unit, any key at any depth. The document cell answers a prefix (`like 'D:\...\2003\01 Jan\23\%'
escape ''`, the day folder). Measured on the pooled connection, a Small instance, the table larger than memory:

| filter | query | ms |
|---|---|---|
| deeds in Queens, newest first | `select doc_id, recorded, pages, document from reproduction.acris_fields where type = 'DEED' and borough = 'QUEENS' order by doc_id desc limit 20` | 207 |
| a year of deeds by recorded date | `select count(*) from reproduction.acris_fields where type = 'DEED' and recorded between '1995-01-01' and '1995-12-31'` (54,581 rows) | 13,282 beside a running profile build; two indexes ANDed |
| long documents | `select doc_id, type, pages from reproduction.acris_fields where pages >= 50 order by pages desc limit 20` | 199 |
| amount above ten million | `select doc_id, type, amount from reproduction.acris_fields where amount >= 10000000 order by amount desc limit 20` | 200 |
| one crfn | `select doc_id from reproduction.acris_fields where crfn = '2003000003997'` | 181 |
| a parcel by bbl | `select doc_id, registry->>'type' from reproduction.acris where registry @> '{"parcels":[{"bbl":"1015131008"}]}' limit 20` | 191 |
| a party by name | `select doc_id, registry->>'type' from reproduction.acris where registry @> '{"parties":[{"name":"CITY OF NEW YORK"}]}' limit 20` | 311 |
| one day folder | `select doc_id, document from reproduction.acris where document like 'D:\NYC CRE Decoded\Reproduction\Acris\By Document\2003\01 Jan\23\%' escape '' limit 20` | 180 |
| richmond book and page | `select doc_id, doc_type, recorded, document from reproduction.richmond_fields where book = '8770' and page = '221'` | 180 |
| one instrument | `select doc_id, doc_type from reproduction.richmond_fields where instrument = '48402'` | 182 |
| richmond deeds in 2020 | `select count(*) from reproduction.richmond_fields where doc_type = 'Deed' and recorded between '2020-01-01' and '2020-12-31'` (7,118 rows) | 553 |
| a richmond parcel | `select doc_id from reproduction.richmond where registry @> '{"parcels":[{"bbl":"5001570097"}]}' limit 20` | 184 |

The dynamic proof, the same run: one throwaway row landed with a registry and a document path was found by five of these
shapes within 2.0 s of landing, each by an index scan, then deleted. The indexes are maintained on every insert and update
(the GIN batches new entries in a pending list that queries also search); the lanes' landings are filterable the moment
they land. Only 0006's profile is a snapshot, refreshed on command.

## The profile (0006, 2026-09-06)

login: "the things we'd want to filter on ... are the things found in the registry realistically ... when training a
rounded framework, we need to look at all types of registry scenarios." Two summary tables per source, materialized,
built by scanning the rows once and refreshed on demand: `acris_profile` / `richmond_profile` count documents by type,
borough and year (facet `type, borough, year`), and by each alone, by how many parcels and parties a document carries,
and by its page count, with `with_document` and the fields 0005's functions could not read (`recorded_unparsed`,
`amount_unparsed`, `pages_unparsed`) counted alongside; the `all` row is the whole table. `acris_keys` / `richmond_keys`
count which keys appear at the registry's top level, inside a parcel and inside a party, so an unusual field shows with
its frequency. A model reads the profile first (a few thousand rows) to see the whole variety, then pulls examples of any
shape through 0005's indexes: `select * from reproduction.acris_fields where type = 'DEED' and borough = 'QUEENS' and
recorded between '1995-01-01' and '1995-12-31' and jsonb_array_length(parcels) >= 3 limit 20`. Refresh after a lane has
landed a lot: `refresh materialized view concurrently reproduction.acris_profile` (the unique index on each allows
`concurrently`, so readers are never blocked); a refresh is one scan of the table.

## What a person sees (0007, 2026-09-06)

login: "You have a database, and you have an updating table that shows you how you're progressing on filling in that
database ... the update table shows how workstations are performing and how we're progressing on reproducing. That's
important, but in terms of actually building our own tables for it, it's probably unnecessary ... build it behind the
scenes so you don't see it." The schema `reproduction` holds three tables: `acris` and `richmond`, the record, and
`updates` - source first, then lane, then workstation: a row per source for the phase (`lane = reproduction`, rows with
every cell filled), a row per lane (its cells filled), and a row per workstation running a lane, that machine's own
landed count, rate, workers, `last_seen` (its heartbeat, every minute while it runs) and `last_word`. The heartbeats
tables are gone into those rows. What the code needs and a person never reads - which doc_ids each workstation holds
for which lane, until when - lives out of sight in the schema `machinery`, table `claims`: two machines can only avoid
taking the same document through a list both can see, so the list stays in the cloud, and a landed pending's wait lives
there as before (0004). The functions `claim`, `land`, `heartbeat`, `reconcile` keep their signatures: `land()` moves the
lane's row and the landing machine's own row; `heartbeat()` is the machine's row; `reconcile()` recounts the totals rows
and leaves each machine's count alone. A way to have no list at all - a fixed share of the ids per machine, by a rule in
the code, each machine remembering its own re-check times - is the follow-up if wanted; its cost is that adding or losing
a machine means restarting the others with the new count, where the list rebalances by itself.

## History

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
2026-09-04/05 — `rate_manager.py` added: the three managers as knobs, live on the home workstation since 2026-09-04
19:37 (the night's record: `D:/CRE Decoding System/Reproduction/Acris Reproduction/ACRIS DOCUMENTATION NIGHT
2026-09-04.md`).

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
(Gate 3: `--lanes synchronization:10,registration:20`). Proven offline: `test_one_batch_offline.py` ALL OK (12 checks),
`test_fleet_sim.py` ALL OK on both sites. Not run live: Gate 3, on login's word after the exit reset. The ten live sims
(`test_*_sim.py` under rulebook/ and the sources' rulebooks, `test_lane_policies.py`) still name the tables 0007 replaces
(`<source>_update`, `_update_lanes`, `_heartbeats`, `_claims`): they stay guarded and unrun until reworked for
`reproduction.updates` / `machinery.claims`.

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
