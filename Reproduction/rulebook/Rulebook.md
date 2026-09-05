# THE RULEBOOK

The phase's shared modules: a rule is written once here and every lane of every source on every workstation gets it.
A source's own rules - its URLs minted from the id, its one user-agent, its refusal detector, where its documents file
- live in `<Source>/rulebook/` (`acris.py` · `Acris.md`, `richmond.py` · `Richmond.md`); nothing about one source is
in here. Every module's docstring is its own authority: the rules, the numbers and where each was measured. This file
says what each module is for and how a program reaches it.

| module | job | proof |
|---|---|---|
| `lane.py` | THE ENTRY every cycle lane shares. A lane file defines a ROLE (what one worker does with one document) and hands it to `run()`, which owns the rest: one pooled session per crew, births `--stagger` apart with one connection each, claim / land / heartbeat once a minute through the outbox, failures that never stop the lane, the refusal park (HTTP 200 + the notice page), the hang-up and the re-entry on a fresh batch, the wall, the width control file, the mega lane, one door per lane. The three managers as knobs (`--manage`, default off): the ramp from one worker, the rate manager's windows, the session cap | `test_managers.py` (the lane's wiring of the managers through the whole loop) |
| `fleet.py` | THE FLEET every source runs: the source's lanes together as one program - one process per lane, one door per lane `--entry-gap` apart, the cycle's order, the watch with the meaning of every exit code, the relaunch cap, a parked lane never relaunched, `status` / `stop` / `width`, one fleet per machine. A source's `<Source> Reproduction.py` is a `Site` (name, lanes, widths, where the programs live, the managers' knobs per lane) and this module | `test_fleet_sim.py` (fake lane programs in a temp tree) |
| `board.py` | THE BOARD every source's update program shares: the counters and the heartbeats read once a minute, one subtraction for rate and increase, every percentage over needed, the four computed statuses, never a clamp, never a scan on a tick | `test_board_offline.py` (the arithmetic), `test_board_sim.py` (the live tabs with throwaway counters) |
| `cloud.py` | THE CLOUD TABLE from a lane's point of view: `claim`, `land`, `heartbeat` as one round trip each to the functions in the migrations, the registries, and the local outbox so a cloud hiccup loses nothing. One connection per lane process, the main thread only | `test_lane_sim.py`, `test_lane_policies.py` (throwaway rows on the live table) |
| `storage.py` | WHERE A DOCUMENT LIVES: the drive found by its label on Windows or Mac, the One Touch layout `<source>\<borough>\<year>\<month>\<id>.pdf`, recorded in canonical `D:\` form whichever machine fetched the file | `test_offline.py` (the drive lookup and the path rule) |
| `rate_manager.py` | THE RATE MANAGER and the session cap: `next_width()` is pure arithmetic (the graduated hand around the docs band, the request ceiling as a projection at the exit's recent speed, the door curve), the `Governor` thread only calls it and the crew's resize | `test_managers.py` (fake exits at 10x speed: the band, the ceiling, the stall, the door curve, the ramp, the session knob) |
| `requirements.txt` | the one install a workstation needs: `pip install -r requirements.txt` | |

## How a program reaches it

Every lane, fleet and board program carries one path line and imports by name:

    PHASE = HERE.parents[2]                           # <lane> -> workflow -> <Source> -> Reproduction
    sys.path.insert(0, str(PHASE / "rulebook"))       # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager
    sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
    import cloud, lane, storage, acris

A second workstation clones the repo and runs the same file; there is no install step beyond `requirements.txt` and
the env file (`C:/dev/nyc-cre-decoded.env` at home, `~/nyc-cre-decoded.env` on a Mac, or `NYC_CRE_DECODED_ENV`),
which is never committed or printed.

## The proofs

`python test_managers.py` runs the managers' proof offline - fake exits, a fake cloud, nothing asked of any source; its
last line is `THREE MANAGERS: ALL OK`. The simulations named above run the shared modules against fake lane programs
or throwaway rows on the live cloud table (never a source); each one says in its first line what it touches.

## History

2026-09-05 — The six modules and their proof moved here from loose files at the phase level (login: "I don't think
they should be loose folders. I don't like that"), so the phase has the same three folders a source has. Nothing in
the modules changed with the move; the twelve programs' path line changed from `PHASE` to `PHASE / "rulebook"`.
2026-09-04/05 — `rate_manager.py` added: the three managers as knobs, live on the home workstation since 2026-09-04
19:37 (the night's record: `D:/CRE Decoding System/Reproduction/Acris Reproduction/ACRIS DOCUMENTATION NIGHT
2026-09-04.md`).
