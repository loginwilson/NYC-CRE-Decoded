# Reproduction

The phase. `SCHEMA.md` is the concept in login's words; `supabase/` holds the phase's migrations, the push script, the SQL executor and the live test. One folder per source holds three folders and nothing loose: `rulebook/` (`<source>.py`, the rules every lane of that source shares - URLs minted from the id, the one user-agent, the refusal detector, where a document files - and `<Source>.md`, that module's authority), `workflow/` and `update/`. Supabase side: schema `reproduction`.

```
<Source>/
  rulebook/           <source>.py · <Source>.md                                          the source's rules as one module, and its authority
  workflow/
    reproduction/     <Source> Reproduction.md · <Source> Reproduction.py     the source's written authority and the whole cycle run as a fleet
    enumeration/      <Source> Enumeration.md · <Source> Enumeration.py       the audit, not a cycle lane
    synchronization/  <Source> Synchronization.md · <Source> Synchronization.py
    registration/     <Source> Registration.md · <Source> Registration.py
    documentation/    <Source> Documentation.md · <Source> Documentation.py
  update/             <Source> Update.md · <Source> Update.py                 the board: one program, two tabs in Supabase
```

Each lane is a pair: the md is that lane's own authority (what it does, its rules, its calibrations, its history), the py is its one program, runnable alone from its folder — `python "Acris Documentation.py" --drive NYCCRED1` is the whole command. The reproduction pair is the cycle: its py is the fleet - one process per lane by default, launched one door at a time and watched (`--mega` hosts the crews in one process) - built on the shared `fleet.py`. Each cycle lane claims its slice from the cloud table, fills its cells once a minute and clocks in with a heartbeat.

Five files every lane shares, so a rule is fixed once and every lane on every workstation gets it: `fleet.py` (the fleet both reproduction programs run on), `board.py` (the board both update programs run on), `lane.py` (the entry: one pooled session per crew, staggered births, failures, retries, the refusal park, the hang-up redial, the wall stop, live width changes, the mega lane, claim/land/heartbeat once a minute), `cloud.py` (the cloud table from a lane's point of view: claim, registries, land, heartbeat, and the local outbox so a cloud hiccup loses nothing), `storage.py` (the drive found by its label on Windows or Mac, and the One Touch layout `source\borough\year\month\id.pdf` recorded in canonical `D:\` form whichever machine fetched the file). `requirements.txt` is the one install a workstation needs.
