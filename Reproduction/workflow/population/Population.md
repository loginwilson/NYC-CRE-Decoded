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
