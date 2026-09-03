# Acris — documentation

One program: `documentation.py`. It batches one group of N workers through a single entry under the current IP; each worker fetches documents by minted access, saves them to the drive and records the full One Touch path in the `document` cell (the path, or `pending`, or `absent`). The redial policy, the notice-page self-park, the dead-transport breaker, the wall stop, the heartbeat and the claim/land calls all live inside it. Nothing else runs for this lane.

Launch, on any workstation (the label names the drive; the file finds where it is mounted):

    python documentation.py --drive NYCCRED1          home (the drive is labelled OneTouch today; rename it and the word changes)
    python3 documentation.py --drive NYCCRED2         workstation 2

Width defaults to 40 (`--width`). While it runs, `documentation.control` beside it takes `width=30` (workers above the number park after their document, missing ones are born staggered) or `stop`. `--also registration:40` hosts another lane's crew in the same process through its own session, 20 s later: the mega lane. `--limit N` is a test run. A lane that parked itself (refusal, three failed redials, a wall) refuses to start again until `--unpark`.

Its working files live beside it and never enter git: `documentation.outbox.jsonl` (landings the cloud has not taken yet), `documentation.fails.jsonl` (every fetch error with its reason), `documentation.control`, `documentation.parked`, `refusals/` (the page a refusal was called on).

Shared pieces it imports: `Reproduction/lane.py` (the entry and the policies every lane shares), `Reproduction/cloud.py` (claim, land, heartbeat, the outbox), `Reproduction/storage.py` (the drive by label, the One Touch layout), `Reproduction/Acris/acris.py` (the ACRIS rules).

Status 2026-09-03: written from the lane that ran before it, proven offline (the path rule, the freshness window, the page count, the refusal detector against a real preserved notice page) and by a simulated run against the live cloud with throwaway rows (claim → fetch → land → counters → claims released → heartbeat → outbox → width change → limit stop). It has not yet made a request to ACRIS: the cloud table holds no rows until the old database moves in, and the first real run is login's call.
