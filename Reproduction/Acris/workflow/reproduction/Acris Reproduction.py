"""ACRIS REPRODUCTION - the fleet: the source's lanes together, one program.

Each lane is its own program (Acris Synchronization.py, Acris Registration.py, Acris Documentation.py)
with its own lock, park, control file and log.  This program launches them together, in order, one
door at a time, and watches them: it relaunches what a relaunch can cure and never relaunches what a
person must decide.  The machinery is ../../../rulebook/fleet.py, shared with every source; this file is the
acris site: its lanes in the cycle's order, their widths, its edge.

    python "Acris Reproduction.py" --drive OneTouch                       the batch: synchronization x9 (+ its monitor = login's 10), registration x10,
                                                                          documentation x10 - one process per lane, each on its own entry, each running the cycle
    python "Acris Reproduction.py" --drive OneTouch --lanes registration:40,documentation:40
    python "Acris Reproduction.py" --drive OneTouch --mega                the frankenstein run: the same crews in ONE process, one entry per crew, one ramp at a time
    python "Acris Reproduction.py" status                                 this machine's lanes, and every workstation's heartbeats in the cloud
    python "Acris Reproduction.py" stop [lane]                            `stop` into the control file(s); waits for the lanes to leave; then force
    python "Acris Reproduction.py" width documentation=60                 a width into a lane's control file (read within a minute)

This file's own authority is Acris Reproduction.md beside it (the cycle's authority; section 0 is this
program).  The rules of lanes together - one process per lane, one door per lane, the order, what each
exit means, the relaunch cap, a parked lane never relaunched, the logs appended, one fleet per machine,
cross-station status - are written once in fleet.py's docstring.

Exit codes: 0 stopped · 2 a lane was refused (everything stilled) · 5 crash.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
WORKFLOW = HERE.parent                            # reproduction -> workflow
PHASE = HERE.parents[2]                           # reproduction -> workflow -> Acris -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))

import fleet                                                    # noqa: E402

SOURCE = "Acris"
LANES = ("synchronization", "registration", "documentation")    # the cycle's order
# THE BATCH (login 2026-09-04): "1 batch of 10 sync (1 monitor, 9 walkers), 10 registers, 10 documenters".  The monitor is
# synchronization's main-thread feed, not a connection, so its crew is 9 walkers; a lane run alone keeps its own default (40).
WIDTHS = {"synchronization": 9, "registration": 10, "documentation": 10}
# THE THREE MANAGERS on the document lane (login 2026-09-04; live and proven 2026-09-04 19:37 -> 09-05 on the home workstation):
# the batch manager is the cycle itself (one entry on a settled exit pool); the RATE manager enters with one worker, adds one every
# --stagger s until the docs/s meets the band, then adjusts every 120 s - a full step down over 8, half down over 7, hold in 6-7,
# half up under 6, full up under 5, with the record's meter first: the request ceiling (60/s; notices came at 58-81 held for hours)
# read as a projection at the exit's recent speed - retire straight to the cap, never grow past it; a grow that buys nothing (the
# door curve) is undone and held; the SESSION manager ends the session at 1,000,000 requests and the cycle re-enters on a fresh batch.
# Knobs, not code: change a number here (or on the lane's command line), never the manager.  Only documentation is managed: the
# band and the ceiling were measured on the document floor; registration and synchronization keep their fixed widths.
MANAGE = {"documentation": {"manage": 1, "ramp_to_rate": 1, "rate_floor": 5, "rate_ideal_lo": 6, "rate_ideal_hi": 7, "dps_ceiling": 8,
                            "rps_ceiling": 60, "width_min": 20, "width_max": 120, "adjust_every": 120, "adjust_step": 10,
                            "session_max_requests": 1000000}}
EDGE_HELP = "synchronization's first start: the last CRFN whose document the table holds"
FRESH_DAYS = 30


def site():
    """Read at call time so a test may point WORKFLOW / HERE elsewhere."""
    return fleet.Site(SOURCE, LANES, WIDTHS, WORKFLOW, HERE, edge_lanes=("synchronization",), manage=MANAGE)


def parse_lanes(spec):
    return site().parse_lanes(spec)


def Fleet(args):
    return fleet.Fleet(site(), args)


def status(args):
    return fleet.status(site(), args)


def stop(args):
    return fleet.stop(site(), args)


def width(args):
    return fleet.width(site(), args)


def main():
    sys.exit(fleet.main(site(), "acris reproduction: the source's lanes together", int, EDGE_HELP, FRESH_DAYS))


if __name__ == "__main__":
    main()
