"""OFFLINE checks of the richmond synchronization lane: the monitor's feed and land against a fake crew and a fake
cloud - the control first, the catch-up windows from the edge, the day probe and the heal cadence, ids landed once,
the edge moving only after the rows are in, a hole after three failed asks, a broken control parking the lane.
No request, no cloud."""
import datetime as dt, importlib.util, json, pathlib, queue, sys, threading, time, types
PHASE = pathlib.Path(__file__).resolve().parents[3]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))
import lane, richmond
spec = importlib.util.spec_from_file_location("richmond_synchronization", str(PHASE / "Richmond" / "workflow" / "synchronization" / "Richmond Synchronization.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("synchronization.*"):
    f.unlink()

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)


class FakeCloud:
    def __init__(self):
        self.calls = []
        self.rows = set()
    def insert_ids(self, ids):
        self.calls.append(list(ids))
        new = [i for i in ids if i not in self.rows]
        self.rows.update(new)
        return len(new)

class FakeCrew:
    def __init__(self):
        self.q = queue.Queue(); self.results = []; self.failed = []; self.lock = threading.Lock(); self.cloud = FakeCloud(); self.width = 4

class FakeCtx:
    def __init__(self):
        self.parked = None; self.args = types.SimpleNamespace(log=""); self.lines = []
    def park(self, why, code):
        self.parked = (code, why)

def drain(crew):
    items = []
    while True:
        try:
            items.append(crew.q.get_nowait()[0])
        except queue.Empty:
            return items

today = dt.date(2026, 9, 3)
args = types.SimpleNamespace(edge=(today - dt.timedelta(days=45)).isoformat(), every=10, heal_every=900, heal_days=30, pace=0.0)
S.lane._log = lambda ctx, msg: ctx.lines.append(msg)
role = S.Synchronization(HERE, args)
role.today = lambda: today
crew, ctx = FakeCrew(), FakeCtx()

print("=== the first feed: control, catch-up from the edge, the heal window, today")
role.feed(crew, ctx)
items = drain(crew)
kinds = [k[0] for k in items]
check("the control is queued first", kinds[0] == "control" and items[0][1:] == richmond.CONTROL[:2], items[:2])
catch = [k for k in items if k[0] == "catch-up"]
check("catch-up covers edge+1 .. the day before the heal window", catch and catch[0][1] == (today - dt.timedelta(days=44)).isoformat()
      and catch[-1][2] == (today - dt.timedelta(days=30)).isoformat(), catch)
heal = [k for k in items if k[0] == "heal"]
check("the heal window is the trailing 30 days inclusive, in one window", len(heal) == 1 and heal[0][1] == (today - dt.timedelta(days=29)).isoformat() and heal[0][2] == today.isoformat(), heal)
check("today's window is queued", ("day", today.isoformat(), today.isoformat()) in items)
check("the keys are JSON-friendly (the crew logs a failed item)", all(json.dumps(k) for k in items))
role.feed(crew, ctx)
check("nothing re-queued while everything is in flight", drain(crew) == [])

print("=== landing: the control answers rows; a day window lands ids once; the edge moves")
rows = lambda ids: [{"recorded": "9/3/2026", "type": "DEED", "internal_id": str(i), "instrument": "1"} for i in ids]
crew.results = [{"doc_id": ("control",) + richmond.CONTROL[:2], "value": ("control", rows([1, 2]))},
                {"doc_id": ("day", today.isoformat(), today.isoformat()), "value": ("day", rows([990000001, 990000002]))}]
role.land(crew, ctx)
check("the edge has not moved while the catch-up and heal windows are still out (it never jumps an open window)", role.edge == today - dt.timedelta(days=45))
crew.results = [{"doc_id": k, "value": (k[0], [])} for k in list(role.inflight) if k[0] in ("catch-up", "heal")]   # they answer, empty
role.land(crew, ctx)
check("two ids inserted as RC_ rows, counted", crew.cloud.calls == [["RC_990000001", "RC_990000002"]] and role.inserted == 2 and role.day_rows == 2, crew.cloud.calls)
check("the edge moved to today after the rows were in", role.edge == today and json.loads((HERE / "synchronization.edge.json").read_text())["edge"] == today.isoformat())
check("the control is no longer pending", not role.control_pending)
crew.results = [{"doc_id": ("day", today.isoformat(), today.isoformat()), "value": ("day", rows([990000001, 990000002, 990000003]))}]
role.land(crew, ctx)
check("the next probe inserts only the new id", crew.cloud.calls[-1] == ["RC_990000003"] and role.inserted == 3, crew.cloud.calls)
crew.results = [{"doc_id": ("day", today.isoformat(), today.isoformat()), "value": ("day", rows([990000001, 990000002, 990000003]))}]
role.land(crew, ctx)
check("no insert when nothing is new", len(crew.cloud.calls) == 2)

print("=== the cadence: the day window every --every, the heal every --heal-every with a control before it")
role.next_day = 0
role.feed(crew, ctx)
items = drain(crew)
check("the day window is queued again when due, nothing else", items == [("day", today.isoformat(), today.isoformat())], items)
for k in [k for k in role.inflight if k[0] in ("heal", "catch-up")]:      # the first heal's windows answered meanwhile
    role.inflight.pop(k)
role.next_heal = 0
role.feed(crew, ctx)
items = drain(crew)
check("a due heal queues the control first, then the trailing window", items[0][0] == "control" and any(k[0] == "heal" for k in items), items)

print("=== a window failing three asks becomes a hole; the control failing three asks is re-asked before the next heal")
key = ("heal", (today - dt.timedelta(days=30)).isoformat(), today.isoformat())
for i in range(3):
    crew.failed = [(key, "SSLError (simulated)")]
    role.land(crew, ctx)
holes = [json.loads(l) for l in (HERE / "synchronization.holes.jsonl").read_text().splitlines()]
check("the hole is recorded after the third failure, the window re-asked twice before", role.holes == 1 and holes[0]["window"] == [key[1], key[2]] and drain(crew) == [key, key], holes)
ckey = ("control",) + richmond.CONTROL[:2]
for i in range(3):
    crew.failed = [(ckey, "timeout (simulated)")]
    role.land(crew, ctx)
check("a control that fails three asks is a hole and no longer pending", not role.control_pending and role.holes == 2)
ckey2 = ("catch-up", "2026-07-01", "2026-07-30")
for i in range(3):
    crew.failed = [(ckey2, "timeout (simulated)")]
    role.land(crew, ctx)
role.next_heal = 0
role.control_pending = False
for k in [k for k in role.inflight if k[0] in ("heal",)]:
    role.inflight.pop(k)
role.feed(crew, ctx)
items = drain(crew)
check("a catch-up hole is asked again at the next heal (outside the heal's own span)", ckey2 in items and ckey2 in role.reask, items)
crew.results = [{"doc_id": ckey2, "value": ("catch-up", rows([990000050]))}]
role.land(crew, ctx)
check("once it answers it leaves the re-ask list", ckey2 not in role.reask and "RC_990000050" in crew.cloud.rows)

print("=== a broken control parks the lane (code 3)")
crew.results = [{"doc_id": ckey, "value": ("control", [])}]
role.land(crew, ctx)
check("the control parsing no rows parks with PROBE BROKEN, code 3", ctx.parked and ctx.parked[0] == 3 and "PROBE BROKEN" in ctx.parked[1], ctx.parked)

print("=== the edge file: fail-closed start, mismatch refused")
for f in HERE.glob("synchronization.edge.*"):
    f.unlink()
try:
    S.Synchronization(HERE, types.SimpleNamespace(edge="", every=10, heal_every=900, heal_days=30, pace=0.0)); check("a first start without --edge is refused", False)
except SystemExit as e:
    check("a first start without --edge is refused", "needs --edge" in str(e))
S.Synchronization(HERE, types.SimpleNamespace(edge="2026-08-25", every=10, heal_every=900, heal_days=30, pace=0.0))._save_edge()
try:
    S.Synchronization(HERE, types.SimpleNamespace(edge="2026-08-01", every=10, heal_every=900, heal_days=30, pace=0.0)); check("an --edge that disagrees with the file is refused", False)
except SystemExit as e:
    check("an --edge that disagrees with the file is refused", "remove the file" in str(e))
check("_iso", S._iso("8/19/2026") == "2026-08-19" and S._iso("garbage") == "9999-12-31")

print("\nRICHMOND SYNC OFFLINE:", "ALL OK" if not fails else "FAILURES: %s" % fails)
sys.exit(1 if fails else 0)
