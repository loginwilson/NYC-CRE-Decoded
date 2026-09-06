# THE DATABASE

One Supabase project, **NYC CRE Decoded** (East US), holds every table the process fills, and this folder is how the
repo reaches it. The mapping is one for one with the tree:

| the tree | the database |
|---|---|
| the project (this repo) | the project |
| a phase (`Reproduction/`; later `Construction/`, `Production/`) | a schema (`reproduction`; later `construction`, `production`) |
| a source (`Reproduction/Acris/`) | a table prefix (`reproduction.acris`, `reproduction.acris_update`, …) |
| a lane (`Acris Documentation.py`) | a cell (`document`) |

**What the database does and does not do.** It never computes the process. The workstations do the work - fetching,
parsing, saving a document; later, reading one on a GPU - and the database does two small things per document: it
hands out a claim and accepts a landing, both index lookups. It holds the tables: the shared to-do list two
workstations draw from without overlap (`claim`), the boards (`*_update`, `*_update_lanes`) and the heartbeats. The
documents are never in it; they live on the One Touch and a cell holds the path. So the plan's included compute is
sized for it, and what it costs is disk (login 2026-09-05: "all the compute is outside of supabase and supabase is
just storage of a data table").

**Where each phase's schema lives.** In that phase's rulebook, as numbered SQL files -
`<Phase>/rulebook/schema/<version>_<name>.sql`, one file per dictated decision, applied once and never edited after; a
new decision is a new file. The phase's rulebook md explains its table in the dictated words
(`Reproduction/rulebook/Rulebook.md`, "The table"). The program beside this file applies the files and records each in
the project's ledger, `supabase_migrations.schema_migrations` - the table the Supabase CLI writes too, so the one file
the CLI applied (0001, 2026-09-03) and every file applied from here sit in one record.

## The program

    python supabase.py check               the server, the schemas and their tables, every SQL file on disk against the ledger
    python supabase.py push --dry          what would be applied, in version order; nothing runs
    python supabase.py push                apply it, one transaction per file, stop at the first failure; a file whose first line says
                                           `-- statement by statement` runs each statement on its own (index builds; CONCURRENTLY)
    python supabase.py sql -c "select 1"   a statement; -f file.sql a script; --dry prints only; every run logged to supabase.log beside this file

Credentials live in the env file (`C:/dev/nyc-cre-decoded.env` at home, `~/nyc-cre-decoded.env` on a Mac, or the path
in `NYC_CRE_DECODED_ENV`): `SUPABASE_DB_URL` (Connect › Session pooler › URI; the direct host is IPv6-only and does not
resolve from home) and `SUPABASE_DB_PASSWORD`. Never committed, never printed. The lanes reach the same database
through `Reproduction/rulebook/cloud.py`, which reads the same file.

## The cost (read 2026-09-05 from supabase.com/pricing and the compute-and-disk guide)

| | |
|---|---|
| Pro plan | $25 / month per organization; includes 8 GB disk, Micro compute (1 GB RAM), 250 GB egress, daily backups |
| disk beyond 8 GB | $0.125 per GB per month; grows as it fills, never shrinks |
| compute steps | Small $15 (recommended to 50 GB) · Medium $60 (to 100 GB) · Large $110 (to 200 GB) - recommendations for apps serving users, not requirements; billed hourly, can be raised for a bulk job and lowered after |
| the free plan | 500 MB - cannot hold the reproduction table |

Reproduction: about 24 million rows (21.6 M acris, 2.5 M richmond), three cells, the registry JSON the only bulk - 30
to 50 GB, about $30 a month on the included compute. Construction: more rows, small typed ones with evidence pointers,
storage of the same order; its compute is the GPU machine, not the database. The rule for what lives where: the
database holds what more than one machine or person must read or write; the drive holds what one machine builds and
reads in bulk, and the documents.

## The program's connection

`supabase.py` connects through the session pooler with TCP keepalives and **no statement timeout**: the project's default
is two minutes on the `postgres` role (`show statement_timeout`), enough for a lane's claim or landing and too short for
a migration that builds an index over the populated table or for a count over it. The population program does the same
(`pg_connect()` in `Reproduction/workflow/population/Population.py`); the lanes keep the default - their statements are
small, and a lane that waits two minutes on the table has something else wrong.

## The state

| when | what |
|---|---|
| 2026-09-03 17:01 | schema `reproduction` created by 0001 (ten tables, four functions), applied with the Supabase CLI and recorded in the ledger |
| 2026-09-05 15:55 | 0002 (pendings first; documentation claims only where a registry is) applied from here with `push` and recorded in the ledger; `test_schema.py` ALL OK on the empty table after it |
| 2026-09-05 15:55 - 17:59 | every table empty (verified 15:55: 0 rows, 0 claims, 0 heartbeats per source; the board rows in place - one phase row and three lane rows per source); the repo's lanes cannot run for real before the rows are in. READY TO RECEIVE: the cell rules as check constraints, the four to-do indexes per source (pendings keyed on `updated_at`), `claim` with its six arguments, `land`, `heartbeat`, `reconcile` |
| 2026-09-05 17:0x | 0003 applied: `source` first in `acris` and `richmond` (`source | doc_id | registry | document | updated_at`); test_schema ALL OK on the empty tables |
| 2026-09-05 17:59 - 21:10 | THE DATA MOVE (`Reproduction/workflow/population/Population.py load`): 24,126,063 rows by COPY from `Legal Instruments.db` - acris 21,623,562, richmond 2,502,501 - zero rejects; 19,095 registries noted for a stripped NUL escape (jsonb cannot hold `\u0000`); database about 23 GB on the 40 GB disk |
| 2026-09-05 21:16 - 23:32 | `apply-found` twice (233,381 then 119,633 more acris cells filled with placed documents' paths - 353,014, every document the old stores gave the tree) and `verify` twice: MATCH on both sources each time, every cell state equal to the old table's shifted by the placements; acris path sample 200 of 200 on the drive; richmond 9 then 35 of 200 while its file move runs (the cells lead the disk until it ends) |
| 2026-09-05 22:04 | 0004 applied with `push` after the load and `verify` (the column drop takes the table's lock; the two acris pending indexes were rebuilt over 21.6M rows, about seven minutes each): `updated_at` and its trigger gone, a row is `source | doc_id | registry | document`, a pending's wait between checks is its claim; test_schema.py ALL OK on the populated table (22:13, its connections without the statement timeout; the first run's recount was cut at two minutes) |

## History

2026-09-05 — Created at the root (first as `rulebook/`, renamed `supabase/` the same hour - login: "should rule book just be supabase?" - the folder is named for the one thing it holds), from `Reproduction/supabase/` (login: "Isn't that a bit confusing? I have no idea
how this works compared to how we've set up the acris and Richmond folders" · "supabase shouldn't even be in
reproduction … the project gets a supabase folder"). The database is the project's, so its md and program live at the
root; each phase keeps only its SQL (`Reproduction/rulebook/schema/`) and its proof (`test_schema.py`).
Retired: the Supabase CLI and its 300-line `config.toml` (settings for a local copy of Supabase we never run),
`db_push.ps1` and `decoded_sql.py` (both folded into `supabase.py`), the folder's README and `SCHEMA.md` (folded into
the phase rulebook's "The table"). The ledger the CLI wrote is kept and shared. Nothing in the database changed with
the move.

2026-09-05 15:55 — The connect step (login: "make the necessary fixes to git hub so we can then move into supabase and assure the
reproduction table is ready for receiving"): `push` applied 0002 - the first file applied from here - and recorded it beside the
CLI's 0001; `check` shows both applied; the proof ran ALL OK against the live, empty table (two hosts claim disjoint slices, the
counters move by what was new, a wrong cell word is refused, heartbeats land, cleanup leaves nothing). The plan must be Pro
before the data move (the free plan's 500 MB cannot hold the table; the database is 11 MB today). Next, on login's word: the
data move (Legal Instruments.db → `reproduction.acris`, every lane paused) - populate is the last step of the sequence.

2026-09-06 11:48 — THE ONE-TRANSACTION INDEX BUILD BROUGHT THE INSTANCE DOWN. 0005 (sixteen indexes over the two
tables) was pushed at 11:36 as one transaction, as every file before it; twelve minutes in, during the second index,
the Micro instance (1 GB, shared with Supabase's own services) ran out of memory and Postgres restarted at 11:48:42
(15:48:42 UTC): the transaction rolled back, the first index with it, nothing recorded, no row touched. The push program
now runs a file whose first line says `-- statement by statement` one statement at a time in autocommit, each index its
own transaction, so a crash costs one index and a re-run skips what exists (`if not exists`); 0005 carries the marker,
the instance's default build memory (64 MB) and `max_parallel_maintenance_workers = 0`. The dashboard was unreachable
for about a minute; a compute of Small (2 GB) is the safer instance for a build of this size.

2026-09-06 12:13 — THE SECOND RESTART, STATEMENT BY STATEMENT. The push re-run at 12:04 (hidden window; a first re-run's
client had vanished at 12:00 while the server finished its index - the statement-by-statement shape held: acris_type stood
committed, 146 MB, and the re-run skipped it) built acris_borough, acris_recorded and acris_doc_date in 160 s each (144-148
MB each; the type index of 21.6 million short values is a tenth of the 1 GB estimated) and one minute into acris_pages the
instance restarted again (16:13:25 UTC). Four indexes stand committed; the client hung on the pooler's dead socket and was
stopped. Two restarts in 25 minutes, both under a sustained index build, with the default 64 MB of build memory and no
parallel worker: the Micro instance (1 GB, shared with Supabase's own services) is not enough for a build of this size.
The build waits for a Small instance (2 GB) - login's setting - and resumes where it stands (`push` skips what exists).

2026-09-06 12:36 — THE THIRD RESTART, AND WHAT THE LOG SAYS. The push resumed on a Small instance (2 GB; login's
setting, 12:33) and two minutes into acris_pages the instance restarted again (16:36:28 UTC). The Postgres log, read by
login: before each of the 12:13 and 12:36 restarts there is no "out of memory" and no "terminated by signal" - the log
simply stops and resumes with "database system was interrupted; last known up at ...": the whole server was killed from
outside, by the platform, not by a Postgres error (the 12:32 stop is the compute change, a clean "fast shutdown request").
Reading: Micro and Small run on a burstable disk (about 87 and 174 MB/s baseline, a daily budget of bursting above it),
an index build reads the 18 GB table at 125 MB/s or more for minutes at a stretch, and today had forty minutes of that
after last night's verify scans; an instance that stops answering under the load is restarted. The remedy is pacing:
`push --rest 600` rests ten minutes after every statement that ran ten seconds or longer, and the remaining twelve
statements of 0005 (then 0006's nine) are built one at a time, the first watched as the test, after a half hour's rest;
if a paced build dies, the rest goes overnight. Nothing in any row was touched by any restart; four indexes stand.

2026-09-06 13:1x — 0007 WRITTEN AND PROVEN, TO BE APPLIED AFTER THE BUILDS. The reproduction schema will show three
tables - acris, richmond, updates - and the claims will sit in the schema `machinery`. The whole migration ran inside one
transaction on the live project and was rolled back: 12 updates rows carried over (8 totals, 4 workstation rows from the
heartbeats), 96 claims carried, then a heartbeat, a claim of one, a landing as pending (the cooldown), a landing as absent
(released; the lane row and the machine's row each +1), reconcile - and nothing kept. `push` applies it in order after
0005 and 0006; the code that reads and writes the new table (cloud.py, board.py, the update programs, Population.py's
verify, test_schema.py) is committed with it.

2026-09-06 13:18 — THE FOURTH RESTART, AND THE INDEX THEY SHARE. The paced push (`--rest 600`, launched 13:16 after a
half hour's rest, on Small) restarted the instance two minutes into acris_pages (17:18:35 UTC). Three of the four restarts
- 12:13 on Micro, 12:36 and 13:18 on Small - came one to two minutes into that same index, while the three indexes before
it (borough, recorded, doc_date) had built back to back in 160 s each without trouble, which rules out the disk's budget as
the reading and points at the index itself. `whole_number` (pages) and `us_money` (amount) were the two functions written
in SQL with a regular expression evaluated per row; `us_date`, plpgsql without one, built twice. Both are now plpgsql
without a regular expression (the 13 cases pass unchanged), committed as df253e4; the push re-creates them (statements 4
and 5, `create or replace`) before it reaches the pages index again. The 11:48 restart, four minutes into borough on Micro
with 128 MB of build memory and a parallel worker, stays read as memory.

2026-09-06 15:36 — 0005 APPLIED AND RECORDED (`push --rest 60`, statement by statement, on the Small instance, no restart
since 13:18). The index functions rewritten without regular expressions (13:3x) were the cure: the builds that had killed the
instance four times ran through. Build times: acris_amount 183 s, acris_crfn 199 s, acris_registry (GIN, jsonb_path_ops over
the whole registry) 5,332 s = 89 min, acris_document 156 s; richmond_doc_type 19 s, richmond_recorded 18 s, richmond_book_page
22 s, richmond_instrument 18 s, richmond_amount 20 s, richmond_registry 94 s, richmond_document 23 s; the two views instant;
analyze 10 s + 9 s. Sizes: acris_registry 4,066 MB, acris_amount 472 MB, acris_crfn 415 MB, acris_document 389 MB, the other
acris field indexes 143-148 MB each; richmond_registry 314 MB, richmond_document 272 MB, its field indexes 17-54 MB. The
database is 29 GB (acris with its indexes 26 GB, richmond 2.9 GB). PROVEN 15:37 (prove_0005_filters, read-only but for one
throwaway row): twelve filters a person or a model would write - deeds in Queens newest first, a year of deeds by recorded
date, pages >= 50, amount >= ten million, one crfn, a parcel by bbl and a party by name through containment on the whole
registry, one day folder by the document cell, richmond book and page, one instrument, deeds in 2020, a parcel by bbl -
every plan an index scan, never the table; 173-311 ms each on the pooled connection (the year-of-deeds COUNT over 54,581
rows took 13 s while 0006's profile was scanning the table beside it). THE DYNAMIC PROOF (login: "as soon as the file comes
in, will it fall into that index?"): one throwaway row landed with a registry and a document path was found by the typed view
(type + borough + crfn; amount + pages), by containment on its parcel and on its party, and by its day folder, each by an
index scan, within 2.0 s of landing; then deleted (0 left). The indexes are maintained on every insert and update: nothing
is a snapshot but 0006's profile, which refreshes on command.
