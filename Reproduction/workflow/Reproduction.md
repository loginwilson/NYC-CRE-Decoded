# REPRODUCTION

> The phase: every public real-estate record source reproduced into one place - the registered data in one cloud
> database (schema `reproduction`), the documents on the One Touch, and the code that keeps both current. It is the
> first of three (REPRODUCTION → CONSTRUCTION → PRODUCTION) and the only one that exists yet. This file is the phase's
> authority; `Reproduction.py` beside it is the phase run as one program.

> **Three levels (login 2026-09-05).** A **lane** is one program in its own folder with its own lock, park, control
> file and log (`Acris Documentation.py`). A **source** is its lanes together, configured in its fleet program
> (`Acris Reproduction.py`: the batch of 9 / 10 / 10 with documentation managed; `Richmond Reproduction.py`: 4 / 4 / 8
> at fixed widths). **The phase** is every source's fleet, kicked off as each is configured - `Reproduction.py`. Each
> level is a folder with the same three folders inside - `rulebook/`, `workflow/`, `update/` - and nothing loose.

## 0 · THE PHASE PROGRAM — `Reproduction.py` (2026-09-05)

    python Reproduction.py --drive OneTouch                                every source's fleet as configured, one fleet at a time, --source-gap s apart, then the watch
    python Reproduction.py --drive OneTouch --sources acris                these sources only
    python Reproduction.py --drive OneTouch --richmond "--edge 2026-08-25" --acris "--lanes documentation:40"
                                                                           a source's own arguments, handed to its fleet whole
    python Reproduction.py status                                          every source: this machine's lanes, every workstation's heartbeats
    python Reproduction.py stop [source]                                   `stop` through each fleet: the lanes finish their minute and leave

| rule | what the phase does | origin |
|---|---|---|
| a source is its fleet program | the phase finds `<Source>/workflow/reproduction/<Source> Reproduction.py` under the phase folder, alphabetical, and knows nothing else about a source; adding a source is adding its folder | login: "reproduction py is essentially the fleet launch in a way that can know if the acris reproduction is configured say 1 batch 10x10x10 and Richmond say just 8 batches" |
| configuration lives in the fleet | the phase hands each fleet `--drive`, `--host` and the source's own arguments (`--acris "..."`, `--richmond "..."`), nothing else; widths, order, managed lanes, the edge type are the fleet program's | one place per fact: the site table in each `<Source> Reproduction.py` |
| one phase per machine | `reproduction.lock` beside the program; a second start is refused (exit 1), the first left alone | the same fail-closed lock every lane and fleet takes (`lane.take_lock`) |
| one fleet per source, `--source-gap` apart | fleets launched 20 s apart, each its own process with its own lock, log and watch | two sources are two doors, never one moment |
| a fleet's exit is its word | 0 every lane left cleanly · 1 refused to start · 2 a lane was REFUSED and the fleet stilled the rest · 5 crash. The phase relaunches nothing; one source's refusal leaves the other fleets running; when the last fleet has left the phase leaves with the worst word it heard (2 over 5 over 1 over 0) | a fleet already relaunches what a relaunch can cure; what it leaves on is a decision for a person |
| stop | Ctrl+C or `stop`: each fleet is told to stop (a break signal on Windows, SIGTERM elsewhere) and stops its lanes as it does alone - `stop` into every control file, a 180-s grace, then force; a fleet still up after `--stop-wait` (240 s) is terminated and its lanes finish on their own locks | the lanes' minute is theirs |
| logs | `reproduction.log` beside the program (the phase's lines); `<source>.log` beside it (each fleet's console) - appended, never truncated | a live log was truncated once, 2026-09-03 |

Exit codes: 0 every fleet left cleanly · 1 refused to start · 2 a fleet was refused by its source · 5 crash. Proven
offline by `test_reproduction.py` beside it (fake fleets in a temp tree: discovery, the arguments handed whole, a
refusal at one source while the other runs on, the stop, the lock, status and stop through each fleet) - `python
test_reproduction.py`, nothing asked of any source.

## 1 · THE LAYOUT

```
Reproduction/
  rulebook/     lane.py · fleet.py · board.py · cloud.py · storage.py · rate_manager.py · requirements.txt   the rules every lane of every source shares (Rulebook.md)
                schema/                                                                                    the phase's tables as numbered SQL, one file per dictated decision
  workflow/     Reproduction.md · Reproduction.py                                                          this file, and the phase run as one program
  update/       Update.md                                                                                  the phase board across sources (a later SQL decision)
  <Source>/
    rulebook/           <source>.py · <Source>.md                                          the source's rules as one module, and its authority
    workflow/
      reproduction/     <Source> Reproduction.md · <Source> Reproduction.py     the source's written authority and its lanes together as a fleet
      enumeration/      <Source> Enumeration.md · <Source> Enumeration.py       the audit, not a cycle lane
      synchronization/  <Source> Synchronization.md · <Source> Synchronization.py
      registration/     <Source> Registration.md · <Source> Registration.py
      documentation/    <Source> Documentation.md · <Source> Documentation.py
    update/             <Source> Update.md · <Source> Update.py                 the board: one program, two tabs in Supabase
```

Every folder that holds code holds a **pair**: the md is that thing's own authority (what it does, its rules, its
calibrations, its history), the py is its one program, runnable alone from its folder - `python "Acris
Documentation.py" --drive OneTouch` is the whole command. A proof sits beside what it proves (`test_*.py`) and asks
nothing of any source. A source folder is its three folders and nothing loose; the phase folder is its three folders
and the sources, and nothing loose; the database's pair is the project's, in `supabase/` at the repo's root.

The reproduction pair of a source is the cycle: its py is the fleet - one process per lane by default, launched one
door at a time and watched (`--mega` hosts the crews in one process) - built on the rulebook's `fleet.py`. Each cycle
lane claims its slice from the cloud table, fills its cells once a minute and clocks in with a heartbeat. The rulebook
is written once so a rule fixed there reaches every lane on every workstation; what it holds is in
`../rulebook/Rulebook.md`.

## 2 · THE SOURCES AS CONFIGURED

| source | fleet program | the batch | managed |
|---|---|---|---|
| acris | `Acris/workflow/reproduction/Acris Reproduction.py` | synchronization x9 (+ its monitor = login's 10), registration x10, documentation x10; `--edge` is a CRFN | documentation runs under the three managers (the fleet's `MANAGE` table: ramp from one worker until the band 5 / 6-7 / 8 docs/s, the request ceiling 60/s as a projection, the session ends at 1,000,000 requests and re-enters on a fresh batch) |
| richmond | `Richmond/workflow/reproduction/Richmond Reproduction.py` | synchronization x4, registration x4, documentation x8, births 0.4 s apart; `--edge` is a date; workstation 2 runs documentation only | none: the county has no metronome, latency is its backpressure; the cycle is dormant there |

The knob is in the fleet program, never in the phase and never in the lane's code. The full account of each source is
its own `<Source> Reproduction.md`.

## 3 · THE DATABASE

One Supabase project, one schema per phase: `reproduction`. Per source a workflow table (`acris`, `richmond`; one row
per document: `source` in front, then the three cells `doc_id` · `registry` · `document`), two update tabs (`*_update`, `*_update_lanes`), a
claims table and a heartbeats table; the functions `claim()`, `land()`, `heartbeat()`, `reconcile()` hold the
cooperation rules so every workstation gets them by construction. The dictated concept is the section "The table" of
`../rulebook/Rulebook.md`; the phase's schema is `../rulebook/schema/`, one numbered SQL file per dictated decision,
applied and recorded by the project's program (`python ../../supabase/supabase.py push`; the database as a whole is
`../../supabase/Supabase.md`). A master view over the sources' update tables is the phase board's later decision
(`../update/Update.md`).

## History

2026-09-05 — Created with the phase program, on login's three levels ("there's lane level ... source level ... the
entire phase itself code, which would kick off all reproductions ... I don't think they should be loose folders")
and the approved shape ("I like the rulebook workflow update approach ... and then you have all the sources
underneath"). The phase's shared modules moved from loose files at the phase level into `rulebook/`, the schema doc
into `supabase/`, and the phase README folded into this file.

2026-09-05 — The database folder left the phase (login: "supabase shouldn't even be in reproduction"): its SQL to
`../rulebook/schema/`, its dictated concept into `../rulebook/Rulebook.md`, its proof to `../rulebook/test_schema.py`,
its program to the root (`supabase/supabase.py` · `supabase/Supabase.md`); the CLI's files retired.
