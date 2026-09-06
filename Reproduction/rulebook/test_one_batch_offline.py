"""ONE BATCH proven offline (login 2026-09-06: "one batch of, say, 30 workers, but of those 30 workers, 10 are syncs and 20 are
registrations") - no ACRIS request, no cloud: a fake Cloud in place of cloud.Cloud, two fake roles in one process.

  host   registration x3: lands, until the far side is told to die - then every fetch raises Transport (the session closed)
  guest  documentation x4: lands all along (the wire never dies for it)

  expect  the guest JOINS right after the host's ramp (the stagger, not --entry-gap), with no entry of its own;
          when the host hangs up the guest leaves too and both wait the same wait; the host re-enters first, then the guest
          joins again; the guest is never hung up on its own account; `stop` ends the run with exit 0
"""
import pathlib, sys, threading, time, types
PHASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE / "rulebook"))
import lane

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simbatch")
HERE.mkdir(parents=True, exist_ok=True)
for f in HERE.glob("*"):
    f.unlink()


class FakeCloud:
    """Enough of cloud.Cloud for the lane loop: claims hand out fresh ids, landings are counted, heartbeats kept."""
    n = 0
    landed = {}
    beats = []

    def __init__(self, source, lane_name, host, app="lane"):
        self.lane = lane_name

    def connect(self):
        pass

    def close(self):
        pass

    def claim(self, n=500, ttl="20 minutes"):
        ids = ["%s-%05d" % (self.lane[:3].upper(), FakeCloud.n + i) for i in range(n)]
        FakeCloud.n += n
        return ids

    def registries(self, ids):
        return {i: {"doc type": "DEED"} for i in ids}

    def land(self, rows, pending_age="1 hour"):
        FakeCloud.landed[self.lane] = FakeCloud.landed.get(self.lane, 0) + len(rows)
        return len(rows)

    def heartbeat(self, width, last_event=None):
        FakeCloud.beats.append((self.lane, width, last_event))


lane.Cloud = FakeCloud
lane.net_up = lambda: True

LINES = []
_log0 = lane._log
def _log(ctx, msg):
    LINES.append((time.time(), msg))
    _log0(ctx, msg)
lane._log = _log


class Host:
    source, lane, ua = "acris", "registration", "sim/0 (never sent)"
    needs_registry = True
    die = False

    def fetch(self, crew, doc_id, registry):
        if Host.die:
            raise lane.Transport("closed")
        time.sleep(0.05)
        return {"doc type": "DEED", "sim": doc_id}


class Guest:
    source, lane, ua = "acris", "documentation", "sim/0 (never sent)"
    needs_registry = True

    def fetch(self, crew, doc_id, registry):
        time.sleep(0.05)
        return r"D:\NYC CRE Decoded\Reproduction\Acris\By Document\2004\08 Aug\21\%s.pdf" % doc_id


STAGGER, GAP, WAIT = 0.5, 10.0, 4       # the host's re-entry keeps --entry-gap from the last ramp: the wait is max(WAIT, GAP)
args = types.SimpleNamespace(lane="registration", width=3, host="SIM-HOST", stagger=STAGGER, claim=0, ttl="20 minutes",
                             pending_age="1 hour", redial_wait=WAIT, tries=3, no_pool_check=True, entry_gap=GAP, also=["documentation:4"],
                             one_batch=True, limit=0, log="", unpark=False, manage=0, ramp_to_rate=1, session_max_requests=0, tick=1)
fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)


def when(text, after=0.0, nth=1):
    hits = [t for t, m in LINES if text in m and t >= after]
    return hits[nth - 1] if len(hits) >= nth else None


rc = {}
t = threading.Thread(target=lambda: rc.__setitem__("code", lane.run([(Host(), 3), (Guest(), 4)], args, HERE)), daemon=True)
t0 = time.time()
t.start()
time.sleep(6)
up = when("ONE BATCH of 7")
entered = when("registration: entered")
joined = when("documentation: joined the batch right after registration's ramp")
check("the lane announced ONE BATCH of 7", up is not None)
check("the host entered", entered is not None)
check("the guest joined the batch (no entry of its own)", joined is not None and when("documentation: entered") is None)
if entered and joined:
    check("the guest joined after the host's ramp and inside the stagger, not --entry-gap (%.0f s)" % GAP,
          2 * STAGGER - 0.2 <= joined - entered <= 2 * STAGGER + 2.5, "%.2f s after the host entered" % (joined - entered))
check("both crews landing", FakeCloud.landed.get("registration", 0) > 0 and FakeCloud.landed.get("documentation", 0) > 0, FakeCloud.landed)

# the far side closes the host's lines: the whole batch hangs up
Host.die = True
t1 = time.time()
deadline = t1 + lane.HANGUP_WINDOW_S + lane.HANGUP_QUIET_S + 10
while time.time() < deadline and when("hanging up", t1) is None:
    time.sleep(0.5)
hung = when("hanging up", t1)
d2 = time.time() + 15                                   # the guest leaves right after: its leave() joins its workers first
while time.time() < d2 and when("documentation: the batch hung up - leaving too", t1) is None:
    time.sleep(0.2)
left = when("documentation: the batch hung up - leaving too", t1)
check("the host hung up (the session closed)", hung is not None and "registration:" in [m for tt, m in LINES if tt == hung][0])
check("the guest left with the batch, right after the host", left is not None and hung is not None and 0 <= left - hung <= 10, (left or 0) - (hung or 0))
check("the guest was never hung up on its own", when("documentation: the session closed", t1) is None and when("documentation: dead transport", t1) is None)
Host.die = False
time.sleep(max(WAIT, GAP) + 2 * STAGGER + 6)
re_host = when("registration: re-entered (1/3)", t1)
re_guest = when("documentation: joined the batch right after registration's ramp", t1)
check("the host re-entered after the wait (%d s)" % WAIT, re_host is not None and hung is not None and re_host - hung >= WAIT - 0.5, (re_host or 0) - (hung or 0))
check("the guest joined again after the host's ramp", re_host is not None and re_guest is not None and 2 * STAGGER - 0.2 <= re_guest - re_host <= 2 * STAGGER + 2.5,
      (re_guest or 0) - (re_host or 0))
check("landings resumed on both", FakeCloud.landed.get("registration", 0) > 0 and FakeCloud.landed.get("documentation", 0) > 0)

(HERE / "registration.control").write_text("stop", encoding="utf-8")
t.join(timeout=20)
check("stop ended the run with exit 0", not t.is_alive() and rc.get("code") == 0, rc)
print("\nONE BATCH (offline):", "ALL OK" if not fails else "FAILURES: %s" % fails, "- no source request, no cloud")
sys.exit(1 if fails else 0)
