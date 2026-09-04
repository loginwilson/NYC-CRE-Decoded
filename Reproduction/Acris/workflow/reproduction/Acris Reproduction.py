"""ACRIS REPRODUCTION - the fleet: the source's lanes together, one program.

Each lane is its own program (Acris Synchronization.py, Acris Registration.py, Acris Documentation.py)
with its own lock, park, control file and log.  This program launches them together, in order, one
door at a time, and watches them: it relaunches what a relaunch can cure and never relaunches what a
person must decide.  The machinery is ../../../fleet.py, shared with every source; this file is the
acris site: its lanes in the cycle's order, their widths, its edge.

    python "Acris Reproduction.py" --drive NYCCRED1                       the cycle: synchronization x20, registration x40,
                                                                          documentation x40 - one process per lane, launched --entry-gap apart
    python "Acris Reproduction.py" --drive NYCCRED1 --lanes registration:40,documentation:40
    python "Acris Reproduction.py" --drive NYCCRED1 --mega                the same crews in ONE process (one entry per crew, --entry-gap apart)
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
sys.path.insert(0, str(PHASE))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))

import fleet                                                    # noqa: E402

SOURCE = "Acris"
LANES = ("synchronization", "registration", "documentation")    # the cycle's order
WIDTHS = {"synchronization": 20, "registration": 40, "documentation": 40}
EDGE_HELP = "synchronization's first start: the last CRFN whose document the table holds"
FRESH_DAYS = 30


def site():
    """Read at call time so a test may point WORKFLOW / HERE elsewhere."""
    return fleet.Site(SOURCE, LANES, WIDTHS, WORKFLOW, HERE, edge_lanes=("synchronization",))


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
