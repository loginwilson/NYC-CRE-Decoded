"""ACRIS DOCUMENTATION - one program.

Batches ONE group of N workers through a SINGLE entry under the current IP (one pooled session, one
connection per worker at birth, keep-alive after, no further handshakes), fetches each claimed
document by minted access, saves it to the drive named by --drive, and records its full One Touch
path in the `document` cell - or the verdict word: pending (recorded in the last --fresh-days, no
image yet) or absent (checked: none).

    python "Acris Documentation.py" --drive NYCCRED1            home
    python3 "Acris Documentation.py" --drive NYCCRED2           workstation 2

This file's own authority is Acris Documentation.md beside it; the cycle's is ../reproduction/Acris Reproduction.md.

The rules are kept from the lane that ran before this one:

  failures    a fetch error never stops the lane: the document stays empty for a later pass and the
              reason is written to documentation.fails.jsonl
  retries     a viewer page without a page count is re-asked 3x in place (a soft refusal, not a
              verdict); a short document (fewer pages than promised) is never a pdf
  refusal     HTTP 200 + the Bandwidth Notice page = a block: park at once, no retry, no rotation
  hang-up     the session closed (every worker hit the wire inside 60 s, nothing landed for 10 s): hang up
              at once, drop the cut batch, wait --redial-wait (60 s with the backoff) with no line open, claim
              a fresh batch, re-enter once with births 5 s apart; 4 re-entries per incident, then park
  wall        40 consecutive 503/429 with no success between: park with the reason
  width       --width at launch; while running, write `width=30` into documentation.control (workers
              above the number park, missing ones are born staggered); `stop` there stops cleanly
  mega lane   --also registration:10 hosts another lane's crew in this process through its own session,
              one ramp at a time, --entry-gap apart (one entry per floor, as measured); each crew runs
              the cycle on its own
  pending     goes back to the backfill: a pending is re-checked once its last check is --pending-age old,
              ahead of the empties; when the lane is up to date every claim is pendings, cycling through
              them, so a scan that appears is recorded on the next pass and a document that ages past
              --fresh-days becomes absent on the next pass
  no overlap  claim() hands this workstation its own slice; land() fills the cells once a minute,
              buffered in documentation.outbox.jsonl until the cloud takes them; heartbeat() every
              minute carries the width and the last word
  one door    documentation.lock: a second start on this machine is refused while the first lives
  drive       once a minute the drive must still be there, or the lane parks with the reason

Exit codes: 0 stopped (control file, limit, Ctrl+C, kill) · 2 refused · 3 redials exhausted · 4 wall ·
5 crash · 6 drive gone.  A parked lane refuses to start until --unpark.

The shared pieces it imports: ../../../lane.py (the entry and the policies), ../../../cloud.py (claim,
land, heartbeat), ../../../storage.py (the drive by label, the One Touch layout), ../../rulebook/acris.py
(the ACRIS rules: URLs minted from the id, the one user-agent, the refusal detector, where a document files).
"""
import argparse
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # documentation -> workflow -> Acris -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))

import img2pdf                                                  # noqa: E402
import acris                                                    # noqa: E402
import lane                                                     # noqa: E402
import storage                                                  # noqa: E402


class Documentation:
    """What one worker does with one document."""
    source, lane_name = "acris", "documentation"
    ua = acris.UA
    noun = "pdfs"                 # the PROGRESS line's word for a filled cell
    needs_registry = True         # the registry places the file and judges freshness

    def __init__(self, drive_root, fresh_days):
        self.root = drive_root
        self.fresh_days = fresh_days

    @property
    def lane(self):
        return self.lane_name

    def check(self, ctx):
        """Once a minute: the drive must still be there.  A pulled drive parks the lane instead of
        leaving it fetching with every write failing (trap 5)."""
        if not os.path.isdir(self.root):
            ctx.park("PARKED: the drive %s is gone at %s - plug it back in, then start with --unpark"
                     % (self.root, time.strftime("%Y-%m-%d %H:%M")), code=6)

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
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))          # 0.6 s, then 1.2 s; no wait after the last miss
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
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.parent / (path.name + ".part")
            tmp.write_bytes(img2pdf.convert(frames))
            os.replace(tmp, path)                        # whole or not at all: never a truncated pdf in the store
        except OSError as e:
            if not os.path.isdir(self.root):
                self.check(crew.ctx)
            raise lane.Retry("could not write the file (%s: %s)" % (type(e).__name__, str(e)[:100]))
        return canon


def role(drive_root, args):
    """This lane's role, for a sibling lane hosting it with --also documentation:N."""
    if not drive_root:
        raise SystemExit("documentation needs --drive <label>: the drive its files are written to")
    return Documentation(drive_root, getattr(args, "fresh_days", 30))


def main():
    ap = argparse.ArgumentParser(description="acris documentation: one entry, N workers, the cloud table as the to-do list")
    ap.add_argument("--drive", required=True, help="label of the drive to write to (NYCCRED1 at home, NYCCRED2 on workstation 2)")
    ap.add_argument("--fresh-days", type=int, default=30, help="a document recorded within this many days with no image is pending, not absent")
    lane.add_common_args(ap)
    args = ap.parse_args()
    args.lane = "documentation"

    drive_root = storage.find_drive(args.drive)
    storage.documents_root(drive_root)
    roles = lane.roles_for("Acris", args, HERE, drive_root, Documentation(drive_root, args.fresh_days))
    print("drive %r -> %s ; documents under %s ; cell records %s..." % (args.drive, drive_root, storage.documents_root(drive_root), storage.CANON_ROOT), flush=True)
    sys.exit(lane.run(roles, args, HERE))


if __name__ == "__main__":
    main()
