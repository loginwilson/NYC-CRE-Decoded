# Richmond Documentation

The documentation lane of the richmond reproduction, as one program: `Richmond Documentation.py`. It batches one group of N workers through a single entry; each worker mints a document's image on the clerk, pulls the pdf from the NY State courts viewer in the same breath, saves it to the drive and records the full One Touch path in the `document` cell — the path, or `pending`, or `absent`. Nothing else runs for this lane. The cycle it belongs to is written in `../reproduction/Richmond Reproduction.md`; this file is the lane's own authority: what it does, its rules, its calibrations, its history.

## Launch

    python "Richmond Documentation.py" --drive NYCCRED1          home
    python3 "Richmond Documentation.py" --drive NYCCRED2         workstation 2

The same file runs on every workstation. `--drive` names the drive by its label. `--width` defaults to 8 (the measured pull width on the courts host). While it runs, `documentation.control` beside it takes `width=N` or `stop`. `--also registration:4` hosts the registration crew in the same process through its own entry. `--limit N` is a test run. A lane that parked itself refuses to start again until `--unpark`.

## Two hosts, three outcomes

The image is minted on the clerk and served by the courts, and the mint's answer is read with redirects OFF:

| the mint answers | meaning | the lane does |
|---|---|---|
| 302 with an **absolute** url on `iapps.courts.state.ny.us` (`viewer?token=v2…`) | the scan is up; the token is self-authenticating and expires in ~10 minutes | pulls it at once, same worker, same breath |
| 302 with a **relative** Location (`/Search/SearchError`), or 200, or 404 | the endpoint answered and there is no image | `pending` inside `--fresh-days`, else `absent` — unless the registry's own reading says the image is **present**, in which case the odd one out is us and the document is asked again |
| 403, 429, 5xx | about us, never about the document | asked again (429/503 count toward the wall) |

Measured 2026-08-26 on one session: RC_2825613 (image up) → 302 to the courts viewer; RC_2820269 (no image) → 302 `/Search/SearchError`. "Any Location at all" was the wrong test and once handed the clerk's error page to the puller.

The pull carries the project's honest user-agent: the courts host **hangs** the library-default UA (ReadTimeout at 45 s, 2/2) and serves the honest one (200 + the pdf in 1.5 s, 2/2; measured 2026-08-22). A browser string was measured to buy nothing. A body is a pdf only when it starts with `%PDF`; anything else is never written or recorded.

## The rules

| rule | what the lane does | origin |
|---|---|---|
| one entry | one pooled session, one connection per worker at birth, keep-alive after; the courts host gets a pool of its own so switching hosts never re-handshakes; the clerk's front door is fetched once for its cookies | lane.py; rc_lane's per-host pools |
| the cell | the canonical One Touch path, or `pending` (no image, recorded inside the lag) or `absent` (checked, none); nothing else enters the cell | login 2026-09-03, the cell rule |
| placement | `D:\CRE Decoding System\Documents\richmond\<year>\<month>\<id>.pdf` — no borough; year and month from the RECORDED date, else `undated` | corpus_paths: recorded is the axis, the id is a submission sequence |
| no registry, no request | a row without a registry cannot be placed or judged fresh; it waits for registration | the acris rule, same reason |
| already on disk | a file already under this drive is recorded without a request | relaunch recovery |
| two sources agree | `absent` needs the registry's `image_state` to agree; a registry that says present sends the document back to be asked again | rc_lane._no_image, 2026-08-26 |
| unreadable date | a recorded date the lane cannot read keeps the document `pending`, never `absent` | rc_lane._in_lag |
| whole or nothing | the pdf is written to a `.part` file and renamed | 2026-09-03 |
| restricted vs refused | a 401/403 from the courts host is ambiguous: sealed records refuse at any rate. Every worker holds `--cooldown`, then ONE probe of a **different** claimed document decides — probe served: the document is RESTRICTED, its evidence goes to `documentation.restricted.jsonl`, the cell records `absent`, it is never asked again (the list survives a restart); probe also refused: the lane is refused — park, exit 2, no retry, no rotation | rc_lane.refusal_verdict; RC_1873622 (an exhibit filed to the City) silenced a 190,594-document run on 2026-08-24 — "richmond should never have stalled" |
| refusal on the clerk | a captcha, access-denied or block page on the mint: park at once, exit 2 | richmond.check_refused |
| failures never stop it | a fetch error leaves the document empty for a later pass and writes the reason to `documentation.fails.jsonl` | login 2026-09-03 |
| hang-up, wall, width, one door, drive, pending recheck, no overlap, the last word | shared with every lane: a burst of cut lines hangs up at once, waits out the window with no line open, re-enters once behind a settled exit pool; 40 consecutive 503/429 park the lane; `documentation.lock`; the drive checked every minute; pendings re-asked after `--pending-age`; the claim table hands each workstation its slice; every stop leaves its reason | lane.py; §17 addendum 17 |

## Calibrations

| knob | value | how it was measured, how it fails |
|---|---|---|
| width | 8 | rc_bench 2026-08-25, one variable: 8 pullers → 28.23 docs/s, 16 → 18.76 (past the pipe, self-contending); richmond has no metronome — latency is the backpressure |
| fresh-days | 7 (`richmond.IMAGE_LAG_DAYS`) | 10 of 10 documents recorded on a Friday read no-image then and present after the weekend; the nightly maturation used the same 7 |
| cooldown | 600 s | the hold before the one probe; long enough that a rate reaction on the courts host has passed |
| token | mint and pull back to back | tokens minted ahead expired (~10 min): 786 dead tokens one morning, 2026-08-22 |
| timeouts | mint 60 s; pull (10 s connect, 90 s read), streamed | a 5 MB pdf is read chunk by chunk, so the read timeout is per chunk |
| pending-age | lane.py's default | one request per pending per interval; the old lane re-asked its pending set every 5 minutes |

## Working files

Beside this file, never in git: `documentation.lock`, `documentation.control`, `documentation.parked`, `documentation.outbox.jsonl`, `documentation.fails.jsonl`, `documentation.restricted.jsonl` (the verdict evidence: id, code, probe, time). Exit codes: 0 stopped · 2 refused · 3 redials exhausted · 4 wall · 5 crash · 6 drive gone.

## What it imports

`Reproduction/lane.py`, `Reproduction/cloud.py`, `Reproduction/storage.py`, `Reproduction/Richmond/richmond.py` (the mint url and its referer, the three outcomes, the pull headers, the lag, the path rule, the refusal detector).

## Open decision

A RESTRICTED document is recorded `absent` (checked; the courts host refuses it at any rate) with its evidence kept beside the lane. The old lane left such rows empty and quarantined them only in memory, so every restart re-asked them and held the lane ten minutes each. `absent` lets completion reach 100 % and the evidence file says why; if login prefers a different word for a sealed record, it is one line.

## History

2026-09-03 — written from the lane that ran before it (`rc_lane.py`: the mint's three outcomes, the per-host pools, the token expiry, the honest-UA finding on the courts host, the refusal verdict, `_no_image` and `_in_lag`; `rc_pdf_pull.py`; `rc_source.py`), every line read. Proven offline (`test_richmond_doc_offline.py`: the three outcomes, the path rule, the lag, a pdf minted and pulled and written whole, the session prepared once, no image → pending/absent/asked again, the mint's 503/403/wire/refusal shapes, the pull's html/500/429, the verdict both ways, the restricted list surviving a restart) and by a simulation against the live cloud with throwaway rows and no request to either host (`test_richmond_doc_sim.py`: paths, a pending and an absent landed through the documentation lane, the lane and phase counters moving by the newly filled cells, cleanup + reconcile). Not yet proven: a real mint and pull.
