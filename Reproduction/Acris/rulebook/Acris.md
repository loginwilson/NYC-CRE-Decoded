# Acris

The rules every acris lane shares, as one module: `acris.py`. ACRIS is the Automated City Register Information System of the NYC Department of Finance - the recorded documents of Manhattan, the Bronx, Brooklyn and Queens (Staten Island records with the Richmond County Clerk and is its own source). The lanes import this module and call it; nothing about how ACRIS is addressed, read or refused is written anywhere else. This file is the module's authority; `../workflow/reproduction/Acris Reproduction.md` is the record of the lanes that ran before the repo, where every rule below was measured (the dates say when).

## What the module knows

| rule | in the module | measured |
|---|---|---|
| the front door | `BASE` = `https://a836-acris.nyc.gov/DS/DocumentSearch` | - |
| the detail page by id | `detail_url(doc_id)` -> `DocumentDetail?doc_id=` : the recorded details, ~131 KB; a document that does not exist answers a ~10 KB stub with no document id | 2026-08-23 |
| the detail page by CRFN | `crfn_url(crfn)` -> `DocumentDetail?hid_CRFN=<crfn>&SearchType=DocID` : one GET, no session, no token; a live CRFN answers the same page as by id, an unissued one the stub | 2026-08-23 |
| the viewer page | `viewer_url(doc_id)` -> `DocumentImageView?doc_id=` : carries the page count | - |
| one page image | `image_url(doc_id, page)` -> `GetImage?doc_id=&page=` : a TIFF; past the last page HTTP 200 with a fixed placeholder image, `PLACEHOLDER_MD5` = the end marker (`is_placeholder`) | - |
| the one user-agent | `UA`, one string, set once, never rotated: the string the 1x40 has run under since the edge flipped four times between 08-24 and 08-31 under others | 2026-08-31 |
| a detail too short to trust | `MIN_DETAIL` = 20,000 bytes: a detail parsed from fewer bytes is suspect truncation and is never reported live | - |
| the id a page is about | `detail_doc_id(html)`: the `DOCUMENT ID:` the page prints, None for the stub; `echoes(html, doc_id)`: the page prints the id that was asked for - a page that does not is a re-ask, never a failure and never a verdict (63 % of a floor's requests under load did not echo) | 2026-08-28 |

Every URL is minted from the id. No URL, token or key is ever stored: the table holds `doc_id`, `registry`, `document` and `updated_at` (the re-check clock), nothing else (`../../supabase/SCHEMA.md`).

## The refusal

ACRIS refuses with HTTP 200 carrying its Bandwidth Notice page - never a status code. `check_refused(data, ctype, where)` raises `lane.Refused`, the one exception a crew parks on (exit 2, no retry, no rotation, the reason written beside the lane).

- Images and PDFs pass at once (a body starting `II`, `MM` or `%PDF`).
- Everything else is read as **visible text**: markup stripped, entities resolved. The notice is Word-generated HTML whose sentences are split across tags, so the raw bytes never contain the phrases (2026-08-06).
- Two shapes are a refusal: any of the notice's own phrases (`NOTICE_SIGNALS`: "further access to acris is denied", "acris bandwidth notice", "automated scripts/robots", "exceeded the bandwidth limits", "subscription data services"; or the title "Bandwidth Notice"), or the word bandwidth in the first 2,000 characters of a page that carries no document id.
- The body is **preserved** as `refusals/refusal-<stamp>.html` beside this file before the exception is raised, so the verdict can be audited. A detector that halted a night on a wifi interstitial had thrown its evidence away (2026-08-26).

A connection cut is not a refusal: the far side closing lines is the hang-up, handled by `lane.py` as the cycle - a closed line is redialed by its worker; the whole width closed inside a minute with nothing landing is the session's end: hang up at once, drop the cut batch, 60 s of silence, one re-entry on a fresh batch. Only the notice page is a block, and a block lifts on its own clock - never probed.

## The page count and the imageless verdict

`total_pages(viewer_html)` reads the `TotalPages` token from the viewer page. Zero or less is the source itself saying "no image": a true imageless document identifies itself. **None** - a page without the token - is an unknown shape and never a verdict: a fixed 4,922-byte error page read as 0 produced thousands of false imageless verdicts in ten minutes (2026-08-28). `is_tiff(data)` and `is_placeholder(data)` decide what a `GetImage` answer was.

## Where a document files

The One Touch address of a document is a pure function of its id and registry (`canonical_path(doc_id, registry)` -> `storage.canonical("acris", borough, year, month folder, doc_id)`):

- **borough** (`borough_of`): the registry's own BOROUGH line; else the first parcel's BBL digit; else the microfilm id's borough digit (`FT_<borough>...`); else `Unknown`.
- **year / month** (`recorded_ym`): the RECORDED date - the axis that aligns every source; the id's embedded date is the submission date and can lag recording by days. Fallbacks: the document date, then a digital id's own date. None for undated microfilm -> `undated/undated`.
- `fresh(registry, days)`: recorded within the last `days` - a document without an image yet is `pending`, not `absent`; the documentation lane's `--fresh-days`.

## The index - an audit, never a discovery source

ACRIS publishes its own extract on NYC Open Data (Socrata): one master per corpus, `INDEX` = real property `bnx9-e6tj` and personal property `sv7x-dduq`, refreshed monthly and weeks behind (`good_through_date` says how far). A different host from the web endpoint, so reading it is never a second door at ACRIS. Measured 2026-09-03: real 17,049,742 distinct ids and personal 4,544,590, both good through 2026-07-31; both hold the film bands (`FT_` + a borough digit 1-4 + a digit; `BK_` + a two-digit year 66-81) and the digital ids (2002-12 on).

| rule | why |
|---|---|
| ids are counted DISTINCT | rows repeat: 15,348 duplicate rows in the real master |
| every pull is held to the index's own count; fewer raises `Void`, never an empty answer | a throttled call answers HTTP 200 and `[]` (2026-08-31) |
| pages of `SOCRATA_PAGE` = 50,000 with `$order=:id` | without an order `$offset` silently drops and duplicates rows (2026-08-06); 50,000 is honoured (2026-08-05); a short page ends a walk |
| `X-App-Token` from `SOCRATA_APP_TOKEN` in the env file, never printed | without it the index throttles |
| a 5xx or a dropped wire is asked again after 2, 4, 8 s; a 4xx is raised at once | the first is the server's moment, the second is our query - never retried into silence |

`index_state(dataset)` (distinct ids, newest recorded date, good-through date, highest CRFN), `index_prefixes(dataset, lo, hi, n)` (the id prefixes the index holds - the shard list is the index's own, never assumed), `index_count`, `index_ids(dataset, lo, hi)`, `index_crfns(dataset, year)` (a CRFN is YYYY + nine digits; the year's sequence numbers, held to the count). The enumeration lane is the only caller: the index is what the table is audited against, never what fills it.

## The recorded details page - the one parser

login, 2026-08-20: "all 4 url paths result in the exact same format so just figure it out once and you are good for all 24,039,303". `parse_acris(html)` is that one parser, copied verbatim from the code that registered every document and not rewritten: a second regex for the same page is how the same page gets learned wrong twice (a fresh one once truncated MCON to "M" while this one read it right).

- **Copy-paste rule.** Capture the page verbatim; omit only N/A, blank, or a flag column's N. `clean_html` unescapes entities BEFORE any parsing (`&nbsp;` is data-shaped noise).
- **Tables classify themselves** by their own header row (`_TABLE_SIGS`: a party table has NAME + ADDRESS 1; parcels BOROUGH + BLOCK + LOT; references CRFN + DOCUMENT ID), never by position - position bounding failed twice in one evening. The page nests 32 tables, so the parser tracks the nesting and every table yields its own rows; a header-only table's signature carries to the headerless data table after it.
- **The caller asserts the echo first** (`echoes`), then parses. The parser only reads.
- **Scalars** (`FIELD_KEYS`), read with the next label as the lookahead so a value can never swallow the following label: DOC. TYPE -> `type` · # of PAGES -> `pages` · DOC. DATE -> `doc_date` · CRFN -> `crfn` · RECORDED / FILED -> `recorded` · BOROUGH -> `borough` · DOC. AMOUNT -> `amount` · % TRANSFERRED -> `pct` · SLID # -> `slid` · ASSESSMENT DATE -> `assessment` · EXPIRATION DATE -> `expiration` · COLLATERAL -> `collateral` · FILE NUMBER -> `file_nbr` · RPTT # -> `rptt` · MAP SEQUENCE # -> `map_seq` · MESSAGE -> `message` · REEL-PAGE -> `reel_page`.
- **Parties**: `panel` 1 / 2 / 3 from the nearest preceding panel title, `name`, and address, address2, city, state, zip, country when printed; ghost rows (a header or a panel title read as a name) are skipped.
- **Parcels**: `bbl` = borough digit + block (5) + lot (4), with partial, use, address, unit, remarks when printed and `easement` / `air_rights` / `subterranean` when the flag column says Y.
- **References**: crfn, doc_id, borough, year, reel, page, file_nbr - each value must LOOK like its column claims (a title cell or stray text can never impersonate a CRFN or an id); a row is kept only with a crfn, a doc_id or a file number.
- **Remarks** is a text box, not a table: the textarea's own content.

## Who calls what

| lane | from the module |
|---|---|
| synchronization | `BASE`, `UA`, `crfn_url`, `detail_doc_id`, `clean_html`, `check_refused`, `MIN_DETAIL` |
| enumeration | `INDEX`, `index_state`, `index_prefixes`, `index_ids`, `index_crfns`, `Void`, `crfn_url`, `detail_doc_id`, `clean_html`, `check_refused`, `UA`, `MIN_DETAIL`, `BASE` |
| registration | `BASE`, `UA`, `detail_url`, `echoes`, `clean_html`, `check_refused`, `parse_acris` |
| documentation | `UA`, `viewer_url` (with `detail_url` as the page it is reached from), `check_refused`, `total_pages`, `image_url`, `is_tiff`, `is_placeholder`, `fresh`, `canonical_path` |
| reproduction, update | nothing - the fleet and the board never talk to the source |

The module imports `storage` (the One Touch layout) and `lane.Refused` (so a refusal here is the same exception every crew parks on); `cloud` is imported lazily for the index's app token. It makes no request of its own except the index calls the enumeration lane asks for.

## Working files

Beside this file, never in git: `refusals/` - the body of every refusal ever detected, one HTML file per verdict.

## History

2026-09-05 — the review against the code: `updated_at` named as the table's fourth column; the lazy `cloud` import named; a refusal page that could not be saved is now said so in the Refused message instead of silently.

2026-09-03 - the module written with the repo, every rule carried from the lanes that ran before it with its measured date; the index measured the same day (real 17,049,742 / personal 4,544,590, good through 2026-07-31). Moved into `rulebook/` with this authority beside it the same evening, on login's word: a source folder is `rulebook/`, `workflow/`, `update/` and nothing loose.

2026-09-04 (night) - the review of every acris file against the cycle: nothing in this module changed; the callers' table and the refusal paragraph were read against the reviewed lane module. The six refusal pages preserved beside the module's old location were folded into `refusals/` here.
