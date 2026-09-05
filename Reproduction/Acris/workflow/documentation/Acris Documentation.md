# Acris Documentation

The documentation lane of the acris reproduction, as one program: `Acris Documentation.py`. It batches one group of N workers through a single entry under the current IP; each worker fetches documents by minted access, saves them to the drive and records the full One Touch path in the `document` cell — the path, or `pending`, or `absent`. Nothing else runs for this lane. The cycle it belongs to is written in `../reproduction/Acris Reproduction.md`; this file is the lane's own authority: what it does, its rules, its calibrations, its history.

## Launch

    python "Acris Documentation.py" --drive OneTouch          home (the One Touch's volume label; the word follows the label)
    python3 "Acris Documentation.py" --drive <label>         workstation 2

The same file runs on every workstation. `--drive` names the drive by its label; the program finds where it is mounted on Windows or Mac. `--width` defaults to 40. While it runs, `documentation.control` beside it takes `width=30` (workers above the number park after their document, missing ones are born staggered) or `stop`. `--also registration:40` hosts another lane's crew in the same process through its own entry, twenty seconds later. `--limit N` is a test run. A lane that parked itself refuses to start again until `--unpark`. In the fleet's batch (`../reproduction/Acris Reproduction.py`) this lane is MANAGED: it enters with one worker and the rate manager sets its width between 20 and 120 (its `--width 10` only sizes the claim), beside registration 10 and synchronization 9 plus its monitor, each crew on its own entry, one ramp at a time.

## The rules

| rule | what the lane does | origin |
|---|---|---|
| one entry | one pooled session, one connection per worker at birth, births 5 s apart (a ramp of about 200 s at width 40), keep-alive after, no further handshakes, no pacer | login 2026-09-03, "handshake security, workers deploy to their floor"; the 08-28 pooled runs |
| managed width | with `--manage 1` (the acris fleet passes it) the crew enters with ONE worker and the rate manager births one every `--stagger` s until the docs/s meets the band, then adjusts every window: the docs band (floor 5, ideal 6-7, hard 8 docs/s) and, first, the request ceiling (60/s) read as a projection at the exit's recent speed - retire straight to the cap, never grow past it, hold under 3 lines; a grow that buys nothing is undone; at `--session-max-requests` (1,000,000) the session ends on purpose and the cycle re-enters on a fresh batch. Knobs on the command line and in the acris site's MANAGE table, never code | login 2026-09-04: "ramp until rate is met and then adjust"; live 09-04 19:37 -> 09-05 |
| one door | a second start on the same machine is refused while the first lives (`documentation.lock`, pid liveness, fail-closed) | trap 8, 2026-08-29 |
| the cell | a document lands as its canonical One Touch path, or `pending` (recorded within `--fresh-days`, no image yet) or `absent` (checked, none); nothing else can enter the cell | login 2026-09-03, the cell rule |
| placement | `D:\NYC CRE Decoded\Reproduction\Acris\By Document\<year>\<MM Mon>\<day>\<id>.pdf` - the day from the RECORDED date, else a digital id's own date, else the id split (`<id[:4]>\<id[4:8]>`); no borough folder | login 2026-09-05 (the One Touch mirrors GitHub and Supabase); corpus_paths.doc_store_dir's rule kept exactly so the moved tree stays true: recorded is the axis, the id's date is submission and lags recording |
| no registry, no request | a row without a registry object cannot be placed or judged fresh; it waits for registration | login 2026-09-03 audit |
| already on disk | a file already under this drive is recorded without a request | relaunch recovery |
| re-ask | a viewer page without a page count is asked three times in place (0.6 s, then 1.2 s between asks), then left for a later pass — never a verdict | trap 1, 30,718 false verdicts reversed on 2026-08-28 |
| short is not a pdf | fewer pages than the count promised is a retry row; the end marker and any non-TIFF page end the walk | acris_pdf.Short, "a 1-of-8 read looks exactly like success" |
| whole or nothing | the pdf is written to a `.part` file and renamed; the store never holds a truncated pdf | 2026-09-03 |
| failures never stop it | a fetch error leaves the document empty for a later pass and writes the reason to `documentation.fails.jsonl`; a transport error gets one more try after a 5 s pause | login 2026-09-03, "a fetch error never stops a lane"; stale keep-alives after an idle spell |
| refusal | HTTP 200 carrying the Bandwidth Notice is the only block: park at once, write the reason, exit 2, no retry, no rotation; the page is preserved under `refusals/` | fetch_pages / live_delta detectors; the 08-26 false positive |
| hang-up | the session closed: every worker a transport error inside 60 s and nothing landed for 10 s (a partial close is redialed worker by worker while the other lines keep landing, and the width comes back). ACRIS's ordinary session end, not a block: hang up at once, land what the crew holds, drop the cut batch (its claims expire on their own and come back in a later pass), wait `--redial-wait` (60 s) with no line open, wait for the wire, claim a fresh batch, re-enter once, births 5 s apart - without blocking any other crew in the process. A refused re-entry (cut inside five minutes with under 300 landed) doubles the next wait (cap 80 min), a served one halves it back; four re-entries per incident, then park, exit 3 | login 2026-09-04: "batch, enter, stagger, redial until close, exit, rebatch, cycle"; proven unattended 14:51-14:58 (§17 addendum 19); the closing waves and the 19:43 storm are what a re-entry inside them looks like |
| wifi is not a block | a network outage waits without spending a try | login 2026-09-03 01:0x |
| wall | forty consecutive 503 or 429 on the crew with no success between: park, exit 4 | trap 2 |
| drive | once a minute the drive must still be there; a pulled drive parks the lane, exit 6 | trap 5 |
| pending goes back to the backfill | a pending is re-checked once its last check is `--pending-age` old, ahead of the empties; when the lane is up to date every claim is pendings, cycling through them. The wait is the claim itself: `land()` keeps a landed pending's claim as a cooldown for `--pending-age` and `claim()` offers it again when that is gone (0004; the table holds no clock) | login 2026-09-03 23:5x; 2026-09-05 18:4x |
| no overlap | the table hands this workstation its slice (claim); cells land once a minute (or at 200 results) through `documentation.outbox.jsonl`, so a cloud hiccup loses nothing; a heartbeat every minute carries the width and the last word | SCHEMA.md, the cooperation rules |
| the last word | every stop — control file, limit, Ctrl+C, kill, refusal, redials exhausted, wall, crash, drive — leaves its reason in the heartbeat and, for a park, in `documentation.parked` | the board's status follows the lane |

## Calibrations

| knob | value | how it was measured, how it fails |
|---|---|---|
| width | 40 | the clean shape; 1×60 was refused at 105 min and 1×80 at 121 min with the same bytes as a clean 1×40 (the block ledger); a wider lane trades a ban for speed |
| managed width | ramp from 1, then 59-70 on the 31.171.153 exit | the exit's requests per line (0.81-0.95/s) set it: 95% of the 60/s ceiling = 61-70 lines; five live ramps ended at 60, 66, 65, 62 and 65 in 302-331 s |
| rate band | floor 5, ideal 6-7, hard 8 docs/s | login's band ("i think 6 is the number we want to be around", "no more than 8 ever"); on that exit the ceiling binds first and the lane lands 5.0-5.5 |
| request ceiling | 60/s, projected at the exit's recent speed | the record's meter: the 09-04 notices came at 58-81 requests/s held for hours, the golden day ran ~57 with none; a same-window cap rose on stalled windows and grew into slow exits (66/71/65/75/63/73 on 09-04 23:41-00:30) - the recent-speed cap held 61 for twenty minutes |
| adjust window | 120 s, step 10 | shorter windows read the exit's minute-to-minute swing (3.9-8.1 docs/s at one width) as a signal; a grow is decided on two windows, a retire on one |
| session knob | 1,000,000 requests | login: "just try 1 million ... worse comes to worse we move somewhere else"; never reached live on 09-04/05 - the door cut every session at 40-96 min (124,000-314,000 requests) |
| stagger | 5 s | births over ~200 s. The ramp is the entry the door serves: on 2026-09-04 two entries born over 20 s were cut inside a minute and entries born over 196 s and 785 s were served at the golden rate, same door, same hour (login's design: "enter and stagger the widening"). The cost is about half the ramp in full-width time. A burst of handshakes is what "40×5" did, and it blocks |
| timeout | 90 s | per request; a 1,000-page document is one worker for minutes, not a fault |
| user-agent | one Chrome string, never rotated | the edge flipped four times between 08-24 and 08-31; this string has served since; forty consecutive 503/429 are the wall (exit 4) and are never called a refusal |
| fresh-days | 30 | a document recorded inside the window with no image is `pending`, past it `absent` |
| pending-age | 1 hour | one request per pending per interval; the old lane used 5 minutes in a hot queue |
| claim | 12 × width, 20-minute ttl | a slice turns over in about two minutes at 40 workers; an expired claim goes back on the list |
| redial-wait | 60 s, ×2 per refused re-entry, ÷2 per served one | the door served a fresh-batch re-entry 60 s after the last dead line cleared (09-04 14:54) and 5 min after a close (12:45); what it refuses is a re-entry into its own closing waves on the old batch (13:03) and a storm (09-03 19:43) |
| hang-up quiet | 10 s | a partial close keeps landing on the lines still open; a closed session lands nothing - the whole width inside 60 s counts only once nothing has landed for 10 s |
| tries | 4 re-entries per incident | an incident closes once a re-entry lands 300 or lives five minutes; the wait doubles each refused try, so four span 1, 2, 4 and 8 minutes at the base |
| re-asks | 3, then a later pass | the soft refusal resolves on a calm retry; a fourth ask is spent budget |
| wall | 40 consecutive 503/429 | per crew; another crew's successes never silence it |

## Working files

Beside this file, never in git: `documentation.lock` (the running pid), `documentation.log` (every launch's output, appended by the fleet and by `--log`), `documentation.control` (`width=N`, `stop`), `documentation.parked` (the reason a person must read), `documentation.outbox.jsonl` (landings the cloud has not taken), `documentation.fails.jsonl` (every fetch error with its reason), `Reproduction/Acris/rulebook/refusals/` (the page a refusal was called on - one folder for every acris lane). Exit codes: 0 stopped · 2 refused · 3 redials exhausted · 4 wall · 5 crash · 6 drive gone.

## What it imports

`Reproduction/rulebook/lane.py` (the entry and the policies every lane shares), `Reproduction/rulebook/cloud.py` (claim, land, heartbeat, the outbox), `Reproduction/rulebook/storage.py` (the drive by label, the One Touch layout), `Reproduction/Acris/rulebook/acris.py` (the ACRIS rules: URLs minted from the id, the one user-agent, the refusal detector, the page count, where a document files).

## History


2026-09-05 — the review of this file against the code: the launch line names the One Touch's real label (`--drive OneTouch`; `NYCCRED1` was a label no mounted drive carries, so the written command could not have run); the batch line says what the managers do with this lane (one worker in, 20..120, `--width 10` sizes the claim); the working files list `documentation.log`; landing is once a minute or at 200 results; the imports point at `Reproduction/rulebook/`.

2026-09-05 (night) — THE THREE MANAGERS ported from the lane that ran them live all night (batch = the cycle; rate = ramp until the rate is met, then adjust under the docs band and the projected request ceiling; session = end at the request knob, re-enter on a fresh batch), as knobs the acris fleet passes to this lane; `--manage 0` is the lane as before. Proven offline by `Reproduction/rulebook/test_managers.py` (the rate manager against fake exits, and this lane's wiring through the whole loop). The night's record is `D:/CRE Decoding System/Reproduction/Acris Reproduction/ACRIS DOCUMENTATION NIGHT 2026-09-04.md`.

2026-09-04 (night) — the review of every acris file against the cycle (login: "assure it reflects the current approach that works"). Found and fixed in the shared lane module: the re-entry was resuming the cut batch from the same queue - now the cut batch is dropped at the hang-up and a fresh batch is claimed right before the ramp; the whole width means every worker inside 60 s with nothing landed for 10 s (a partial close keeps landing); served means 300 landings or five minutes; births run on their own thread and the wait is a state the loop re-enters, so a crew's wait or ramp never stalls another crew in the process; the fleet passed 0.5-s births, a 600-s wait and 3 tries to every lane - it now passes the knobs only when given, and its batch is login's 9 plus the monitor / 10 / 10. Nothing of this lane's own changed. Proven again offline and by the simulations.

2026-09-04 (evening) — THE CYCLE (login's design, proven unattended at 14:51-14:58): the hang-up is the whole width failing inside a minute, not the first wave; the wait after it is 60 s with a backoff (×2 refused, ÷2 served); the re-entry claims a fresh batch; four tries. Replaces the 1,800-s ladder of the morning.

2026-09-04 (later) — the entry became a ramp: `--stagger` 0.5 s → 5 s. Two 0.5-s entries were cut at the door inside a minute; a 20-s and a 5-s ramp were served at 7 docs/s on the same door (ACRIS REPRODUCTION.md addendum 19, 10:33-12:08). The door objects to the handshake burst, not to forty lines.

2026-09-04 — the wait after a cut re-set from 600 s to 1,800 s times the try number, from the night of 09-03/04: the golden-day lane file (byte-identical to the file that ran five of the six golden runs) was refused 18 minutes after a cut and served after 30, at the golden rate; the golden day itself was six runs with five cuts (ACRIS REPRODUCTION.md addendum 19). The old lane's supervisor and runbook carry the same window.

2026-09-03 — written from the lane that ran before it (the document floor of `acris_reproduction.py`, `acris_pdf.py`, `night_supervisor.py`), every line read. Proven offline (the drive lookup, the path rule, freshness, the page count, the refusal detector against a real notice page preserved that morning) and by three simulated runs against the live cloud with throwaway rows and no ACRIS request: the loop (claim → fetch → land → counters → claims released → heartbeat → outbox → a width change → a limit stop), the guards (a second start refused, a parked lane refused, a zero-width crew refused), and the two stop policies (hang-up → redial → redial → park, exit 3; refusal → park at once, exit 2, restart refused). Not yet proven: a real fetch. The cloud table holds no rows until the data moves in, which is the last step, after every lane's code is done and connected.
