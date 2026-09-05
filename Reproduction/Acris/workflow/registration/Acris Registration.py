"""ACRIS REGISTRATION - one program.

Batches ONE group of N workers through a SINGLE entry under the current IP (one pooled session, one
connection per worker at birth, keep-alive after, no further handshakes), fetches each claimed
document's recorded details from the DocumentDetail page minted from its id - one request per
document, no navigation step - and records them in the `registry` cell as a JSON object.

    python "Acris Registration.py"                    home
    python3 "Acris Registration.py"                   workstation 2

This file's own authority is Acris Registration.md beside it; the cycle's is ../reproduction/Acris Reproduction.md.

The rules are kept from the register floor that ran before this one:

  echo        a page that does not print DOCUMENT ID: <id> is a re-ask, not a failure and never a
              verdict: asked again in place 3x (0.5 s, then 1 s between asks), then left for a later pass
  the page    parsed by the one parser that knows its format (acris.parse_acris): the copy-paste rule,
              tables classified by their own header row, the page's 32 nested tables walked by a real
              parser; the parse happens only after the echo is proven
  no verdict  this lane writes a registry or nothing; the words pending / absent for a registry are a
              decision recorded in Acris Registration.md (the same few ids fail every pass), not a
              count this lane keeps
  failures    a fetch error never stops the lane: the document stays empty for a later pass and the
              reason is written to registration.fails.jsonl
  refusal     HTTP 200 + the Bandwidth Notice page = a block: park at once, no retry, no rotation
  hang-up     the session closed (every worker hit the wire inside 60 s, nothing landed for 10 s): hang up
              at once, drop the cut batch, wait --redial-wait (60 s with the backoff) with no line open, claim
              a fresh batch, re-enter once with births 5 s apart; 4 re-entries per incident, then park
  wall        40 consecutive 503/429 with no success between: park with the reason
  width       --width at launch; `width=30` or `stop` in registration.control while it runs
  mega lane   --also documentation:10 --drive OneTouch hosts the documentation crew in this process through
              its own session, one ramp at a time, --entry-gap apart (one entry per floor, as measured);
              each crew runs the cycle on its own
  pending     a registry pending goes back to the backfill like a document pending: re-checked once
              its last check is --pending-age old, ahead of the empties
  no overlap  claim() hands this workstation its own slice; land() fills the cells once a minute,
              buffered in registration.outbox.jsonl until the cloud takes them; heartbeat() every
              minute carries the width and the last word
  one door    registration.lock: a second start on this machine is refused while the first lives

Exit codes: 0 stopped · 2 refused · 3 redials exhausted · 4 wall · 5 crash.  A parked lane refuses
to start until --unpark.

The shared pieces it imports: ../../../rulebook/lane.py (the entry and the policies), ../../../rulebook/cloud.py (claim,
land, heartbeat), ../../rulebook/acris.py (the ACRIS rules: URLs minted from the id, the one user-agent,
the refusal detector, the page parser).
"""
import argparse
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # registration -> workflow -> Acris -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))

import acris                                                    # noqa: E402
import lane                                                     # noqa: E402
import storage                                                  # noqa: E402


class Registration:
    """What one worker does with one document."""
    source, lane_name = "acris", "registration"
    ua = acris.UA
    noun = "registries"           # the PROGRESS line's word for a filled cell
    needs_registry = False        # the registry is what this lane fetches

    @property
    def lane(self):
        return self.lane_name

    def fetch(self, crew, doc_id, registry):
        body, ct, html = b"", "", ""
        for attempt in range(3):
            body, ct = crew.get(acris.detail_url(doc_id), acris.BASE + "/")
            acris.check_refused(body, ct, doc_id)
            html = acris.clean_html(body.decode("utf-8", "replace"))
            if acris.echoes(html, doc_id):
                break
            with crew.lock:
                crew.stats["reask"] += 1                 # a page that is not about our document: ask again
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))          # 0.5 s, then 1 s; no wait after the last miss
        else:
            raise lane.Retry("page does not echo the id after 3 asks (%d bytes, ct=%s)" % (len(body), ct))
        rec = acris.parse_acris(html)
        if not rec:
            raise lane.Retry("page echoed the id but no field parsed (%d bytes)" % len(body))
        rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")     # when this registry was read
        return rec


def role(drive_root, args):
    """This lane's role, for a sibling lane hosting it with --also registration:N."""
    return Registration()


def main():
    ap = argparse.ArgumentParser(description="acris registration: one entry, N workers, the cloud table as the to-do list")
    ap.add_argument("--drive", default="", help="only for --also documentation:N - the label of the drive it writes to")
    ap.add_argument("--fresh-days", type=int, default=30, help="only for --also documentation:N")
    lane.add_common_args(ap)
    args = ap.parse_args()
    args.lane = "registration"

    drive_root = storage.find_drive(args.drive) if args.drive else None
    roles = lane.roles_for("Acris", args, HERE, drive_root, Registration())
    sys.exit(lane.run(roles, args, HERE))


if __name__ == "__main__":
    main()
