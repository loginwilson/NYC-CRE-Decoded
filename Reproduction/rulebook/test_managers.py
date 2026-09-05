"""OFFLINE PROOF OF THE THREE MANAGERS - nothing asked of any source, no cloud.

    python test_managers.py

Part 1 proves rate_manager.py alone against fake exits (10x scale so integer landings move in short windows: floor 50, ideal
60-70, hard 80; a 0.6-s window stands for a 120-s one): the arithmetic of one decision, the ramp until the rate is met, the
door curve (a grow that buys nothing is undone, the hold doubles), the request ceiling as a projection at the exit's recent
speed (retire straight to the cap, never grow past it, hold under 3 lines, a stalled window never raises the cap).

Part 2 proves the WIRING in lane.py: a managed crew with a fake role and a fake cloud enters with ONE worker, ramps, the
Governor decides, the SESSION knob ends the session on purpose, the cycle re-enters on a fresh batch (batch -> ramp -> adjust
-> session -> batch), and an unmanaged crew still enters at its fixed width - the lane as before.
"""
import pathlib
import random
import re
import sys
import threading
import time
import types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import rate_manager as RM       # noqa: E402
import lane                     # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)


# ═══════════════════════════════════════════ PART 1: the rate manager alone ═══════════════════════════════════════════
print("=== 1a. next_width: the one decision (floor 5, ideal 6-7, hard 8, 20..120, step 10)")
nw = lambda dps, w: RM.next_width(dps, w, 5.0, 6.0, 7.0, 8.0, 20, 120, 10)
check("2.7 docs/s at 40 (below the floor) -> a full step up (50)", nw(2.7, 40) == 50, nw(2.7, 40))
check("5.5 at 80 (under the band) -> a half step up (85)", nw(5.5, 80) == 85, nw(5.5, 80))
check("6.5 at 90 (in the band) -> hold", nw(6.5, 90) == 90, nw(6.5, 90))
check("6.0 and 7.0 at 90 (the edges) -> hold", nw(6.0, 90) == 90 and nw(7.0, 90) == 90)
check("7.5 at 90 (over the band) -> a half step down (85)", nw(7.5, 90) == 85, nw(7.5, 90))
check("9.0 at 90 (over the hard line) -> a full step down (80)", nw(9.0, 90) == 80, nw(9.0, 90))
check("never below width_min (20 at 20 docs/s -> 20), never above width_max (1.0 at 115 -> 120)", nw(20.0, 25) == 20 and nw(1.0, 115) == 120)
check("a crawl grows by the step, not the ratio (0.5 at 40 -> 50)", nw(0.5, 40) == 50, nw(0.5, 40))


class Fake:
    """An exit: total docs/s = rate(width) x factor; landings accumulate by real elapsed time."""
    factor = 1.0

    def __init__(self, rate, width, per_doc=0):
        self.rate, self.width, self.per_doc, self.landed, self.lock = rate, width, per_doc, 0.0, threading.Lock()
        self.stop = threading.Event(); self.log_lines = []; self.max_width = width
        self.t = threading.Thread(target=self._run, daemon=True); self.t.start()

    def _run(self):
        last = time.time()
        while not self.stop.is_set():
            time.sleep(0.01)
            now = time.time()
            with self.lock:
                self.landed += Fake.factor * self.rate(self.width) * (now - last)
            last = now

    def landings(self):
        with self.lock:
            return int(self.landed)

    def requests(self):
        with self.lock:
            return int(self.landed * self.per_doc)

    def alive(self): return self.width
    def spawn(self, n): self.width += n; self.max_width = max(self.max_width, self.width)
    def retire(self, n): self.width -= n
    def log(self, m): self.log_lines.append(m)


def gov(f, **kw):
    args = dict(floor=50.0, ideal_lo=60.0, ideal_hi=70.0, hard=80.0, lo=20, hi=120, step=10, every=0.6, settle=0.3,
                knee_windows=2, knee_hold=5, knee_gain=1.5)
    args.update(kw)
    return RM.Governor(f.landings, f.alive, f.spawn, f.retire, f.stop, f.log, **args)


print("=== 1b. the Governor against fake exits (10x scale: floor 50, ideal 60-70, hard 80)")
Fake.factor = 1.0
f = Fake(lambda w: 0.6 * w, 80)                                   # a slow exit: 48 docs/s at 80, the band needs 100-116
g = gov(f); g.start(); time.sleep(13.0); f.stop.set(); g.join(1)
widths = [d[2] for d in g.decisions]
check("slow exit: grew from 80 and settled in the band (100..116), holding", widths and max(widths) > 80 and 100 <= widths[-1] <= 116 and widths[-1] == widths[-2], widths[-6:])
check("slow exit: every grow was judged before the next", all(("judging" in f.log_lines[i + 1] or "holding" in f.log_lines[i + 1]) for i, l in enumerate(f.log_lines[:-1]) if "GROW" in l))

f = Fake(lambda w: 2.0 * w, 40)                                   # a fast exit: 80 docs/s at 40 = the hard line
g = gov(f); g.start(); time.sleep(6.0); f.stop.set(); g.join(1)
widths = [d[2] for d in g.decisions]
check("fast exit: came down from 40 and settled in the band (29..35)", widths and 29 <= widths[-1] <= 35 and any("RETIRE" in l for l in f.log_lines), widths[-5:])

f = Fake(lambda w: 0.5 * min(w, 100) - 0.3 * max(0, w - 100), 80)   # the door curve: past 100 lines every extra line costs
g = gov(f, every=0.3); g.start(); time.sleep(7.5); f.stop.set(); g.join(1)
widths = [d[2] for d in g.decisions]
first_knee = next((i for i, d in enumerate(g.decisions) if d[2] == 100 and d[1] > 100), None)
runs, run = [], 0
for d in (g.decisions[first_knee + 1:] if first_knee is not None else []):
    run = run + 1 if d[1] > 100 else 0
    runs.append(run)
holds = [int(re.search(r"holding there (\d+) windows", l).group(1)) for l in f.log_lines if "holding there" in l]
check("door curve: never ran to width_max, saw the grow past the knee buy nothing, stepped back to 100", f.max_width <= 110 and any("bought nothing" in l for l in f.log_lines) and first_knee is not None, (f.max_width, first_knee))
check("door curve: every later probe lasted at most 3 windows and came back; each repeated knee holds twice as long", (not runs or max(runs) <= 3) and holds and holds == sorted(holds) and (len(holds) < 2 or holds[1] == 2 * holds[0]), (runs, holds))

print("=== 1c. the request ceiling as a projection at the exit's recent speed")
f = Fake(lambda w: 0.6 * w, 80, per_doc=15)                       # long documents: 720 req/s at 80, the ceiling 600 -> the cap is 63
g = gov(f, requests=f.requests, rps_ceiling=600.0); g.start(); time.sleep(3.6); f.stop.set(); g.join(1)
widths = [d[2] for d in g.decisions]
check("over the ceiling: retired straight to the cap (63 +-2) in the first window, then never grew past it", widths and 61 <= widths[0] <= 65 and max(widths) <= 66, widths[:5])
f = Fake(lambda w: 0.6 * w, 80, per_doc=11)                       # room under the ceiling: 528 req/s, the cap is 86 (not the step's 90)
g = gov(f, requests=f.requests, rps_ceiling=600.0); g.start(); time.sleep(5.0); f.stop.set(); g.join(1)
widths = [d[2] for d in g.decisions]
check("under the ceiling: the docs band's grow stopped at the cap (86 +-2), then held", 84 <= f.max_width <= 88 and widths[-1] == widths[-2] == f.max_width and not any("RETIRE" in l for l in f.log_lines), (f.max_width, widths[-3:]))
Fake.factor = 1.0
f = Fake(lambda w: 0.6 * w, 86, per_doc=11)                       # at the cap; then the exit STALLS for one window
g = gov(f, requests=f.requests, rps_ceiling=600.0); g.start()
time.sleep(2.1); Fake.factor = 0.5; time.sleep(0.6); Fake.factor = 1.0; time.sleep(3.0); f.stop.set(); g.join(1)
widths = [d[2] for d in g.decisions]
check("a stalled window (docs and requests halve) raises no cap and grows nothing: the width stayed at 86", widths and all(w == 86 for w in widths) and not any("GROW" in l for l in f.log_lines), widths)
check("the hold names the exit's recent speed", any("recent speed" in l for l in f.log_lines))

print("=== 1d. the ramp until the rate is met")
f = Fake(lambda w: 0.6 * w, 1)
g = gov(f, ramp=True, stagger=0.02, ramp_window=0.6, settle=0.3, every=0.6); g.start(); time.sleep(5.5); f.stop.set(); g.join(1)
done = [l for l in f.log_lines if "RAMP DONE" in l]
check("ramp: one worker in, one every stagger, RAMP DONE when the rate is met, near the band's floor (95..125 at 0.6/worker)", done and "the rate is met" in done[0] and 95 <= f.max_width <= 125, (done[:1], f.max_width))
f = Fake(lambda w: 0.6 * w, 1, per_doc=15)                        # long documents: the ceiling's 90% line comes first
g = gov(f, ramp=True, stagger=0.02, ramp_window=0.6, settle=0.3, every=0.6, requests=f.requests, rps_ceiling=600.0); g.start(); time.sleep(3.0); f.stop.set(); g.join(1)
done = [l for l in f.log_lines if "RAMP DONE" in l]
check("ramp: stops on the request ceiling's 90% line when that comes first, read at the current width (60 +-4, no half-window overshoot)", done and "within 10% of the ceiling" in done[0] and 56 <= f.max_width <= 64, (done[:1], f.max_width))

print("=== 1e. the session knob")
check("no time cap never ends; 120 min ends at 120:00 not 119:59", RM.session_over(1000.0, 0, now=1000.0 + 10 ** 7) is False and RM.session_over(1000.0, 120, now=1000.0 + 7199) is False and RM.session_over(1000.0, 120, now=1000.0 + 7200) is True)


# ═══════════════════════════════════════════ PART 2: the wiring in lane.py ═══════════════════════════════════════════
print("=== 2. the wiring: a managed crew through the whole loop (batch -> ramp -> adjust -> session knob -> batch)")


class FakeCloud:
    """The to-do list: claim hands out ids, land takes rows, heartbeat records the width."""
    ids = 0
    def __init__(self, *a, **k): self.beats = []; self.landed = 0
    def connect(self): pass
    def close(self): pass
    def claim(self, n, ttl):
        out = ["D%08d" % i for i in range(FakeCloud.ids, FakeCloud.ids + n)]
        FakeCloud.ids += n
        return out
    def registries(self, ids): return {i: {"recorded": "2026-09-04"} for i in ids}
    def land(self, rows, pending_age="1 hour"): self.landed += len(rows)
    def heartbeat(self, width, last_event=None): self.beats.append((width, last_event))


class FakeOutbox:
    def __init__(self, path): self.rows = []; self.path = path
    def append(self, rows): self.rows.extend(rows)
    def drain(self, land):
        land(self.rows); n = len(self.rows); self.rows = []
        return n, 0
    def count(self): return len(self.rows)


class Role:
    """A document takes two requests and 40 ms: a fast exit (at 10x scale the band sits at 60-70 docs/s)."""
    source, lane_name, ua, noun, needs_registry = "test", "documentation", "test-ua", "pdfs", True
    lane = "documentation"
    def fetch(self, crew, doc_id, registry):
        with crew.lock:
            crew.stats["reqs"] += 2
        time.sleep(0.04)
        return "canon/" + doc_id


def run_lane(manage, seconds, **knobs):
    lane.Cloud, lane.Outbox = FakeCloud, FakeOutbox                 # no cloud, no source
    lane.net_up = lambda: True
    here = HERE / "_test_managers_tmp"
    here.mkdir(exist_ok=True)
    for p in here.glob("documentation.*"):
        p.unlink()
    ns = dict(width=40, host="test", stagger=0.02, claim=0, ttl="20 minutes", pending_age="1 hour", redial_wait=1, tries=4,
              no_pool_check=True, entry_gap=0.0, also=[], limit=0, log="", unpark=False, lane="documentation", tick=1,
              manage=manage, ramp_to_rate=1, rate_floor=50.0, rate_ideal_lo=60.0, rate_ideal_hi=70.0, dps_ceiling=80.0,
              rps_ceiling=0.0, width_min=2, width_max=60, adjust_every=1, adjust_step=10, session_max_requests=0, ramp_window=1.0)
    ns.update(knobs)
    args = types.SimpleNamespace(**ns)
    lines = []
    lane._log_orig = getattr(lane, "_log_orig", lane._log)
    def capture(ctx, msg):
        lines.append(msg)
    lane._log = capture
    stop_at = time.time() + seconds
    ctxs = []
    real_ctx = lane.Context
    class Ctx(real_ctx):
        def __init__(self, *a, **k):
            super().__init__(*a, **k); ctxs.append(self)
    lane.Context = Ctx
    def stopper():
        while time.time() < stop_at:
            time.sleep(0.05)
        for c in ctxs:
            c.exit_code, c.exit_reason = 0, "test over"
            c.stopping.set()
    threading.Thread(target=stopper, daemon=True).start()
    rc = lane.run([(Role(), args.width)], args, here)
    lane.Context = real_ctx
    return rc, lines


rc, lines = run_lane(manage=1, seconds=12.0, session_max_requests=2500)     # the ramp ends (the band or width_max), verdicts follow, then the knob
entered = [l for l in lines if "entered" in l and "RATE MANAGER on" in l]
ramp_done = [l for l in lines if "RAMP DONE" in l]
verdicts = [l for l in lines if "RATE MANAGER:" in l]
resets = [l for l in lines if "SESSION RESET" in l]
reentries = [l for l in lines if "re-entered" in l]
progress = [l for l in lines if l.startswith("PROGRESS")]
check("managed: the crew entered with ONE worker and said so", entered and "one worker in" in entered[0], entered[:1])
check("managed: RAMP DONE - the rate manager ramped it (the width grew past one)", ramp_done and any("width" in l and "ramping" not in l for l in progress), ramp_done[:1])
check("managed: the manager gave verdicts after the ramp", len(verdicts) >= 1, verdicts[:2])
check("managed: the SESSION knob ended the session on purpose (2,500 requests)", resets and "ending on purpose" in resets[0], resets[:1])
check("managed: the cycle re-entered on a fresh batch after the planned close - the loop closed", reentries and any("RATE MANAGER on" in l for l in reentries), reentries[:1])
check("managed: a planned close spent no try (re-entered (1/4), not (2/4))", reentries and "(1/4)" in reentries[0], reentries[:1])
check("managed: the claim was a whole batch (12 x the target 40 = 480) although the crew had one worker", FakeCloud.ids >= 480, FakeCloud.ids)
check("the run ended cleanly", rc == 0, rc)

rc, lines = run_lane(manage=0, seconds=2.5)
entered = [l for l in lines if "entered" in l]
check("unmanaged: the lane as before - entered at its fixed width, no manager", entered and "40 workers" in entered[0] and not any("RATE MANAGER" in l for l in lines), entered[:1])
check("the run ended cleanly", rc == 0, rc)

import shutil
shutil.rmtree(HERE / "_test_managers_tmp", ignore_errors=True)
print("\nTHREE MANAGERS:", "ALL OK" if not fails else "FAILURES: %s" % fails, "- offline, nothing asked of any source")
sys.exit(1 if fails else 0)
