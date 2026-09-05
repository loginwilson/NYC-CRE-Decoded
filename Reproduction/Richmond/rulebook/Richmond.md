# Richmond

The rules every richmond lane shares, as one module: `richmond.py`. The Richmond County Clerk holds Staten Island's recorded instruments - the pre-ACRIS and parallel corpus, on its own site with its own shapes. The lanes import this module and call it; nothing about how the county is addressed, read or refused is written anywhere else. This file is the module's authority; `../workflow/reproduction/Richmond Reproduction.md` is the record of the lanes that ran before the repo, where every rule below was measured (the dates say when).

## What the module knows

| rule | in the module | measured |
|---|---|---|
| the front door | `BASE` = `https://www.richmondcountyclerk.com` | - |
| identify honestly | `UA` = `nyc-cre-decoded/1.0 (public land records indexing; contact via repo owner)`: the county serves the listing identically to any user-agent, so this project names itself truthfully and never presents a fake fingerprint | 2026-08-18 |
| the listing | `listing_url(start, end, page)` -> `Search/DateRangeSearch?StartSearchDate=&EndSearchDate=&SelectedDocumentIdentifier=0&pageNumber=` : GET, no session, no token; every row carries the recorded date, the type, the INTERNAL id (in the `ViewDocumentInfo` href) and the instrument number (the redesigned site) | 2026-08-21 |
| the window cap | `WINDOW_DAYS` = 30: a longer window answers a SILENT ZERO; `windows(start, end, days)` cuts any span into inclusive windows of at most 30 days | 2026-08-21 |
| the start of time | `START` = 1850-01-01, before organized county recording: the first nonzero window marks the true start | - |
| the control window | `CONTROL` = 2026-08-19 to 2026-08-20, 315 documents: a window KNOWN to hold rows; page 1 must parse rows or the parser is broken (`ProbeBroken`) and no zero from it may be believed | - |
| the rows | `parse_listing(html)` -> recorded, type, internal_id, instrument, split per `<tr>` so the pattern can never bleed across rows; `page_count(html)` reads "Page 1 of 18" -> 18, None when the page carries no pager (an empty window) | 2026-08-21 |
| our id | `doc_id(internal_id)` = `RC_` + the INTERNAL id (the `ViewDocumentInfo` key, unique) - never the instrument number, which repeats across eras: two namespaces | 2026-08-21 |
| the detail page | `detail_url(internal_id)` -> `Search/viewDocumentInfo/<id>`; `is_detail(html)` = the page carries RECORDED DETAILS | 2026-08-21 |
| the image lag | `IMAGE_LAG_DAYS` = 7: "No Image Available At This Time" inside the lag is `pending`, outside it `absent` | 2026-08-25 |

## The refusal

`check_refused(html, where)` raises `richmond.Refused` - a `lane.Refused`, so a crew parks on it exactly as on the ACRIS notice page: stop, do not retry, do not rotate. The shapes: "captcha" or "access denied" in the first 4,000 characters, or "blocked" on a page that carries no `ViewDocumentInfo` link. Neither the shell nor the unauthorized answer below is a refusal.

## The grant rule

A detail unlocks only after the SAME SESSION fetched the listing page the id appears on (2026-08-21). A cold GET answers HTTP 200 and a shell (4,212 bytes) or "INVALID REQUEST: UNAUTHORIZED SEARCH ACCESS" (2,180 bytes) - never a refusal, never an absence: our grant did not take. So a reader fetches the page, then the details of that page's ids, in that order, in one session; the walkers (synchronization, registration) are built on it. The image has no grant rule: its grant is the token (below).

## The detail page - the one parser

`parse_detail(html)` is the parser that landed 2.4 million details, kept verbatim: RECORDED DETAILS + BLOCKS AND LOTS + PARTIES in the corpus schema, or None for a page that is not a detail (the shell, the unauthorized answer).

- **Fields**: `instrument` (the label is "Document No.:" on modern pages, a PERIOD before the colon, and "Document No:" on old ones - a plain match caught only the old form and every same-day 2026 document froze with instrument '' on 2026-08-22), `book`, `page`, `doc_type`, `recorded` (Date Recorded, as the clerk prints it, M/D/YYYY), `amount` (Consideration Amount), `status`, `image_state`.
- **Parcels**: `bbl` = 5 + block (5) + lot (4) from every "Block N, Lot N" the page prints.
- **Parties**: name, role, and the COLUMN the clerk typed the name in (`column` = name or company, with both cells kept). The page tells where the clerk typed it, not whether the party is a person - inferring the type manufactures a fact.
- `premature(rec)`: a document registered the day it was recorded can carry no instrument number yet - the detail is not mature and the registry is `pending` until it is (2026-08-22).

**`image_state(flat, recorded)`** is the ONE definition every reader shares: `present` (the page offers View Imaged Document or a ViewVscms link) · `pending` / `absent` ("No Image Available At This Time", split by age against the lag - login 2026-08-25: "the lag determines the state"; an unreadable date is always `pending`) · `unknown` (neither phrase: not a conclusion, ask again).

## The image - minted on the clerk, served by the courts

Two hosts. The clerk MINTS: `mint_url(internal_id)` -> `ViewVscmsDocument/ViewContent?p_endorsementId=<id>` with redirects OFF answers a 302 whose Location is a self-authenticating token URL on the New York State courts viewer (`IAPPS` = `https://iapps.courts.state.ny.us`, `vscms_public/viewer?token=v2...`). The PDF never lives on the clerk.

Three outcomes, never two - login 2026-08-25: "we have the url, if it doesnt show, its absent, if it shows a fetch its pdf, and if its absent but the recorded date of the doc id is in the lag period it gets pending" - measured 2026-08-26 on one session (RC_2825613, image up -> 302 to the courts viewer; RC_2820269, no image -> 302 `/Search/SearchError`, the clerk's own error page). `classify_mint(status, location)`:

| the mint answered | verdict |
|---|---|
| a redirect to an ABSOLUTE url | `present` + the token URL to pull |
| a redirect to a relative Location, or 200, or 404 | `noimage` - the endpoint answered and handed us no image; `fresh(registry)` then says `pending` (inside the lag) or `absent` |
| 403, 429, 5xx | `error` - about us, never about the document; asked again |

- The mint takes a bare id: no grant rule. `mint_referer(internal_id)` is the detail page it is reached from (spelled `ViewDocumentInfo` as the browser sent it; `detail_url` spells the site's own link `viewDocumentInfo` - the county's routing answers both and both ran live).
- The token EXPIRES (~10 min, 2026-08-22): mint and pull in one breath, never a buffer of tokens.
- **The courts host gates on the user-agent** (2026-08-22, one variable, everything else identical): the library default `python-requests/2.34.2` hangs to a ReadTimeout at 45 s, 2 of 2; this project's honest `UA` answers 200 and the full PDF in 1.5 s, 2 of 2. So the pull carries the same honest string with `PULL_HEADERS` (Referer the clerk's front door, Accept `application/pdf,*/*`). A browser string was measured to buy nothing and would make the client dishonest.
- `is_pdf(data)`: a PDF is a PDF only when the body starts `%PDF`.
- `fresh(registry, days)`: inside the scan lag, a document with no image yet is `pending`, not `absent`. An UNREADABLE date is always inside the lag - guessing wrong records a scanned document as having no scan forever; staying pending costs one re-ask (2026-08-26). `recorded_date(registry)` reads the clerk's M/D/YYYY.
- `canonical_path(doc_id, registry)` -> `storage.canonical("richmond", None, year, month folder, doc_id)`: richmond has no borough; year and month from the RECORDED date (the id's digits are a submission sequence, not a date), else `undated/undated`.

## The access shape - and why the cycle is dormant here

The county was measured under the DRUMROLL RULE (`Richmond Reproduction.md` §3): no pacer, no governor, latency is the only governor; 160 concurrent connections ran 26 hours clean; restarts are free; the only safety is stop-on-refusal. What it objects to is a handshake burst - 160 cold TLS opens in one instant answered SSLError across the board - so births are 0.4 s apart and keep-alive removes every later handshake. Synchronization keeps the census's polite 0.3 s between the pages of one window and registration keeps it between the details of one page (its pages fan out across the walkers) - measured over 2.4 million requests without a trip. The courts host hangs the library-default user-agent and serves the honest one.

The lanes inherit the cycle from `lane.py` (login's acris design: one entry, staggered births, a hang-up when the whole width dies with nothing landing, a 60-s wait, one re-entry on a fresh batch). At this county it is DORMANT: no session close was ever measured here, so the hang-up fires only when the wire itself dies (wifi, a dead host) - the right thing then. The walkers drop their cut windows and pages at a hang-up and ask them again at the next heal or walk; documentation drops its claims and takes fresh ones. login 2026-09-04: "the way it works doesnt require this whole batch, enter, stagger, redial, exit, rebatch approach ... richmond can just enter and hammer" - the record agrees.

## Who calls what

| lane | from the module |
|---|---|
| synchronization | `BASE`, `UA`, `WINDOW_DAYS`, `CONTROL`, `windows`, `listing_url`, `parse_listing`, `page_count`, `doc_id`, `check_refused`, `IMAGE_LAG_DAYS` |
| enumeration | `UA`, `WINDOW_DAYS`, `START`, `CONTROL`, `windows`, `listing_url`, `parse_listing`, `page_count`, `doc_id`, `check_refused`, `Refused`, `ProbeBroken` |
| registration | `BASE`, `UA`, `WINDOW_DAYS`, `CONTROL`, `windows`, `listing_url`, `parse_listing`, `page_count`, `doc_id`, `detail_url`, `parse_detail`, `premature`, `check_refused`, `IMAGE_LAG_DAYS` |
| documentation | `BASE`, `UA`, `IAPPS`, `PULL_HEADERS`, `mint_url`, `mint_referer`, `classify_mint`, `is_pdf`, `fresh`, `canonical_path`, `check_refused`, `Refused`, `IMAGE_LAG_DAYS` |
| reproduction | `IMAGE_LAG_DAYS` - the fleet's `--fresh-days` default |
| update | nothing - the board never talks to the source |

The module imports `lane` (for `Refused`) and `storage` (the One Touch layout). It makes no request of its own.

## Working files

None. The county's refusal shapes are not preserved as files yet: a refusal here parks the lane with the reason written beside it, and the page can be re-fetched by hand once the lane is parked.

## History

2026-09-05 — the review against the code: the 0.3-s pace is per page in synchronization and per detail in registration; the two spellings of the detail route named.

2026-09-03 - the module written with the repo, every rule carried from the lanes that ran before it with its measured date; the image section (two hosts, three outcomes, the honest user-agent at the courts host) added when the documentation lane was written. Moved into `rulebook/` with this authority beside it the same evening, on login's word: a source folder is `rulebook/`, `workflow/`, `update/` and nothing loose.

2026-09-04 (night) - the review of every richmond file against the record (login: "finish richmond the same way"): nothing in this module changed; the access shape written down above, with the finding that the cycle is dormant at this county.
