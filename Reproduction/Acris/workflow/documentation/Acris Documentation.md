# Acris Documentation

The documentation lane of the acris reproduction, as one program: `Acris Documentation.py`. It batches one group of N workers through a single entry under the current IP; each worker fetches documents by minted access, saves them to the drive and records the full One Touch path in the `document` cell — the path, or `pending`, or `absent`. Nothing else runs for this lane. The cycle it belongs to is written in `../reproduction/Acris Reproduction.md`; this file is the lane's own authority: what it does, its rules, its calibrations, its history.

## Launch

    python "Acris Documentation.py" --drive NYCCRED1          home (the drive is labelled OneTouch today; the word follows the label)
    python3 "Acris Documentation.py" --drive NYCCRED2         workstation 2

The same file runs on every workstation. `--drive` names the drive by its label; the program finds where it is mounted on Windows or Mac. `--width` defaults to 40. While it runs, `documentation.control` beside it takes `width=30` (workers above the number park after their document, missing ones are born staggered) or `stop`. `--also registration:40` hosts another lane's crew in the same process through its own entry, twenty seconds later. `--limit N` is a test run. A lane that parked itself refuses to start again until `--unpark`.

## The rules

| rule | what the lane does | origin |
|---|---|---|
| one entry | one pooled session, one connection per worker at birth staggered 0.5 s apart, keep-alive after, no further handshakes, no pacer | login 2026-09-03, "handshake security, workers deploy to their floor"; the 08-28 pooled runs |
| one door | a second start on the same machine is refused while the first lives (`documentation.lock`, pid liveness, fail-closed) | trap 8, 2026-08-29 |
| the cell | a document lands as its canonical One Touch path, or `pending` (recorded within `--fresh-days`, no image yet) or `absent` (checked, none); nothing else can enter the cell | login 2026-09-03, the cell rule |
| placement | borough from the registry (the BOROUGH line, else the first parcel, else a microfilm id's digit), year and month from the RECORDED date, else the document date, else a digital id's date, else `undated` | corpus_paths.doc_store_dir: recorded is the axis; the id's date is submission and lags recording |
| no registry, no request | a row without a registry object cannot be placed or judged fresh; it waits for registration | login 2026-09-03 audit |
| already on disk | a file already under this drive is recorded without a request | relaunch recovery |
| re-ask | a viewer page without a page count is asked three times in place (0.6 s, 1.2 s, 1.8 s), then left for a later pass — never a verdict | trap 1, 30,718 false verdicts reversed on 2026-08-28 |
| short is not a pdf | fewer pages than the count promised is a retry row; the end marker and any non-TIFF page end the walk | acris_pdf.Short, "a 1-of-8 read looks exactly like success" |
| whole or nothing | the pdf is written to a `.part` file and renamed; the store never holds a truncated pdf | 2026-09-03 |
| failures never stop it | a fetch error leaves the document empty for a later pass and writes the reason to `documentation.fails.jsonl`; a transport error gets one immediate second try | login 2026-09-03, "a fetch error never stops a lane"; stale keep-alives after an idle spell |
| refusal | HTTP 200 carrying the Bandwidth Notice is the only block: park at once, write the reason, exit 2, no retry, no rotation; the page is preserved under `refusals/` | fetch_pages / live_delta detectors; the 08-26 false positive |
| hang-up | every line dropped at once (transport errors, nothing landing) is dead transport: hang up, wait `--redial-wait`, wait for the wire, re-enter through one fresh entry; three tries per incident, then park, exit 3 | §17 addenda 15–16, the dead window of 6–10 min; login 2026-09-03 01:0x, three tries |
| wifi is not a block | a network outage waits without spending a try | login 2026-09-03 01:0x |
| wall | forty consecutive 503 or 429 on the crew with no success between: park, exit 4 | trap 2 |
| drive | once a minute the drive must still be there; a pulled drive parks the lane, exit 6 | trap 5 |
| pending goes back to the backfill | a pending is re-checked once its last check is `--pending-age` old, ahead of the empties; when the lane is up to date every claim is pendings, cycling through them | login 2026-09-03 23:5x |
| no overlap | the table hands this workstation its slice (claim); cells land once a minute through `documentation.outbox.jsonl`, so a cloud hiccup loses nothing; a heartbeat every minute carries the width and the last word | SCHEMA.md, the cooperation rules |
| the last word | every stop — control file, limit, Ctrl+C, kill, refusal, redials exhausted, wall, crash, drive — leaves its reason in the heartbeat and, for a park, in `documentation.parked` | the board's status follows the lane |

## Calibrations

| knob | value | how it was measured, how it fails |
|---|---|---|
| width | 40 | the clean shape; 1×60 was refused at 105 min and 1×80 at 121 min with the same bytes as a clean 1×40 (the block ledger); a wider lane trades a ban for speed |
| stagger | 0.5 s | births over ~20 s; a burst of handshakes is what "40×5" did, and it blocks |
| timeout | 90 s | per request; a 1,000-page document is one worker for minutes, not a fault |
| user-agent | one Chrome string, never rotated | the edge flipped four times between 08-24 and 08-31; this string has served since; a 503 wall is checked against a known-good id before it is called a refusal |
| fresh-days | 30 | a document recorded inside the window with no image is `pending`, past it `absent` |
| pending-age | 1 hour | one request per pending per interval; the old lane used 5 minutes in a hot queue |
| claim | 12 × width, 20-minute ttl | a slice turns over in about two minutes at 40 workers; an expired claim goes back on the list |
| redial-wait | 600 s | after a drop every connection from here gets EOF for 6–10 min; a redial at +6 burned, one at +12 lived |
| tries | 3 per incident | an incident closes after 30 minutes of service |
| re-asks | 3, then a later pass | the soft refusal resolves on a calm retry; a fourth ask is spent budget |
| wall | 40 consecutive 503/429 | per crew; another crew's successes never silence it |

## Working files

Beside this file, never in git: `documentation.lock` (the running pid), `documentation.control` (`width=N`, `stop`), `documentation.parked` (the reason a person must read), `documentation.outbox.jsonl` (landings the cloud has not taken), `documentation.fails.jsonl` (every fetch error with its reason), `refusals/` (the page a refusal was called on). Exit codes: 0 stopped · 2 refused · 3 redials exhausted · 4 wall · 5 crash · 6 drive gone.

## What it imports

`Reproduction/lane.py` (the entry and the policies every lane shares), `Reproduction/cloud.py` (claim, land, heartbeat, the outbox), `Reproduction/storage.py` (the drive by label, the One Touch layout), `Reproduction/Acris/acris.py` (the ACRIS rules: URLs minted from the id, the one user-agent, the refusal detector, the page count, where a document files).

## History

2026-09-03 — written from the lane that ran before it (the document floor of `acris_reproduction.py`, `acris_pdf.py`, `night_supervisor.py`), every line read. Proven offline (the drive lookup, the path rule, freshness, the page count, the refusal detector against a real notice page preserved that morning) and by three simulated runs against the live cloud with throwaway rows and no ACRIS request: the loop (claim → fetch → land → counters → claims released → heartbeat → outbox → a width change → a limit stop), the guards (a second start refused, a parked lane refused, a zero-width crew refused), and the two stop policies (hang-up → redial → redial → park, exit 3; refusal → park at once, exit 2, restart refused). Not yet proven: a real fetch. The cloud table holds no rows until the data moves in, which is the last step, after every lane's code is done and connected.
