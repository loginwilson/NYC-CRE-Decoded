# THE RULEBOOK

The phase's shared modules: a rule is written once here and every lane of every source on every workstation gets it.
A source's own rules - its URLs minted from the id, its one user-agent, its refusal detector, where its documents file
- live in `<Source>/rulebook/` (`acris.py` · `Acris.md`, `richmond.py` · `Richmond.md`); nothing about one source is
in here. Every module's docstring is its own authority: the rules, the numbers and where each was measured. This file
says what each module is for and how a program reaches it.

| module | job | proof |
|---|---|---|
| `rulebook.py` | THE MACHINERY, one file, six parts in dependency order - storage (where a document lives: the drive by its label, the One Touch tree, the day folders), the three managers (batch / rate / session), cloud (claim, land, heartbeat, the outbox: one round trip each), lane (THE ENTRY every cycle lane shares: one pooled session, staggered births, hang-up, rebatch, re-entry, the park), fleet (the source's lanes together as one program), board (the update board: the counters read once a minute, rates / eta / status written back). A lane does `import rulebook` |
| the README's pip line | the one install a workstation needs: `pip install requests>=2.31 psycopg2-binary>=2.9 img2pdf>=0.5 Pillow>=10` | |
| `supabase/schema.sql` | THE TABLE's definition beside the database program: the whole database as it stands, one file, written from the project itself by `python supabase/supabase.py baseline`; a change is a numbered `supabase/<version>_<name>.sql` applied once with `push`, folded in with `baseline`, removed in the same commit |

## How a program reaches it

Every lane, fleet and board program carries one path line and imports by name:

    PHASE = HERE.parents[2]                           # <lane> -> workflow -> <Source> -> Reproduction
    sys.path.insert(0, str(PHASE / "rulebook"))       # the phase's rulebook: rulebook.py, the machinery as one module
    sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
    import rulebook, acris

A second workstation clones the repo and runs the same file; there is no install step beyond the README's pip line and
the env file (`C:/dev/nyc-cre-decoded.env` at home, `~/nyc-cre-decoded.env` on a Mac, or `NYC_CRE_DECODED_ENV`),
which is never committed or printed.

## The table — as dictated (2026-09-03)

login's organization concept for NYC CRE Decoded, in the words it was given, followed by the mapping onto Supabase, git
and the drive. The SQL files in `supabase/schema.sql` beside this file implement it one dictated decision at a time; nothing is
created that was not dictated. The database as a whole - one project, one schema per phase, the program that applies
these files - is `../../supabase/Supabase.md`.

### The concept

**Supabase** is the database the lane codes feed. A phase (`reproduction`) holds source folders (`acris`, `richmond`). Each source has a *workflow* database that its lanes fill and an *update* database that reads the workflow's progress.

**The four lanes per source.** Enumeration, identification, registration, documentation. Each is its own code, toggled on and off independently, and configurable in width: 1x40, 1x20, 1x80; identification 1x20 beside documentation 1x40; or one entry of 100 split 20 identification, 40 registration, 40 documentation.

- **Enumeration is not part of the reproduction cycle.** It is the first step to get reproduction up, and afterwards an audit: it counts the source (acris: Socrata + CRFN; richmond: census + date/range), compares with the database total, and the difference must be 0. It never touches the cloud database and has no table.
- **Identification** keeps the database live: for acris it sits at the CRFN edge and any CRFN movement triggers an edge walk that populates new ids; for richmond it walks from the last recorded id by date range. One monitor worker, the rest walkers.
- **Registration** acquires the registry information (the recorded details) for each id, using the source rules and a URL minted by the code from the id stem. No navigation step, no URL column.
- **Documentation** does the same for the document itself: minted access, save to the drive, record the path.

**The workflow row** is as simple as `doc id | registry | document`: identification fills the id, registration the registry, documentation the document. (2026-09-05: a `source` column stands in front of the three cells - `source | doc_id | registry | document` - a constant the table enforces, so a cross-source table or view carries the source in every row without a join; login: "knowing acris, richmond, dob now, dof, bis web, etc. is helpful as we expand and link datasets". The two sources keep their own tables.)

**The cell rule.** A lane's outcome lives in the cell that lane fills, and there are exactly two words a cell may hold instead of its fill: `pending` (still being checked; it stays in the backfill until it becomes the fill or `absent`) and `absent` (checked: there is none). Anything but empty counts as landed. The rules for when a cell becomes pending or absent are part of the lane code.

**The path.** Recorded as something that pastes into the file bar and opens the document: the full One Touch path. (2026-09-05, superseding the layout dictated here on 09-03: the One Touch mirrors GitHub and Supabase - `D:\NYC CRE Decoded\Reproduction\<Source>\By Document\<year>\<MM Mon>\<day>\<id>.pdf`, the day folder from the RECORDED date; login: "NYC CRE Decoded -> reproduction -> source -> by document -> by year -> by month -> by day ... the PDFs stay in the OneTouch because Supabase is just for storing the data table". No borough folder.) Two workstations: the second mounts its own drive under the same letter and writes the same layout, so the recorded path opens the file on whichever machine holds it; its documents are transferred into the One Touch before it continues, and nothing in the database changes on transfer. A click-to-open link is not possible for a file on a drive; it would require the PDFs served from the cloud (the corpus is on the order of 20 TB at full size, so that is a real cost, not a schema change).

**The update database** is the board, built cleaner: 60-second and 5-minute rate, increase, percentage and eta, plus landed, needed, percentage of total, the status and the as-of stamp. Three blocks of four rows (0017, 2026-09-07): the totals - reproduction as rows with all three cells filled against rows, each lane as the cells of that lane landed against rows - then workstation 1's four and workstation 2's four, a blank line before each workstation block, source before lane (10 rows, 5 documented = 50 % on documentation). The update code is one program per source that always runs and only reads.

**Two workstations, no overlap (dictated 2026-09-03 16:xx).** "What do we do to assure there's no overlap in what they're pulling?" The table is the only to-do list. A lane never picks its own work: it calls `claim(source, lane, host, n, ttl)`, which hands out a slice of empty cells with the workstation's name and an expiry written on it, atomically (`FOR UPDATE SKIP LOCKED` plus the claims key), skipping anything another workstation holds; two machines asking in the same second get two different slices. Pendings whose cooldown has run out are taken first, then empties, both in id order straight off the partial indexes (no sort) - migrations 0002 and 0004; a landed pending keeps its claim as a cooldown for `pending_age` (`land()`'s fifth argument), so the claims table is the only clock and the workflow tables carry no timestamp. The lane fills its cells with `land()` in batches once a minute, which also drops its claims; a machine that dies leaves claims that expire and go back on the list. Each running lane writes `heartbeat()` once a minute into `*_heartbeats` (one row per lane per workstation); the update program folds those into the lane row (hosts, width, freshest heartbeat, last word). Identification runs on one machine only (two monitors at the CRFN edge would find the same ids); registration and documentation can run anywhere. Claims need the rows in the cloud, so the second workstation joins after the row move; until then the only overlap-free split is the fixed id-range split built 2026-09-02.

**The status follows the lane.** Each lane writes a heartbeat once a minute into its own row of `machinery.updates` (workstation, workers, last seen, its last word) and the board folds it into the lane's update row, so the board can say: `active` = heartbeat fresh and landed rising · `pending` = no fresh heartbeat and not complete (the lane is paused or parked by a person) · `stalled` = the lane's last word is a refusal or a wall (rejected by the source) · `complete` = 100 %. A fetch error never stops a lane; only the notice page does, and a hang-up is redialed.

### The mapping

| concept | Supabase | git | drive |
|---|---|---|---|
| phase | schema `reproduction` | `Reproduction/` (its tables defined in `supabase/`, explained here) | |
| source | table-name prefix `acris_`, `richmond_` | `Reproduction/Acris/`, `Reproduction/Richmond/` (each with its reproduction doc) | `acris\…`, `richmond\…` under the store root |
| workflow database | `reproduction.acris` (source, identifier, registry, document) | `Reproduction/Acris/workflow/{reproduction,enumeration,identification,registration,documentation}/` (reproduction/ is the fleet program and the source's authority) | documents land here |
| update database | `reproduction.acris_update` (three blocks of four rows: the totals, workstation 1, workstation 2) over `machinery.updates` | `Reproduction/Acris/update/` | |
| enumeration | no table | `…/workflow/enumeration/` | |

Postgres has one level of folder above tables, so the phase is the schema and the source sits in the table name; in the Table Editor, choose the schema `reproduction` and the four things a person reads: `acris`, `acris_update`, `richmond`, `richmond_update` (0016, 2026-09-07; the machinery and the reading layer live in their own schemas, `machinery` and `reading`).

### The decisions in the schema

Each was a numbered file, applied once; since 0016 (2026-09-07) they are folded into the one file `supabase/schema.sql` and the ledger keeps the versions. The names below are the versions.

| file | decision |
|---|---|
| `20260903150000_reproduction.sql` | the phase schema; `acris` / `richmond` (doc_id `collate "C"` so index order is id order and range seeks walk the key) with the cell rule as check constraints (JSON or path, `pending`, `absent`); four partial to-do indexes per source (`*_registration_empty/_pending`, `*_documentation_empty/_pending`); `*_claims` (doc_id, lane, host, until; key (doc_id, lane)); `*_heartbeats` (lane, host, width, heartbeat_at, last_event); the functions `claim()`, `land()`, `heartbeat()`, `reconcile()`; `*_update` and `*_update_lanes` (with the folded hosts, width, heartbeat_at, last_event); the lane-status enum; `updated_at` touch trigger |
| `20260903230000_pending_backfill.sql` | pendings first: `claim()`'s sixth argument `pending_age` (its default now 1 hour, was 1 day) offers the pendings due for a re-check before the empties, and documentation claims only rows whose registry is a JSON object; the pending indexes are re-keyed on `updated_at` so the due set is an index range (login 2026-09-03 23:5x, "pending goes back to the backfill") |
| `20260905170000_source_column.sql` | the `source` column first in `acris` and `richmond` (a constant per table, `check (source = 'acris')`, default filled so every insert that names only doc_id still works); the empty tables rebuilt in the dictated order with every rule, index, trigger and comment kept and the claims tables rebuilt for their foreign keys; `doc_id` keeps its name (login 2026-09-05 16:5x: "source, id, registry, document ... separating acris and richmond given they each have their own table") |
| `20260905200000_cooldown_in_claims.sql` | the re-check clock leaves the table: `updated_at` and its touch trigger dropped from `acris` and `richmond`, so a row is `source | doc_id | registry | document` and nothing about when; a pending's wait between two checks is its CLAIM - `land()` keeps a landed pending's claim as a cooldown until now() + `pending_age` (its new fifth argument, default 1 hour) and `claim()` (five arguments now) offers the pendings whose claim is gone, then empties, both in id order off the partial indexes (the pending indexes re-keyed on `doc_id`); the claims table is the schema's only clock and holds only rows in flight or cooling (login 2026-09-05 18:4x: "Does it have to be there? Makes the table less clean") |

**The counting rule (speed).** The board never counts 21.6M rows once a minute. `land()` adds exactly what was new to the lane's `landed` (cells that were empty) and to the phase's `landed` (rows whose other cell was already filled); a pending that becomes a path was already counted and adds nothing. `reconcile(source)` recounts from the primary key and the four partial indexes (index-only scans, seconds on the full table) and overwrites the counters; the update program runs it on demand only (`reconcile`): after the data move, after a hand edit, never on the tick. The 60-second and 5-minute rates are the board's subtraction of `landed` between its own ticks.

Apply a change with the project's program: `python supabase/supabase.py push --dry` shows what would be applied, `push` applies it and records it in the project's ledger; then `baseline` folds it into `schema.sql` and the change file leaves in the same commit. A version already applied is never edited - a new decision is a new change file.

## The proofs

A proof or a simulation lives outside the repo (login 2026-09-07: "all your tests need to go, every single one ... even if you're doing a test, it should wait and then go in once approved that it works"); what it proves goes into the existing file it proves, dated, and the code it approves alters the existing program - never a new file for a small adjustment. The live cloud table is never a proof's fixture: a simulation that must touch the cloud uses throwaway rows and says so in its first line.

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
| deeds in Queens, newest first | `select identifier, recorded, pages, document from reproduction.acris_fields where type = 'DEED' and borough = 'QUEENS' order by identifier desc limit 20` | 207 |
| a year of deeds by recorded date | `select count(*) from reproduction.acris_fields where type = 'DEED' and recorded between '1995-01-01' and '1995-12-31'` (54,581 rows) | 13,282 beside a running profile build; two indexes ANDed |
| long documents | `select identifier, type, pages from reproduction.acris_fields where pages >= 50 order by pages desc limit 20` | 199 |
| amount above ten million | `select identifier, type, amount from reproduction.acris_fields where amount >= 10000000 order by amount desc limit 20` | 200 |
| one crfn | `select identifier from reproduction.acris_fields where crfn = '2003000003997'` | 181 |
| a parcel by bbl | `select identifier, registry->>'type' from reproduction.acris where registry @> '{"parcels":[{"bbl":"1015131008"}]}' limit 20` | 191 |
| a party by name | `select identifier, registry->>'type' from reproduction.acris where registry @> '{"parties":[{"name":"CITY OF NEW YORK"}]}' limit 20` | 311 |
| one day folder | `select identifier, document from reproduction.acris where document like 'D:\NYC CRE Decoded\Reproduction\Acris\By Document\2003\01 Jan\23\%' escape '' limit 20` | 180 |
| richmond book and page | `select identifier, doc_type, recorded, document from reproduction.richmond_fields where book = '8770' and page = '221'` | 180 |
| one instrument | `select identifier, doc_type from reproduction.richmond_fields where instrument = '48402'` | 182 |
| richmond deeds in 2020 | `select count(*) from reproduction.richmond_fields where doc_type = 'Deed' and recorded between '2020-01-01' and '2020-12-31'` (7,118 rows) | 553 |
| a richmond parcel | `select identifier from reproduction.richmond where registry @> '{"parcels":[{"bbl":"5001570097"}]}' limit 20` | 184 |

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
tables are gone into those rows. What the code needs and a person never reads - which identifiers each workstation holds
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
folder"): the two SQL files moved from `Reproduction/supabase/migrations/` to `supabase/schema.sql` here, a proof run before it went in became
a proof run before it went in, the dictated schema (`SCHEMA.md`) became the section "The table" above; the push script, the SQL tool
and the Supabase CLI's config were retired for the project's one program, `supabase/supabase.py` at the root
(`Supabase.md` beside it; the folder was named `rulebook/` for an hour, then for what it holds). 0001's header still names `Reproduction/SCHEMA.md`, its home when it was applied: an applied
file is never edited.

2026-09-05 — the review of every module against its own words (three reviewers, then each finding read in the code): lane.py - the exit-pool check and the fresh batch's claim moved off the main thread and after the wait (a mega lane's crews no longer stall while one waits for the VPN); a retire during a grow now ends the grow; a `stop` in the control file is cleared when acted on and at start; failed ids leave `held`; HTTPStatus keeps its url; the Governor's grow/retire are relative to the live count it reads; `urllib.error` imported; the help strings show each lane's own defaults. fleet.py - exit 3 is a park, never relaunched; `--edge` on a lane's first launch only; a lane the fleet terminates is logged as such; `--stop-wait` 180; the drive help names the real label. board.py - the increase prints with its sign. cloud.py - `pending_age` defaults to 1 hour (migration 0002); one lock per connection. rate_manager.py - a dead attribute removed. The proofs that had lived only in the scratchpad now sit here (a proof run before it went in, a proof run before it went in, a proof run before it went in, a proof run before it went in, a proof run before it went in, a proof run before it went in) and all pass.

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
a proof run before it went in rewritten for the populated table: it inserts its own pendings and claims exactly those, proves the
cooldown, and lands the counters' proof on empty test rows directly.

2026-09-05 19:2x — THE SIMS AND THE POPULATED TABLE. Running the proofs after the 0004 code change, three of them
(a proof run before it went in, a proof run before it went in, a proof run before it went in) turned out to prove the lane loop against the LIVE
cloud with SIM rows - and `claim()` hands out the first empties of the whole table in id order, so on the populated
table they claimed 28 real acris documents (2003030501723001 .. 2005080202430001) in the test host's name. Checked
before anything else: every document cell in the table is a real path or a verdict word (0 odd cells), the counters
never moved (0), no outbox or parked file was left; the 28 claims were deleted (they would have expired by 19:42
anyway). Each of the three now refuses a table that holds anything but SIM rows, before it inserts a row. a proof run before it went in
is the one proof written for the populated table: it inserts its own pendings and claims exactly those.

2026-09-05 20:1x — THE NUL ESCAPE IN A LANDING. The population load met 8,710+ old registries whose JSON carries `\u0000` (a NUL from the source page inside a party name); PostgreSQL's jsonb refuses it (`unsupported Unicode escape sequence`). The new lanes would meet the same character in a fresh registry, and a landing jsonb refuses would fail `land()` forever and sit in the outbox - so `cloud.py` `land()` strips that six-character escape from the landing's JSON before it goes to the table; nothing else is touched. Proven offline on a value carrying a real NUL.

2026-09-05 22:04 — 0004 APPLIED on the populated tables, after the load and its verify (MATCH on both sources, 21:52). The table is `source | doc_id | registry | document`. a proof run before it went in ALL OK on the populated table (22:13, its connections without the statement timeout; the first run's recount was cut at two minutes): its own pendings claimed and nothing real, the cooldown held in the landing host's name for about an hour, an expired cooldown handed out again and the rows still held skipped, the counters moved by what was new, the cell rule and the heartbeats as before.

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
(Gate 3: `--lanes identification:10,registration:20`). Proven offline: a proof run before it went in ALL OK (12 checks),
a proof run before it went in ALL OK on both sites. Not run live: Gate 3, on login's word after the exit reset. The ten live sims
(`test_*_sim.py` under rulebook/ and the sources' rulebooks, a proof run before it went in) still name the tables 0007 replaces
(`<source>_update`, `_update_lanes`, `_heartbeats`, `_claims`): they stay guarded and unrun until reworked for
`machinery.updates` / `machinery.claims`. The schema `reproduction` holds the record and its two boards - `acris`, `acris_update`, `richmond`, `richmond_update` - and nothing else (0016, 2026-09-07); `machinery` holds what the code needs and a person never reads (`claims`, `updates`); `reading` holds the reading layer for products (`acris_fields`, `acris_parcels`, `acris_keys`, `acris_profile` and the richmond four).

2026-09-06 17:1x — GATE 2's THREE MIGRATIONS DONE: 0005 (15:36, proven 15:37: twelve filters every plan an index scan, a landed
row found within 2 s), 0006 (17:07, proven 17:08: four populated profile views, a facet in about 200 ms), 0007 (17:08, proven
17:10: a proof run before it went in ALL OK on the live table - two workstations claiming at once, the cooldown, the counters on the lane row
and the workstation's own row). The key census against the index: every key answers by containment, ranges on the typed
fields; two gaps named and written as 0008 (`schema/20260906150000_lookup_more.sql`): block keys with their own GIN and the
helpers block_key / bbl / parcel that build the key from words ("Manhattan block 573 lot 24" without assembling ten digits),
party names as one text with a trigram GIN (a name by part of it), a typed expiration date, and the parcels views with borough,
block and lot derived. Its functions proven in a rolled-back transaction; the build follows the audit. The proof of 0008 after
the build: `prove_0008_filters` (plans and timings of a block, a lot from words, a partial name, an expiration range, the
parcels view, and a landed row found by block and by part of a name).

2026-09-06 19:4x — GATE 2 CLOSED. 0008 built (the trigram over party names 37 min, 1.9 GB) and proven: a block from words
(`reproduction.block_keys(registry) @> array[reproduction.block_key('MANHATTAN', 573)]`, 522 ms), a lot from words
(`registry @> reproduction.parcel('MANHATTAN', 573, 24)`, 320 ms), an expiration range (1.4 s), a landed row found by all of
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
a proof run before it went in on throwaway rows in a rolled-back transaction, before the push and again after: ALL OK (8 checks); the due
query reads the recorded index and lists 500 in 425 ms. 8,876 real registries are due tonight - gate 3's registration crew
takes them first, then the new documents the sync finds. `--pending-age "1 day"` on the batch.

2026-09-06 21:21 — GATE 3 LEVEL ON BOTH SOURCES (identification + registration). ACRIS: one batch of 30 (sync 10 + registration 20) entered 20:44:28, level 20:54:03 (edge 2026000254029, 8,323 new documents), the 8,876 provisional registries re-read by 21:02 (0 left), one session close 20:57 → the batch-wide hang-up and a re-entry served 20:58:36, registration 21,631,885 / 21,631,885 at 21:21 (Acris Reproduction.md §18). Richmond: level in two minutes (0 new, 0 to register). Richmond documentation (499 pages) parked on CLOUDFLARE'S CHALLENGE in front of the courts host - proven not the code's (the request is the old lane's byte for byte; three UA strings, a bound socket, curl.exe, and a fetcher on a datacenter network with no VPN were all challenged on tokens the clerk had just minted) and not one exit's (login: the VPN was on for the whole 2.5M-page week): the courts host's own posture, on record flipping before (Richmond Documentation.md 21:2x); `richmond.is_challenge()` now parks the lane at once, named. Gate 4 (ACRIS documentation on two workstations) may start on login's word; the 499 richmond pages wait on the courts host - one `--unpark` pull tells when.

2026-09-06 22:00 — RICHMOND DOCUMENTATION LEVEL: 2,502,936 / 2,502,936 (137 pending = scan lag). login's theory proven: every lane stopped at 21:43 (both fleets exit 0), the VPN off, the same documentation code entered on the home line 69.204.251 at 21:57:19 and pulled 536 pdfs in two minutes, 0 fails - Cloudflare in front of the courts host challenges the VPN's exits and serves the residential line; the 21:21 entry's "not one exit" is refuted. THE RULE: richmond documentation on a line WITHOUT the VPN, ACRIS ON it, never both through one machine's tunnel → workstation 2 (the office IP) takes richmond documentation (README, Richmond Documentation.md). GATE 3 IS CLOSED on every lane but ACRIS documentation, which is Gate 4. ACRIS is not relaunched until the VPN is back on (ACRIS never on the home address).

2026-09-06 22:38 — 0010 THE TWO UPDATE VIEWS (`reproduction.acris_update`, `reproduction.richmond_update`): the one updates table cut per source in reading order, for login to open in Supabase (Supabase.md 0010). Gate 4's first document lane: 1x40 entered 22:30:46 on the fresh block 94.20.154 (the tenth notice at 22:15 refused the first request on 45.95.243), 40/40 workers at minute 4, 1,212 pdfs by minute 7 at 3.6-4.1 docs/s, both boards ticking.

2026-09-06 22:45 — 0011: `acris_update` / `richmond_update` are four rows per source (the phase and the three lanes, no workstation column); the per-station rows moved to `acris_workstations` / `richmond_workstations` (Supabase.md 0011). 22:41:48 THE ELEVENTH NOTICE: the 1x40 document lane refused after 11.2 minutes and ~23k requests at 35 req/s on the fresh block 94.20.154 - parked, the board stalled, a person decides (Acris Reproduction.md §18).

2026-09-06 22:5x — 0012: the update views trimmed to what a person reads (four rows; landed / needed / pct, the two blocks, status, as_of); the per-station views carry the machine's own count, rates, workers, status and last word (Supabase.md 0012).

2026-09-06 23:1x — 0013: `as_of`/`last_seen` render in Eastern (`as_of_et`, `last_seen_et`) in the four update views (login's word). 23:11:48 THE TWELFTH NOTICE: the managed 1x40 (band 4-5, held exactly) refused after 11.2 min on the fresh block 135.136.69 - the SAME ~11 min as the eleventh on a different fresh block at a different rate → a per-exit allowance on this VPN provider, not the code/rate/UA (all verified against the proven decoder). The office line (workstation 2) is the discriminator and the path forward; relaunching into fresh VPN blocks stopped.

- **2026-09-07 00:11 — the fourteenth notice; the A/B is closed.** The proven OneTouch lane (1x40 pinned, no manager) served 6.8 min / 26,279 requests / 2,422 pdfs on a fresh VPN block, then the notice. Three fresh blocks tonight fell at 24k / 28.5k / 26.3k requests (2.0-2.7k documents) at 35 / 43 / 64 req/s, in 11.2 / 11.2 / 6.8 min: the meter tonight is a per-exit REQUEST BUDGET on this provider's ranges, not a rate and not the code (old and new meet the same wall). Gate 4 waits on an address, not a change: workstation 2's own line or another provider. See Acris Reproduction.md.

- **2026-09-07 01:10 — 0014 applied:** pct_60s / pct_5m dropped from the two source update views (kept in the table); the views read landed / needed / pct, then rate · increase · eta for 60 s and 5 min, status, as_of_et. Known wart, not fixed yet: the lane flushes landings once a minute or at 200 results and the board ticks once a minute, so the 60-second cell sometimes reads 0 and then double; the 5-minute block is smooth. The fix is a shorter lane flush (15 s / 50 results) at the next natural exit.

- **2026-09-07 01:18 — the fifteenth notice.** The golden-band GitHub run on 89.106.14 was cut at 22.5 min / ~49k requests / ~4,600 pdfs: double the earlier fresh blocks after a longer cooldown, still nowhere near the golden runs. The VPN's exits are throttled for us tonight regardless of code/rate/ramp/band; the sustain test moves to the office line (workstation 2) or to a block held still for hours. Documentation parked; the fleet stilled every lane.

## Access: how the tunnel works and how each source answers it

login, 2026-09-07 06:1x: "We need to figure out the correspondence between how the vpn works and acris access. This is key. Richmond
also had some issues with the vpn." This file is that correspondence, from measurements, in one place. It changes only when a
measurement changes it.

### 1. The tunnel, as measured on the home workstation

| fact | measured |
|---|---|
| where the tunnel sits | in the app on the workstation, below the socket layer: the app keeps a /32 host route to its Lightway server (2.57.171.151 via the Wi-Fi gateway while on 'Brazil'), no virtual adapter is Up, the default route stays the Wi-Fi's, and the lane's sockets bind to the LAN address (192.168.1.168) - yet every byte leaves from the server's block. (First read as a router tunnel; the host route settled it: the app's Lightway driver carries the whole machine, invisibly to netstat.) The server the app connects to and the block the traffic exits from are one block, so the app's server list is the exit list |
| the app's settings, read from settings.json | `automaticTransport = True` (the app may change protocol on its own = a reconnect mid-run), `protocol = udp`, `lightwayTurboEnabled = True` with `lightwayTurboNumberOfTunnels = 1` (turbo on, but one tunnel = one block), split tunnel off. For the lane: Automatic OFF, Lightway UDP fixed, one tunnel |
| every exit the app knows | `C:\Program Files\ExpressVPN\data\data.json` -> `cachedModernRegionsList`: 215 locations, 1,036 server addresses. `python C:\dev\cre-office\exits_map.py` groups them by block, looks every block's owner up (no ACRIS request) and writes exits_map.md: label -> country -> blocks -> owner -> refused / candidate |
| one connection, one address | a new TCP connection is NATed to a random address of the exit's /24: 20 draws in a row gave 11 distinct addresses of 2.57.171.0/24. The lane's 40-80 lines sit on many addresses of ONE block; the block is the unit we can see |
| the app's location name | a label. "Bolivia" exited from Phoenix (GSL Networks). "Bosnia" from Lelystad, Netherlands (Clouvider). "Brazil" from Sao Paulo (Latitude.sh). "Singapore" from GSL Networks, Singapore. The owner of the range, not the city, is what a source sees |
| few owners behind many labels | GSL Networks AS137409 (Singapore, Phoenix, Dallas, Amsterdam, Frankfurt), Datacamp AS212238 (Vienna), Delta Telecom AS29049 (Baku), Clouvider AS62240 (Netherlands), Latitude.sh AS262287 (Sao Paulo) - five owners across nine blocks on the ledger |
| every exit is a known proxy | ip-api flags all nine blocks `proxy: true`, served and refused alike. A public proxy flag is therefore NOT the gate ACRIS uses; ACRIS keeps its own standing per range |
| a switch | re-keys the router's tunnel: every open connection in the house dies at once (the lane's "dead transport"); the next connections come from the new block |
| a pool that spans blocks | five draws in two blocks = the tunnel mid-switch, or a multi-tunnel mode: the lane's lines would go out on two exits. Never launch on it; wait for one block (the exit-pool gate) |
| protocol modes | single Lightway holds one tunnel = one block. "Automatic" may change protocol or server on its own (a reconnect mid-run = dead transport). A dual / turbo mode opens more than one tunnel = lines spread over exits (the spread pool). The lane wants ONE tunnel, held: single Lightway, not Automatic, not dual |

Read the exit before every entry, no source touched:

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
exceeded the bandwidth limits"; for large amounts of data, the City Register's subscription data services, 212-487-6300.

What the allowance buys: ~10.7 requests per numeric-id document, ~5.4 per microfilm (FT_/BK_) document; 415k requests = ~39k numeric
documents in 2.5 h on one exit. Unknown: whether a spent range renews (one request after a rest, on login's word), and a range's
allowance before it is spent (only running shows it).

### 3. Richmond

The clerk's registry pages serve through the tunnel. The courts host that serves the document images sits behind Cloudflare, which
challenges the tunnel's exits (the 403 challenge page; `is_challenge` parks the lane at once). 2026-09-06 21:57: the same code with the
VPN OFF served 536 pdfs in 2 minutes. Richmond documentation runs on a line without the tunnel; a challenge is never solved by code.

### 4. The rules that follow

1. Before an entry: `doc_lane.py exit`. A provider on `spent_providers.json` is not entered. A fresh one gets ONE entry; the first
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

## UPDATE — the phase board

Nothing runs here yet. Each source has its own board today - `<Source>/update/<Source> Update.py`, one program that
always runs and only reads, writing two tabs in Supabase: the phase row of that source (rows with all three cells
filled against rows) and its lane rows (each cell filled against rows), with the 60-second and 5-minute rate,
increase, percent and eta, landed, needed, percent of total, the computed status and the as-of stamp.

The phase board is the same two tabs across every source: one row per source on tab 1, the sources' lane rows on tab 2,
the phase's own total on top. It reads the sources' update tables through a master view - a later migration in
`../supabase/`, after the data move - and `Update.py` beside this file will read that view the way every
board does (`../rulebook/board.py`: one subtraction, every percentage over needed, the four statuses, never a clamp,
never a scan on a tick). Until then this folder holds this file, so the phase has the same three folders a source has.

## History

2026-09-05 — Created as the phase's third folder (login: "rulebook workflow update ... and then you have all the sources
underneath"). The master view is the Supabase step's business, after the GitHub tree is complete.
