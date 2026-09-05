"""LIVE-CLOUD simulation of the richmond registration lane, no county request: throwaway RC_9900000xx rows; the table's
todo answers the empty and the DUE pendings only; the lane's own land drives reproduction.land through the outbox and
moves the lane counter by the newly filled cells (a pending into an empty cell counts once, the dict over it counts
nothing); a value the cell rule rejects stays in the outbox and the lane says so; cleanup + reconcile restore the counters."""
import datetime as dt, importlib.util, json, pathlib, queue, sys, threading, types
PHASE = pathlib.Path(__file__).resolve().parents[3]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))
import cloud, lane, richmond
spec = importlib.util.spec_from_file_location("richmond_registration", str(PHASE / "Richmond" / "workflow" / "registration" / "Richmond Registration.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("registration.*"):
    f.unlink()

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)

IDS = ["RC_9900000%02d" % i for i in range(41, 46)]
C = cloud.Cloud("richmond", "registration", "SIM-HOST", app="richmond registration SIM")

def counters():
    lanes = {r[0]: (r[1], r[2]) for r in C._run("select lane, landed, needed from reproduction.richmond_update_lanes order by lane", (), True)}
    phase = C._run("select landed, needed from reproduction.richmond_update", (), True)[0]
    return lanes, tuple(phase)

def cleanup():
    C._run("delete from reproduction.richmond where doc_id = any(%s)", (IDS,), False)
    C._run("delete from reproduction.richmond_claims where doc_id = any(%s)", (IDS,), False)

class FakeCrew:
    def __init__(self):
        self.q = queue.Queue(); self.results = []; self.failed = []; self.lock = threading.Lock(); self.cloud = C; self.width = 4
        self.stats = {"reqs": 0}; self.outbox = cloud.Outbox(HERE / "registration.outbox.jsonl")

class FakeCtx:
    def __init__(self):
        self.parked = None; self.args = types.SimpleNamespace(log=""); self.lines = []
    def park(self, why, code):
        self.parked = (code, why)

R.lane._log = lambda ctx, msg: ctx.lines.append(msg) or print("   log:", msg)
today = dt.date.today()
role = R.Registration(HERE, types.SimpleNamespace(edge=(today - dt.timedelta(days=3)).isoformat(), days=30, every=900, pace=0.0, pending_age="1 hour"))
crew, ctx = FakeCrew(), FakeCtx()
a, b = (today - dt.timedelta(days=29)).isoformat(), today.isoformat()
role.windows[(a, b)] = {"pages": 1, "answered": {1}, "details": 0}

def detail(instrument):
    return {"instrument": instrument, "book": "", "page": "", "doc_type": "DEED", "recorded": "8/19/2026", "amount": "$500,000.00", "status": "Recorded",
            "image_state": "present", "parcels": [{"bbl": "5012340056"}], "parties": [{"name": "SMITH, JOHN", "role": "GRANTOR", "column": "name", "person": "SMITH, JOHN", "company": ""}],
            "at": "sim", "listing": {"recorded": "8/19/2026", "type": "DEED", "instrument": instrument}}

try:
    cleanup()
    before_lanes, before_phase = counters()
    print("=== five throwaway rows, empty")
    n = C.insert_ids(IDS)
    check("five rows inserted (needed moved by the same transaction)", n == 5 and counters()[0]["registration"][1] == before_lanes["registration"][1] + 5)
    check("todo: every empty registry needs work", C.todo(IDS, "1 hour") == set(IDS))
    check("todo of nothing is nothing, no round trip", C.todo([], "1 hour") == set())

    print("=== the lane lands a dict and a pending through the outbox")
    role.windows[(a, b)]["details"] = 1
    crew.results = [{"doc_id": ("details", a, b, 1, (IDS[0], IDS[1])), "value": ("details", [(IDS[0], detail("1008999")), (IDS[1], "pending")])}]
    role.land(crew, ctx)
    regs = C.registries(IDS)
    check("the dict is in the cell, the pending is the word, the rest empty", isinstance(regs[IDS[0]], dict) and regs[IDS[0]]["instrument"] == "1008999"
          and regs[IDS[1]] == "pending" and all(regs[i] is None for i in IDS[2:]), regs)
    check("the outbox is empty after the landing", crew.outbox.count() == 0)
    lanes, phase = counters()
    check("the lane's landed moved by the two newly filled cells; the phase by none (documents empty)",
          lanes["registration"][0] == before_lanes["registration"][0] + 2 and phase[0] == before_phase[0], (lanes["registration"], before_lanes["registration"], phase, before_phase))
    check("todo at 1 hour: the empties only - the fresh pending is not due", C.todo(IDS, "1 hour") == set(IDS[2:]))
    check("todo at 0 seconds: the pending is due again", C.todo(IDS, "0 seconds") == set(IDS[1:]))
    check("the edge moved to today once the window's details were in", role.edge == today)

    print("=== the pending matures: the dict lands over it, the counter does not move again")
    role.windows[(a, b)] = {"pages": 1, "answered": {1}, "details": 1}
    crew.results = [{"doc_id": ("details", a, b, 1, (IDS[1],)), "value": ("details", [(IDS[1], detail("1009000"))])}]
    role.land(crew, ctx)
    regs = C.registries(IDS)
    check("the matured detail replaced the pending", isinstance(regs[IDS[1]], dict) and regs[IDS[1]]["instrument"] == "1009000")
    check("the lane's landed is still +2", counters()[0]["registration"][0] == before_lanes["registration"][0] + 2)
    check("todo no longer hands it back", C.todo(IDS, "0 seconds") == set(IDS[2:]))

    print("=== a value the cell rule rejects: the whole batch stays in the outbox and the lane says so")
    role.windows[(a, b)] = {"pages": 1, "answered": {1}, "details": 1}
    crew.results = [{"doc_id": ("details", a, b, 1, (IDS[2], IDS[3])), "value": ("details", [(IDS[2], detail("1009001")), (IDS[3], "garbage")])}]
    role.land(crew, ctx)
    regs = C.registries(IDS)
    check("nothing half-landed: both cells still empty", regs[IDS[2]] is None and regs[IDS[3]] is None, regs)
    check("both rows wait in the outbox and the log says the cloud did not take them", crew.outbox.count() == 2 and any("did not take 2" in l for l in ctx.lines), ctx.lines[-2:])
    check("the lane counter did not move", counters()[0]["registration"][0] == before_lanes["registration"][0] + 2)
finally:
    print("=== cleanup + reconcile")
    cleanup()
    (HERE / "registration.outbox.jsonl").unlink(missing_ok=True)
    rows = C._run("select * from reproduction.reconcile('richmond')", (), True)
    print("   reconcile:", rows)
    lanes, phase = counters()
    check("the counters are back where they started", lanes == before_lanes and phase == before_phase, (lanes, before_lanes, phase, before_phase))
    check("no throwaway row left", C.count("RC_99000004", "RC_99000005") == 0)
    C.close()

print("\nRICHMOND REG SIM:", "ALL OK" if not fails else "FAILURES: %s" % fails)
sys.exit(1 if fails else 0)
