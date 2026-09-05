"""REPRODUCTION - the phase: every source's fleet as configured, one program.

Three levels (login 2026-09-05).  A LANE is one program in its own folder - `Acris Documentation.py` - with its own
lock, park, control file and log.  A SOURCE is its lanes together, configured in its fleet program - `Acris
Reproduction.py`: the batch of 9 / 10 / 10 with documentation managed by the three managers; `Richmond
Reproduction.py`: 4 / 4 / 8 at fixed widths, births 0.4 s apart.  THE PHASE is every source's fleet, kicked off as
each one is configured - this program.  It adds no rule of its own: what a source runs is written in its fleet
program, what a lane does in the rulebook (../rulebook/).

    python Reproduction.py --drive OneTouch                                every source's fleet as configured, one fleet at a
                                                                           time --source-gap s apart, then the watch
    python Reproduction.py --drive OneTouch --sources acris                these sources only (folder names, any case)
    python Reproduction.py --drive OneTouch --richmond "--edge 2026-08-25" --acris "--lanes documentation:40"
                                                                           a source's own arguments, handed to its fleet whole
    python Reproduction.py status                                          every source: this machine's lanes, and every
                                                                           workstation's heartbeats in the cloud
    python Reproduction.py stop [source]                                   `stop` through each fleet: the lanes finish their
                                                                           minute and leave

A source is a folder holding a fleet program at <Source>/workflow/reproduction/<Source> Reproduction.py; the phase
finds them in alphabetical order and knows nothing else about them.  The rules of fleets together:

  one phase per machine   reproduction.lock beside this file: a second start is refused (exit 1) and the first left alone
  a fleet per source      each fleet is its own process with its own lock, its own log beside its file and its own watch
                          over its lanes.  The phase launches them --source-gap apart (two sources are two doors, never
                          one moment) and hands each --drive, --host and the source's own arguments - nothing else
  a fleet's exit is its word   0 every lane left cleanly · 1 refused to start (its lock is taken, bad arguments) · 2 a
                          lane was REFUSED by the source and the fleet stilled the rest - a person decides · 5 crash.
                          The phase relaunches nothing: a fleet already relaunches what a relaunch can cure, and what it
                          leaves on is a decision.  One source's refusal is not another's business: the others run on
  the watch               every few seconds the phase reads its fleets and writes a line a minute; when the last fleet
                          has left, the phase leaves with the worst word it heard (2 over 5 over 1 over 0)
  stop                    Ctrl+C or `stop`: each fleet is told to stop (a break signal on Windows, SIGTERM elsewhere) and
                          stops its lanes the way it does alone - `stop` into every control file, a grace, then force.
                          A fleet still up after --stop-wait is terminated; its lanes keep their own locks and finish
  logs                    the phase's lines go to reproduction.log beside this file; each fleet's console to <source>.log
                          beside this file - appended, never truncated

Exit codes: 0 every fleet left cleanly · 1 refused to start · 2 a fleet was refused by its source · 5 crash.
"""
import argparse
import pathlib
import shlex
import signal
import socket
import subprocess
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent             # Reproduction/workflow
PHASE = HERE.parent                                         # Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager

import lane                                                 # noqa: E402  - take_lock, pid_alive, reason

MEANING = {0: "every lane left cleanly", 1: "refused to start", 2: "REFUSED by the source - a person decides", 5: "crash"}
WORST = {0: 0, 1: 1, 5: 2, 2: 3}                            # the phase leaves with the worst word it heard


def sources(phase=PHASE):
    """[(name, fleet program)] - every folder under the phase with <Source>/workflow/reproduction/<Source> Reproduction.py,
    in alphabetical order.  The name is the folder's, lower-cased (acris, richmond) - the cloud's table prefix too."""
    out = []
    for d in sorted(pathlib.Path(phase).iterdir(), key=lambda p: p.name.lower()):
        p = d / "workflow" / "reproduction" / ("%s Reproduction.py" % d.name)
        if d.is_dir() and p.is_file():
            out.append((d.name.lower(), p))
    return out


def pick(srcs, spec):
    """'acris,richmond' -> the named sources in the order given; '' -> every source in alphabetical order."""
    if not spec:
        return list(srcs)
    known = dict(srcs)
    out = []
    for part in spec.split(","):
        n = part.strip().lower()
        if n not in known:
            raise SystemExit("--sources takes %s (got %r)" % (", ".join(k for k, _ in srcs), n))
        if any(k == n for k, _ in out):
            raise SystemExit("--sources names %s twice" % n)
        out.append((n, known[n]))
    return out


class Phase:
    def __init__(self, args, srcs, here=None):
        self.args = args
        self.srcs = list(srcs)
        self.here = pathlib.Path(here) if here else HERE
        self.host = args.host or socket.gethostname()
        self.log_path = self.here / "reproduction.log"
        self.children = {}            # name -> dict(proc, started, log)
        self.stopping = False
        self.exit_code = 0

    # -- the phase's own words --
    def log(self, msg):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # -- one fleet's command line: --drive, --host and the source's own arguments, nothing else --
    def argv(self, name, path):
        a = self.args
        argv = [sys.executable, "-u", str(path), "--drive", a.drive, "--host", self.host]
        return argv + shlex.split(getattr(a, name, "") or "")

    def launch(self, name, path):
        argv = self.argv(name, path)
        log = self.here / ("%s.log" % name)
        with log.open("a", encoding="utf-8") as f:                        # appended, never truncated
            f.write("\n=== phase launch %s on %s: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), self.host, " ".join(argv[3:])))
        out = log.open("ab")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        proc = subprocess.Popen(argv, cwd=str(path.parent), stdout=out, stderr=subprocess.STDOUT, creationflags=flags)
        self.children[name] = {"proc": proc, "started": time.time(), "log": out}
        self.log("%s: fleet launched, pid %d - %s" % (name, proc.pid, " ".join(argv[3:]) or "as configured"))
        return proc

    # -- the watch --
    def run(self):
        lock = self.here / "reproduction.lock"
        lane.take_lock(lock)
        a = self.args
        self.log("phase up on %s - %s - one fleet per source, launched %ds apart" % (self.host, ", ".join(n for n, _ in self.srcs), a.source_gap))

        def _signalled(signum, _frame):
            self.log("signal %d - stopping the fleets" % signum)
            self.stopping = True
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None), getattr(signal, "SIGBREAK", None)):
            if sig is not None:
                try:
                    signal.signal(sig, _signalled)
                except Exception:
                    pass
        try:
            for i, (name, path) in enumerate(self.srcs):
                if i:
                    self._sleep(a.source_gap)
                    if self.stopping:
                        break
                self.launch(name, path)
            last_line = time.time()
            while not self.stopping:
                self._sleep(3)
                self._poll()
                if not self.children:
                    self.log("every fleet has left - phase done")
                    break
                if time.time() - last_line >= 60:
                    last_line = time.time()
                    self.log("phase: " + " - ".join("%s pid %d up %.0f min" % (n, c["proc"].pid, (time.time() - c["started"]) / 60)
                                                    for n, c in self.children.items()))
            if self.stopping:
                self.stop_fleets(a.stop_wait)
        except KeyboardInterrupt:
            self.log("stopped by hand - stopping the fleets")
            self.stop_fleets(a.stop_wait)
        except SystemExit:
            self.stop_fleets(a.stop_wait)
            raise
        except Exception as e:
            self.exit_code = 5
            self.log("CRASH %s: %s - stopping the fleets" % (type(e).__name__, lane.reason(e)))
            self.stop_fleets(a.stop_wait)
            traceback.print_exc()
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
            self.log("phase end - exit %d" % self.exit_code)
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
        self.log("%s: fleet pid %d left after %.0f min - %s (%d)%s" % (name, c["proc"].pid, up / 60, meaning, rc,
                 "; the other fleets run on" if rc and self.children else ""))
        if WORST.get(rc, WORST[5]) > WORST.get(self.exit_code, WORST[5]):
            self.exit_code = rc if rc in WORST else 5

    # -- stopping: each fleet stops its own lanes --
    def stop_fleets(self, wait):
        up = [n for n, c in self.children.items() if c["proc"].poll() is None]
        if not up:
            return
        for name in up:
            proc = self.children[name]["proc"]
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM)
            except Exception as e:
                self.log("%s: could not signal pid %d (%s)" % (name, proc.pid, lane.reason(e)))
        self.log("stop sent to %s - waiting up to %d s for the fleets to stop their lanes and leave" % (", ".join(up), wait))
        end = time.time() + wait
        while time.time() < end and any(c["proc"].poll() is None for c in self.children.values()):
            time.sleep(1)
        self._poll()
        for name, c in list(self.children.items()):
            if c["proc"].poll() is None:
                self.log("%s: still up after %d s - terminating pid %d (its lanes keep their own locks and finish on their own)" % (name, wait, c["proc"].pid))
                try:
                    c["proc"].terminate()
                    c["proc"].wait(timeout=15)
                except Exception:
                    try:
                        c["proc"].kill()
                    except Exception:
                        pass
        self._poll()


# -- the commands that go through each fleet program: status, stop --
def run_each(srcs, tail, host):
    worst = 0
    for name, path in srcs:
        print("=== %s ===" % name, flush=True)
        argv = [sys.executable, "-u", str(path)] + tail + (["--host", host] if host else [])
        rc = subprocess.call(argv, cwd=str(path.parent))
        worst = max(worst, rc)
    return worst


def build_parser(srcs):
    ap = argparse.ArgumentParser(description="reproduction: every source's fleet as configured")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "status", "stop"])
    ap.add_argument("target", nargs="?", default="", help="stop: one source (default: every source)")
    ap.add_argument("--sources", default="", help="SOURCE,... to run, in this order (default: every source, alphabetical: %s)" % ", ".join(n for n, _ in srcs))
    ap.add_argument("--drive", default="", help="documentation's drive label (the volume label: OneTouch at home, workstation 2's own); run needs it")
    ap.add_argument("--source-gap", type=int, default=20, help="seconds between one fleet's launch and the next")
    ap.add_argument("--stop-wait", type=int, default=240, help="seconds for a fleet to stop its lanes and leave (a fleet gives its lanes 180) before it is terminated")
    ap.add_argument("--within", default="10 minutes", help="status: heartbeats this recent")
    ap.add_argument("--host", default="", help="this workstation's name in the cloud (default: the machine name)")
    for name, _ in srcs:
        ap.add_argument("--" + name, default="", metavar="ARGS", help="the %s fleet's own arguments, handed to it whole, e.g. \"--lanes documentation:40 --mega\"" % name)
    return ap


def main(argv=None, phase=PHASE, here=None):
    srcs = sources(phase)
    if not srcs:
        raise SystemExit("no source under %s has a fleet program (<Source>/workflow/reproduction/<Source> Reproduction.py)" % phase)
    args = build_parser(srcs).parse_args(argv)
    if args.command == "status":
        return run_each(pick(srcs, args.sources), ["status", "--within", args.within], args.host)
    if args.command == "stop":
        return run_each(pick(srcs, args.target or args.sources), ["stop", "--stop-wait", str(max(1, args.stop_wait - 60))], args.host)
    if not args.drive:
        raise SystemExit("run needs --drive <label> (the volume label: OneTouch at home, workstation 2's own): every source's batch has documentation in it")
    return Phase(args, pick(srcs, args.sources), here).run()


if __name__ == "__main__":
    sys.exit(main())
