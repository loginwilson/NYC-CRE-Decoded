# Acris Registration

The registration lane of the acris reproduction, as one program: `Acris Registration.py`. It batches one group of N workers through a single entry under the current IP; each worker fetches a document's recorded details from the DocumentDetail page minted from its id — one request per document, no navigation step — and records them in the `registry` cell as a JSON object. Nothing else runs for this lane. The cycle it belongs to is written in `../reproduction/Acris Reproduction.md`; this file is the lane's own authority.

## Launch

    python "Acris Registration.py"                    home
    python3 "Acris Registration.py"                   workstation 2

No drive: the registry is text and lives in the cloud table only. `--width` defaults to 40. While it runs, `registration.control` beside it takes `width=30` or `stop`. `--also documentation:40 --drive NYCCRED1` hosts the documentation crew in the same process through its own entry, twenty seconds later. `--limit N` is a test run. A parked lane refuses to start again until `--unpark`. In the fleet's batch it runs 10 wide beside documentation 10 and synchronization 9 plus its monitor, each crew on its own entry.

## The rules

| rule | what the lane does | origin |
|---|---|---|
| one entry | one pooled session, one connection per worker at birth, births 5 s apart, keep-alive after, no further handshakes | login 2026-09-03; the 08-28 pooled runs |
| one door | a second start on the same machine is refused while the first lives (`registration.lock`) | trap 8 |
| the URL | `DocumentDetail?doc_id=<id>`, minted from the id, the search page as referer; no navigation step | login: "mints url via stems" |
| the echo | the page must print `DOCUMENT ID: <id>` before it is believed; a page that does not is asked three times in place (0.5 s, then 1 s between asks), then left for a later pass — never a failure count, never a verdict | trap 1: under load 63% of a floor's requests came back as a short or generic page, and the same ids served full pages seconds later |
| the parser | `acris.parse_acris`, the one place the page format is known, copied verbatim from the code that registered every document: capture the page verbatim, omit only N/A, blank or a flag-column N; tables classify themselves by their own header row; the page's 32 nested tables are walked by a real parser; the parse runs only after the echo is proven | rd_parse.py, login 2026-08-20 |
| the cell | the registry lands as the JSON object: the scalar fields (type, pages, doc_date, crfn, recorded, borough, amount, …), parties by panel, parcels as bbl with their flags, references, remarks, and `at`, the time it was read | the cell rule |
| no verdict from the lane | the lane writes a registry or nothing. A page that never echoes the id is indistinguishable, per request, from the transient; only persistence across passes tells them apart, and the lane keeps no count. The words `pending` / `absent` for a registry are a decision to record here when it is taken (see Open) | trap 1; §12 "the 322 are the same 322" |
| failures never stop it | a fetch error leaves the document empty for a later pass and writes the reason to `registration.fails.jsonl`; a transport error gets one more try after a 5 s pause | login 2026-09-03 |
| refusal | HTTP 200 carrying the Bandwidth Notice is the only block: park at once, exit 2, no retry, no rotation; the page is preserved under `Reproduction/Acris/rulebook/refusals/` | the detectors; the 08-26 false positive |
| hang-up | the session closed (every worker a transport error inside 60 s, nothing landed for 10 s): hang up at once, drop the cut batch, wait `--redial-wait` (60 s, ×2 per refused re-entry, ÷2 per served), claim a fresh batch, re-enter once, births 5 s apart; four re-entries per incident, then park, exit 3 | the cycle, login 2026-09-04; see Acris Documentation.md |
| wall | forty consecutive 503 or 429 with no success between: park, exit 4 | trap 2 |
| pending goes back to the backfill | a registry pending is re-checked once its last check is `--pending-age` old, ahead of the empties | login 2026-09-03 23:5x |
| no overlap | claim, land once a minute through `registration.outbox.jsonl`, heartbeat every minute | SCHEMA.md |
| the last word | every stop leaves its reason in the heartbeat and, for a park, in `registration.parked` | the board's status follows the lane |

## Calibrations

| knob | value | how it was measured, how it fails |
|---|---|---|
| width | 40 | the clean shape for one entry; the meter is per connection count and rate, not volume |
| speed | about ten to eleven documents a second per process | the parse is pure Python under one interpreter lock; that is the ceiling of one process and it is plenty for the inflow. Never scale it with more processes: each is another door (trap 8, six doors on 2026-08-29). If a full re-registration were ever wanted faster, the shape is one entry in this process fanning raw pages out to child processes for parsing — never more sessions |
| re-asks | 3 at 0.5 s steps | the transient resolves on a calm retry; a fourth ask is spent budget |
| claim | 12 × width, 20-minute ttl | a slice turns over in about a minute at 40 workers |
| pending-age | 1 hour | shared knob; registry pendings are rare |
| redial-wait, tries, wall | 60 s with the backoff, 4, 40 | shared with documentation; see Acris Documentation.md |

## Open

The same few ids (322 of the whole table on 2026-09-02) never echo on the detail page; their registries were settled from the Socrata bulk feed. The lane leaves them empty and spends three requests on each per pass. The decision still to take: whether the audit settles such ids from Socrata into the registry cell, or whether a persistent no-echo across N passes becomes `absent`. Recorded here when login decides.

## Working files

Beside this file, never in git: `registration.lock`, `registration.control`, `registration.parked`, `registration.outbox.jsonl`, `registration.fails.jsonl`, `Reproduction/Acris/rulebook/refusals/`. Exit codes: 0 stopped · 2 refused · 3 redials exhausted · 4 wall · 5 crash.

## History

2026-09-04 — the review against the cycle: the lane module's amendments (the rebatch, the quiet rule, the non-blocking wait and ramp) apply here unchanged; nothing of this lane's own changed. The batch width in the fleet is 10.

2026-09-03 — written from the register floor of `acris_reproduction.py` and `rd_parse.py`, every line read; the parser copied verbatim. Proven offline against a synthetic detail page in the real page's shape and against the key set of a real registry row, and by a simulated run against the live cloud with throwaway rows and no ACRIS request. Not yet proven: a real fetch, which waits for the data move.
