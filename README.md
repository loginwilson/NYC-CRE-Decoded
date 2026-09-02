# NYC CRE Decoded

The reproduction of New York City's public real-estate record sources into one place:
the registered data in one cloud database, the documents on drives, and the code that
keeps both current. This repo is the process. The data is not in it.

## Sources

| source | registry | what it holds |
|---|---|---|
| `acris` | NYC Department of Finance, ACRIS | recorded instruments for the five boroughs, including the microfilm era |
| `richmond` | Richmond County Clerk | Staten Island's own registry, its own numbering |

## Lanes, per source

| lane | job |
|---|---|
| enumeration | the audit: what the source holds against what we hold |
| synchronization | keeps the table live and watches the source for change; the source's URLs are minted by code from the id, never stored |
| registration | mines the registered data behind each id into the table |
| documentation | populates the document's access path on the drive, with its state (path, pending, absent, imageless, unservable) carried in the table |

The monitor has two tabs: tab 1 is reproduction as a whole; tab 2 is the three running
lanes (synchronization, registration, documentation) per source.

## Layout

```
docs/                    the reproduction docs, one folder per source: the written authority
supabase/migrations/     the schema, one numbered SQL file per decision, applied with the Supabase CLI
reproduction/acris/      the four lanes for ACRIS
reproduction/richmond/   the four lanes for Richmond
reproduction/monitor/    tab 1 the whole, tab 2 the lanes
tools/                   the SQL executor, the storage check, the fleet
```

## Where things are

- Cloud database: Supabase project **NYC CRE Decoded** (`bhyputyffmuxxhapvhsz`, East US). Credentials live in an
  env file outside this repo (`C:/dev/nyc-cre-decoded.env` at home) and are never committed or printed.
- Documents: the One Touch at home (`D:/CRE Decoding System`), an exFAT drive at the office. Paths recorded in the
  table are relative to the acquisition store, so they hold on both sides.
- The previous code (a Downloads folder, never versioned) is reference only. Each lane is rebuilt here deliberately,
  under dictation, and the old folder is retired when the last lane moves.

## How the schema changes

One decision, one migration file under `supabase/migrations/`, one commit. Applied with:

```
npx supabase db push --db-url "$SUPABASE_DB_URL"
```

The database can be rebuilt from this folder on any project.

## Rules that do not bend

- One entry per client, 40 workers. 60 was refused at 105 min, 80 at 121; 40 has hundreds of clean minutes.
- Stop on refusal and stay stopped. No retry, no probe, nothing rotated. Restoring access is a person's decision.
- Nothing auto-restarts.
- Never repair a number to make a check pass. Report the failure.
- Env files, databases, documents and bulk inputs never enter git.
