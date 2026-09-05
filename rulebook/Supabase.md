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
    python supabase.py push                apply it, one transaction per file, stop at the first failure
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

## The state

| when | what |
|---|---|
| 2026-09-03 17:01 | schema `reproduction` created by 0001 (ten tables, four functions), applied with the Supabase CLI and recorded in the ledger |
| 2026-09-05 | 0002 (pendings first; documentation claims only where a registry is) pending - applied from here on login's word, see the history |
| until the data move | every table empty; the repo's lanes cannot run for real before the rows are in |

## History

2026-09-05 — Created at the root, from `Reproduction/supabase/` (login: "Isn't that a bit confusing? I have no idea
how this works compared to how we've set up the acris and Richmond folders" · "supabase shouldn't even be in
reproduction … the project gets a supabase folder"). The database is the project's, so its md and program live in the
project's rulebook; each phase keeps only its SQL (`Reproduction/rulebook/schema/`) and its proof (`test_schema.py`).
Retired: the Supabase CLI and its 300-line `config.toml` (settings for a local copy of Supabase we never run),
`db_push.ps1` and `decoded_sql.py` (both folded into `supabase.py`), the folder's README and `SCHEMA.md` (folded into
the phase rulebook's "The table"). The ledger the CLI wrote is kept and shared. Nothing in the database changed with
the move.
