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

## The four commands

    python Population.py survey              read the old table once, in id order: rows per source, the words in each cell, the path shapes; writes population.survey.json only
    python Population.py organize [--dry]    the One Touch tree (below); every move to population.moves.jsonl; --dry counts and moves nothing
    python Population.py load [--limit N]    the rows into both cloud tables by COPY, --slice 50,000 per transaction, routed by the id, resuming after the last id in either table
    python Population.py verify              counts on both sides by cell state, a sample of recorded paths opened on the drive, reconcile() per source, the board rows

Run in that order. `load` refuses to start while the survey names a word without a mapping (fail closed), and warns when
`organize` has not run for real, since the paths it writes assume the new tree.

## The cell mapping (old → new), the same for both sources

| old `navigation` | new cell | note |
|---|---|---|
| `id` | `doc_id` | text; byte order on both sides (SQLite BINARY = Postgres `collate "C"`), so a resume after the last id is exact. `RC_` ids go to `richmond`, every other id to `acris` |
| `recorded_details` = `''` | `registry` NULL | registration's to-do |
| `recorded_details` = `{…}` | `registry` (jsonb) | the recorded details as the old lane landed them |
| `pdf` = `''` | `document` NULL | documentation's to-do - unless `organize` found the document in By Parcel / By Party and placed it, then the new full path |
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
   for is **placed** into `By Document` by its recorded date and remembered in `population.found.json`, which `load` uses
   to fill that cell; a document whose recorded file is missing is **restored** to that place; an id not in the table is
   logged and left.
5. Folders under `Acris\By Document` left empty by the richmond move are removed (empty folders only).

Preconditions: no old lane process runs (the old `acris_reproduction.py` and its supervisor write into the old tree -
stopped 2026-09-05 17:0x, never to run again; the repo's lanes replace them), and nothing holds a file open inside the
tree (the rename fails with "in use" otherwise - Explorer windows on the folder included).

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
