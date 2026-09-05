"""RICHMOND REGISTRATION - one program.

Fills the registry cell of every richmond row that needs one: the recorded details of the county's
detail page (instrument, book and page, type, date recorded, consideration, status, the parcels as BBLs,
the parties with their column, the image state), as JSON.  The county grants a detail only to a session
that has fetched the listing page the id appears on, so this lane cannot take ids from a claim and go
get them: it walks the trailing window's listing pages, asks the table which of the ids on each page
need work (empty, or pending and due), fetches that page again in the worker's own session and then
those ids' details - page, then details, in order, in one session - and lands the registries.  On a
start after downtime it walks the days since its edge first.  Everything else the lane machinery gives
every lane: one entry, staggered births, the outbox, the heartbeat, refusal, hang-up, wall, width, the
control file, the lock.

    python "Richmond Registration.py" --edge 2026-08-25          the first start names the last day walked
    python "Richmond Registration.py"                            afterwards the edge file remembers it

This file's own authority is Richmond Registration.md beside it; the cycle's is ../reproduction/Richmond Reproduction.md.

The rules, kept from the walker that landed 2.4M details (rc_rd_walk.py, rc_rd_refresh.py, rc_source.py):

  the grant     a detail unlocks after THIS session fetched the listing page the id sits on; a cold
                fetch answers HTTP 200 and a shell - never a refusal, never an absence: the item is
                asked again (three asks), then it is a hole
  one session   each walker holds its own keep-alive session (the grant is per session): page, then
                that page's details, in order; first handshakes are staggered by the crew's births
  the walk      the trailing --days (30) every --every seconds (15 min: the old heal), page by page in
                parallel; the details only for ids the table says need work; a catch-up from the edge
                on a start; the edge moves only after a window's pages and details are all in
  control       a window known to hold documents must parse rows before any empty page is believed;
                asked at start and before every walk; parsing nothing parks the lane (exit 3)
  premature     a detail with no instrument number yet (a document registered the day it was recorded)
                is landed as `pending`: the table hands it back after --pending-age and it is asked
                again until it matures (rc_rd_refresh, 2026-08-22)
  the parser    the corpus schema, verbatim: "Document No." carries a period on modern pages; parcels
                as BBLs; parties keep the column the clerk typed the name in; the image state has one
                definition (present / pending inside the lag / absent past it / unknown = ask again)
  the cell      the registry only; documentation reads the image in its own pass
  refusal       a captcha, access-denied or block page = the county's decision: park at once, no
                retry, no rotation
  hang-up, wall, width, one door   shared with every lane (lane.py).  The hang-up is DORMANT at this county
                (no session close was ever measured here: the drumroll rule); it fires only when the
                wire itself dies - hang up, drop the cut pages and details (asked again at the next
                walk; the table still says which ids need work), wait 60 s, re-enter once, births
                0.4 s apart; four re-entries in a row refused, then park
  one machine   the walk is the work list; two walkers of the same window would spend the county's
                requests twice for the same registries. Run this lane on one workstation

Exit codes: 0 stopped · 2 refused · 3 redials exhausted or the probe broken · 4 wall · 5 crash.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import queue
import sys
import threading
import time

import requests

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # registration -> workflow -> Richmond -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))

import lane                                                     # noqa: E402
import richmond                                                 # noqa: E402

CONTROL = "control"


class Registration:
    """The monitor (feed + land on the lane's main thread) and what one walker does with one page."""
    source, lane_name = "richmond", "registration"
    ua = richmond.UA
    noun = "detail batches"       # the PROGRESS line's word for an answered item (a details item with a registry in it); pages and registries are in the status
    needs_registry = False

    def __init__(self, here, args):
        self.here = pathlib.Path(here)
        self.state_path = self.here / "registration.edge.json"
        self.holes_path = self.here / "registration.holes.jsonl"
        self.days = max(1, min(args.days, richmond.WINDOW_DAYS))
        self.every, self.pace, self.pending_age = args.every, args.pace, args.pending_age
        self.edge = self._load_edge(args.edge)
        self.tls = threading.local()
        self.inflight = {}            # key -> True
        self.attempts = {}            # key or doc_id -> failed asks
        self.reask = set()            # page keys that became holes: asked again at every walk
        self.windows = {}             # (a, b) -> {"pages": n or None, "answered": set(), "details": n inflight}
        self.started = False
        self.next_walk = 0.0
        self.control_pending = False
        self.filled = self.pending = self.holes = self.pages = 0
        self.today = dt.date.today

    @property
    def lane(self):
        return self.lane_name

    # ── the edge file ────────────────────────────────────────────────────────────────────
    def _load_edge(self, given):
        if self.state_path.exists():
            saved = dt.date.fromisoformat(json.loads(self.state_path.read_text(encoding="utf-8"))["edge"])
            if given and dt.date.fromisoformat(given) != saved:
                raise SystemExit("the edge file says %s but --edge says %s: remove the file if the day is meant to change" % (saved, given))
            return saved
        if not given:
            raise SystemExit("no %s yet: the first start needs --edge <the last day whose registries were walked>. Never guessed."
                             % self.state_path.name)
        return dt.date.fromisoformat(given)

    def _save_edge(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"edge": self.edge.isoformat(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                   "filled_this_run": self.filled, "pending_this_run": self.pending, "holes_this_run": self.holes}, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self.state_path)

    # ── the wire: one session per walker (the grant is per session) ─────────────────────
    def session(self):
        s = getattr(self.tls, "session", None)
        if s is None:
            s = lane.make_session(1, self.ua)
            self.tls.session = s
        return s

    def get(self, crew, url, where):
        """A page or a detail, three asks with a growing pause: the retry unit is the request, never the
        window (one mid-walk timeout once aborted whole windows every sweep, 2026-08-21)."""
        last = None
        for attempt in range(3):
            if attempt:
                time.sleep(3 * attempt)
            with crew.lock:
                crew.stats["reqs"] += 1
            try:
                r = self.session().get(url, headers={"Referer": richmond.BASE + "/"}, timeout=90)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError) as e:
                last = lane.Transport("%s: %s" % (type(e).__name__, lane.reason(e)))
                continue
            try:
                if r.status_code >= 400:
                    raise lane.HTTPStatus(r.status_code, url)
                html = r.text
            finally:
                r.close()
            richmond.check_refused(html, where)
            return html
        raise last

    # ── one walker, one item ─────────────────────────────────────────────────────────────
    def fetch(self, crew, key, _registry):
        """("control"|"page", a, b, n) -> (kind, {"rows", "pages"});
           ("details", a, b, n, ids) -> the page again (the grant), then each id's detail -> (kind, [(doc_id, value|None)])."""
        kind, a, b, n = key[:4]
        html = self.get(crew, richmond.listing_url(a, b, n), "%s..%s page %d" % (a, b, n))
        rows = richmond.parse_listing(html)
        pages = richmond.page_count(html)
        if kind != "details":
            return (kind, {"rows": rows, "pages": pages})
        on_page = {richmond.doc_id(r["internal_id"]): r for r in rows}
        out = []
        for doc_id in key[4]:
            row = on_page.get(doc_id)
            if row is None:
                out.append((doc_id, None))                     # the page no longer lists it: asked again, then a hole
                continue
            time.sleep(self.pace)
            page = self.get(crew, richmond.detail_url(row["internal_id"]), "detail %s" % doc_id)
            rec = richmond.parse_detail(page)
            if rec is None:
                out.append((doc_id, None))                     # the shell: the grant did not take - asked again
                continue
            if rec["image_state"] == "unknown":
                out.append((doc_id, None))                     # unrecognised page: never a conclusion
                continue
            if richmond.premature(rec):
                out.append((doc_id, "pending"))
                continue
            rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            rec["listing"] = {"recorded": row["recorded"], "type": row["type"], "instrument": row["instrument"]}
            out.append((doc_id, rec))
        return (kind, out)

    def classify(self, value):
        kind, payload = value
        if kind != "details":
            return "blank"
        got = [v for _, v in payload if v is not None]
        if any(isinstance(v, dict) for v in got):
            return "filled"
        return "pending" if got else "blank"

    # ── the monitor: what to ask next ────────────────────────────────────────────────────
    def _queue(self, crew, key):
        if key in self.inflight:
            return
        self.inflight[key] = True
        crew.q.put((key, None, 0))

    def _walk(self, crew, ctx, start, end, what):
        for s, e in richmond.windows(start, end, richmond.WINDOW_DAYS):
            a, b = s.isoformat(), e.isoformat()
            self.windows[(a, b)] = {"pages": None, "answered": set(), "details": 0}
            self._queue(crew, ("page", a, b, 1))
        lane._log(ctx, "registration: walking %s (%s..%s)" % (what, start, end))

    def feed(self, crew, ctx):
        now = time.time()
        today = self.today()
        if not self.started:
            self.started = True
            a, b, _ = richmond.CONTROL
            self._queue(crew, (CONTROL, a, b, 1))
            self.control_pending = True
            walk_start = today - dt.timedelta(days=self.days - 1)
            if self.edge + dt.timedelta(days=1) < walk_start:
                self._walk(crew, ctx, self.edge + dt.timedelta(days=1), walk_start - dt.timedelta(days=1), "the catch-up")
            self.next_walk = now
        if now >= self.next_walk:
            self.next_walk = now + self.every
            if not self.control_pending:
                a, b, _ = richmond.CONTROL
                self._queue(crew, (CONTROL, a, b, 1))
                self.control_pending = True
            self._walk(crew, ctx, today - dt.timedelta(days=self.days - 1), today, "the trailing %d days" % self.days)
            for key in list(self.reask):
                self.windows.setdefault((key[1], key[2]), {"pages": None, "answered": set(), "details": 0})
                self._queue(crew, key)

    # ── the monitor: what the walkers found ──────────────────────────────────────────────
    def _hole(self, ctx, key, why):
        self.holes += 1
        try:
            with self.holes_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "item": list(key[:4]) + ([list(key[4])] if len(key) > 4 else []),
                                    "why": why[:120]}) + "\n")
        except OSError:
            pass
        lane._log(ctx, "registration: %s %s..%s page %s failed three asks - a hole; asked again at the next walk" % (key[0], key[1], key[2], key[3]))

    def _window_done(self, a, b):
        w = self.windows.get((a, b))
        if not w or w["pages"] is None or w["details"] > 0:
            return False
        return len(w["answered"]) >= w["pages"]

    def rebatch(self, crew, ctx):
        """THE REBATCH for this walker (the cycle's hang-up - dormant at this county unless the wire dies): the cut
        items are dropped from the queue and forgotten as in flight.  A page or a control is asked again at the next
        walk; a details item releases its window's count so the window can close, and its ids are asked again then
        because the table still says they need work."""
        n = 0
        while True:
            try:
                key, _, _ = crew.q.get_nowait()
            except queue.Empty:
                break
            self.inflight.pop(key, None)
            self.attempts.pop(key, None)
            if key[0] == CONTROL:
                self.control_pending = False
            elif key[0] == "details":
                w = self.windows.get((key[1], key[2]))
                if w:
                    w["details"] = max(0, w["details"] - 1)
            else:
                self.reask.add(key)
            n += 1
        return n

    def land(self, crew, ctx):
        with crew.lock:
            results, crew.results = crew.results, []
            failed, crew.failed = crew.failed, []
        for key, why in failed:
            self.attempts[key] = self.attempts.get(key, 0) + 1
            if self.attempts[key] < 3:
                crew.q.put((key, None, 0))                      # an error is not an absence: ask again
                continue
            self.inflight.pop(key, None)
            self.attempts.pop(key, None)
            if key[0] == CONTROL:
                self.control_pending = False
            elif key[0] == "details":
                w = self.windows.get((key[1], key[2]))
                if w:
                    w["details"] -= 1
            else:
                self.reask.add(key)
            self._hole(ctx, key, why)
        to_land = []
        for r in results:
            key, (kind, payload) = r["doc_id"], r["value"]
            self.inflight.pop(key, None)
            self.attempts.pop(key, None)
            self.reask.discard(key)
            a, b, n = key[1], key[2], key[3]
            if kind == CONTROL:
                self.control_pending = False
                if not payload["rows"]:
                    ctx.park("PROBE BROKEN: the control window %s..%s parsed no rows (it holds %d) at %s - the county's markup changed;"
                             " no empty page is believed until the parser is re-proven" % (a, b, richmond.CONTROL[2], time.strftime("%Y-%m-%d %H:%M")), code=3)
                    return
                continue
            w = self.windows.setdefault((a, b), {"pages": None, "answered": set(), "details": 0})
            if kind == "page":
                self.pages += 1
                w["answered"].add(n)
                if n == 1:
                    w["pages"] = payload["pages"] or 1
                    for k in range(2, w["pages"] + 1):
                        self._queue(crew, ("page", a, b, k))
                ids = [richmond.doc_id(row["internal_id"]) for row in payload["rows"]]
                if ids:
                    try:
                        need = crew.cloud.todo(ids)
                    except Exception as e:
                        lane._log(ctx, "registration: could not ask the table about %d ids (%s) - the page is asked again at the next walk" % (len(ids), lane.reason(e)))
                        self.reask.add(key)
                        continue
                    if need:
                        key2 = ("details", a, b, n, tuple(sorted(need)))
                        if key2 not in self.inflight:
                            w["details"] += 1
                            self._queue(crew, key2)
                continue
            # details
            w["details"] = max(0, w["details"] - 1)
            again = []
            for doc_id, value in payload:
                if value is None:
                    self.attempts[doc_id] = self.attempts.get(doc_id, 0) + 1
                    if self.attempts[doc_id] < 3:
                        again.append(doc_id)
                    else:
                        self.attempts.pop(doc_id, None)
                        self._hole(ctx, ("details", a, b, n, (doc_id,)), "no detail after three asks")
                    continue
                self.attempts.pop(doc_id, None)
                to_land.append({"doc_id": doc_id, "value": value})
                if value == "pending":
                    self.pending += 1
                else:
                    self.filled += 1
            if again:
                key2 = ("details", a, b, n, tuple(again))
                if key2 not in self.inflight:
                    w["details"] += 1
                    self._queue(crew, key2)
        if to_land:
            crew.outbox.append(to_land)
        if crew.outbox.count():
            try:
                landed, left = crew.outbox.drain(lambda rows: crew.cloud.land(rows, self.pending_age))
                if landed:
                    lane._log(ctx, "registration: landed %d registr%s" % (landed, "y" if landed == 1 else "ies"))
                if left:
                    lane._log(ctx, "registration: the cloud did not take %d landing%s - kept in the outbox for the next minute" % (left, "" if left == 1 else "s"))
            except Exception as e:
                lane._log(ctx, "registration: landing failed (%s) - kept in the outbox" % lane.reason(e))
        # the edge never jumps a window still open or holed: a done window moves it only when no earlier window is
        # open; a done window behind an open one is kept until the open one answers, then both move the edge
        today = self.today()
        done = {k for k in self.windows if self._window_done(*k)}
        open_starts = [a for (a, b) in self.windows if (a, b) not in done]
        earliest_open = min(open_starts) if open_starts else None
        moved = None
        for (a, b) in done:
            end = dt.date.fromisoformat(b)
            if end <= today and (earliest_open is None or b < earliest_open):
                moved = max(moved or end, end)
        if moved and moved > self.edge:
            self.edge = moved
            self._save_edge()
        elif to_land:
            self._save_edge()
        for k in done:
            if k[1] <= self.edge.isoformat():
                del self.windows[k]                          # behind the edge: forgotten

    def status(self):
        return "edge %s - filled %d - pending %d - holes %d - pages %d" % (self.edge, self.filled, self.pending, self.holes, self.pages)


def role(drive_root, args):
    """This lane's role, for the fleet hosting it with --also registration:N - its own knobs, the host's --edge and --pending-age."""
    return Registration(HERE, lane.role_args(args, ("edge", "pending_age"), edge="", days=30, every=900, pace=0.3, pending_age="1 hour"))


def main():
    ap = argparse.ArgumentParser(description="richmond registration: the recorded details behind the county's grant, walked by the listing")
    ap.add_argument("--edge", default="", help="the last day whose registries were walked, YYYY-MM-DD (first start only)")
    ap.add_argument("--days", type=int, default=30, help="the trailing window walked every --every seconds (at most the county's 30-day cap)")
    ap.add_argument("--every", type=int, default=900, help="seconds between walks of the trailing window")
    ap.add_argument("--pace", type=float, default=0.3, help="seconds between the details of one page")
    ap.add_argument("--drive", default="", help="only for --also documentation:N")
    ap.add_argument("--fresh-days", type=int, default=richmond.IMAGE_LAG_DAYS, help="only for --also documentation:N (the 7-day scan lag)")
    lane.add_common_args(ap)
    ap.set_defaults(width=4, stagger=0.4)            # 0.4 s between first handshakes: the county's measured stagger
    args = ap.parse_args()
    args.lane = "registration"

    drive_root = None
    if args.drive:
        import storage
        drive_root = storage.find_drive(args.drive)
    roles = lane.roles_for("Richmond", args, HERE, drive_root, Registration(HERE, args))
    sys.exit(lane.run(roles, args, HERE))


if __name__ == "__main__":
    main()
