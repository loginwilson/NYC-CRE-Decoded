# POPULATION — the move into the new homes (2026-09-05)

> The phase's record had two old homes on the One Touch: `Legal Instruments.db` (one table, `navigation`, both sources
> mixed by id) and the acquisition store's `By Document` tree (both sources' PDFs mixed, plus older documents left in
> `By Parcel` and `By Party`). This program moves both, once, into the homes the process has now: the cloud tables
> `reproduction.acris` and `reproduction.richmond`, and the One Touch tree that mirrors GitHub and Supabase. `Population.py`
> beside this file is the program; this file is its authority.

## The law it serves (login 2026-09-05)

- **The PDFs stay on the One Touch.** Supabase is the table only. "Very, very, very important ... We don't put the PDFs
  anywhere else."
- **The tree mirrors GitHub and Supabase:** `D:\NYC CRE Decoded\Reproduction\<Source>\By Document\<year>\<MM Mon>\<day>\<id>.pdf`.
  "You go to Acris, then you see By Documents. You go in, then you see By Year, then By Month, then By Day. You click on
  that, and you see all the documents that fall into that day." The day folder comes from the recorded date, else a
  digital id's own date, else the id split - the old lane's rule kept exactly (`../../rulebook/storage.py`), so the moved
  tree keeps every folder it had.
- **The cell holds the full path** a person pastes into the File Explorer bar. The old table's cells started at
  `By Document`; every cell written here is the whole path. The Windows form (`D:\...\29\RC_1900390.pdf`) is the path;
  `file:///D:/...` is only how a browser displays it.
- **Workstation 2 writes the same paths** for files on its own drive until the transfer; nothing in the table changes on
  transfer.
- **Nothing is deleted by this program.** Duplicates are counted and left in place; what has no home is logged; the
  removal of empty old folders and of anything else on the drive is a person's step after `verify`.

## The eight commands

    python Population.py survey              read the old table once, in id order: rows per source, the words in each cell, the path shapes; writes population.survey.json only
    python Population.py organize [--dry]    the One Touch tree (below); every move to population.moves.jsonl; --dry counts and moves nothing
    python Population.py load [--limit N]    the rows into both cloud tables by COPY, --slice 50,000 per transaction, routed by the id, resuming after the last id in either table
    python Population.py apply-found         the paths organize found for documents the table had no file for, into cells that are empty / pending / absent (never over a path); then reconcile - runs any time after load and again as the placement goes on
    python Population.py verify              counts on both sides by cell state, a sample of recorded paths opened on the drive, a sample of registries compared value for value with the old table (--registry-sample 2000), reconcile() per source, the board rows; --only samples runs the two samples alone
    python Population.py sweep               every file in both trees by directory listing: an empty file, or a small file that is not a whole PDF, is a stub - listed in population.sweep.jsonl with the other copies the moves log knows for that id; reads only
    python Population.py resolve [--dry]     the duplicates the file move met at a destination, and the stubs sweep listed, decided by the files: identical copies and other renderings staged, a stub replaced by its whole copy; the cell untouched; nothing deleted (below)
    python Population.py audit               GATE 1 (login 2026-09-06): every row of the old table against the cloud, both walked in id order at once - every id present, none invented, every registry the same JSON value, every document cell what the mapping says; the classes counted in population.audit.json, the first differences named; reads only

Run in that order; `apply-found` and `verify` may be repeated; `sweep` then `resolve` run after the file move has ended, and `verify` once more after them. `load` refuses to start while the survey names a word without a
mapping (fail closed), and warns when `organize` has not run for real, since the paths it writes assume the new tree. Launch
`load` with its output on disk: `python -u Population.py load > population.load.log` (PowerShell: Start-Process with
-RedirectStandardOutput) - a refused slice and its reason are otherwise invisible.

## The cell mapping (old → new), the same for both sources

| old `navigation` | new cell | note |
|---|---|---|
| `id` | `doc_id` | text; byte order on both sides (SQLite BINARY = Postgres `collate "C"`), so a resume after the last id is exact. `RC_` ids go to `richmond`, every other id to `acris` |
| `recorded_details` = `''` | `registry` NULL | registration's to-do |
| `recorded_details` = `{…}` | `registry` (jsonb) | the recorded details as the old lane landed them |
| `pdf` = `''` | `document` NULL | documentation's to-do - unless `organize` found the document in an old store and placed it: then `apply-found` writes the new full path |
| `pdf` = `pending` / `absent` | the same word | the cell words, unchanged |
| `pdf` = `imageless` | `absent` | the old lane's word for "the source has no image": checked, none |
| `pdf` = `By Document\…` | `D:\NYC CRE Decoded\Reproduction\<Source>\By Document\…` | the full path, the tree as `organize` leaves it |
| anything else | - | the survey names it; `load` refuses until it has a mapping |
| `rd_url`, `pdf_url`, `keyed_by`, `key` | dropped | every URL is minted from the id; the parcels are inside the registry |

A slice the database refuses is retried row by row: the rows that pass load; a row that fails is written to
`population.rejects.jsonl` with the reason and loaded with the failing cell EMPTY, so the lane that owns the cell fills it
again. Nothing dropped, nothing invented.

## What `organize` does to the drive

1. `D:\NYC CRE Decoded\Reproduction\Acris` and `\Richmond` are created.
2. The old store's `By Document` tree is **renamed** under `Acris` - one rename on the same volume, instant, every folder and
   file untouched inside.
3. Richmond's files (every `RC_` row with a path) are moved file by file from `Acris\By Document\…` to
   `Richmond\By Document\…`, keeping their day folders; a file missing on disk is logged as `missing` (the table claimed
   a file that is not there - reported, never invented).
4. The documents in `By Parcel` and `By Party` (files named `YYYY-MM-DD_<id>.pdf`) are placed by the table: a document
   the table already has a file for is a **duplicate** and stays where it is (counted); a document the table has no file
   for is **placed** into `By Document` by its recorded date and remembered in the moves log and `population.found.json`,
   which `apply-found` uses to fill that cell; a document whose recorded file is missing is **restored** to that place; an id not in the table is
   logged and left.
5. Folders under `Acris\By Document` left empty by the richmond move are removed (empty folders only).

Preconditions: no old lane process runs (the old `acris_reproduction.py` and its supervisor write into the old tree -
stopped 2026-09-05 17:0x, never to run again; the repo's lanes replace them), and nothing holds a file open inside the
tree (the rename fails with "in use" otherwise - Explorer windows on the folder included).

## What `sweep` and `resolve` do (2026-09-06)

The file move met 65 files already at their destinations (09:40): the old lane had pulled some documents twice, and on
2026-08-18 22:0x it saved stubs - error pages of 2-7 KB, one empty file - under ids it re-pulled whole a week later into
the other tree. The cell names the destination, so the destination must be the document. `resolve` decides each pair by
the files, never by the name: identical bytes - the second copy is staged; the destination not a whole PDF (no `%PDF-` at
the start, or no `%%EOF` in the last 64 bytes) and the other copy whole - the stub is staged and the whole file moved into
its place, the cell untouched and now right; both whole and different (two renderings from two pulls) - the cell's file
stays, the other is staged; neither whole - reported, nothing moved, the cell needs its lane. `sweep` finds the stubs the
move never met: it walks both trees by directory listing (the size comes with the listing; no file at or above 16 KB is
opened - the old lanes wrote `.part` and renamed on completion, so a cut download never wore a `.pdf` name) and lists
every empty file and every small file that is not a whole PDF, with the other copies the moves log knows for that id;
`resolve` then treats each listed stub the same way, and names the stubs that have no whole copy anywhere (their cells
need the documentation lane). Staged copies go under `D:\Ignore\Staged by population\<why>\<origin path>` - `duplicate`,
`other rendering`, `stub` - for a person to delete with the rest of `D:\Ignore`. Nothing is deleted.

## The audit (gate 1, 2026-09-06)

login: "we shouldn't start any lanes until we know the database is 100% accurate and didn't miss a thing." The counts
matched and the samples matched; the audit is the whole. `audit` walks the old table (`select ... order by id`) and the
two cloud tables (acris, then richmond - the old table's own byte order: digits, `BK_`, `FT_`, `RC_`) at the same time,
streamed, and for every id asks: present on both sides; the registry the same JSON value (jsonb keeps values, not key
order or spacing; the NUL escape set aside as `map_registry` does); the document cell exactly what `map_document` gives
for the old cell, with the found map for the documents the old stores gave. An id the cloud has and the old table never
had is a row a lane landed after the load, counted and named, not a defect. The verdict is EXACT or DIFFERENCES, with
every class counted and the first differences named; it costs one read of each side, about half an hour, and no lane
starts before it says EXACT.

## The disk

Supabase grows a disk on its own only four times in a rolling 24 hours (at 90%, by 50%) and puts the project into
read-only mode at 95% once that is spent. The rows are about 20-25 GB (the registry JSON is 0.4-0.8 KB per row), so the
disk is set by hand above that in Project Settings › Database before `load` - 40 GB asked for, room for the lanes' landings.

## History

2026-09-05 — Written for the night's job (login: "get everything onto the cloud so we can start experimenting with those
dual station pulls"; "make sure it is done right please since this database is a big deal"). Facts read before writing:
`navigation` holds 24,126,063 rows - digital 11,586,986 · BK_ 1,721,172 · FT_ 8,315,404 · RC_ 2,502,501; the old paths hang
from `D:\CRE Decoding System\02 Acquisitions\Legal Instruments Acquisition\` (two sample files opened there); By Parcel
holds 3,289 PDFs and By Party 14,730, named `YYYY-MM-DD_<id>.pdf`. The survey's and organize's numbers are appended here
when they are in.

2026-09-05 17:4x — THE FOURTH AND FIFTH OLD STORES. `D:/Ignore` (900,061 files, 920 GB - the framework tree from before
08-19, which the clean-up list had marked as space to reclaim) holds two more stores of documents: `Acquisition by parcel`
(520,447 files named `YYYY-MM-DD__<id>__TYPE__reel-page.pdf`) and `Documents` (379,538 files named `<id>.pdf` under `20/`,
`BK/`, `FT/`, `_acqtest/`, `_boundary/`). A sample of 3,000 against the old table: 2,790 documents the table shows as never
fetched (empty cell), 210 duplicates of files already in By Document, none unknown to the table. So `organize` places all
four stores, and nothing in Ignore is removed before its counts are read. The tree rename ran at 17:40:50 (one operation,
102 year folders); the placement of the old stores started at once, about 100 documents a second, richmond's files after
it. The disk was set to 40 GB by login at 17:4x (from 2 GB, +$4 a month).

2026-09-05 17:57 — THE SURVEY (24,126,063 rows in 4,176 s, every word accounted for). Document cells: 5,699,987 paths into
By Document (acris 3,207,346 · richmond 2,492,641), 18,241,681 empty (richmond 64), 174 pending (all richmond), 9,622
absent (all richmond), 156,583 `imageless` (all acris; mapped to `absent`: the old lane's word for "the source has no
image"), and 18,016 cells pointing INTO `By Party\<name>\YYYY-MM-DD_<id>.pdf` - the old store organize places by the table,
so those cells are to-dos until `apply-found` writes the new full path. Registry cells: 24,125,999 objects, 64 empty, no
verdict words. The richmond side was counted through the RC_ band of the primary key (its 2,502,501 rows add up exactly);
the acris side is the totals minus richmond. The load started 17:59:10: 50,000 rows per transaction, about 1,550 rows a
second, 1 KB a row in the database (about 24 GB when done), zero rejects in the first 250,000.

2026-09-05 19:44-19:58 — THE REFUSED SLICE AND THE NUL ESCAPE. At 19:44 the slice after `BK_8140137700677` was refused
and the loader fell into its row-by-row retry: one COPY and one commit per row, 1.2 rows a second - eleven hours for the
slice - and its log was invisible (the launch had not kept its output). The retry is now a HALVING: a refused set of rows
is split in two and each half tried, so a bad row is found in about sixteen round trips and a passing refusal costs two;
the leaf keeps the rule (the row goes to `population.rejects.jsonl` with the reason and lands with the failing cell empty,
the cell read from the whole error text; a row that still fails is written NOT LANDED and the load goes on). The reason,
seen once the log was on disk (`population.load.log`): `unsupported Unicode escape sequence` - a 1968 microfilm registry
(`FT_1000008448800`, a party name ending in `\u0000`) carries the JSON escape for NUL, which PostgreSQL's jsonb cannot
hold; the old lane had kept the character from the source page. `map_registry` now strips that six-character escape and
`cell_rows` notes every such row in the rejects file (`nul escape stripped from the registry`, with the count), so the
one unrepresentable character is the only thing lost and every modified row is on record. Proven on the real row before
the restart (the raw text carries the escape once; the mapped text parses and carries none). The load resumed 19:58:34
after `FT_1000008448700` - the halving had landed a contiguous prefix in id order, so the resume was exact - and the
first slice passed at 1,861 rows a second; the stretch of FT_10000084xx rows carries the escape in more than a thousand
registries (all noted). Also: the start-up row count is the planner's estimate now (a full count of the populated
table is minutes of IO on the small compute, and it was only a log line), and `load` is launched with its output on
disk (`python -u Population.py load` with stdout to `population.load.log`).

2026-09-05 21:10 — THE LOAD IS IN. `load` read the old table to its last id (`RC_999999`) at 21:10:16: 24,126,063 rows in
two runs (17:59-19:44 and 19:58-21:10, about 2,300 rows a second each; the gap is the refused slice above), ZERO rows
rejected, 19,095 registries noted for a stripped NUL escape, the one 19:57 reject line superseded by the restart. The
placement (`organize --only old`) was suspended 20:24-21:53 so the load had the One Touch to itself (a table lookup and a
rename per file had the drive's queue at 3.8 and the load down to 500 rows a second; alone, the load ran at up to 3,300).

2026-09-05 21:16-21:27 — APPLY-FOUND: 233,381 acris cells filled with the full path of a document placed from an old
store, 0 cells that already held a different path; richmond's one found file (restored) already had its cell. The first
attempt (21:11) was cancelled by the project's two-minute statement timeout on one UPDATE over the whole join; the
population's connection now runs without a statement timeout (`pg_connect()`) and the update goes in chunks of 5,000 by
the primary key. `reconcile`: acris phase 3,597,310 / 21,623,562, registration 21,623,562, documentation 3,597,310;
richmond phase 2,502,437 / 2,502,501, registration 2,502,437, documentation 2,502,437.

2026-09-05 21:52 — VERIFY: MATCH ON BOTH SOURCES. acris: rows 21,623,562 | document empty 18,026,252 · pending 0 ·
absent 156,583 · path 3,440,727 | registry object 21,623,562, empty 0 - every number equal to the old table's, with
apply-found's 233,381 cells moved from empty to path and the 156,583 `imageless` read as `absent`. richmond: rows
2,502,501 | document empty 64 · pending 174 · absent 9,622 · path 2,492,641 | registry object 2,502,437, empty 64.
Registry over both sources: 24,125,999 objects, 64 empty - the survey's totals. Paths on the drive: acris 200 of 200
sampled cells open a file; richmond 9 of 200 - EXPECTED, not a defect: richmond's files still sit under
`Acris\By Document` until the file move (`organize --only richmond`) carries them to `Richmond\By Document`; the cells
already say where each file will be, and the move runs after the old-store placement, overnight. The first verify
(21:27) hung on a cloud connection that had died under it (no keepalive; no session for it on the server); the
population's connection now asks for TCP keepalives and `found_shift` redoes a chunk on a fresh line. The old table
`Legal Instruments.db` is now a copy: the cloud is the record.

2026-09-05 22:49 — THE OLD STORES ARE PLACED. `organize --only old` read all four stores (By Parcel, By Party, Ignore's
`Acquisition by parcel` and `Documents`; 17:40-22:49 with the pause 20:24-21:53): 353,012 documents placed into
`Acris\By Document` by their recorded date, 63 restored to the place their cell already named (the file had been missing
there), 556,658 duplicates left in place, 0 files unknown to the table, 0 unreadable names; the found map holds 353,014.
What remains in the four old stores is therefore duplicates only - files the tree already has - and can go on login's
word. `organize --only richmond` began at 22:49: richmond's 2.49 million files move one by one from `Acris\By Document`
to `Richmond\By Document`, about 75 files a second on the One Touch (a rename is a metadata write on a USB disk), so it
runs into the morning; the richmond cells already name the destination.

2026-09-05 22:59 — APPLY-FOUND, SECOND PASS: 119,633 more acris cells filled (353,014 in all - every document the old stores gave the tree now has its path in its cell), 0 cells that held a different path; richmond 0 (its 63 restored files' cells already named the place). Run again after any later placement: the command is idempotent.

2026-09-05 23:32 — VERIFY, SECOND PASS: MATCH ON BOTH SOURCES with every placed document in its cell. acris: rows
21,623,562 | document empty 17,906,619 · pending 0 · absent 156,583 · path 3,560,360 (the old table's 18,259,633 empties
less the 353,014 placed; its 3,207,346 paths plus the same) | registry object 21,623,562; 200 of 200 sampled paths open a
file. richmond unchanged and equal (empty 64 · pending 174 · absent 9,622 · path 2,492,641; registry 2,502,437 / 64);
its path sample 35 of 200, rising as the file move goes on (116,014 files moved at 23:15). Registry totals equal
(24,125,999 / 64). The board: acris documentation 3,716,943 / 21,623,562 (17.19 %), registration and synchronization
100 %; richmond documentation 2,502,437 / 2,502,501. The mover was paused 23:16-23:32 so verify's match stage had the
drive (88 documents a second against it, 300 without); it resumed the moment verify ended. The record of the move is
complete but for richmond's files; `verify` once more when the move has ended shows the richmond sample at 200 of 200.

2026-09-06 11:15 — THE REGISTRY, VALUE FOR VALUE (login: "confirm nothing in registry has changed from the Legal Instruments
db"). The counts had matched as totals (24,125,999 objects, 64 empties); this pass compares cells: `verify --only samples`
takes 2,000 random cells per source from the cloud, reads each old row back by id, and asks whether the old
`recorded_details` text (the NUL escape set aside) and the cloud's jsonb are the same JSON value - jsonb keeps values, not
key order or spacing. acris 2,000 of 2,000 equal, richmond 2,000 of 2,000 equal, 0 different, 0 rows landed after the
load in either sample. The path samples: acris 200 of 200 open a file (the third time); richmond 200 of 200 - one page of
consecutive ids whose files the move has already carried, not yet the whole tree (1,861,468 of 2,492,641 moved at 11:14).
The one deliberate change to any registry on the way in stands recorded: the six-character NUL escape removed from
19,095 registries (jsonb cannot hold it), each noted by id in population.rejects.jsonl.

2026-09-06 15:42 — THE RICHMOND MOVE ENDED (pid 27752, 09-05 22:49 -> 15:42, exit 0): richmond_moved 2,460,075 +
already in place 32,503 + duplicate at destination 63 = 2,492,641, missing 0; the folders the moves emptied removed. 15:43
`resolve` (after its dry run said the same 65 pairs as the morning): 22 stubs replaced by their whole documents (all 22
read %PDF- and %%EOF afterwards), 41 identical copies and 2 other renderings STAGED under D:\Ignore\Staged by population
(nothing deleted, the cells untouched), 0 neither-whole, 0 without a copy. 15:43 `sweep` launched over both trees for the
stubs the move never met (hidden window, population.sweep.1543.log); `resolve` again for what it lists, then the full
`verify`, then the audit (gate 1) once 0006 and 0007 have finished their scans.

2026-09-06 16:11 — THE SWEEP (15:43 -> 16:11, 1,646 s): 6,053,150 files in 41,151 folders under both trees; 65 files under
16 KB opened; 8 stubs, all of them EMPTY (0 bytes), all acris microfilm documents (FT_1050008687105 / -405 / -505 / -605 of
1968-03, FT_3530001540653 of 1990-05, FT_3090007635509 / -637209 / -638609 of 2001-04/05), none with a whole copy anywhere
(`resolve --dry`: stub_without_copy 8, nothing to stage). Their cells point at these empty files, which is what the old table
said too: the old lane saved nothing for them. POLICY (login's call, reported before any cell write): set the eight cells to
'' so the documentation lane claims and fetches them again in gate 4, and stage the empty files; until then the audit reads
them as EXACT, because the audit is the migration's mirror, not a wholeness check. 16:11 the AUDIT (gate 1) launched over the
whole table in a hidden window (population.audit.1611.log) beside 0006's keys scan; the full `verify` follows the audit.

2026-09-06 16:2x — THE EIGHT EMPTY FILES, TRACED: the old table's cell for each is '' (never documented), the moves log and
the found map never touched them, and the cloud cell for each is NULL - they are ALREADY IN THE BACKFILL, and the empty files
are orphans a cut write left in the tree (the lane writes the file, then the cell; a drop between the two leaves an empty
file and no cell). login: "add those back into the backfill" - they never left it. Done 16:2x: the eight empty files staged
under D:/Ignore/Staged by population/empty (logged in the moves log as kind staged, why empty), NO cell written, the
documentation lane fetches them again in gate 4. The audit, running since 16:11, is untouched.

2026-09-06 18:23 — THE AUDIT (gate 1), the whole table, 75 minutes (16:11 launch dropped by the pooler at 6.5 M rows; relaunched
17:08 resumable; 24,126,063 old rows against 24,126,498 cloud rows at about 5,200 rows/s): EQUAL 24,125,999 · registry
different 64 · document different 0 · MISSING IN THE CLOUD 0 · landed after the load 435 · unknown word 0. The 64 and the 435
are ONE thing, proven by query afterwards: 499 richmond rows whose registry the cloud stamped between 2026-09-06T00:00:11 and
00:01:44 - the richmond registration lane's run at midnight, after the load - the old table's registry cell empty for all 499
(the 64 that were in the old table as empties, the 435 the sync lane added after the load); no acris registry stamped after
the load. Every old value is in the cloud unchanged, nothing is missing, and every difference is the cloud having moved
forward. The audit's rule now names that shape `registry_landed_after_load` (a landing, never a defect; the reverse - a
registry gone - would be one) and the same run would read EXACT under it; a rerun for the printed word is 75 minutes and can
go overnight on login's word. GATE 1: the migration is exact. The full `verify` (18:24) closes the record.
