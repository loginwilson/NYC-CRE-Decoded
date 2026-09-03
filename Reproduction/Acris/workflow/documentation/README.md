# Acris — documentation

One program: `documentation.py`. It batches one group of N workers through a single entry under the current IP; each worker fetches documents by minted access, saves them to the drive and records the full One Touch path in the `document` cell (the path, or `pending`, or `absent`). The redial policy, the notice-page self-park, the dead-transport breaker, the heartbeat and the claim/land calls all live inside it. Nothing else runs for this lane.

Launch, on any workstation:

    python documentation.py --width 40

The same file runs on workstation 2. What differs per machine is one untracked settings file (host name, drive root, width); the claims table hands each machine its own slice, so the two never overlap.

Status: `documentation.py` is being written from the lane that runs today (the old decoder folder, old database). Until it lands here, that old lane is what runs.
