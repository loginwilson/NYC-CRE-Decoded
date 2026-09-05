"""RICHMOND UPDATE - the board, one program, always running, reading only.

Two tabs in the cloud: reproduction.richmond_update (tab 1: the phase - rows with all three cells filled
against rows) and reproduction.richmond_update_lanes (tab 2: one row per lane - that lane's cells filled
against rows, with the lane's heartbeats folded in).  Every minute this program reads the counters
that land() and insert_ids() keep exact, subtracts them from its own readings a minute and five
minutes back, and writes rate, increase, percentage, eta, status and the as-of stamp.  It never counts
the workflow table.

    python "Richmond Update.py"                 the board: a tick every 60 s until stopped
    python "Richmond Update.py" --once          one tick, written
    python "Richmond Update.py" show            read and print the two tabs; nothing written
    python "Richmond Update.py" reconcile       recount landed and needed from the table's indexes and overwrite
                                                the counters: after the data move, after a hand edit - never on the tick

This file's own authority is Richmond Update.md beside it; the shared rules are in ../../board.py.

The status of a row is computed, never hand-set:  complete (landed >= needed) · stalled (the lane's
last word is a refusal or a wall; the phase when any lane's is) · active (the counters moved in the
window) · pending (everything else: no fresh heartbeat, or alive with nothing landing yet).  eta
follows the status.  A counter outside 0..needed is never clamped: the metrics go null and the row
says to run reconcile.

Run one board per source; its as_of stamp is its pulse.  Exit codes: 0 stopped · 5 crash.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[1]                       # update -> Richmond -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager

import board                                                    # noqa: E402

SOURCE = "richmond"
LANES = ("synchronization", "registration", "documentation")


def main():
    ap = argparse.ArgumentParser(description="richmond update: the board - reads the counters and the heartbeats, writes the two tabs")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "show", "reconcile"])
    ap.add_argument("--every", type=int, default=60, help="seconds between ticks")
    ap.add_argument("--once", action="store_true", help="one tick, then exit")
    ap.add_argument("--fresh", type=int, default=180, help="a heartbeat older than this many seconds is not alive")
    ap.add_argument("--host", default="", help="this workstation's name (default: the machine name)")
    args = ap.parse_args()
    b = board.Board(SOURCE, LANES, HERE, args)
    if args.command == "show":
        sys.exit(b.show())
    if args.command == "reconcile":
        sys.exit(b.reconcile())
    sys.exit(b.run())


if __name__ == "__main__":
    main()
