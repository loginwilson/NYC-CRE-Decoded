"""THE ENTRY EVERY CYCLE LANE SHARES: one pooled session per crew, staggered births, workers each on
their own connection, and the policies that keep a lane alive without a person - measured on the
acris lanes of 2026-08/09 and written down in ACRIS REPRODUCTION.md.

A lane file (documentation.py, registration.py, ...) defines a ROLE - what one worker does with one
document - and hands it to run().  run() owns everything else:

  claim / land / heartbeat   the cloud hands this workstation its slice (claim); results land once a
                             minute through the outbox, so a cloud hiccup loses nothing; heartbeat
                             once a minute carries the width and the last word
  failures                   a fetch error never stops the lane; the document stays empty for a later
                             pass and the reason is written to <lane>.fails.jsonl
  refusal                    HTTP 200 + the Bandwidth Notice = the source's decision: park at once,
                             no retry, no rotation, exit
  hang-up                    the session closed: every worker hit the wire inside 60 s and nothing has
                             landed for 10 s (a partial close is redialed worker by worker).  Hang up at
                             once, land what the crew holds, DROP the cut batch, wait --redial-wait
                             (60 s; x2 after a refused re-entry, /2 after a served one) with no line
                             open - wifi down waits without spending a try - then re-enter ONCE on a
                             fresh batch with staggered births; 4 re-entries per incident, then park
  wall                       40 consecutive 503/429 on a crew with no success between: park
  width                      <lane>.control holds `width=N` (or `<lane>=N` per crew) and `stop`; read
                             once a minute; workers above N park after their current document, the
                             missing ones are born staggered, one connection each
  mega lane                  several roles in one process (the fleet's --mega, login's frankenstein
                             run): each crew enters through ITS OWN session, one ramp at a time and
                             --entry-gap apart, and runs the cycle on its own - one crew's wait never
                             stalls another (mixing floors through one session made acris serve empty
                             viewer pages for documents whose images exist, run 3, 2026-08-28)
  one door                   <lane>.lock holds the running pid; a second start on the same machine is
                             refused while that pid lives (two processes on one lane = two doors = the
                             ban condition, trap 8); a stale lock from a crash is taken over
  drive                      a role may define check(ctx); documentation parks when its drive is gone
                             (a pulled USB left the old lane fetching with every write failing, trap 5)

THE CYCLE (login 2026-09-04: "batch, enter, stagger, redial until close, exit, rebatch, cycle"; proven
unattended 14:51-14:58): one entry, workers born --stagger (5 s) apart; a worker whose line the far side
closes redials it on its next request, pausing HANGUP_PAUSE_S (5 s) first; when the far side has closed the
WHOLE width - every worker a transport error inside HANGUP_WINDOW_S (60 s) and nothing landed for
HANGUP_QUIET_S (10 s) - the crew hangs up AT ONCE (Crew.hung_up -> _hangup), lands what it holds, DROPS the
cut batch (_rebatch: the queue is emptied; the dropped claims expire on their own and come back in a later
pass; a role that walks a range re-asks its window), waits --redial-wait (60 s) with no line open, claims a
fresh batch and re-enters ONCE (_await_entry), staggered, after exit_pool() shows five draws in one block.
The wait is a state: a re-entry the door refuses (cut inside five minutes with fewer than SERVED_LANDINGS
landed) doubles the next wait, capped at 80 minutes; a served one halves it back to the base.  Neither the
wait nor the ramp blocks the process: births run on their own thread and the main loop keeps feeding and
landing every other crew.
A cut is ACRIS's ordinary session end, not a block: it closed every session of 2026-09-04 after 12-59
minutes and served the fresh-batch re-entry 60 s after the last dead line cleared (14:54, 0 fails by minute
4).  What it refuses is a re-entry made while its own closing waves are still running on the old batch, and
a relaunch storm (2026-09-03 19:43: nine in 96 minutes, each cut sooner).  A notice page is never re-entered.

Exit codes: 0 stopped (control file, limit, Ctrl+C, kill) · 2 refused (notice page) · 3 redials
exhausted · 4 wall · 5 crash · 6 drive gone.  Every stop writes its reason as the lane's last word.
"""
import json
import os
import pathlib
import queue
import signal
import socket
import sys
import threading
import time
import traceback
import types
import urllib.request

import requests
import requests.adapters

from cloud import Cloud, Outbox


class Refused(RuntimeError):
    """The source declined (the notice page).  Stop the lane; a person decides."""


class Transport(RuntimeError):
    """The wire failed (EOF, reset, timeout): our side, retryable, counted toward a hang-up."""


class HTTPStatus(RuntimeError):
    def __init__(self, code, url):
        super().__init__("HTTP %d" % code)
        self.code = code


class Retry(RuntimeError):
    """Leave the document empty for a later pass (short document, unknown page shape)."""


def reason(e):
    t = str(e)
    i = t.rfind("Caused by")
    return (t[i:] if i >= 0 else t[-160:])[:160]


def pid_alive(pid):
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            k.GetExitCodeProcess(h, ctypes.byref(code))
            return code.value == 259                    # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def take_lock(path):
    """One process per lane per machine.  Fail closed: if we cannot prove we are the only door, we
    do not open one."""
    try:
        if path.exists():
            old = int((path.read_text(encoding="utf-8").strip() or "0"))
            if pid_alive(old):
                raise SystemExit("REFUSING TO START: %s is already running as pid %d on this machine."
                                 " Two processes on one lane = two doors at the source = the ban condition."
                                 " Stop that one first." % (path.stem, old))
            print("stale lock from pid %d (not running) - taking the lane" % old, flush=True)
        path.write_text(str(os.getpid()), encoding="utf-8")
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit("REFUSING TO START: could not take the lock %s (%s) - cannot prove this is the only door."
                         % (path.name, type(e).__name__))


def add_common_args(ap):
    """The knobs every cycle lane shares; a lane file adds its own (documentation: --drive, --fresh-days)."""
    ap.add_argument("--width", type=int, default=40, help="workers = connections (default 40)")
    ap.add_argument("--host", default="", help="this workstation's name in the cloud (default: the machine name)")
    ap.add_argument("--stagger", type=float, default=5.0, help="seconds between worker births: a ramp of about 200 s at width 40 (2026-09-04: 0.5-s entries were cut, 5-s and 20-s entries served on the same door)")
    ap.add_argument("--claim", type=int, default=0, help="documents taken per claim (default 12 x width)")
    ap.add_argument("--ttl", default="20 minutes", help="how long a claim is ours before it goes back on the list")
    ap.add_argument("--pending-age", default="1 hour",
                    help="re-check a pending once its last check is this old; pendings ride ahead of the backfill, and when"
                         " the lane is up to date every claim is pendings (one request per pending per interval)")
    ap.add_argument("--redial-wait", type=int, default=60, help="seconds of silence after the session closes before the fresh-batch re-entry; a refused re-entry doubles the next wait (cap 4,800 s), a served one halves it back to this base")
    ap.add_argument("--tries", type=int, default=4, help="re-entries per incident before parking (the wait doubles each time: 1, 2, 4, 8 minutes at the base)")
    ap.add_argument("--no-pool-check", action="store_true", help="skip the exit-pool check at entry (tests only)")
    ap.add_argument("--entry-gap", type=float, default=20.0, help="seconds between one crew's entry and the next (--also)")
    ap.add_argument("--also", action="append", default=[], metavar="LANE:WIDTH", help="host another lane's crew too, e.g. registration:40")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many documents (a test run)")
    ap.add_argument("--log", default="", help="also append the printed lines to this file")
    ap.add_argument("--unpark", action="store_true", help="start although the lane parked itself (a person has decided)")
    return ap


def sibling_role(source, name, here, drive_root, args):
    """The role of a sibling lane file, loaded by path (`<Source> <Name>.py` carries a space): its
    module-level role(drive_root, args)."""
    sib = pathlib.Path(here).parent / name / ("%s %s.py" % (source, name.capitalize()))
    if not sib.is_file():
        raise SystemExit("no lane file for --also %s (expected %s)" % (name, sib))
    import importlib.util
    spec = importlib.util.spec_from_file_location("%s_%s" % (source.lower(), name), sib)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.role(drive_root, args)


def role_args(args, shared=(), **defaults):
    """A hosted crew's own arguments (--also): its OWN defaults, overlaid only with the shared names the host
    carries (--edge, --pending-age, --fresh-days ...).  A host's --every is the host's, never the guest's
    (audit 2026-09-03: a guest read its knobs off the host's namespace and crashed at start)."""
    ns = types.SimpleNamespace(**defaults)
    for k in shared:
        if hasattr(args, k):
            setattr(ns, k, getattr(args, k))
    return ns


def roles_for(source, args, here, drive_root, own):
    """[(role, width), ...]: this lane's own role first, then every --also LANE:WIDTH crew."""
    roles = [(own, args.width)]
    for spec in args.also:
        name, _, w = spec.partition(":")
        name = name.strip().lower()
        try:
            w = int(w or 40)
        except ValueError:
            raise SystemExit("--also takes LANE:WIDTH, e.g. registration:40 (got %r)" % spec)
        if name == args.lane:
            raise SystemExit("--also %s: that is this lane" % name)
        roles.append((sibling_role(source, name, here, drive_root, args), w))
    return roles


def net_up():
    """Any HTTP answer from a neutral host = the wire is up.  A wifi outage is never a block."""
    for host in ("https://www.nyc.gov/", "https://github.com/"):
        try:
            urllib.request.urlopen(urllib.request.Request(host, method="HEAD",
                                   headers={"User-Agent": "Mozilla/5.0"}), timeout=10)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            continue
    return False


HANGUP_WINDOW_S, HANGUP_PAUSE_S = 60, 5     # every worker failing inside 60 s is the session closed; a cut worker pauses 5 s then redials
HANGUP_QUIET_S = 10                         # ... and nothing landed for 10 s: a partial close keeps landing on the lines still open
SERVED_LANDINGS, SERVED_S = 300, 300        # a re-entry that landed this many, or lived five minutes, was served then closed by the door; fewer and sooner = refused
MAX_WIDTH = 128          # the pool's ceiling; a connection is opened only when a worker first asks


def exit_pool(draws=5, pause=1.0):
    """Five fresh-connection draws of the public exit (never the source).  The lane has no IP: the VPN
    hands EACH connection an exit from a pool, so one draw is one draw; five in one /24 = the pool is
    settled, five spanning blocks = the VPN app is mid-switch and no entry goes out."""
    seen = []
    for i in range(draws):
        try:
            r = urllib.request.urlopen(urllib.request.Request("https://api.ipify.org", headers={
                "User-Agent": "nyc-cre-decoded lane (exit check)", "Connection": "close"}), timeout=15)
            seen.append(r.read().decode().strip())
        except Exception as e:
            seen.append("fail:" + type(e).__name__)
        if i < draws - 1:
            time.sleep(pause)
    blocks = sorted({".".join(x.split(".")[:3]) for x in seen if x[:1].isdigit()})
    return seen, blocks


def wait_for_pool(ctx, c):
    """No entry while the exit pool spans blocks (the VPN app mid-switch) or answers nothing."""
    if getattr(ctx.args, "no_pool_check", False):
        return
    while not ctx.stopping.is_set():
        seen, blocks = exit_pool()
        if len(blocks) == 1 and all(x[:1].isdigit() for x in seen):
            _log(ctx, "%s: exit pool %s - one block %s, entering" % (c.role.lane, ", ".join(seen), blocks[0]))
            return
        _log(ctx, "%s: exit pool %s - %s; waiting 30 s, no entry" % (c.role.lane, ", ".join(seen),
             "SPANS BLOCKS %s (the VPN app is mid-switch)" % blocks if len(blocks) > 1 else "no answer"))
        try:
            c.cloud.heartbeat(0, "waiting for a settled exit pool")
        except Exception:
            pass
        time.sleep(30)


def make_session(width, ua):
    s = requests.Session()
    s.headers.update({"User-Agent": ua})
    s.mount("https://", requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=MAX_WIDTH + 4,
                                                      max_retries=0, pool_block=True))
    return s


class Crew:
    """One role, one session, N workers, its own queue, results, counters and detectors."""

    def __init__(self, role, width, lane_ctx):
        self.role, self.width, self.ctx = role, width, lane_ctx
        self.session = None
        self.workers = []
        self.stop = threading.Event()
        self.q = queue.Queue()
        self.results = []
        self.lock = threading.Lock()
        self.stats = {"reqs": 0, "ok": 0, "fail": 0, "reask": 0, "short": 0,
                      "filled": 0, "pending": 0, "absent": 0, "blank": 0}
        self.failed = []                  # (item, reason) since the last land - a role that walks a range re-asks these
        self.transport_streak = 0
        self.transport_hits = []          # times of recent transport errors: a burst is a cut line
        self.wall_streak = 0
        self.last_success = time.time()
        self.cloud = Cloud(role.source, role.lane, lane_ctx.host, app="%s %s" % (role.source, role.lane))
        self.outbox = Outbox(lane_ctx.here / ("%s.outbox.jsonl" % role.lane))
        self.fails = lane_ctx.here / ("%s.fails.jsonl" % role.lane)
        self.held = set()                 # claimed, not yet landed
        self.tries = 0                    # redials in the current incident
        self.wait_s = None                # the backoff state: set from --redial-wait at the first hang-up; x2 per refused re-entry, /2 per served one
        self.ok_at_redial = 0             # landings when the last re-entry was made: served or refused is decided by landings, never by age
        self.last_redial = 0.0
        self.reentry_at = None            # set at start and by a hang-up: when the crew may enter; the main loop enters it (nothing blocks)
        self.entries = 0                  # entries made in the life of the process: the first, then every re-entry
        self.ramp = None                  # the births thread of the current entry
        self.ramp_end = 0.0               # when the last ramp completed: the next crew enters --entry-gap after it
        self.born = 0                     # workers born in the current entry
        self.idle_until = 0.0             # when the to-do list came back empty, do not ask again before this
        self.progress_at = time.time()    # when the last PROGRESS line was printed (the rate divides by real time)

    # ── the fetcher every worker uses: counts, closes, classifies ────────────────────────
    def get(self, url, referer, timeout=90):
        with self.lock:
            self.stats["reqs"] += 1
        try:
            r = self.session.get(url, headers={"Referer": referer}, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            raise Transport("%s: %s" % (type(e).__name__, reason(e)))
        try:
            if r.status_code >= 400:
                raise HTTPStatus(r.status_code, url)
            return r.content, r.headers.get("Content-Type", "")
        finally:
            r.close()

    def note_fail(self, doc_id, err):
        with self.lock:
            self.stats["fail"] += 1
            self.failed.append((doc_id, err))
        try:
            with self.fails.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "id": doc_id, "err": err[:160]}) + "\n")
        except OSError:
            pass

    def worker(self, born):
        while not self.stop.is_set():
            try:
                doc_id, registry, attempt = self.q.get(timeout=1)
            except queue.Empty:
                continue
            try:
                value = self.role.fetch(self, doc_id, registry)
                classify = getattr(self.role, "classify", None)
                with self.lock:
                    self.results.append({"doc_id": doc_id, "value": value})
                    self.stats["ok"] += 1
                    self.stats[classify(value) if classify else ("filled" if value not in ("pending", "absent") else value)] += 1
                    self.transport_streak = 0
                    self.wall_streak = 0
                    self.last_success = time.time()
            except Refused as e:
                self.ctx.park("REFUSED at %s %s - %s" % (doc_id, time.strftime("%Y-%m-%d %H:%M"), e), code=2)
                return
            except HTTPStatus as e:
                with self.lock:
                    if e.code in (429, 503):             # the wall counts these two only (trap 2)
                        self.wall_streak += 1
                self.note_fail(doc_id, str(e))
            except Transport as e:
                now = time.time()
                with self.lock:
                    self.transport_streak += 1
                    self.transport_hits.append((now, born))
                    self.transport_hits = [(t, b) for t, b in self.transport_hits if now - t <= HANGUP_WINDOW_S]
                if attempt == 0 and not self.stop.is_set():
                    self.q.put((doc_id, registry, 1))     # one more try: a stale keep-alive after an idle spell fails once
                else:
                    self.note_fail(doc_id, str(e))
                self.stop.wait(HANGUP_PAUSE_S)            # a cut line never re-dials at full speed (the 40x5 pattern)
            except Retry as e:
                with self.lock:
                    if str(e).startswith("short"):
                        self.stats["short"] += 1
                self.note_fail(doc_id, str(e))
            except Exception as e:
                self.note_fail(doc_id, "%s: %s" % (type(e).__name__, reason(e)))
            # a parked worker (width lowered) leaves after its document
            if born > self.width:
                return

    def hung_up(self):
        """The far side closed the session: every worker hit the wire inside HANGUP_WINDOW_S and nothing has landed
        for HANGUP_QUIET_S (login 2026-09-04: "you will know its time to rebatch when ALL lanes are closed").  A
        partial close is not this - those workers redial one by one while the other lines keep landing, and the
        crew keeps its width (2026-09-04 12:27: 17 lines closed, all 40 back in 30 s).  A healthy crew fails a
        handful of requests an hour; a closed session fails the whole width inside a minute (measured 2026-09-04
        14:51: 40 errors in 60 s) and lands nothing after.  During a ramp the whole width is the workers born."""
        now = time.time()
        with self.lock:
            self.transport_hits = [(t, b) for t, b in self.transport_hits if now - t <= HANGUP_WINDOW_S]
            if not self.transport_hits or now - self.last_success <= HANGUP_QUIET_S:
                return False
            whole = max(1, min(self.width, self.born))
            return len({b for _, b in self.transport_hits}) >= whole or len(self.transport_hits) >= self.width

    def enter(self, stagger):
        """ONE entry: a fresh pooled session, workers born `stagger` apart on their own thread - one handshake
        each, then keep-alive for the life of the crew.  Returns at once: the main loop keeps feeding and
        landing while the ramp runs (a 40-wide ramp is about 200 s)."""
        self.stop = threading.Event()
        self.transport_hits = []
        self.session = make_session(self.width, self.role.ua)
        self.workers = []
        self.born = 0
        self.entries += 1
        self.transport_streak = 0
        self.wall_streak = 0
        self.last_success = time.time()
        self.ramp = threading.Thread(target=self._births, args=(1, self.width, stagger), daemon=True, name="%s-births" % self.role.lane)
        self.ramp.start()

    def _births(self, lo, hi, stagger):
        for i in range(lo, hi + 1):
            if self.stop.is_set():
                break
            t = threading.Thread(target=self.worker, args=(i,), daemon=True, name="%s-%d" % (self.role.lane, i))
            t.start()
            self.workers.append(t)
            self.born = max(self.born, i)
            if i < hi:
                self.stop.wait(stagger)
        self.ramp_end = time.time()

    def ramping(self):
        return self.ramp is not None and self.ramp.is_alive()

    def leave(self):
        self.stop.set()
        if self.ramp is not None:
            self.ramp.join(timeout=30)
        for t in list(self.workers):
            t.join(timeout=120)
        try:
            self.session.close()
        except Exception:
            pass

    def resize(self, new_width, stagger):
        """Workers above the new width park after their current document; missing ones are born staggered on
        the births thread, never blocking the loop."""
        old, self.width = self.width, new_width
        if new_width > old:
            self.ramp = threading.Thread(target=self._births, args=(old + 1, new_width, stagger), daemon=True, name="%s-births" % self.role.lane)
            self.ramp.start()

    def alive(self):
        return sum(1 for t in list(self.workers) if t.is_alive())


class Context:
    def __init__(self, here, host, args):
        self.here, self.host, self.args = here, host, args
        self.exit_code = None
        self.exit_reason = None
        self.stopping = threading.Event()

    def park(self, why, code):
        """Stop the whole process with a written reason; the lane refuses to start again until
        --unpark, so nobody walks it back into a refusal by habit."""
        if self.stopping.is_set():
            return
        self.exit_code, self.exit_reason = code, why
        self.stopping.set()
        try:
            (self.here / ("%s.parked" % self.args.lane)).write_text(why + "\n", encoding="utf-8")
        except OSError:
            pass


def _log(ctx, msg):
    line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    if ctx.args.log:
        try:
            with open(ctx.args.log, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def _control(ctx, crews):
    """<lane>.control: `width=N` / `<lane>=N` per crew, `stop` to stop.  Read once a minute."""
    p = ctx.here / ("%s.control" % ctx.args.lane)
    if not p.exists():
        return
    try:
        lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return
    for l in lines:
        if l.lower() == "stop":
            ctx.exit_code, ctx.exit_reason = 0, "stopped by %s at %s" % (p.name, time.strftime("%H:%M"))
            ctx.stopping.set()
            return
        if "=" in l:
            k, v = [x.strip() for x in l.split("=", 1)]
            for c in crews:
                if (k == "width" and c is crews[0]) or k == c.role.lane:
                    try:
                        n = min(int(v), MAX_WIDTH)
                    except ValueError:
                        continue
                    if n != c.width and n > 0:
                        _log(ctx, "%s width %d -> %d (control file)" % (c.role.lane, c.width, n))
                        c.resize(n, ctx.args.stagger)


def _feed(ctx, c):
    """Keep the crew's queue a batch ahead: claim when it runs low, fetch the registries, queue.
    A role that walks a range instead (synchronization) brings its own feed."""
    if hasattr(c.role, "feed"):
        c.role.feed(c, ctx)
        return
    if c.q.qsize() >= c.width or time.time() < c.idle_until:
        return
    if ctx.args.limit and c.stats["ok"] + c.q.qsize() >= ctx.args.limit:
        return
    try:
        ids = c.cloud.claim(ctx.args.claim or 12 * c.width, ctx.args.ttl, ctx.args.pending_age)
        regs = c.cloud.registries(ids) if getattr(c.role, "needs_registry", True) else {}
    except Exception as e:
        _log(ctx, "%s: claim failed (%s) - will retry" % (c.role.lane, reason(e)))
        c.idle_until = time.time() + 30
        return
    if not ids:
        c.idle_until = time.time() + 60          # nothing to do: ask again in a minute, not every second
        return
    for i in ids:
        c.held.add(i)
        c.q.put((i, regs.get(i), 0))


def _land(ctx, c, final=False):
    if hasattr(c.role, "land"):
        c.role.land(c, ctx)               # a role that walks a range lands its own way (ids + the edge)
        return
    with c.lock:
        rows, c.results = c.results, []
        c.failed = []                     # claim lanes leave a failed document for a later pass
    if rows:
        c.outbox.append(rows)
        for r in rows:
            c.held.discard(r["doc_id"])
    if c.outbox.path.exists() and c.outbox.path.stat().st_size > 0:
        landed, left = c.outbox.drain(c.cloud.land)
        if left:
            _log(ctx, "%s: cloud did not take %d landings (kept in %s)" % (c.role.lane, left, c.outbox.path.name))


def _progress(ctx, c, t0, last):
    s = dict(c.stats)
    now = time.time()
    el = max(now - t0, 1e-9)
    docs = (s["ok"] - last.get("ok", 0)) / max(now - c.progress_at, 1e-9)   # real window, never an assumed minute
    c.progress_at = now
    fmt = ("PROGRESS %dm %s - reqs %s (%.1f/s) - %s " + getattr(c.role, "noun", "filled")
           + " - %s absent - %s pending - short %d - fail %d - reask %d - width %d/%d - held %d - outbox %d - %.2f docs/s")
    line = fmt % (el / 60, c.role.lane, "{:,}".format(s["reqs"]), s["reqs"] / el, "{:,}".format(s["filled"]),
                  "{:,}".format(s["absent"]), "{:,}".format(s["pending"]), s["short"], s["fail"], s["reask"],
                  c.alive(), c.width, len(c.held), c.outbox.count(), docs)
    if c.reentry_at is not None:
        line += " - re-entry in %ds" % max(0, int(c.reentry_at - now))
    elif c.ramping():
        line += " - ramping %d/%d" % (c.born, c.width)
    status = getattr(c.role, "status", None)
    _log(ctx, line + (" - " + status() if status else ""))
    return s


def _rebatch(ctx, c):
    """THE REBATCH (login 2026-09-04: "pull out, rebatch, then launch"): the cut batch is dropped so the
    re-entry asks for NEW work.  A claim lane empties its queue - the dropped claims expire on their own
    (--ttl) and come back in a later pass; a role that walks a range (synchronization) brings its own
    rebatch (the window is re-asked from the edge, which never moved past an unanswered number).  Without
    this the re-entry resumed the cut batch from the same queue, which is what the door's closing waves
    refuse (2026-09-04 13:03)."""
    if hasattr(c.role, "rebatch"):
        return c.role.rebatch(c, ctx)
    n = 0
    while True:
        try:
            item = c.q.get_nowait()
        except queue.Empty:
            break
        c.held.discard(item[0])
        n += 1
    return n


def _hangup(ctx, c, why):
    """The session closed (or the wire died): hang up at once, land what the crew holds, drop the cut batch
    and set the wait; the main loop re-enters the crew when it is due (_await_entry).  Nothing blocks:
    every other crew keeps feeding and landing."""
    now = time.time()
    if c.wait_s is None:
        c.wait_s = ctx.args.redial_wait
    if c.tries and (c.stats["ok"] - c.ok_at_redial >= SERVED_LANDINGS or now - c.last_redial >= SERVED_S):
        c.tries = 0                      # the last re-entry was SERVED (a real batch landed, or five minutes lived) and the door then closed it: the incident closed
        c.wait_s = max(c.wait_s // 2, ctx.args.redial_wait)
    elif c.tries:
        c.wait_s = min(c.wait_s * 2, 4800)   # the last re-entry was REFUSED at the door (cut inside its ramp): the next wait doubles
    if c.tries >= ctx.args.tries:
        ctx.park("PARKED: %d re-entries in a row refused (%s) at %s" % (c.tries, c.role.lane, time.strftime("%Y-%m-%d %H:%M")), code=3)
        return
    _log(ctx, "%s: %s - hanging up" % (c.role.lane, why))
    c.leave()
    _land(ctx, c)                                       # what the crew had already fetched lands now
    dropped = _rebatch(ctx, c)
    c.reentry_at = time.time() + c.wait_s
    _log(ctx, "%s: %d of the cut batch dropped (their claims expire on their own) - re-entry %d/%d on a fresh batch in %ds, no line open"
         % (c.role.lane, dropped, c.tries + 1, ctx.args.tries, c.wait_s))
    try:
        c.cloud.heartbeat(0, "hang-up: re-entry %d/%d at %s" % (c.tries + 1, ctx.args.tries, time.strftime("%H:%M", time.localtime(c.reentry_at))))
    except Exception:
        pass


def _await_entry(ctx, crews, c):
    """A crew waiting to enter (the first entry, or a re-entry after a hang-up) enters when its wait is over,
    no other crew is ramping, the last ramp ended --entry-gap ago, the wire is up and the exit pool is
    settled.  The fresh batch is claimed right before the ramp so the first-born workers have work; the
    try is spent here, at the re-entry itself - never while the wire is down."""
    now = time.time()
    if now < c.reentry_at or ctx.stopping.is_set():
        return
    if any(o is not c and o.ramping() for o in crews):
        return                                              # one ramp at a time: three doors, never one moment
    if now - max([o.ramp_end for o in crews] + [0.0]) < ctx.args.entry_gap:
        return
    if not net_up():
        c.reentry_at = now + 60
        _log(ctx, "%s: network is DOWN - waiting a minute, no try spent" % c.role.lane)      # wifi is not a block
        return
    _feed(ctx, c)
    wait_for_pool(ctx, c)
    if ctx.stopping.is_set():
        return
    if c.entries:
        c.tries += 1
        c.last_redial = time.time()
        c.ok_at_redial = c.stats["ok"]
    c.enter(ctx.args.stagger)
    c.reentry_at = None
    _log(ctx, "%s: %s - %d workers, births %.0fs apart, one entry" % (c.role.lane, "entered" if c.entries == 1 else "re-entered (%d/%d)" % (c.tries, ctx.args.tries), c.width, ctx.args.stagger))


def run(roles, args, here):
    """roles = [(role, width), ...]; the first is the lane's own."""
    here = pathlib.Path(here)
    host = args.host or socket.gethostname()
    ctx = Context(here, host, args)
    parked = here / ("%s.parked" % args.lane)
    if parked.exists() and not args.unpark:
        raise SystemExit("this lane is PARKED: %s\n  start it again with --unpark once a person has decided."
                         % parked.read_text(encoding="utf-8").strip())
    if parked.exists():
        parked.unlink()
    for role, width in roles:
        if width <= 0 or width > MAX_WIDTH:
            raise SystemExit("%s: width %d - a crew has 1 to %d workers; a zero-worker floor does not exist" % (role.lane, width, MAX_WIDTH))
    lock = here / ("%s.lock" % args.lane)
    take_lock(lock)

    def _signalled(signum, _frame):
        ctx.exit_code, ctx.exit_reason = 0, "stopped by signal %d at %s" % (signum, time.strftime("%H:%M"))
        ctx.stopping.set()
    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)):
        if sig is not None:
            try:
                signal.signal(sig, _signalled)
            except Exception:
                pass

    crews = [Crew(role, width, ctx) for role, width in roles]
    _log(ctx, "%s up on %s - %s - one pooled session per crew, staggered births, keep-alive after, no pacer"
         % (args.lane, host, ", ".join("%s x%d" % (c.role.lane, c.width) for c in crews)))
    for c in crews:
        try:
            c.cloud.connect()
            c.cloud.heartbeat(c.width, "started 1x%d at %s" % (c.width, time.strftime("%Y-%m-%d %H:%M")))
        except Exception as e:
            raise SystemExit("the cloud table is unreachable (%s) - nothing to claim, not entering ACRIS" % reason(e))
        _land(ctx, c)                                  # anything left in the outbox from last time
        _feed(ctx, c)
        c.reentry_at = time.time()                     # every crew starts waiting to enter: the loop enters them one ramp at a time, --entry-gap apart
    t0 = time.time()
    last = {c.role.lane: dict(c.stats) for c in crews}
    tick = time.time()
    quiet = {c.role.lane: 0 for c in crews}
    try:
        while not ctx.stopping.is_set():
            time.sleep(1)
            for c in crews:
                if c.reentry_at is not None:
                    _await_entry(ctx, crews, c)             # the first entry, or a re-entry after a hang-up: one ramp at a time
                    continue                                # no feed, no detectors while the crew has no line open
                _feed(ctx, c)
                with c.lock:
                    n = len(c.results)
                if n >= 200:
                    _land(ctx, c)
                # detectors
                if c.wall_streak >= 40:
                    ctx.park("wall: %d consecutive 503/429 on %s at %s - not retrying, not rotating"
                             % (c.wall_streak, c.role.lane, time.strftime("%Y-%m-%d %H:%M")), code=4)
                if c.hung_up():                               # at once on a close: no re-handshake storm, the wait, ONE entry on a fresh batch
                    _hangup(ctx, c, "the session closed (every worker hit the wire inside %ds, nothing landed for %ds)"
                            % (HANGUP_WINDOW_S, int(time.time() - c.last_success)))
                elif c.transport_streak >= 3 * c.width and time.time() - c.last_success > 60:
                    _hangup(ctx, c, "dead transport (%d transport errors in a row, nothing landed for %ds)"
                            % (c.transport_streak, int(time.time() - c.last_success)))
                if args.limit and c.stats["ok"] >= args.limit and c.q.empty():
                    ctx.exit_code, ctx.exit_reason = 0, "limit %d reached" % args.limit
                    ctx.stopping.set()
            if time.time() - tick >= getattr(args, "tick", 60):     # the minute; shorter only in tests
                tick = time.time()
                _control(ctx, crews)
                for c in crews:
                    if hasattr(c.role, "check"):
                        c.role.check(ctx)                         # e.g. the drive is still there
                    _land(ctx, c)
                    s = _progress(ctx, c, t0, last[c.role.lane])
                    asked = s["reqs"] - last[c.role.lane]["reqs"]
                    moved = s["ok"] - last[c.role.lane]["ok"]
                    quiet[c.role.lane] = quiet[c.role.lane] + 1 if (asked > 0 and moved == 0) else 0
                    if quiet[c.role.lane] >= 5 and c.reentry_at is None:      # five minutes asking, nothing landing = our wire
                        quiet[c.role.lane] = 0
                        _hangup(ctx, c, "five minutes asking, nothing landing (our wire)")
                    last[c.role.lane] = s
                    try:
                        c.cloud.heartbeat(c.alive(), None)
                    except Exception as e:
                        _log(ctx, "%s: heartbeat failed (%s)" % (c.role.lane, reason(e)))
    except KeyboardInterrupt:
        ctx.exit_code, ctx.exit_reason = 0, "stopped by hand (Ctrl+C) at %s" % time.strftime("%H:%M")
        ctx.stopping.set()
    except Exception as e:
        ctx.exit_code, ctx.exit_reason = 5, "CRASH %s: %s at %s" % (type(e).__name__, reason(e), time.strftime("%H:%M"))
        ctx.stopping.set()
        traceback.print_exc()                            # the traceback prints and the process leaves with 5 - a raise here
                                                         # made the interpreter exit 1, which the fleet reads as "refused to start"
    finally:
        for c in crews:
            c.leave()
            _land(ctx, c, final=True)
            try:
                c.cloud.heartbeat(0, ctx.exit_reason)
            except Exception:
                pass
            c.cloud.close()
        try:
            lock.unlink()
        except OSError:
            pass
        _log(ctx, "run end %.1f min - %s" % ((time.time() - t0) / 60, ctx.exit_reason or "stopped"))
    return ctx.exit_code or 0
