# The schema — as dictated (2026-09-03)

This is login's organization concept for NYC CRE Decoded, in the words it was given, followed by the mapping onto Supabase, git and the drive. Migrations under `Reproduction/supabase/migrations/` implement it one dictated decision at a time; nothing is created that was not dictated.

## The concept

**Supabase** is the database the lane codes feed. A phase (`reproduction`) holds source folders (`acris`, `richmond`). Each source has a *workflow* database that its lanes fill and an *update* database that reads the workflow's progress.

**The four lanes per source.** Enumeration, synchronization, registration, documentation. Each is its own code, toggled on and off independently, and configurable in width: 1x40, 1x20, 1x80; synchronization 1x20 beside documentation 1x40; or one entry of 100 split 20 synchronization, 40 registration, 40 documentation.

- **Enumeration is not part of the reproduction cycle.** It is the first step to get reproduction up, and afterwards an audit: it counts the source (acris: Socrata + CRFN; richmond: census + date/range), compares with the database total, and the difference must be 0. It never touches the cloud database and has no table.
- **Synchronization** keeps the database live: for acris it sits at the CRFN edge and any CRFN movement triggers an edge walk that populates new ids; for richmond it walks from the last recorded id by date range. One monitor worker, the rest walkers.
- **Registration** acquires the registry information (the recorded details) for each id, using the source rules and a URL minted by the code from the id stem. No navigation step, no URL column.
- **Documentation** does the same for the document itself: minted access, save to the drive, record the path.

**The workflow row** is as simple as `doc id | registry | document`: synchronization fills the id, registration the registry, documentation the document.

**The cell rule.** A lane's outcome lives in the cell that lane fills, and there are exactly two words a cell may hold instead of its fill: `pending` (still being checked; it stays in the backfill until it becomes the fill or `absent`) and `absent` (checked: there is none). Anything but empty counts as landed. The rules for when a cell becomes pending or absent are part of the lane code.

**The path.** Recorded as something that pastes into the file bar and opens the document: the full One Touch path, `D:\CRE Decoding System\Documents\<source>\<borough>\<year>\<month>\<id>.pdf` (richmond has no borough). Two workstations: the second mounts its own drive under the same letter and writes the same layout, so the recorded path opens the file on whichever machine holds it; its documents are transferred into the One Touch before it continues, and nothing in the database changes on transfer. A click-to-open link is not possible for a file on a drive; it would require the PDFs served from the cloud (the corpus is on the order of 20 TB at full size, so that is a real cost, not a schema change).

**The update database** is the board, built cleaner: 60-second and 5-minute rate, increase, percentage and eta, plus landed, needed, percentage of total, the status and the as-of stamp. Two tabs: tab 1 reads the phase as completion of rows landed against rows (all three cells filled); tab 2 reads each lane as the cells of that lane landed against rows (10 rows, 5 documented = 50 % on documentation). The update code is one program per source that always runs and only reads.

**Two workstations, no overlap (dictated 2026-09-03 16:xx).** "What do we do to assure there's no overlap in what they're pulling?" The table is the only to-do list. A lane never picks its own work: it calls `claim(source, lane, host, n, ttl)`, which hands out a slice of empty cells with the workstation's name and an expiry written on it, atomically (`FOR UPDATE SKIP LOCKED` plus the claims key), skipping anything another workstation holds; two machines asking in the same second get two different slices. Empties are taken first, in id order straight off the `*_empty` index (no sort); pendings only after they have aged (`*_pending` index). The lane fills its cells with `land()` in batches once a minute, which also drops its claims; a machine that dies leaves claims that expire and go back on the list. Each running lane writes `heartbeat()` once a minute into `*_heartbeats` (one row per lane per workstation); the update program folds those into the lane row (hosts, width, freshest heartbeat, last word). Synchronization runs on one machine only (two monitors at the CRFN edge would find the same ids); registration and documentation can run anywhere. Claims need the rows in the cloud, so the second workstation joins after the row move; until then the only overlap-free split is the fixed id-range split built 2026-09-02.

**The status follows the lane.** Each lane writes its own heartbeat into its update row (host, width, a timestamp every minute, its last word), so the board can say: `active` = heartbeat fresh and landed rising · `pending` = no fresh heartbeat and not complete (the lane is paused or parked by a person) · `stalled` = the lane's last word is a refusal (fully rejected) · `complete` = 100 %. A fetch error never stops a lane; only the notice page does, and a hang-up is redialed.

## The mapping

| concept | Supabase | git | drive |
|---|---|---|---|
| phase | schema `reproduction` | `Reproduction/` (with `SCHEMA.md` and `supabase/migrations/`) | |
| source | table-name prefix `acris_`, `richmond_` | `Reproduction/Acris/`, `Reproduction/Richmond/` (each with its reproduction doc) | `acris\…`, `richmond\…` under the store root |
| workflow database | `reproduction.acris` (doc_id, registry, document) | `Reproduction/Acris/workflow/{enumeration,synchronization,registration,documentation}/` | documents land here |
| update database | `reproduction.acris_update` (tab 1), `reproduction.acris_update_lanes` (tab 2) | `Reproduction/Acris/update/` | |
| enumeration | no table | `…/workflow/enumeration/` | |

Postgres has one level of folder above tables, so the phase is the schema and the source sits in the table name; in the Table Editor, choose the schema `reproduction` and the six tables are the whole picture. A non-public schema must be exposed under Project Settings → Data API before the REST layer can read it; direct SQL needs nothing.

## Migrations

| file | decision |
|---|---|
| `20260903150000_reproduction.sql` | the phase schema; `acris` / `richmond` (doc_id `collate "C"` so index order is id order and range seeks walk the key) with the cell rule as check constraints (JSON or path, `pending`, `absent`); four partial to-do indexes per source (`*_registration_empty/_pending`, `*_documentation_empty/_pending`); `*_claims` (doc_id, lane, host, until; key (doc_id, lane)); `*_heartbeats` (lane, host, width, heartbeat_at, last_event); the functions `claim()`, `land()`, `heartbeat()`, `reconcile()`; `*_update` and `*_update_lanes` (with the folded hosts, width, heartbeat_at, last_event); the lane-status enum; `updated_at` touch trigger |

**The counting rule (speed).** The board never counts 21.6M rows once a minute. `land()` adds exactly what was new to the lane's `landed` (cells that were empty) and to the phase's `landed` (rows whose other cell was already filled); a pending that becomes a path was already counted and adds nothing. `reconcile(source)` recounts from the primary key and the four partial indexes (index-only scans, seconds on the full table) and overwrites the counters; the update program runs it on demand only (`reconcile`): after the data move, after a hand edit, never on the tick. The 60-second and 5-minute rates are the board's subtraction of `landed` between its own ticks.

Apply with `Reproduction/supabase/db_push.ps1` (reads `C:\dev\nyc-cre-decoded.env`, never prints it); `-Extra --dry-run` shows the plan first.
