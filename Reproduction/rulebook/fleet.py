"""THE FLEET EVERY SOURCE RUNS - the source's lanes together, one program per source built on this.

Each lane is its own program (<Source> Synchronization.py, <Source> Registration.py, <Source> Documentation.py)
with its own lock, park, control file and log.  A fleet launches them together, in order, one door at a
time, and watches them: it relaunches what a relaunch can cure and never relaunches what a person must
decide.  `Acris Reproduction.py` and `Richmond Reproduction.py` are thin: a Site (the source's name, its
lanes in order, their widths, where the lane programs live) and this module.

Lanes together - the rules:

  one process per lane   the GIL is the throughput wall: registration beside documentation in one interpreter
                         ran 2.7 docs/s against 8 to 11 alone (2026-08-27).  Three lanes, three processes, three GILs
  one door per lane      every lane enters the source through its own pooled session, and the fleet launches lanes
                         --entry-gap apart: three doors, never one moment.  Births inside a lane are its --stagger
  the cycle              each lane runs login's cycle on its own session (lane.py): enter once, births --stagger (5 s)
                         apart, a closed line redialed by its worker, hang up when the whole width is closed, drop the
                         cut batch, wait --redial-wait (60 s; x2 refused, /2 served), re-enter once on a fresh batch.
                         The fleet passes --stagger, --redial-wait and --tries only when given, so the lanes' own
                         defaults are the one truth; a session close is never the fleet's business - exit 3 comes
                         only after four refused re-entries in a row
  the order              synchronization first (it hands the edge), then registration, then documentation - or the
                         order written in --lanes
  the watch              the fleet stays up and reads its children every few seconds.  What each exit means:
                           0  stopped cleanly (control file, --limit, a signal)   done, not relaunched
                           1  refused to start (another door open, parked, a bad --drive; also a Windows kill)   left alone, logged
                           2  REFUSED by the source (the notice page)   every other lane is told to stop; exit 2; a person decides
                              (argparse also exits 2, so a flag the fleet passes must exist on every lane's parser - it does)
                           3  four re-entries in a row refused: the lane PARKED itself   never relaunched; a person decides
                           4  wall (40 consecutive 503/429)   parked by the lane; left alone
                           5  crash   relaunched after a short wait
                           6  drive gone (documentation)   the fleet waits for the drive and relaunches with --unpark when it is back
                         a lane relaunched more than --relaunch-cap times in an hour is parked by the fleet with the
                         reason: every start is a stampede of handshakes, and a cure that keeps failing is not a cure
  a parked lane          is never relaunched by the fleet (the park is the lane's word, or a person's); the drive
                         coming back is the one exception, because the fleet can verify it
  the window             a lane's own cycle already waits out the door's closing window (--redial-wait with the
                         backoff) before it leaves with 3; the fleet's wait comes on top, so a relaunch never lands
                         inside a window
  mega lane              --mega hosts every crew inside the first lane's process through --also (login's frankenstein
                         run); one child to watch.  Inside it every crew keeps its own session, enters one ramp at a
                         time --entry-gap apart, and cycles on its own.  The GIL rule above is why one process per
                         lane is the default
  one fleet per machine  reproduction.lock; the lanes keep their own locks, so a lane already running by hand is
                         refused (exit 1) and left alone - never doubled
  logs                   each lane's output is appended to <lane>/<lane>.log beside its file (never truncated:
                         a live lane's log was truncated once, 2026-09-03), with a fleet banner at every launch
  stop                   `stop` into each control file; the lanes finish their minute and leave; after --stop-wait
                         seconds (180) what is left is terminated and logged as such
  cross-station          `status` reads the workstation rows of reproduction.updates: every lane on every workstation, its
                         width, its age, its last word - a second workstation runs the same file with its own --drive

Exit codes: 0 stopped · 2 a lane was refused (everything stilled) · 5 crash.
"""
import argparse
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time
import traceback

import cloud
import lane
import storage

WAIT_AFTER = {5: 60}                                             # seconds before a relaunch, by exit code: only a crash is relaunched
MEANING = {0: "stopped cleanly", 1: "refused to start", 2: "REFUSED by the source", 3: "parked itself: four re-entries in a row refused",
           4: "wall - parked by the lane", 5: "crash", 6: "drive gone"}


class Site:
    """One source's fleet: its name, its lanes in the cycle's order, their widths, where the lane programs
    live, and which lanes take --edge on a first start."""

    def __init__(self, source, lanes, widths, workflow, here, edge_lanes=("synchronization",), manage=None):
        self.source = source
        self.manage = dict(manage or {})      # lane -> {knob: value}: the three managers' knobs, passed on that lane's command line (see lane.add_common_args)
        self.lanes = tuple(lanes)
        self.widths = dict(widths)
        self.workflow = pathlib.Path(workflow)
        self.here = pathlib.Path(here)
        self.edge_lanes = tuple(edge_lanes)

    @property
    def key(self):
        return self.source.lower()                                # the cloud's table prefix: acris, richmond

    def lane_file(self, name):
        return self.workflow / name / ("%s %s.py" % (self.source, name.capitalize()))

    def lane_dir(self, name):
        return self.workflow / name

    def parse_lanes(self, spec):
        """'registration:40,documentation:40' -> [(name, width)]; '' -> the whole cycle in its order."""
        if not spec:
            return [(n, self.widths[n]) for n in self.lanes]
        out = []
        for part in spec.split(","):
            name, _, w = part.strip().partition(":")
            name = name.strip().lower()
            if name not in self.lanes:
                raise SystemExit("--lanes takes %s (got %r)" % (", ".join(self.lanes), name))
            if any(n == name for n, _ in out):
                raise SystemExit("--lanes names %s twice" % name)
            try:
                w = int(w) if w else self.widths[name]
            except ValueError:
                raise SystemExit("--lanes takes LANE:WIDTH (got %r)" % part)
            if w <= 0 or w > lane.MAX_WIDTH:
                raise SystemExit("%s: width %d - a crew has 1 to %d workers" % (name, w, lane.MAX_WIDTH))
            out.append((name, w))
        return out


class Fleet:
    def __init__(self, site, args):
        self.site = site
        self.args = args
        self.host = args.host or socket.gethostname()
        self.lanes = site.parse_lanes(args.lanes)
        self.log_path = site.here / "reproduction.log"
        self.children = {}            # name -> dict(proc, width, started, log, launches [times], also)
        self.waiting = {}             # name -> (relaunch_at, why, unpark)
        self.history = {}             # name -> the last child record (launch times, width, also)
        self.stopping = False
        self.exit_code = 0

    # ── the fleet's own words ──
    def log(self, msg):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # ── one lane's command line ──
    def argv(self, name, width, unpark=False, also=(), first=True):
        a = self.args
        argv = [sys.executable, "-u", str(self.site.lane_file(name)), "--width", str(width), "--host", self.host,
                "--entry-gap", str(a.entry_gap), "--pending-age", a.pending_age]
        for flag, val in (("--stagger", a.stagger), ("--redial-wait", a.redial_wait), ("--tries", a.tries)):
            if val is not None:
                argv += [flag, str(val)]                       # only when given: the lane's own defaults are the cycle's
        crews = (name,) + tuple(n for n, _ in also)
        if "documentation" in crews:
            if not a.drive:
                raise SystemExit("documentation needs --drive <label> (the volume label: OneTouch at home, workstation 2's own)")
            argv += ["--drive", a.drive, "--fresh-days", str(a.fresh_days)]
        if first and a.edge and any(n in self.site.edge_lanes for n in crews):     # the edge only on a lane's FIRST launch: afterwards its edge file is the truth, and a disagreeing --edge is refused
            argv += ["--edge", str(a.edge)]
        for n, w in also:
            argv += ["--also", "%s:%d" % (n, w)]
        if a.limit:
            argv += ["--limit", str(a.limit)]
        if unpark or a.unpark:
            argv.append("--unpark")
        if getattr(a, "no_pool_check", False):
            argv.append("--no-pool-check")
        for knob, val in sorted(self.site.manage.get(name, {}).items()):      # the managers' knobs: the site's word for this lane
            argv += ["--" + knob.replace("_", "-"), str(val)]
        return argv

    def launch(self, name, width, unpark=False, also=()):
        first = not (self.children.get(name) or {}).get("launches")
        argv = self.argv(name, width, unpark, also, first)
        log = self.site.lane_dir(name) / ("%s.log" % name)
        with log.open("a", encoding="utf-8") as f:                      # appended, never truncated
            f.write("\n=== fleet launch %s on %s: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), self.host,
                                                          " ".join(argv[2:]).replace(str(self.site.workflow), "...")))
        out = log.open("ab")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        proc = subprocess.Popen(argv, cwd=str(self.site.lane_dir(name)), stdout=out, stderr=subprocess.STDOUT, creationflags=flags)
        c = self.children.get(name) or {"launches": []}
        c.update({"proc": proc, "width": width, "started": time.time(), "log": out, "also": also})
        c["launches"].append(time.time())
        self.children[name] = c
        self.log("%s: launched pid %d, width %d%s%s" % (name, proc.pid, width,
                 (" + " + ", ".join("%s x%d" % (n, w) for n, w in also)) if also else "", " (--unpark)" if unpark else ""))
        return proc

    # ── the watch ──
    def run(self):
        lock = self.site.here / "reproduction.lock"
        lane.take_lock(lock)
        a = self.args
        self.log("fleet up on %s - %s - %s" % (self.host, ", ".join("%s x%d" % (n, w) for n, w in self.lanes),
                                                 "one process (mega lane)" if a.mega else "one process per lane, launched %ds apart" % a.entry_gap))

        def _signalled(signum, _frame):
            self.log("signal %d - stopping the lanes" % signum)
            self.stopping = True
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None), getattr(signal, "SIGBREAK", None)):
            if sig is not None:
                try:
                    signal.signal(sig, _signalled)
                except Exception:
                    pass
        try:
            if a.mega:
                first, width = self.lanes[0]
                self.launch(first, width, also=tuple(self.lanes[1:]))
            else:
                for i, (name, width) in enumerate(self.lanes):
                    if i:
                        self._sleep(a.entry_gap)
                        if self.stopping:
                            break
                    self.launch(name, width)
            last_line = time.time()
            while not self.stopping:
                self._sleep(3)
                self._poll()
                self._relaunch_due()
                if not self.children and not self.waiting:
                    self.log("every lane has left - fleet done")
                    break
                if time.time() - last_line >= 60:
                    last_line = time.time()
                    self._status_line()
            if self.stopping:
                self.stop_lanes(a.stop_wait)
        except KeyboardInterrupt:
            self.log("stopped by hand - stopping the lanes")
            self.stop_lanes(a.stop_wait)
        except SystemExit:
            self.stop_lanes(a.stop_wait)
            raise
        except Exception as e:
            self.exit_code = 5
            self.log("CRASH %s: %s - stopping the lanes" % (type(e).__name__, lane.reason(e)))
            self.stop_lanes(a.stop_wait)
            traceback.print_exc()                       # the fleet leaves with 5 (a raise made it exit 1)
        finally:
            for c in self.children.values():
                try:
                    c["log"].close()
                except Exception:
                    pass
            try:
                lock.unlink()
            except OSError:
                pass
            self.log("fleet end - exit %d" % self.exit_code)
        return self.exit_code

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end and not self.stopping:
            time.sleep(min(1.0, end - time.time()))

    def _poll(self):
        for name in list(self.children):
            c = self.children[name]
            rc = c["proc"].poll()
            if rc is None:
                continue
            try:
                c["log"].close()
            except Exception:
                pass
            del self.children[name]
            self._exited(name, c, rc)

    def _exited(self, name, c, rc):
        up = time.time() - c["started"]
        meaning = MEANING.get(rc, "exit %d" % rc)
        parked = self.site.lane_dir(name) / ("%s.parked" % name)
        if c.get("terminated"):
            self.log("%s: pid %d terminated by the fleet after the stop grace (exit %d)" % (name, c["proc"].pid, rc))
            return
        self.log("%s: pid %d left after %.0f min - %s (%d)" % (name, c["proc"].pid, up / 60, meaning, rc))
        if rc == 0 or rc == 1:
            return                                                    # done, or a person's / another door's - left alone
        if rc == 2:
            self.log("%s was REFUSED by the source: stilling every lane; a person decides (%s)" % (name, parked.name))
            self.exit_code = 2
            self.stopping = True
            return
        if rc in (3, 4):
            self.log("%s: parked itself (%s) - not relaunched; a person decides" % (name, parked.name))
            return                                                    # parked by the lane (3: four refused re-entries, 4: the wall) - its word
        self.history[name] = c
        if rc == 6:
            self.waiting[name] = (0, "the drive is gone - waiting for it", True)
            return
        # 5 and anything else: a relaunch is the cure, within the cap
        hour_ago = time.time() - 3600
        n = sum(1 for t in c["launches"] if t > hour_ago)
        if n > self.args.relaunch_cap:
            why = "parked by the fleet %s: %d launches in an hour, the last left with %s (%d)" % (time.strftime("%Y-%m-%d %H:%M"), n, meaning, rc)
            try:
                parked.write_text(why + "\n", encoding="utf-8")
            except OSError:
                pass
            self.log("%s: %s - not relaunched; a person decides" % (name, why))
            return
        wait = WAIT_AFTER.get(rc, WAIT_AFTER[5]) if not self.args.relaunch_wait else self.args.relaunch_wait
        self.waiting[name] = (time.time() + wait, meaning, False)
        self.log("%s: relaunch in %d s (%s; launch %d of %d this hour)" % (name, wait, meaning, n + 1, self.args.relaunch_cap))

    def _relaunch_due(self):
        for name in list(self.waiting):
            at, why, unpark = self.waiting[name]
            hist = self.history.get(name) or {"launches": [], "width": dict(self.lanes).get(name, self.site.widths[name]), "also": ()}
            parked = self.site.lane_dir(name) / ("%s.parked" % name)
            if unpark:
                try:
                    storage.find_drive(self.args.drive)                # the drive: relaunch only when it is back
                except SystemExit:
                    continue
                self.log("%s: the drive %r is back - relaunching with --unpark" % (name, self.args.drive))
            else:
                if time.time() < at:
                    continue
                if parked.exists():
                    self.log("%s: parked meanwhile (%s) - not relaunched" % (name, parked.read_text(encoding="utf-8").strip()[:100]))
                    del self.waiting[name]
                    continue
            del self.waiting[name]
            width = dict(self.lanes).get(name, hist.get("width", self.site.widths[name]))
            self.children[name] = {"launches": hist.get("launches", [])}
            self.launch(name, width, unpark=unpark, also=hist.get("also", ()))

    def _status_line(self):
        parts = []
        for name, c in self.children.items():
            parts.append("%s pid %d up %.0f min" % (name, c["proc"].pid, (time.time() - c["started"]) / 60))
        for name, (at, why, unpark) in self.waiting.items():
            parts.append("%s waiting (%s)" % (name, why))
        self.log("fleet: " + (" - ".join(parts) if parts else "nothing running"))

    # ── stopping ──
    def stop_lanes(self, wait):
        names = list(self.children)
        if not names:
            return
        for name in names:
            write_control(self.site, name, "stop")
        self.log("stop written to %s - waiting up to %d s for the lanes to leave" % (", ".join(names), wait))
        end = time.time() + wait
        while time.time() < end and any(c["proc"].poll() is None for c in self.children.values()):
            time.sleep(1)
        self._poll()
        for name, c in list(self.children.items()):
            if c["proc"].poll() is None:
                self.log("%s: still running after %d s - terminating pid %d" % (name, wait, c["proc"].pid))
                c["terminated"] = True
                try:
                    c["proc"].terminate()
                    c["proc"].wait(timeout=15)
                except Exception:
                    try:
                        c["proc"].kill()
                    except Exception:
                        pass
        self._poll()


# ── the commands that touch running lanes: control files, locks, the cloud ─────────────
def write_control(site, name, text):
    p = site.lane_dir(name) / ("%s.control" % name)
    p.write_text(text + "\n", encoding="utf-8")
    return p


def lock_pid_at(path):
    try:
        pid = int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0
    return pid if lane.pid_alive(pid) else 0


def lock_pid(site, name):
    return lock_pid_at(site.lane_dir(name) / ("%s.lock" % name))


def last_line(path):
    try:
        data = path.read_bytes()[-4000:].replace(b"\x00", b"")
    except OSError:
        return ""
    lines = [l for l in data.decode("utf-8", "replace").splitlines() if l.strip()]
    return lines[-1].strip() if lines else ""


def status(site, args):
    host = args.host or socket.gethostname()
    print("%s lanes on %s:" % (site.key, host))
    for name in site.lanes:
        pid = lock_pid(site, name)
        parked = site.lane_dir(name) / ("%s.parked" % name)
        ctl = site.lane_dir(name) / ("%s.control" % name)
        state = "RUNNING pid %d" % pid if pid else "not running"
        if parked.exists():
            state += " - PARKED: %s" % parked.read_text(encoding="utf-8").strip()[:90]
        if ctl.exists() and ctl.read_text(encoding="utf-8").strip():
            state += " - control: %s" % ctl.read_text(encoding="utf-8").strip()[:40]
        print("  %-16s %s" % (name, state))
        ll = last_line(site.lane_dir(name) / ("%s.log" % name))
        if ll:
            print("  %-16s   %s" % ("", ll[:150]))
    fleet_pid = lock_pid_at(site.here / "reproduction.lock")
    print("  %-16s %s" % ("fleet", "RUNNING pid %d" % fleet_pid if fleet_pid else "not running"))
    print("heartbeats in the cloud (every workstation, last %s):" % args.within)
    try:
        c = cloud.Cloud(site.key, "reproduction", host, app="%s reproduction status" % site.key)
        c.connect()
        rows = c.alive(args.within)
        c.close()
    except Exception as e:
        print("  the cloud is unreachable (%s)" % lane.reason(e))
        return 5
    if not rows:
        print("  none")
    for lane_name, h, width, age, last_event in rows:
        print("  %-16s %-14s width %-4s %4ds ago  %s" % (lane_name, h, width, age, (last_event or "")[:90]))
    return 0


def stop(site, args):
    names = [args.target] if args.target else list(site.lanes)
    for n in names:
        if n not in site.lanes:
            raise SystemExit("stop takes one of %s" % ", ".join(site.lanes))
    running = {n: lock_pid(site, n) for n in names if lock_pid(site, n)}
    if not running:
        print("nothing running on this machine for %s" % ", ".join(names))
        return 0
    for n in running:
        write_control(site, n, "stop")
    print("stop written for %s - waiting up to %d s for the lanes to leave" % (", ".join(running), args.stop_wait))
    end = time.time() + args.stop_wait
    while time.time() < end and any(lane.pid_alive(p) for p in running.values()):
        time.sleep(1)
    for n, pid in running.items():
        if lane.pid_alive(pid):
            print("  %s: still running after %d s - terminating pid %d" % (n, args.stop_wait, pid))
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        else:
            print("  %s: left" % n)
    return 0


def width(site, args):
    name, _, w = (args.target or "").partition("=")
    name = name.strip().lower()
    if name not in site.lanes or not w.strip().isdigit():
        raise SystemExit("width takes LANE=N, e.g. documentation=60")
    w = int(w)
    if w <= 0 or w > lane.MAX_WIDTH:
        raise SystemExit("a crew has 1 to %d workers" % lane.MAX_WIDTH)
    p = write_control(site, name, "width=%d" % w)
    print("width=%d written to %s - %s reads it within a minute%s" % (w, p.name, name, "" if lock_pid(site, name) else " (it is not running now)"))
    return 0


def build_parser(site, description, edge_type, edge_help, fresh_days_default):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "status", "stop", "width"])
    ap.add_argument("target", nargs="?", default="", help="stop: a lane name; width: LANE=N")
    ap.add_argument("--lanes", default="", help="LANE:WIDTH,... in launch order (default: %s)" % ",".join("%s:%d" % (n, site.widths[n]) for n in site.lanes))
    ap.add_argument("--mega", action="store_true", help="every crew in one process through the first lane's --also")
    ap.add_argument("--drive", default="", help="documentation's drive label (the volume label: OneTouch at home, workstation 2's own)")
    ap.add_argument("--fresh-days", type=int, default=fresh_days_default, help="documentation: a document recorded within this many days with no image is pending, not absent")
    ap.add_argument("--edge", type=edge_type, default=edge_type(), help=edge_help)
    ap.add_argument("--entry-gap", type=int, default=20, help="seconds between lane launches (and between crews inside a mega lane)")
    ap.add_argument("--stagger", type=float, default=None, help="seconds between worker births inside a lane (default: the lane's own)")
    ap.add_argument("--pending-age", default="1 hour")
    ap.add_argument("--redial-wait", type=int, default=None, help="seconds of silence before a re-entry (default: the lane's own, 60 s with the backoff)")
    ap.add_argument("--tries", type=int, default=None, help="re-entries per incident before a lane parks (default: the lane's own, 4)")
    ap.add_argument("--limit", type=int, default=0, help="each lane stops after this many documents (a test run)")
    ap.add_argument("--unpark", action="store_true", help="start parked lanes too (a person has decided)")
    ap.add_argument("--no-pool-check", action="store_true", help="the lanes skip the exit-pool check at entry (tests only)")
    ap.add_argument("--relaunch-wait", type=int, default=0, help="seconds before relaunching a crashed lane (default 60)")
    ap.add_argument("--relaunch-cap", type=int, default=3, help="relaunches per lane per hour before the fleet parks it")
    ap.add_argument("--stop-wait", type=int, default=180, help="seconds for the lanes to leave after `stop` (a lane reads its control file on the minute, then joins its workers) before terminating them")
    ap.add_argument("--within", default="10 minutes", help="status: heartbeats this recent")
    ap.add_argument("--host", default="")
    return ap


def main(site, description, edge_type, edge_help, fresh_days_default):
    args = build_parser(site, description, edge_type, edge_help, fresh_days_default).parse_args()
    if args.command == "status":
        return status(site, args)
    if args.command == "stop":
        return stop(site, args)
    if args.command == "width":
        return width(site, args)
    return Fleet(site, args).run()
