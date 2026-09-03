"""ACRIS DOCUMENTATION - one program.

Batches ONE group of N workers through a SINGLE entry under the current IP (one pooled session, one
connection per worker at birth, keep-alive after, no further handshakes), fetches each claimed
document by minted access, saves it to the drive named by --drive, and records its full One Touch
path in the `document` cell - or the verdict word: pending (recorded in the last --fresh-days, no
image yet) or absent (checked: none).

    python documentation.py --drive NYCCRED1            home
    python3 documentation.py --drive NYCCRED2           workstation 2

The rules are kept from the lane that ran before this one (ACRIS REPRODUCTION.md is the authority):

  failures    a fetch error never stops the lane: the document stays empty for a later pass and the
              reason is written to documentation.fails.jsonl
  retries     a viewer page without a page count is re-asked 3x in place (a soft refusal, not a
              verdict); a short document (fewer pages than promised) is never a pdf
  refusal     HTTP 200 + the Bandwidth Notice page = a block: park at once, no retry, no rotation
  hang-up     every line dropped at once = dead transport: redial (wifi down waits; 3 tries per
              incident, --redial-wait apart), then park with the reason
  wall        40 consecutive 503/429 with no success between: park with the reason
  width       --width at launch; while running, write `width=30` into documentation.control (workers
              above the number park, missing ones are born staggered); `stop` there stops cleanly
  mega lane   --also registration:40 hosts another lane's crew in this process, entered --entry-gap
              later through its own session (one entry per floor, as measured)
  no overlap  claim() hands this workstation its own slice; land() fills the cells once a minute,
              buffered in documentation.outbox.jsonl until the cloud takes them; heartbeat() every
              minute carries the width and the last word

The shared pieces it imports: ../../../lane.py (the entry and the policies), ../../../cloud.py (claim,
land, heartbeat), ../../../storage.py (the drive by label, the One Touch layout), ../../acris.py (the
ACRIS rules: URLs minted from the id, the one user-agent, the refusal detector, where a document files).
"""
import argparse
import importlib
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # documentation -> workflow -> Acris -> Reproduction
sys.path.insert(0, str(PHASE))
sys.path.insert(0, str(PHASE / "Acris"))

import img2pdf                                                  # noqa: E402
import acris                                                    # noqa: E402
import lane                                                     # noqa: E402
import storage                                                  # noqa: E402


class Documentation:
    """What one worker does with one document."""
    source, lane_name = "acris", "documentation"
    ua = acris.UA

    def __init__(self, drive_root, fresh_days):
        self.root = drive_root
        self.fresh_days = fresh_days

    @property
    def lane(self):
        return self.lane_name

    def fetch(self, crew, doc_id, registry):
        if not isinstance(registry, dict):
            # no recorded details yet: the document cannot be placed (borough, year, month) or judged
            # fresh; it waits for registration - not one request is spent on it
            raise lane.Retry("no registry yet (%s)" % (registry if registry else "empty"))
        canon = acris.canonical_path(doc_id, registry)
        path = storage.local(self.root, canon)
        if path.is_file() and path.stat().st_size > 0:
            return canon                                     # already on this drive: no request spent

        # 1. the page count, from the viewer page (Referer chain as a browser walks it: detail -> viewer -> image)
        total = None
        for attempt in range(3):
            body, ct = crew.get(acris.viewer_url(doc_id), acris.detail_url(doc_id))
            acris.check_refused(body, ct, doc_id)
            total = acris.total_pages(body)
            if total is not None:
                break
            with crew.lock:
                crew.stats["reask"] += 1
            time.sleep(0.6 * (attempt + 1))
        if total is None:
            raise lane.Retry("viewer page did not identify itself after 3 asks (%d bytes, ct=%s)" % (len(body), ct))
        if total <= 0:
            return "pending" if acris.fresh(registry, self.fresh_days) else "absent"

        # 2. every page, in order; the placeholder is the end marker, anything not a TIFF ends the walk
        frames, why = [], ""
        for p in range(1, total + 1):
            data, ct = crew.get(acris.image_url(doc_id, p), acris.viewer_url(doc_id))
            acris.check_refused(data, ct, "%s p%d" % (doc_id, p))
            if acris.is_placeholder(data):
                why = "placeholder (end marker) at page %d" % p
                break
            if not acris.is_tiff(data):
                why = "non-TIFF at page %d: ct=%s len=%d" % (p, ct, len(data))
                break
            frames.append(data)
        if len(frames) != total:
            raise lane.Retry("short: %d/%d pages - %s" % (len(frames), total, why))

        # 3. the file, written whole or not at all
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / (path.name + ".part")
        tmp.write_bytes(img2pdf.convert(frames))
        os.replace(tmp, path)                            # whole or not at all: never a truncated pdf in the store
        return canon


def role_for(name, drive_root, args):
    """--also <lane>:<width>: the sibling lane file's role, in this process (its own session)."""
    if name == "documentation":
        return Documentation(drive_root, args.fresh_days)
    sib = HERE.parent / name / ("%s.py" % name)
    if not sib.is_file():
        raise SystemExit("no lane file for --also %s (expected %s)" % (name, sib))
    sys.path.insert(0, str(sib.parent))
    return importlib.import_module(name).role(drive_root, args)


def main():
    ap = argparse.ArgumentParser(description="acris documentation: one entry, N workers, the cloud table as the to-do list")
    ap.add_argument("--drive", required=True, help="label of the drive to write to (NYCCRED1 at home, NYCCRED2 on workstation 2)")
    ap.add_argument("--width", type=int, default=40, help="workers = connections (default 40)")
    ap.add_argument("--host", default="", help="this workstation's name in the cloud (default: the machine name)")
    ap.add_argument("--fresh-days", type=int, default=30, help="a document recorded within this many days with no image is pending, not absent")
    ap.add_argument("--stagger", type=float, default=0.5, help="seconds between worker births")
    ap.add_argument("--claim", type=int, default=500, help="documents taken per claim")
    ap.add_argument("--ttl", default="20 minutes", help="how long a claim is ours before it goes back on the list")
    ap.add_argument("--pending-age", default="1 day", help="how old a pending must be before it is re-asked")
    ap.add_argument("--redial-wait", type=int, default=600, help="seconds to wait after a hang-up before re-entering")
    ap.add_argument("--tries", type=int, default=3, help="redials per incident before parking")
    ap.add_argument("--entry-gap", type=float, default=20.0, help="seconds between one crew's entry and the next (--also)")
    ap.add_argument("--also", action="append", default=[], metavar="LANE:WIDTH", help="host another lane's crew too, e.g. registration:40")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many documents (a test run)")
    ap.add_argument("--log", default="", help="also append the printed lines to this file")
    ap.add_argument("--unpark", action="store_true", help="start although the lane parked itself (a person has decided)")
    args = ap.parse_args()
    args.lane = "documentation"

    drive_root = storage.find_drive(args.drive)
    storage.documents_root(drive_root)
    roles = [(Documentation(drive_root, args.fresh_days), args.width)]
    for spec in args.also:
        name, _, w = spec.partition(":")
        roles.append((role_for(name.strip(), drive_root, args), int(w or 40)))
    print("drive %r -> %s ; documents under %s ; cell records %s..." % (args.drive, drive_root, storage.documents_root(drive_root), storage.CANON_ROOT), flush=True)
    sys.exit(lane.run(roles, args, HERE))


if __name__ == "__main__":
    main()
