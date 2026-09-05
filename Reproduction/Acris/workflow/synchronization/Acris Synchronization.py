"""ACRIS SYNCHRONIZATION - one program.

Keeps the table live at the CRFN edge.  ACRIS issues the City Register File Number as one strict
citywide counter, so the numbers above the last one we hold are the only live window the source
offers (it sells no date search).  The lane sits at the edge with one monitor and a crew of
walkers: while the edge is level the monitor probes a few numbers past it every --every seconds;
the moment a filing shows, the crew walks a full bite of numbers in parallel and every document
found lands as a new row - the doc_id cell, nothing else - and the edge moves to the last document
seen.  One request per number, a plain GET of the detail page by CRFN, through one pooled session.

    python "Acris Synchronization.py" --edge 2026000247108      the first start names the edge
    python "Acris Synchronization.py"                           afterwards the edge file remembers it

This file's own authority is Acris Synchronization.md beside it; the cycle's is ../reproduction/Acris Reproduction.md.

The rules, kept from the sync floor that ran before this one:

  the edge     synchronization.edge.json beside this file holds the last CRFN whose document we hold;
               a start without it needs --edge (never guessed); the edge moves only after the documents
               it passes are in the table, so a crash re-walks and loses nothing
  level        --watch numbers past the edge every --every seconds; blanks past the last document are
               unissued numbers and are asked again next time
  behind       a document near the end of the probed window means more beyond: walk a --bite at once,
               and keep walking until the window ends in --watch blanks
  the holes    a number that fails three asks is recorded in synchronization.holes.jsonl and passed,
               so one bad number never freezes the edge; the audit reconciles it
  ucc runs     personal-property filings take numbers in the same counter and answer blank here; after
               --widen-after empty watches one wider look (--widen numbers) is taken, so a run of them
               can never hide a document from the monitor
  a blank is   an answer, not a failure: the source said no document is at that number
  an error is  not an absence: a request that fails is asked again, never read as blank (2026-08-23)
  the cell     the doc_id only; registration reads the recorded details in its own pass (the same page,
               one more request per new document - the cell rule is worth it)
  refusal      HTTP 200 + the Bandwidth Notice page = a block: park at once, no retry, no rotation
  hang-up      the session closed (every walker hit the wire inside 60 s, nothing answered for 10 s): hang
               up at once, drop the cut window from the queue (rebatch: the numbers are forgotten as in
               flight and the monitor asks them again from the edge), wait --redial-wait (60 s with the
               backoff) with no line open, re-enter once with births 5 s apart; 4 re-entries, then park
  wall         40 consecutive 503/429 with no success between: park with the reason
  width        --width walkers at launch (default 20 alone; 9 + the monitor in the fleet's batch); `width=N`
               or `stop` in synchronization.control
  one door     synchronization.lock: a second start on this machine is refused while the first lives
  one machine  the edge lives on one workstation; run this lane at home only

Exit codes: 0 stopped · 2 refused · 3 redials exhausted · 4 wall · 5 crash.
"""
import argparse
import json
import os
import pathlib
import queue
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # synchronization -> workflow -> Acris -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))

import acris                                                    # noqa: E402
import lane                                                     # noqa: E402
import storage                                                  # noqa: E402


class Synchronization:
    """The monitor (feed + land, on the lane's main thread) and what one walker does with one number."""
    source, lane_name = "acris", "synchronization"
    ua = acris.UA
    noun = "documents"            # the PROGRESS line's word for a live number
    needs_registry = False

    def __init__(self, here, args):
        self.here = pathlib.Path(here)
        self.state_path = self.here / "synchronization.edge.json"
        self.holes_path = self.here / "synchronization.holes.jsonl"
        self.every, self.watch, self.bite = args.every, args.watch, args.bite
        self.widen, self.widen_after = args.widen, args.widen_after
        self.edge = self._load_edge(args.edge)
        self.answers = {}             # crfn -> doc_id | None (blank) | "hole"
        self.attempts = {}            # crfn -> failed asks
        self.inflight = set()
        self.behind = False
        self.next_watch = 0.0
        self.empty_watches = 0
        self.inserted = 0
        self.holes = 0
        self.window_end = self.edge

    @property
    def lane(self):
        return self.lane_name

    # ── the edge file ────────────────────────────────────────────────────────────────────
    def _load_edge(self, given):
        if self.state_path.exists():
            saved = int(json.loads(self.state_path.read_text(encoding="utf-8"))["edge"])
            if given and given != saved:
                raise SystemExit("the edge file says %d but --edge says %d: remove the file if the number is meant to change" % (saved, given))
            return saved
        if not given:
            raise SystemExit("no %s yet: the first start needs --edge <last CRFN whose document the table holds>. Never guessed."
                             % self.state_path.name)
        return int(given)

    def _save_edge(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"edge": self.edge, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                   "inserted_this_run": self.inserted, "holes_this_run": self.holes}, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_path)

    # ── one walker, one number ───────────────────────────────────────────────────────────
    def fetch(self, crew, crfn, _registry):
        body, ct = crew.get(acris.crfn_url(crfn), acris.BASE + "/", timeout=45)
        acris.check_refused(body, ct, "crfn %d" % crfn)
        html = acris.clean_html(body.decode("utf-8", "replace"))
        doc_id = acris.detail_doc_id(html)
        if doc_id is None:
            return ("blank", None)                                  # an answer: no document at this number
        if len(body) < acris.MIN_DETAIL:
            raise lane.Retry("detail parsed from only %d bytes - suspect truncation, not reported live" % len(body))
        return ("live", doc_id)

    def classify(self, value):
        return "filled" if value[0] == "live" else "blank"

    # ── the monitor: what to ask next ────────────────────────────────────────────────────
    def feed(self, crew, ctx):
        if crew.q.qsize() >= crew.width:
            return
        now = time.time()
        if self.behind:
            n = self.bite
        else:
            if now < self.next_watch:
                return
            self.next_watch = now + self.every
            n = self.watch
            if self.empty_watches >= self.widen_after:
                n = self.widen
                self.empty_watches = 0
                lane._log(ctx, "synchronization: %d empty watches - one wider look of %d numbers past the edge"
                          % (self.widen_after, n))
        window_end = self.edge + n
        for crfn in range(self.edge + 1, window_end + 1):
            if crfn in self.answers or crfn in self.inflight:
                continue
            self.inflight.add(crfn)
            crew.q.put((crfn, None, 0))
        self.window_end = window_end                    # THIS window's end, never the widest ever walked

    # ── the monitor: what the walkers found ──────────────────────────────────────────────
    def land(self, crew, ctx):
        with crew.lock:
            results, crew.results = crew.results, []
            failed, crew.failed = crew.failed, []
        for r in results:
            crfn, (state, doc_id) = r["doc_id"], r["value"]
            self.inflight.discard(crfn)
            self.answers[crfn] = doc_id if state == "live" else None
        for crfn, why in failed:
            self.inflight.discard(crfn)
            self.attempts[crfn] = self.attempts.get(crfn, 0) + 1
            if self.attempts[crfn] < 3:
                self.inflight.add(crfn)
                crew.q.put((crfn, None, 0))                    # an error is not an absence: ask again
            else:
                self.answers[crfn] = "hole"
                self.holes += 1
                try:
                    with self.holes_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "crfn": crfn, "why": why[:120]}) + "\n")
                except OSError:
                    pass
        # the contiguous answered prefix past the edge; the edge moves to the LAST DOCUMENT in it
        end = self.edge
        while (end + 1) in self.answers:
            end += 1
        lives = [(n, self.answers[n]) for n in range(self.edge + 1, end + 1) if self.answers[n] not in (None, "hole")]
        if not lives:
            if end >= self.window_end and end > self.edge:
                # a whole window answered without a document: level; blanks past the edge are unissued
                # numbers and are asked again next time, so their answers are dropped
                self.behind = False
                self.empty_watches += 1
                for n in range(self.edge + 1, end + 1):
                    self.answers.pop(n, None)
                    self.attempts.pop(n, None)
            return
        try:
            n = crew.cloud.insert_ids([d for _, d in lives])
        except Exception as e:
            lane._log(ctx, "synchronization: could not land %d documents (%s) - kept, next minute" % (len(lives), lane.reason(e)))
            return
        self.inserted += n
        old, self.edge = self.edge, lives[-1][0]
        for k in range(old + 1, self.edge + 1):
            self.answers.pop(k, None)
            self.attempts.pop(k, None)
        self._save_edge()
        self.empty_watches = 0
        # more beyond?  a document within --watch numbers of the end of what we have seen says yes
        self.behind = (end - self.edge) < self.watch
        for k in list(self.answers):                            # blanks past the new edge: asked again
            if k <= end:
                self.answers.pop(k, None)
                self.attempts.pop(k, None)
        lane._log(ctx, "synchronization: %d documents found, %d new - edge %d -> %d - %s"
                  % (len(lives), n, old, self.edge, "BEHIND, walking a bite" if self.behind else "level"))

    def rebatch(self, crew, ctx):
        """THE REBATCH for a walker crew (the cycle, login 2026-09-04): the cut window is dropped from the queue and
        forgotten as in flight, so the next feed asks the same numbers again from the edge - which never moved past an
        unanswered number.  The walk's fresh batch is the window itself."""
        n = 0
        while True:
            try:
                crfn, _, _ = crew.q.get_nowait()
            except queue.Empty:
                break
            self.inflight.discard(crfn)
            n += 1
        return n

    def status(self):
        return "edge %d - %s - inserted %d - holes %d" % (self.edge, "behind" if self.behind else "level", self.inserted, self.holes)


def role(drive_root, args):
    """This lane's role, for the fleet hosting it with --also synchronization:N - its own knobs, the host's --edge."""
    return Synchronization(HERE, lane.role_args(args, ("edge",), edge=0, every=60, watch=8, bite=1000, widen=64, widen_after=5))


def main():
    ap = argparse.ArgumentParser(description="acris synchronization: the CRFN edge, one monitor, a crew of walkers")
    ap.add_argument("--edge", type=int, default=0, help="the last CRFN whose document the table holds (first start only)")
    ap.add_argument("--every", type=int, default=60, help="seconds between watches while level")
    ap.add_argument("--watch", type=int, default=8, help="numbers probed past the edge per watch")
    ap.add_argument("--bite", type=int, default=1000, help="numbers walked at once while behind")
    ap.add_argument("--widen", type=int, default=64, help="one wider look after --widen-after empty watches (a run of personal-property numbers)")
    ap.add_argument("--widen-after", type=int, default=5, help="empty watches before the wider look")
    ap.add_argument("--drive", default="", help="only for --also documentation:N")
    ap.add_argument("--fresh-days", type=int, default=30, help="only for --also documentation:N")
    lane.add_common_args(ap)
    ap.set_defaults(width=20)
    args = ap.parse_args()
    args.lane = "synchronization"

    drive_root = storage.find_drive(args.drive) if args.drive else None
    roles = lane.roles_for("Acris", args, HERE, drive_root, Synchronization(HERE, args))
    sys.exit(lane.run(roles, args, HERE))


if __name__ == "__main__":
    main()
