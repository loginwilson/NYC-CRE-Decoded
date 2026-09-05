"""THE BOARD every source's update program shares: read the counters and the heartbeats once a minute,
subtract, write the two tabs, print the rows.  It only reads the workflow's progress - it never counts
the workflow table (land() and insert_ids() keep the counters exact; reconcile() recounts on demand).

A source's update program (Acris Update.py, Richmond Update.py) names the source and its lanes and
hands them to Board; everything else is here so both boards say the same thing the same way.

The rules, kept from the board that ran before this one (routine_update.py / board_truth.py):

  the five metrics       rate, increase, percentage increase, percentage of total, landed / needed -
                         by the minute (60 s) and by the window (5 min); eta on both bases
  one subtraction        rate and increase come from the SAME subtraction of the counters between the
                         board's own readings (a rate differenced from one series and an increase from
                         another once printed "5.42/s with +0")
  the denominator        every percentage is over NEEDED, the fixed ruler
  status is computed     never hand-set, and only these four (login 2026-08-23):
                           complete   landed >= needed, needed > 0 (nothing owed IS complete)
                           stalled    the lane's last word is a refusal or a wall: the source rejected it
                           active     the counters moved in the last window (measured movement outranks
                                      every proxy: whatever the process list believes)
                           pending    everything else: no fresh heartbeat (paused or parked by a person),
                                      or alive with nothing landing yet
                         eta follows status: complete -> "complete"; pending / stalled -> "paused";
                         active -> from the rate and what remains
  never clamp            a counter outside 0..needed is not published as a metric: the metrics go null,
                         the row says why, and `reconcile` is the cure (a clamp hides the bug and still
                         reports a false level)
  no scan on a tick      reconcile() is on demand only - after a load, after a hand edit - never hourly
                         (login 2026-09-03: "why are we counting all rows every hour?")
  the heartbeats         folded into the lane row: hosts "HOST:width, HOST2:width" of the lanes alive
                         (a heartbeat fresher than --fresh seconds), the width across them, the
                         freshest heartbeat, the last word of the freshest
  as_of is the pulse     stamped every tick by the board; a stale stamp IS the signal the board died
"""
import json
import os
import pathlib
import signal
import socket
import time

from cloud import Cloud
import lane

KEEP = 8 * 60                 # seconds of readings kept for the windows
COLUMNS = ("pct", "rate_60s", "increase_60s", "pct_60s", "eta_60s", "rate_5m", "increase_5m", "pct_5m", "eta_5m", "status")


def eta_text(remaining, rate):
    if rate is None or rate <= 0 or remaining <= 0:
        return None
    s = remaining / rate
    if s >= 86400:
        return "%.1f days" % (s / 86400)
    if s >= 3600:
        return "%.1f hours" % (s / 3600)
    if s >= 60:
        return "%d min" % round(s / 60)
    return "under a minute"


def fmt(n):
    return "{:,}".format(n) if isinstance(n, int) else ("-" if n is None else str(n))


def fmt_signed(n):
    return ("+" + fmt(n)) if isinstance(n, int) and n > 0 else fmt(n)      # an increase reads +288, a hold 0


class Board:
    def __init__(self, source, lanes, here, args):
        self.source, self.lanes = source, tuple(lanes)
        self.here = pathlib.Path(here)
        self.args = args
        self.host = args.host or socket.gethostname()
        self.fresh = getattr(args, "fresh", 180)
        self.state_path = self.here / "update.state.json"
        self.log_path = self.here / "update.log"
        self.readings = self._load()
        self.cloud = Cloud(source, "update", self.host, app="%s update" % source)
        self.stopping = False
        self.failures = 0

    # ── words ──
    def log(self, msg):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # ── the readings ring (the board's own memory of the counters) ──
    def _load(self):
        try:
            d = json.loads(self.state_path.read_text(encoding="utf-8"))
            return [(float(t), v) for t, v in d.get("readings", [])]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self):
        cutoff = time.time() - KEEP
        self.readings = [(t, v) for t, v in self.readings if t >= cutoff]
        tmp = self.state_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"readings": self.readings, "host": self.host}), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            pass

    def _then(self, now, back, key):
        """The reading nearest to `back` seconds ago (at least 3/4 of the way back), or None."""
        best = None
        for t, v in self.readings:
            if key not in v:
                continue
            age = now - t
            if age < back * 0.75:
                continue
            if best is None or abs(age - back) < abs((now - best[0]) - back):
                best = (t, v)
        return best

    # ── read ──
    def read(self):
        s = self.source
        phase = self.cloud._run("select landed, needed from reproduction.%s_update" % s, (), True)[0]
        lanes = self.cloud._run("select lane, landed, needed from reproduction.%s_update_lanes" % s, (), True)
        beats = self.cloud._run("select lane, host, width, heartbeat_at, extract(epoch from now() - heartbeat_at)::int, last_event"
                                " from reproduction.%s_heartbeats" % s, (), True)
        counters = {"phase": (int(phase[0]), int(phase[1]))}
        for name, landed, needed in lanes:
            counters[name] = (int(landed), int(needed))
        return counters, beats

    # ── compute ──
    def fold(self, beats, name):
        """hosts, width, heartbeat_at, last_event, alive for one lane (name) or every lane (None)."""
        rows = [b for b in beats if name is None or b[0] == name]
        if not rows:
            return {"hosts": None, "width": None, "heartbeat_at": None, "last_event": None, "alive": False, "rejected": False}
        alive = [b for b in rows if b[4] is not None and b[4] < self.fresh]
        freshest = min(rows, key=lambda b: b[4] if b[4] is not None else 10 ** 9)
        last = (freshest[5] or "")
        # a rejection on ANY lane stalls the phase (name None): a fresher "started" on another lane never masks
        # a refusal (audit 2026-09-03).  For one lane the freshest word across its hosts decides.
        per_lane = {}
        for b in rows:
            age = b[4] if b[4] is not None else 10 ** 9
            if b[0] not in per_lane or age < per_lane[b[0]][0]:
                per_lane[b[0]] = (age, b[5] or "")
        rejected = any(w.startswith("REFUSED") or w.startswith("wall") for _, w in per_lane.values())
        return {"hosts": ", ".join("%s:%s" % (b[1], b[2]) for b in sorted(alive, key=lambda b: b[1])) or None,
                "width": sum(int(b[2] or 0) for b in alive) or None,
                "heartbeat_at": freshest[3], "last_event": last or None, "alive": bool(alive),
                "rejected": rejected}

    def compute(self, now, counters, beats):
        rows = {}
        for key, (landed, needed) in counters.items():
            f = self.fold(beats, None if key == "phase" else key)
            r = {"landed": landed, "needed": needed, "hosts": f["hosts"], "width": f["width"],
                 "heartbeat_at": f["heartbeat_at"], "last_event": f["last_event"], "why": None}
            if landed < 0 or needed < 0 or landed > needed:
                r.update({c: None for c in COLUMNS})
                r["why"] = "OUT OF BOUNDS: landed %s against needed %s - metrics not published; run `reconcile`" % (fmt(landed), fmt(needed))
                rows[key] = r
                continue
            r["pct"] = round(landed * 100.0 / needed, 2) if needed else None
            moved = False
            for tag, back in (("60s", 60), ("5m", 300)):
                then = self._then(now, back, key)
                if then is None:
                    r["rate_" + tag] = r["increase_" + tag] = r["pct_" + tag] = r["eta_" + tag] = None
                    continue
                t, v = then
                inc = landed - int(v[key])
                dt = now - t
                rate = inc / dt if dt > 0 else None
                r["increase_" + tag] = inc
                r["rate_" + tag] = round(rate, 2) if rate is not None else None
                r["pct_" + tag] = round(inc * 100.0 / needed, 4) if needed else None
                r["eta_" + tag] = eta_text(needed - landed, rate)
                moved = moved or inc > 0
            if needed > 0 and landed >= needed:
                status = "complete"
            elif f["rejected"]:
                status = "stalled"
            elif moved:
                status = "active"
            else:
                status = "pending"
            r["status"] = status
            if status == "complete":
                r["eta_60s"] = r["eta_5m"] = "complete"
            elif status != "active":
                r["eta_60s"] = r["eta_5m"] = "paused"
            rows[key] = r
        return rows

    # ── write ──
    def write(self, rows):
        s = self.source
        p = rows["phase"]
        self.cloud._run("update reproduction.%s_update set pct=%%s, rate_60s=%%s, increase_60s=%%s, pct_60s=%%s, eta_60s=%%s,"
                        " rate_5m=%%s, increase_5m=%%s, pct_5m=%%s, eta_5m=%%s, status=%%s::reproduction.lane_status, as_of=now()" % s,
                        tuple(p[c] for c in COLUMNS), False)
        for name in self.lanes:
            r = rows.get(name)
            if r is None:
                continue
            self.cloud._run("update reproduction.%s_update_lanes set pct=%%s, rate_60s=%%s, increase_60s=%%s, pct_60s=%%s, eta_60s=%%s,"
                            " rate_5m=%%s, increase_5m=%%s, pct_5m=%%s, eta_5m=%%s, status=%%s::reproduction.lane_status, as_of=now(),"
                            " hosts=%%s, width=%%s, heartbeat_at=%%s, last_event=%%s where lane=%%s" % s,
                            tuple(r[c] for c in COLUMNS) + (r["hosts"], r["width"], r["heartbeat_at"], r["last_event"], name), False)

    # ── print ──
    def line(self, key, r):
        if r["why"]:
            return "UPDATE %-8s | %-15s | %s | %s / %s" % (self.source, key if key != "phase" else "reproduction", r["why"], fmt(r["landed"]), fmt(r["needed"]))
        def kit(tag):
            rate, inc, pct, eta = r["rate_" + tag], r["increase_" + tag], r["pct_" + tag], r["eta_" + tag]
            if rate is None and inc is None:
                return "%-3s      -" % tag
            return "%-3s %6.2f/s %8s %+8.4f%%  eta %s" % (tag, rate or 0.0, fmt_signed(inc), pct or 0.0, eta or "-")
        pct = ("%.2f%%" % r["pct"]) if r["pct"] is not None else "-"
        out = "UPDATE %-8s | %-15s | %s | %s | %s / %s = %s | %s" % (
            self.source, key if key != "phase" else "reproduction", kit("60s"), kit("5m"), fmt(r["landed"]), fmt(r["needed"]), pct,
            (r["status"] or "?").upper())
        if key != "phase":
            beat = ""
            if r["heartbeat_at"] is not None:
                beat = " - %s" % (r["hosts"] or "no lane alive")
                if r["last_event"]:
                    beat += " - last: %s" % r["last_event"][:80]
            out += beat
        return out

    # ── one tick ──
    def tick(self, write=True):
        now = time.time()
        counters, beats = self.read()
        rows = self.compute(now, counters, beats)
        if write:
            self.write(rows)
        self.readings.append((now, {k: v[0] for k, v in counters.items()}))
        self._save()
        for key in ("phase",) + self.lanes:
            if key in rows:
                self.log(self.line(key, rows[key]))
        return rows

    # ── the loop ──
    def run(self):
        lock = self.here / "update.lock"
        lane.take_lock(lock)

        def _signalled(signum, _frame):
            self.stopping = True
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None), getattr(signal, "SIGBREAK", None)):
            if sig is not None:
                try:
                    signal.signal(sig, _signalled)
                except Exception:
                    pass
        code = 0
        every = getattr(self.args, "every", 60)
        self.log("%s update up on %s - every %d s, reading only (reconcile on demand)" % (self.source, self.host, every))
        try:
            while not self.stopping:
                t = time.time()
                try:
                    self.tick()
                    self.failures = 0
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self.failures += 1
                    self.log("tick failed (%s) - %d in a row; the readings are kept, next tick continues" % (lane.reason(e), self.failures))
                    try:
                        self.cloud.close()
                    except Exception:
                        pass
                if getattr(self.args, "once", False):
                    break
                while not self.stopping and time.time() - t < every:
                    time.sleep(1)
        except KeyboardInterrupt:
            self.log("stopped by hand")
        except Exception as e:
            code = 5
            self.log("CRASH %s: %s" % (type(e).__name__, lane.reason(e)))
            import traceback
            traceback.print_exc()                       # the process leaves with 5 (a raise made it exit 1)
        finally:
            self.cloud.close()
            try:
                lock.unlink()
            except OSError:
                pass
            self.log("%s update end - exit %d" % (self.source, code))
        return code

    def show(self):
        """Read and print once; nothing written, the readings untouched."""
        now = time.time()
        counters, beats = self.read()
        rows = self.compute(now, counters, beats)
        for key in ("phase",) + self.lanes:
            if key in rows:
                print(self.line(key, rows[key]), flush=True)
        for b in sorted(beats, key=lambda b: (b[0], b[1])):
            print("  heartbeat %-16s %-14s width %-4s %6ds ago  %s" % (b[0], b[1], b[2], b[4] or 0, (b[5] or "")[:80]), flush=True)
        self.cloud.close()
        return 0

    def reconcile(self):
        """Recount landed and needed from the table's indexes and overwrite the counters - on demand only."""
        s = self.source
        before = self.read()[0]
        t = time.time()
        rows = self.cloud._run("select what, landed, needed from reproduction.reconcile(%s)", (s,), True)
        self.log("reconcile(%s) in %.1f s:" % (s, time.time() - t))
        for what, landed, needed in rows:
            key = what
            b = before.get(key, (None, None))
            drift = "" if b[0] == landed and b[1] == needed else "   (was %s / %s)" % (fmt(b[0]), fmt(b[1]))
            self.log("  %-16s landed %12s  needed %12s%s" % (what, fmt(int(landed)), fmt(int(needed)), drift))
        self.cloud.close()
        return 0
