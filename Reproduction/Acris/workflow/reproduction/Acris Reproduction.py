"""ACRIS REPRODUCTION - the fleet: the source's lanes together, one program.

Each lane is its own program (Acris Synchronization.py, Acris Registration.py, Acris Documentation.py)
with its own lock, park, control file and log.  This program launches them together, in order, one
door at a time, and watches them: it relaunches what a relaunch can cure and never relaunches what a
person must decide.  The machinery is ../../../rulebook/fleet.py, shared with every source; this file is the
acris site: its lanes in the cycle's order, their widths, its edge.

    python "Acris Reproduction.py" --drive OneTouch                       ONE BATCH (login 2026-09-06): synchronization x5 + registration x5 + documentation x5 in
                                                                          ONE process on ONE entry - one ramp from the first worker to the last (5 s apart), one
                                                                          hang-up, one re-entry from the top, no rate manager ("stay low and be patient")
    python "Acris Reproduction.py" --lanes synchronization:10,registration:20
                                                                          the widths by login's word (Gate 3: sync + registration, 30 in one batch)
    python "Acris Reproduction.py" --drive OneTouch --lanes documentation:40
                                                                          ONE lane alone: its own managers (the rate manager finds the ceiling) - a lane alone is maximized
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
# THE BATCH (login 2026-09-04): "1 batch of 10 sync (1 monitor, 9 walkers), 10 registers, 10 documenters"; 2026-09-06: ONE BATCH
# with the worker types inside it, "a 5 would work ... I could just tell you, change the workers to 10, 10, 10" - the widths are
# login's word, on the command line (--lanes) or here.  The monitor is synchronization's main-thread feed, not a connection.
WIDTHS = {"synchronization": 5, "registration": 5, "documentation": 5}
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
    # ONE BATCH (login 2026-09-06): "with Acris you can only have one batch that enters" - the crews in one process on one entry,
    # the hosted crews with --one-batch and without manager knobs; a lane run alone keeps its managers (MANAGE) and is maximized.
    return fleet.Site(SOURCE, LANES, WIDTHS, WORKFLOW, HERE, edge_lanes=("synchronization",), manage=MANAGE, one_batch=True, mega_default=True)


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
