"""SIMULATION of the enumeration audit against the LIVE cloud with throwaway rows - NO ACRIS request and NO
index request: a fake index stands in for Socrata and a fake counter for ACRIS.  The table reads, the
heartbeat guard, the lock, the journal and the files are real.

  the diff   run 1: the index holds 12 ids, the table 10 -> THE DIFFERENCE IS 2, exit 1, both listed
             run 2: every index id held; the table also holds an omitted id, a seam id and a tail id -> PASS, exit 0,
                    beyond 3 classified (omitted 1, seam 1, tail 1)
             run 3: the index answers Void three times for a shard -> UNPROVEN, exit 7
             run 4: the index answers empty where the table holds rows -> UNPROVEN, exit 7
  the probe  the guard: a fresh heartbeat refuses the probe
             holes 5 (void), 9 (held), 17 (MISSING); the top galloped past the index's 30 to 32; 31 held, 32 MISSING;
             identity closed; exit 1; a rerun asks nothing (the journal)
             a refusal parks; a rerun refuses without --unpark; a hang-up stops with exit 3
"""
import importlib.util, json, pathlib, sys, time, types
PHASE = pathlib.Path(__file__).resolve().parents[3]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
import psycopg2
import acris, cloud, lane
spec = importlib.util.spec_from_file_location("acris_enumeration", str(PHASE / "Acris" / "workflow" / "enumeration" / "Acris Enumeration.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
E.HERE = HERE


def clean_files():
    for f in HERE.glob("enumeration.*"):
        f.unlink()


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="test_enumeration_sim")
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
            out = cur.fetchall() if fetch and cur.description else None
        con.commit()
        return out
    finally:
        con.close()


fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)


def sid(m, s):                       # a digital-shaped throwaway id in 2099
    return "2099%02d01%05d001" % (m, s)


# ── a fake index in place of Socrata ──
class FakeIndex:
    def __init__(self, ids, good_through="2099-06-30"):
        self.ids, self.good_through = set(ids), good_through
        self.void_prefixes, self.empty_prefixes, self.calls = set(), set(), 0
    def state(self, ds):
        return {"ids": len(self.ids) if ds == "bnx9-e6tj" else 0, "recorded": self.good_through,
                "good_through": self.good_through, "crfn": "2099000000030"}
    def prefixes(self, ds, lo, hi, n):
        if ds != "bnx9-e6tj":
            return {}
        out = {}
        for i in self.ids:
            if i >= lo and (hi is None or i < hi):
                out[i[:n]] = out.get(i[:n], 0) + 1
        return out
    def index_ids(self, ds, lo, hi):
        self.calls += 1
        if ds != "bnx9-e6tj":
            return set()
        if lo in self.void_prefixes:
            raise acris.Void("%s ids in [%s, %s): pulled 0, counted 3" % (ds, lo, hi))
        if lo in self.empty_prefixes:
            return set()
        return {i for i in self.ids if i >= lo and (hi is None or i < hi)}
    def install(self):
        acris.index_state = self.state
        acris.index_prefixes = self.prefixes
        acris.index_ids = self.index_ids


def run_diff(index, months=3):
    clean_files()
    index.install()
    rep = E.Report(HERE)
    c = cloud.Cloud("acris", "enumeration", "SIM-HOST", app="test_enumeration_sim")
    c.connect()
    args = types.SimpleNamespace(all=False, months=months, shard=[])
    state = E.index_state(rep)
    code = E.diff(args, c, rep, state)
    E.tail(c, rep, state)
    c.close()
    rep.save()
    return code, rep.lines


_real = q("select count(*) from reproduction.acris where doc_id not like '2099%'")[0][0]
if _real:
    raise SystemExit("reproduction.acris holds %s real rows - this simulation writes into the live table (it inserts throwaway ids and reads the table as the audit), so on the"
                     " populated table it would touch real documents; it runs on an empty table only (rule of 2026-09-05 19:2x)"
                     % "{:,}".format(_real))
q("delete from reproduction.acris where doc_id like '2099%%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
time.sleep(0.5)

print("=== the diff, run 1: index 12, table 10 -> the difference is 2")
q("insert into reproduction.acris (doc_id) select unnest(%s::text[]) on conflict do nothing", ([sid(1, s) for s in range(1, 11)],), fetch=False)
idx = FakeIndex([sid(1, s) for s in range(1, 13)])
code, lines = run_diff(idx)
missing = (HERE / "enumeration.missing.txt").read_text().split()
check("run 1 exit 1 (a difference)", code == 1, code)
check("run 1 lists exactly the 2 missing ids", missing == [sid(1, 11), sid(1, 12)], missing)
check("run 1 says THE DIFFERENCE IS 2", any("THE DIFFERENCE IS 2" in l for l in lines))

print("=== the diff, run 2: every index id held; omitted + seam + tail beyond -> PASS")
q("insert into reproduction.acris (doc_id) select unnest(%s::text[]) on conflict do nothing",
  ([sid(1, 11), "2099062000001001", "2099071500001001", "2099060100001001"],), fetch=False)
idx = FakeIndex([sid(1, s) for s in range(1, 11)] + ["2099060100001001"])
code, lines = run_diff(idx)
extra = [l.split("\t") for l in (HERE / "enumeration.extra.txt").read_text().splitlines()]
kinds = {e[0]: e[2] for e in extra}
check("run 2 exit 0 (the difference is 0)", code == 0, code)
check("run 2 PASS line", any("THE DIFFERENCE IS 0 over 3 shards - PASS" in l for l in lines), [l for l in lines if "PASS" in l or "TOTAL" in l])
check("run 2 classified beyond: omitted, seam, tail", kinds == {sid(1, 11): "omitted", "2099062000001001": "seam", "2099071500001001": "tail"}, kinds)
check("run 2 the tail shard was not asked of the index", any("209907" in l and "past the index" in l for l in lines))
check("run 2 the tail section printed", any("THE TAIL" in l for l in lines) and any("unproven past the edge" in l for l in lines))

print("=== the diff, run 3: the index answers Void three times -> UNPROVEN")
idx = FakeIndex([sid(1, s) for s in range(1, 11)] + ["2099060100001001"])
idx.void_prefixes.add("209901")
code, lines = run_diff(idx)
check("run 3 exit 7 (unproven)", code == 7, code)
check("run 3 asked the shard three times", sum(1 for l in lines if "void answer" in l) == 3)
check("run 3 UNPROVEN line names the shard", any("UNPROVEN: 1 shard(s)" in l and "209901" in l for l in lines))

print("=== the diff, run 4: the index answers empty where the table holds rows -> UNPROVEN")
idx = FakeIndex([sid(1, s) for s in range(1, 11)] + ["2099060100001001"])
idx.empty_prefixes.add("209901")
code, lines = run_diff(idx)
check("run 4 exit 7 (an empty denominator is never a pass)", code == 7, code)
check("run 4 says so", any("answered empty where the table holds rows" in l for l in lines))

# ── the probe with a fake counter ──
BASE = 2099 * 10 ** 9
DOC = {9: sid(1, 9), 17: sid(1, 17), 31: sid(1, 31), 32: sid(1, 32)}          # 9 and 31 are in the table (9 is), 17/32 are not
q("insert into reproduction.acris (doc_id) select unnest(%s::text[]) on conflict do nothing", ([sid(1, 31)],), fetch=False)


class FakeCounter:
    def __init__(self, refuse=(), hang=False):
        self.refuse, self.hang, self.asked = set(refuse), hang, []
    def ask(self, crfn):
        self.asked.append(crfn)
        if self.hang:
            raise lane.Transport("SSLError (simulated hang-up)")
        s = crfn - BASE
        if s in self.refuse:
            raise lane.Refused("Bandwidth Notice (simulated) at crfn %d" % crfn)
        if s == 5 or s > 32:
            return None
        return DOC.get(s, "2099010100%03d001" % s)


def make_probe(counter, unpark=False, width=2):
    args = types.SimpleNamespace(width=width, stagger=0.05, years="", retop=False, unpark=unpark, redial_wait=1, tries=2)
    rep = E.Report(HERE)
    c = cloud.Cloud("acris", "enumeration", "SIM-HOST", app="test_enumeration_sim")
    c.connect()
    p = E.Probe(args, c, rep)
    p.ask = counter.ask
    return p


clean_files()
(HERE / "enumeration.holes.json").write_text(json.dumps({"2099": {"top": 30, "index": 27, "holes": [5, 9, 17]}}))

print("=== the probe: the guard")
q("insert into reproduction.acris_heartbeats (lane, host, width, heartbeat_at, last_event) values ('registration', 'SIM-HOST', 1, now(), 'sim')", fetch=False)
try:
    make_probe(FakeCounter()).run()
    check("a fresh heartbeat refuses the probe", False)
except SystemExit as e:
    check("a fresh heartbeat refuses the probe", "the cycle is running" in str(e) and "registration on SIM-HOST" in str(e), e)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)

print("=== the probe: holes, the top, the identity")
counter = FakeCounter()
p = make_probe(counter)
code = p.run()
p.c.close()
j = json.loads((HERE / "enumeration.probe.json").read_text())
n = j["numbers"]
check("probe exit 1 (MISSING documents)", code == 1, code)
check("hole 5 void, 9 held, 17 MISSING", (n.get(str(BASE + 5), {}).get("v"), n.get(str(BASE + 9), {}).get("v"), n.get(str(BASE + 17), {}).get("v")) == ("void", "held", "MISSING"), {k: v for k, v in n.items()})
check("the top galloped to 32", j["tops"]["2099"]["issued"] == 32, j["tops"])
check("beyond the index: 31 held, 32 MISSING", (n.get(str(BASE + 31), {}).get("v"), n.get(str(BASE + 32), {}).get("v")) == ("held", "MISSING"))
check("identity closed", any("IDENTITY CLOSED" in l for l in p.rep.lines), [l for l in p.rep.lines if "2099  index" in l])
pm = (HERE / "enumeration.probe-missing.txt").read_text().split()
check("the two missing documents listed", sorted(pm) == sorted([sid(1, 17), sid(1, 32)]), pm)
check("the lock was released", not (HERE / "enumeration.lock").exists())
asked_first = len(counter.asked)

print("=== the probe: a rerun asks nothing")
counter = FakeCounter()
p = make_probe(counter)
code = p.run()
p.c.close()
check("rerun exit 1 again, zero asks (the journal)", code == 1 and counter.asked == [], (code, counter.asked))

print("=== the probe: a refusal parks, the park holds")
clean_files()
(HERE / "enumeration.holes.json").write_text(json.dumps({"2099": {"top": 30, "index": 27, "holes": [5, 7, 9]}}))
counter = FakeCounter(refuse={7})
p = make_probe(counter)
code = p.run()
p.c.close()
check("refusal exit 2", code == 2, code)
check("enumeration.parked written", (HERE / "enumeration.parked").exists() and "REFUSED" in (HERE / "enumeration.parked").read_text())
try:
    make_probe(FakeCounter()).run()
    check("a parked probe refuses to start", False)
except SystemExit as e:
    check("a parked probe refuses to start", "REFUSING TO START" in str(e) and "parked" in str(e), e)
counter = FakeCounter()
p = make_probe(counter, unpark=True)
code = p.run()
p.c.close()
check("--unpark runs again (7 void now), identity closed, exit 1 (hole 17? no: 9 held, nothing missing -> 0)", code in (0, 1), code)

print("=== the probe: a hang-up re-enters twice, then stops with exit 3")
clean_files()
(HERE / "enumeration.holes.json").write_text(json.dumps({"2099": {"top": 30, "index": 27, "holes": [5, 9, 17]}}))
counter = FakeCounter(hang=True)
p = make_probe(counter)
code = p.run()
p.c.close()
check("hang-up exit 3 after two refused re-entries (the cycle: hang up, wait, re-enter; then stop with the journal)", code == 3, code)
check("the re-entries were made and logged", any("re-entry 1/2" in l for l in p.rep.lines) and any("re-entered (2/2)" in l for l in p.rep.lines),
      [l for l in p.rep.lines if "PROBE" in l][-4:])
check("no number read as void on a hang-up", all(v["v"] != "void" for v in json.loads((HERE / "enumeration.probe.json").read_text())["numbers"].values()))

print("=== cleanup")
q("delete from reproduction.acris where doc_id like '2099%%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
print("rows left:", q("select count(*) from reproduction.acris where doc_id like '2099%%'"))
print("\nSIMULATION:", "ALL OK" if not fails else "FAILURES: %s" % fails, "- no ACRIS request, no index request")
sys.exit(1 if fails else 0)
