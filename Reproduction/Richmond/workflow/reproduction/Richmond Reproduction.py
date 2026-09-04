"""RICHMOND REPRODUCTION - the fleet: the source's lanes together, one program.

Each lane is its own program (Richmond Synchronization.py, Richmond Registration.py, Richmond
Documentation.py) with its own lock, park, control file and log.  This program launches them together,
in order, one door at a time, and watches them: it relaunches what a relaunch can cure and never
relaunches what a person must decide.  The machinery is ../../../fleet.py, shared with every source;
this file is the richmond site: its lanes in the cycle's order, their widths, its edge.

    python "Richmond Reproduction.py" --drive NYCCRED1 --edge 2026-08-25      the cycle at home: synchronization x4, registration x4,
                                                                              documentation x8 - one process per lane, launched --entry-gap apart
                                                                              (--edge only on the very first start: the last day walked)
    python "Richmond Reproduction.py" --drive NYCCRED2 --lanes documentation:8
                                                                              workstation 2: documentation only - synchronization and
                                                                              registration WALK the county's listing, and two walkers of the
                                                                              same window would spend the county's requests twice (one station)
    python "Richmond Reproduction.py" status                                  this machine's lanes, and every workstation's heartbeats in the cloud
    python "Richmond Reproduction.py" stop [lane]                             `stop` into the control file(s); waits for the lanes to leave; then force
    python "Richmond Reproduction.py" width documentation=24                  a width into a lane's control file (read within a minute)

This file's own authority is Richmond Reproduction.md beside it (the cycle's authority; section 0 is
this program).  The rules of lanes together are written once in fleet.py's docstring.  What is
richmond's own here: three small crews (the county has no metronome, latency is its backpressure, and
the listing walk is one door by nature), births 0.4 s apart (the county's measured handshake stagger,
set in each lane); --edge is a DATE (YYYY-MM-DD), handed to synchronization and registration on a first
start; documentation's pending window is the measured 7-day scan lag.  The cycle the lanes inherit from
lane.py is DORMANT at this county (no session close was ever measured here - login: "richmond can just
enter and hammer"); it fires only when the wire itself dies.

Exit codes: 0 stopped · 2 a lane was refused (everything stilled) · 5 crash.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
WORKFLOW = HERE.parent                            # reproduction -> workflow
PHASE = HERE.parents[2]                           # reproduction -> workflow -> Richmond -> Reproduction
sys.path.insert(0, str(PHASE))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))

import fleet                                                    # noqa: E402
import richmond                                                 # noqa: E402

SOURCE = "Richmond"
LANES = ("synchronization", "registration", "documentation")    # the cycle's order
WIDTHS = {"synchronization": 4, "registration": 4, "documentation": 8}       # 8 pullers measured faster than 16 (rc_bench 2026-08-25)
EDGE_HELP = "first start only: the last day (YYYY-MM-DD) synchronization and registration walked"
FRESH_DAYS = richmond.IMAGE_LAG_DAYS


def site():
    """Read at call time so a test may point WORKFLOW / HERE elsewhere."""
    return fleet.Site(SOURCE, LANES, WIDTHS, WORKFLOW, HERE, edge_lanes=("synchronization", "registration"))


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
    sys.exit(fleet.main(site(), "richmond reproduction: the source's lanes together", str, EDGE_HELP, FRESH_DAYS))


if __name__ == "__main__":
    main()
