"""RICHMOND SYNCHRONIZATION - one program.

Keeps the table live at the county's date edge.  Richmond County lists its recorded instruments by date
range, so the live window is the calendar: the lane's monitor reads today's listing every --every
seconds and lands every new internal id as a new row - the doc_id cell, nothing else - within seconds of
the county listing it; every --heal-every seconds it re-reads the trailing --heal-days so a filing the
county lists late (back-dated to its recorded day) lands too; and on a start after downtime it walks the
days it missed.  One plain GET per listing page, through one pooled session; the walkers take whole
windows, pages in order, --pace apart.

    python "Richmond Synchronization.py" --edge 2026-08-25        the first start names the last day walked
    python "Richmond Synchronization.py"                          afterwards the edge file remembers it

This file's own authority is Richmond Synchronization.md beside it; the cycle's is ../reproduction/Richmond Reproduction.md.

The rules, kept from the lane that ran before this one (rc_lane.py's monitor and heal, rc_window.py):

  the edge     synchronization.edge.json beside this file holds the last day whose listing was walked;
               a start without it needs --edge (never guessed); the edge moves only after the ids of a
               window are in the table, so a crash re-walks and loses nothing
  the day      today's listing every --every seconds (10 s): a filing lands within seconds
  the heal     the trailing --heal-days (30) every --heal-every seconds (15 min): a filing the county
               lists late lands within a quarter hour; windows never longer than the county's 30-day cap
  catch-up     on a start, the days between the edge and the heal window are walked first
  control      a window KNOWN to hold documents must parse rows before any empty answer is believed:
               asked at start and before every heal; if it parses nothing the parser is broken and the
               lane parks (the 2026-08-21 lesson: a sync printed level for hours on a false zero)
  a blank is   an answer: the county listed nothing for that day (weekends, holidays, early morning)
  an error is  not an absence: a page that fails is asked again (three asks), a window that keeps
               failing is recorded in synchronization.holes.jsonl and re-asked by the next heal
  two names    the internal id (ViewDocumentInfo) is ours: RC_<internal>; the instrument number
               repeats across eras and is never a key
  the cell     the doc_id only; registration reads the recorded details in its own pass (the listing
               page it needs for the grant is one request away)
  refusal      a captcha, access-denied or block page = the county's decision: park at once, no retry,
               no rotation
  hang-up      every line dropped at once = dead transport: redial (wifi down waits; 3 tries per
               incident, --redial-wait apart), then park with the reason
  wall         40 consecutive 503/429 with no success between: park with the reason
  width        --width walkers at launch (default 4: the day window, the heal, a catch-up); `width=N`
               or `stop` in synchronization.control
  one door     synchronization.lock: a second start on this machine is refused while the first lives
  one machine  the edge lives on one workstation; run this lane on one machine

Exit codes: 0 stopped · 2 refused · 3 redials exhausted or the probe broken · 4 wall · 5 crash.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # synchronization -> workflow -> Richmond -> Reproduction
sys.path.insert(0, str(PHASE))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))

import lane                                                     # noqa: E402
import richmond                                                 # noqa: E402

CONTROL = "control"


class Synchronization:
    """The monitor (feed + land, on the lane's main thread) and what one walker does with one window."""
    source, lane_name = "richmond", "synchronization"
    ua = richmond.UA
    noun = "windows"              # the PROGRESS line's word for a walked window; documents are in the status
    needs_registry = False

    def __init__(self, here, args):
        self.here = pathlib.Path(here)
        self.state_path = self.here / "synchronization.edge.json"
        self.holes_path = self.here / "synchronization.holes.jsonl"
        self.every, self.heal_every, self.heal_days, self.pace = args.every, args.heal_every, args.heal_days, args.pace
        self.edge = self._load_edge(args.edge)
        self.inflight = {}            # key -> (start, end)
        self.attempts = {}
        self.started = False
        self.next_day = 0.0
        self.next_heal = 0.0
        self.control_pending = False
        self.reask = set()            # holes (kind, start, end) asked again at every heal until they answer
        self.seen = {}                # doc_id -> last listed (date)
        self.inserted = 0
        self.holes = 0
        self.day_rows = 0
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
            raise SystemExit("no %s yet: the first start needs --edge <the last day whose listing was walked>. Never guessed."
                             % self.state_path.name)
        return dt.date.fromisoformat(given)

    def _save_edge(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"edge": self.edge.isoformat(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                   "inserted_this_run": self.inserted, "holes_this_run": self.holes}, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_path)

    # ── one walker, one window ───────────────────────────────────────────────────────────
    def fetch(self, crew, key, _registry):
        """Every row the county lists for the window: all pages, in order, --pace apart -> (kind, rows).
        key = (kind, start, end) with ISO dates: JSON-friendly, since the crew logs a failed item."""
        _kind, a, b = key
        rows, seen, n, total = [], set(), 1, 1
        while n <= total:
            body, ct = crew.get(richmond.listing_url(a, b, n), richmond.BASE + "/", timeout=60)
            html = body.decode("utf-8", "replace")
            richmond.check_refused(html, "%s..%s page %d" % (a, b, n))
            pages = richmond.page_count(html)
            if pages:
                total = pages
            got = richmond.parse_listing(html)
            if not got:
                break
            for r in got:
                if r["internal_id"] not in seen:
                    seen.add(r["internal_id"])
                    rows.append(r)
            n += 1
            if n <= total:
                time.sleep(self.pace)
        return (key[0], rows)

    def classify(self, value):
        return "filled" if value[1] else "blank"

    # ── the monitor: what to ask next ────────────────────────────────────────────────────
    def _queue(self, crew, kind, start, end):
        key = (kind, start.isoformat(), end.isoformat())
        if key in self.inflight:
            return
        self.inflight[key] = (start, end)
        crew.q.put((key, None, 0))

    def feed(self, crew, ctx):
        now = time.time()
        today = self.today()
        if not self.started:
            self.started = True
            a, b, _ = richmond.CONTROL
            self._queue(crew, CONTROL, dt.date.fromisoformat(a), dt.date.fromisoformat(b))
            self.control_pending = True
            heal_start = today - dt.timedelta(days=self.heal_days - 1)      # heal_days inclusive: never past the county's cap
            if self.edge + dt.timedelta(days=1) < heal_start:
                wins = richmond.windows(self.edge + dt.timedelta(days=1), heal_start - dt.timedelta(days=1), richmond.WINDOW_DAYS)
                for s, e in wins:
                    self._queue(crew, "catch-up", s, e)
                lane._log(ctx, "synchronization: catching up %d window(s) from %s to %s" % (len(wins), self.edge + dt.timedelta(days=1), heal_start - dt.timedelta(days=1)))
            self.next_heal = now                     # the first heal at once (its control is already queued)
            self.next_day = now
        if now >= self.next_heal:
            self.next_heal = now + self.heal_every
            if not self.control_pending:            # a control before every heal (the first one is queued above)
                a, b, _ = richmond.CONTROL
                self._queue(crew, CONTROL, dt.date.fromisoformat(a), dt.date.fromisoformat(b))
                self.control_pending = True
            for s, e in richmond.windows(today - dt.timedelta(days=self.heal_days - 1), today, richmond.WINDOW_DAYS):
                self._queue(crew, "heal", s, e)
            for kind, a, b in list(self.reask):              # every hole is asked again at every heal until it answers
                self._queue(crew, kind, dt.date.fromisoformat(a), dt.date.fromisoformat(b))
        if now >= self.next_day:
            self.next_day = now + self.every
            self._queue(crew, "day", today, today)

    # ── the monitor: what the walkers found ──────────────────────────────────────────────
    def land(self, crew, ctx):
        with crew.lock:
            results, crew.results = crew.results, []
            failed, crew.failed = crew.failed, []
        for key, why in failed:
            self.attempts[key] = self.attempts.get(key, 0) + 1
            if self.attempts[key] < 3:
                crew.q.put((key, None, 0))                      # an error is not an absence: ask again
            else:
                self.inflight.pop(key, None)
                self.attempts.pop(key, None)
                self.holes += 1
                if key[0] == CONTROL:
                    self.control_pending = False      # asked again before the next heal
                else:
                    self.reask.add(key)
                try:
                    with self.holes_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "window": [key[1], key[2]],
                                            "kind": key[0], "why": why[:120]}) + "\n")
                except OSError:
                    pass
                lane._log(ctx, "synchronization: %s window %s..%s failed three asks - a hole; the next heal asks again" % (key[0], key[1], key[2]))
        new_ids = {}
        moved = None
        # the edge never jumps a window still out or holed: only windows before the earliest open one may move it
        answered = {r["doc_id"] for r in results}
        open_starts = ([k[1] for k in self.inflight if k not in answered and k[0] != CONTROL]
                       + [k[1] for k in self.reask if k[0] != CONTROL])
        earliest_open = min(open_starts) if open_starts else None
        for r in results:
            key, (kind, rows) = r["doc_id"], r["value"]
            self.inflight.pop(key, None)
            self.attempts.pop(key, None)
            self.reask.discard(key)
            if kind == CONTROL:
                self.control_pending = False
                if not rows:
                    ctx.park("PROBE BROKEN: the control window %s..%s parsed no rows (it holds %d) at %s - the county's markup changed;"
                             " no empty answer is believed until the parser is re-proven" % (key[1], key[2], richmond.CONTROL[2], time.strftime("%Y-%m-%d %H:%M")), code=3)
                    return
                continue
            if kind == "day":
                self.day_rows = len(rows)
            for row in rows:
                d = richmond.doc_id(row["internal_id"])
                if d not in self.seen:
                    new_ids[d] = row.get("recorded", "")
            end = dt.date.fromisoformat(key[2])
            if end <= self.today() and (earliest_open is None or key[2] < earliest_open):
                moved = max(moved or end, end)
        if new_ids:
            try:
                n = crew.cloud.insert_ids(list(new_ids))
            except Exception as e:
                lane._log(ctx, "synchronization: could not land %d ids (%s) - kept, next minute" % (len(new_ids), lane.reason(e)))
                return
            self.seen.update(new_ids)
            self.inserted += n
            lane._log(ctx, "synchronization: %d ids listed, %d new rows" % (len(new_ids), n))
        if moved and moved > self.edge:
            self.edge = moved
            self._save_edge()
        elif new_ids:
            self._save_edge()
        if len(self.seen) > 200000:                                # bounded memory: keep the heal window's ids
            cutoff = (self.today() - dt.timedelta(days=self.heal_days + 7)).isoformat()
            self.seen = {k: v for k, v in self.seen.items() if _iso(v) >= cutoff}

    def status(self):
        return "edge %s - inserted %d - holes %d - today lists %d" % (self.edge, self.inserted, self.holes, self.day_rows)


def _iso(recorded):
    """'8/19/2026' -> '2026-08-19'; anything unreadable sorts as today (kept)."""
    try:
        m, d, y = recorded.split("/")
        return "%04d-%02d-%02d" % (int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return "9999-12-31"


def role(drive_root, args):
    """This lane's role, for the fleet hosting it with --also synchronization:N - its own knobs, the host's --edge."""
    return Synchronization(HERE, lane.role_args(args, ("edge",), edge="", every=10, heal_every=900, heal_days=30, pace=0.3))


def main():
    ap = argparse.ArgumentParser(description="richmond synchronization: the county's date edge, one monitor, a few walkers")
    ap.add_argument("--edge", default="", help="the last day whose listing was walked, YYYY-MM-DD (first start only)")
    ap.add_argument("--every", type=int, default=10, help="seconds between reads of today's listing")
    ap.add_argument("--heal-every", type=int, default=900, help="seconds between re-reads of the trailing window")
    ap.add_argument("--heal-days", type=int, default=30, help="the trailing window re-read by the heal (at most the county's 30-day cap)")
    ap.add_argument("--pace", type=float, default=0.3, help="seconds between the pages of one window")
    ap.add_argument("--drive", default="", help="only for --also documentation:N")
    ap.add_argument("--fresh-days", type=int, default=richmond.IMAGE_LAG_DAYS, help="only for --also documentation:N (the 7-day scan lag)")
    lane.add_common_args(ap)
    ap.set_defaults(width=4)
    args = ap.parse_args()
    args.lane = "synchronization"
    args.heal_days = max(1, min(args.heal_days, richmond.WINDOW_DAYS))

    drive_root = None
    if args.drive:
        import storage
        drive_root = storage.find_drive(args.drive)
    roles = lane.roles_for("Richmond", args, HERE, drive_root, Synchronization(HERE, args))
    sys.exit(lane.run(roles, args, HERE))


if __name__ == "__main__":
    main()
