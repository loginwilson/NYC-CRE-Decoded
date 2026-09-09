"""ACRIS DOCUMENTATION - one program.

Batches ONE group of N workers through a SINGLE entry under the current IP (one pooled session, one
connection per worker at birth, keep-alive after, no further handshakes), fetches each claimed
document by minted access, saves it to the drive named by --drive, and records its full One Touch
path in the `document` cell - or the verdict word: pending (recorded in the last --fresh-days, no
image yet) or absent (checked: none).

    python "Acris Documentation.py" --drive OneTouch            home
    python3 "Acris Documentation.py" --drive <label>           workstation 2

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
              the cycle on its own.  With --one-batch (what the acris fleet passes, login 2026-09-06) the
              hosted crew joins right after this crew's ramp instead, --stagger apart, no --entry-gap, and
              one hang-up or one re-entry closes and reopens the whole batch
  pending     goes back to the backfill: a pending is re-checked once its last check is --pending-age old,
              ahead of the empties; when the lane is up to date every claim is pendings, cycling through
              them, so a scan that appears is recorded on the next pass and a document that ages past
              --fresh-days becomes absent on the next pass
  no overlap  claim() hands this workstation its own slice; land() fills the cells once a minute,
              buffered in documentation.outbox.jsonl until the cloud takes them; heartbeat() every
              minute carries the width and the last word
  one door    documentation.lock: a second start on this machine is refused while the first lives
  drive       once a minute the drive must still be there, or the lane parks with the reason

Exit codes: 0 stopped (control file, limit, Ctrl+C, a signal) · 2 refused · 3 redials exhausted · 4 wall ·
5 crash · 6 drive gone.  A parked lane refuses to start until --unpark.  A hard kill on Windows (the
fleet's terminate after --stop-wait, taskkill /F) ends the process without its last word: the heartbeat
keeps what it said.

The shared pieces it imports: ../../../rulebook/rulebook.py (the entry and the policies; claim, land, heartbeat,
the outbox; the drive by label and the One Touch layout), ../../rulebook/acris.py (the ACRIS rules: URLs
minted from the id, the one user-agent, the refusal detector, where a document files).
"""
import argparse
import json
import os
import pathlib
import requests
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # documentation -> workflow -> Acris -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: rulebook.py, the machinery as one module
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))

import img2pdf                                                  # noqa: E402
import acris                                                    # noqa: E402
import rulebook  # noqa: E402


class Documentation:
    """What one worker does with one document."""
    source, lane_name = "acris", "documentation"
    ua = acris.UA
    noun = "pdfs"                 # the PROGRESS line's word for a filled cell
    needs_registry = True         # the registry places the file and judges freshness

    def __init__(self, drive_root, fresh_days, box=0):
        self.root = drive_root
        self.fresh_days = fresh_days
        self.box = int(box or 0)          # --box PORT: the on-box fetch through a door's droplet (BoxPrefetch below); 0 = from here

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
            raise rulebook.Retry("no registry yet (%s)" % (registry if registry else "empty"))
        canon = acris.canonical_path(doc_id, registry)
        path = rulebook.local(self.root, canon)
        if path.is_file() and path.stat().st_size > 0:
            return canon                                     # already on this drive: no request spent

        # 1. the page count, from the viewer page (Referer chain as a browser walks it: detail -> viewer -> image).
        #
        #    THE VIEWER IS THE ONLY AUTHORITY ON HOW MANY PAGES A DOCUMENT HAS.  Nothing else may set `total`.  This is
        #    not a preference; it was measured on 2026-09-09 after --trust-registry-pages took the count from
        #    registration instead:
        #      - registration UNDERCOUNTS.  It counts the instrument and misses title pages, covers and riders, so a
        #        nine-page document registers as seven and a pdf lands with its tail missing (login).
        #      - registration also OVERCOUNTS, which we did not expect.  2003012101793002 registers as 39 pages; the
        #        viewer says 3, our pdf holds 3, and page 4 is the end marker.  Ten such documents, all complete.
        #      - the viewer has never been wrong when tested: 475 pdfs across twelve years, every count matched.
        #    Registration is the clerk's record of what was FILED.  It is not a record of what ACRIS imaged, and it is
        #    unreliable in BOTH directions.  The flag that trusted it is gone and must not come back.
        total = None
        # THE ON-BOX FETCH (2026-09-08, --box; login: "Try the workers on the droplets"): through a door whose droplet runs
        # box_fetch.py, ONE call brings the viewer page and every page image, fetched ON the box in parallel (ACRIS takes
        # ~11 s per image whoever asks; the box waits, not this machine's RAM).  The walk below then reads them through
        # the same get(url, referer) it reads ACRIS with, so every verdict - the notice, the count, the end marker, TIFF,
        # short - is made HERE exactly as before, and the cell lands only once the pdf is on the drive.  A re-ask or a
        # page the box did not bring goes to ACRIS through the door as before.  No door (the machine's own line): as before.
        getter = BoxPrefetch(crew, self.box, doc_id, total) if (self.box and crew.door) else crew
        for attempt in range(3):
            if total is not None:
                break
            body, ct = getter.get(acris.viewer_url(doc_id), acris.detail_url(doc_id))
            acris.check_refused(body, ct, doc_id)
            total = acris.total_pages(body)
            if total is not None:
                break
            with crew.lock:
                crew.stats["reask"] += 1
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))          # 0.6 s, then 1.2 s; no wait after the last miss
        # A NON-ANSWER IS NEVER A VERDICT.  If the viewer did not say a number - a 404, a refusal, a page we could not
        # read - the only lawful outcome is Retry, and the cell stays as it was.  On 2026-09-09 a change of mine turned
        # "the viewer 404'd" into pending and absent, and it wrote 64,698 pending cells (every one recorded ~19 years
        # ago) and cost the 2006 stretch about 70,000 documents ACRIS holds and hands over on request.  A refused door
        # must be structurally incapable of emptying a cell, and this line is what makes that true.  Only a POSITIVE
        # statement from the viewer - TotalPages <= 0, meaning ACRIS says it has no image - may become a verdict.
        if total is None:
            raise rulebook.Retry("viewer page did not identify itself after 3 asks (%d bytes, ct=%s)" % (len(body), ct))
        if total <= 0:
            # and which of the two is decided by the RECORDING DATE IN ACRIS (registry['recorded']), never by the date
            # we happened to look: inside the lag it is still being scanned, outside it there is nothing to scan.
            return "pending" if acris.fresh(registry, self.fresh_days) else "absent"

        # 2. every page, in order; the placeholder is the end marker, anything not a TIFF ends the walk
        frames, why = [], ""
        for p in range(1, total + 1):
            data, ct = getter.get(acris.image_url(doc_id, p), acris.viewer_url(doc_id))
            acris.check_refused(data, ct, "%s p%d" % (doc_id, p))
            if acris.is_placeholder(data):
                why = "placeholder (end marker) at page %d" % p
                break
            if not acris.is_tiff(data):
                why = "non-TIFF at page %d: ct=%s len=%d" % (p, ct, len(data))
                break
            frames.append(data)
        if len(frames) != total:
            raise rulebook.Retry("short: %d/%d pages - %s" % (len(frames), total, why))

        # 3. the file, written whole or not at all
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.parent / (path.name + ".part")
            tmp.write_bytes(img2pdf.convert(frames))
            os.replace(tmp, path)                        # whole or not at all: never a truncated pdf in the store
        except OSError as e:
            if not os.path.isdir(self.root):
                self.check(crew.ctx)
            raise rulebook.Retry("could not write the file (%s: %s)" % (type(e).__name__, str(e)[:100]))
        return canon


class BoxPrefetch:
    """The on-box fetch (2026-09-08).  One call to the door's droplet - GET /doc/<id> on box_fetch.py, reached on the box's
    own loopback THROUGH the door's socks tunnel - brings the viewer page and every page image as ACRIS served them (status,
    content-type, bytes; a transport error as words).  get(url, referer) then answers fetch()'s asks from what was brought,
    ONCE each (a second ask for the same url - a re-ask - goes to ACRIS itself through the door, as before), and anything
    not brought goes to ACRIS the same way.  A transport error on the box is a Transport here, an HTTP error an HTTPStatus,
    exactly as crew.get raises them, so the crew's breakers read the box like the wire.  The requests the box made count
    on the crew (the PROGRESS line and the board stay true)."""

    def __init__(self, crew, port, doc_id, total):
        self.crew, self.have = crew, {}
        url = "http://127.0.0.1:%d/doc/%s" % (port, doc_id) + ("?total=%d" % total if total else "")
        with crew.lock:
            crew.stats["reqs"] += 1
        try:
            r = crew.session.get(url, timeout=420)            # a document under a deep gate on the box takes minutes, not a fault
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            raise rulebook.Transport("box: %s: %s" % (type(e).__name__, rulebook.reason(e)))
        try:
            if r.status_code >= 400:
                raise rulebook.HTTPStatus(r.status_code, url)
            body = r.content
        finally:
            r.close()
        try:
            nl = body.index(b"\n")
            head = json.loads(body[:nl].decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise rulebook.Transport("box: unreadable answer (%s, %d bytes)" % (type(e).__name__, len(body)))
        pos = nl + 1
        with crew.lock:
            crew.stats["reqs"] += int(head.get("reqs", 0))
        for it in head.get("items", []):
            n = int(it["n"])
            self.have[it["u"]] = (int(it["s"]), it.get("ct", ""), body[pos:pos + n], it.get("e", ""))
            pos += n

    def get(self, url, referer, timeout=90):
        it = self.have.pop(url, None)
        if it is None:
            return self.crew.get(url, referer, timeout)
        st, ct, data, err = it
        if st == 0:
            raise rulebook.Transport("box: %s" % (err or "no answer from ACRIS"))
        if st >= 400:
            raise rulebook.HTTPStatus(st, url)
        return data, ct


def role(drive_root, args):
    """This lane's role, for a sibling lane hosting it with --also documentation:N."""
    if not drive_root:
        raise SystemExit("documentation needs --drive <label>: the drive its files are written to")
    return Documentation(drive_root, getattr(args, "fresh_days", 30), getattr(args, "box", 0))


def main():
    ap = argparse.ArgumentParser(description="acris documentation: one entry, N workers, the cloud table as the to-do list")
    ap.add_argument("--drive", required=True, help="label of the drive to write to (the volume label: OneTouch at home, workstation 2's own)")
    ap.add_argument("--fresh-days", type=int, default=30, help="a document recorded within this many days with no image is pending, not absent")
    ap.add_argument("--box", type=int, default=0, metavar="PORT",
                    help="the on-box fetch (2026-09-08): through each --door, ask the droplet's box_fetch.py on this port for a"
                         " document's viewer page and every page image, fetched on the box in parallel; 0 = fetch from here")
    rulebook.add_common_args(ap)
    args = ap.parse_args()
    args.lane = "documentation"

    drive_root = rulebook.find_drive(args.drive)
    rulebook.documents_root(drive_root)
    roles = rulebook.roles_for("Acris", args, HERE, drive_root, Documentation(drive_root, args.fresh_days, args.box))
    print("drive %r -> %s ; documents under %s ; cell records %s..." % (args.drive, drive_root, rulebook.documents_root(drive_root), rulebook.CANON_ROOT), flush=True)
    sys.exit(rulebook.run(roles, args, HERE))


if __name__ == "__main__":
    main()
