"""OFFLINE: the two richmond walkers' rebatch (the cycle's hang-up, dormant at the county unless the wire dies).
No county request, no cloud.  A fake crew holds a queue; each role's rebatch must drop everything, forget it as in
flight, and leave the monitor able to ask again: synchronization puts windows on its re-ask list and lets a control be
asked again; registration re-asks pages, releases a details item's window count, lets a control be asked again."""
import datetime as dt, importlib.util, json, pathlib, queue, sys, threading, types
PHASE = pathlib.Path(__file__).resolve().parents[3]          # this file's Reproduction folder
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))
import lane

W = str(PHASE / "Richmond" / "workflow")
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
SY = load("richmond_sync", W + r"\synchronization\Richmond Synchronization.py")
RG = load("richmond_reg", W + r"\registration\Richmond Registration.py")

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simrebatch")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("*.json"):
    f.unlink()

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)

crew = types.SimpleNamespace(q=queue.Queue(), lock=threading.Lock(), results=[], failed=[])
ctx = types.SimpleNamespace(args=types.SimpleNamespace(log=""))
today = dt.date.today()

print("=== synchronization: the cut windows are dropped and re-asked")
args = types.SimpleNamespace(edge=(today - dt.timedelta(days=40)).isoformat(), every=10, heal_every=900, heal_days=30, pace=0.3)
sy = SY.Synchronization(HERE, args)
a, b = (today - dt.timedelta(days=29)), today
sy._queue(crew, "heal", a, b)
sy._queue(crew, "day", today, today)
sy._queue(crew, SY.CONTROL, dt.date.fromisoformat("2026-08-19"), dt.date.fromisoformat("2026-08-20"))
sy.control_pending = True
sy.attempts[("heal", a.isoformat(), b.isoformat())] = 1
check("three items queued and in flight", crew.q.qsize() == 3 and len(sy.inflight) == 3)
n = sy.rebatch(crew, ctx)
check("rebatch drops all three and empties the queue", n == 3 and crew.q.empty(), (n, crew.q.qsize()))
check("nothing stays in flight (the edge can move again)", sy.inflight == {} and sy.attempts == {}, (sy.inflight, sy.attempts))
check("the heal and the day windows are on the re-ask list; the control is not (it is asked again before the next heal)",
      sy.reask == {("heal", a.isoformat(), b.isoformat()), ("day", today.isoformat(), today.isoformat())} and sy.control_pending is False, (sy.reask, sy.control_pending))
sy._queue(crew, "heal", a, b)
check("a dropped window can be queued again at once (no longer in flight)", crew.q.qsize() == 1)
crew.q.get_nowait()

print("=== registration: pages re-asked, a details item releases its window, the control asked again")
args = types.SimpleNamespace(edge=(today - dt.timedelta(days=40)).isoformat(), days=30, every=900, pace=0.3, pending_age="1 hour")
rg = RG.Registration(HERE, args)
a, b = (today - dt.timedelta(days=29)).isoformat(), today.isoformat()
rg.windows[(a, b)] = {"pages": 3, "answered": {1}, "details": 1}
rg._queue(crew, ("page", a, b, 2))
rg._queue(crew, ("page", a, b, 3))
rg._queue(crew, ("details", a, b, 1, ("RC_1", "RC_2")))
rg._queue(crew, (RG.CONTROL, "2026-08-19", "2026-08-20", 1))
rg.control_pending = True
check("four items queued and in flight", crew.q.qsize() == 4 and len(rg.inflight) == 4)
n = rg.rebatch(crew, ctx)
check("rebatch drops all four and empties the queue", n == 4 and crew.q.empty(), (n, crew.q.qsize()))
check("nothing stays in flight", rg.inflight == {} and rg.attempts == {}, rg.inflight)
check("the two pages are on the re-ask list; the details item and the control are not", rg.reask == {("page", a, b, 2), ("page", a, b, 3)}, rg.reask)
check("the details item released its window's count (the window can close)", rg.windows[(a, b)]["details"] == 0, rg.windows[(a, b)])
check("the control will be asked again before the next walk", rg.control_pending is False)
check("a window with no details in flight and every page answered is done", rg._window_done(a, b) is False and (rg.windows[(a, b)]["answered"].update({2, 3}) or rg._window_done(a, b)))

print("=== the lane module drops a claim lane's queue the default way, and calls a walker's own rebatch")
class Role:
    source, lane, ua = "richmond", "documentation", "test"
lctx = types.SimpleNamespace(host="T", here=HERE, args=types.SimpleNamespace(log=""), stopping=threading.Event())
c = lane.Crew(Role(), 4, lctx)
for i in range(5):
    c.q.put(("RC_%d" % i, None, 0)); c.held.add("RC_%d" % i)
check("documentation: five claims dropped, held cleared", lane._rebatch(lctx, c) == 5 and c.q.empty() and not c.held)
c2 = lane.Crew(sy, 4, lctx)
sy._queue(c2, "day", today, today)
check("synchronization through lane._rebatch: its own rebatch runs (1 dropped, re-ask list grew)", lane._rebatch(lctx, c2) == 1 and ("day", today.isoformat(), today.isoformat()) in sy.reask)

print("=== the lanes' defaults: births 0.4 s apart, the county's widths")
import argparse
for mod, width in ((SY, 4), (RG, 4)):
    src = open(mod.__file__, encoding="utf-8").read()
    check("%s sets stagger=0.4 and width=%d" % (mod.__name__, width), ("set_defaults(width=%d, stagger=0.4)" % width) in src)
src = open(W + r"\documentation\Richmond Documentation.py", encoding="utf-8").read()
check("documentation sets stagger=0.4 and width=8", "set_defaults(width=8, stagger=0.4)" in src)

print("\nRICHMOND REBATCH:", "ALL OK" if not fails else "FAILURES: %s" % fails, "- no county request, no cloud")
sys.exit(1 if fails else 0)
