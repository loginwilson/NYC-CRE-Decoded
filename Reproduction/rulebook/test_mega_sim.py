"""SIMULATION of a MEGA LANE (two crews in one process) against the live cloud with throwaway rows - NO ACRIS request.

  crew A  documentation over SIM rows: lands 3, then every fetch raises Transport (the session closed)
  crew B  a walker role with its own feed and land (never touches the workflow table): keeps landing all along

  expect: B enters only after A's ramp completed plus --entry-gap (one ramp at a time); A hangs up on the whole
          width with nothing landed for 10 s, drops its batch, waits --redial-wait (20 s) - and B keeps landing
          THROUGHOUT that wait (nothing blocks); A re-enters once on a fresh batch after the wait; B is never
          hung up; `stop` ends the run with exit 0.
"""
import json, pathlib, sys, threading, time, types
PHASE = pathlib.Path(__file__).resolve().parents[1]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
import psycopg2
import cloud, lane, acris

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in list(HERE.glob("documentation.*")) + list(HERE.glob("synchronization.*")):
    f.unlink()


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="test_mega_sim")
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
            out = cur.fetchall() if fetch and cur.description else None
        con.commit()
        return out
    finally:
        con.close()


IDS = ["SIM-%04d" % i for i in range(1, 41)]
REG = {"recorded": "8/21/2004 7:56:37 PM", "parcels": [{"bbl": "100450012"}]}
q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
q("insert into reproduction.acris (doc_id, registry) select unnest(%s::text[]), %s::jsonb", (IDS, json.dumps(REG)), fetch=False)

LINES = []                                   # (time, line) of everything the lane logs
_log0 = lane._log
def _log(ctx, msg):
    LINES.append((time.time(), msg))
    _log0(ctx, msg)
lane._log = _log


class A:
    """documentation: 3 landings, then the wire dies for good."""
    source, lane, ua = "acris", "documentation", "sim/0 (never sent)"
    noun, needs_registry = "pdfs", True
    n = 0

    def fetch(self, crew, doc_id, registry):
        with crew.lock:
            crew.stats["reqs"] += 1
            self.n += 1
            k = self.n
        time.sleep(0.3)
        if k <= 3:
            return acris.canonical_path(doc_id, registry)
        raise lane.Transport("SSLError: UNEXPECTED_EOF_WHILE_READING (simulated close)")


class B:
    """a walker: its own feed (fake numbers) and land (a count), never the workflow table; lands all along."""
    source, lane, ua = "acris", "synchronization", "sim/0 (never sent)"       # a real lane name: the cloud's heartbeat refuses an unknown lane
    noun, needs_registry = "numbers", False

    def __init__(self):
        self.next = 0
        self.landed = []                       # times of every landing

    def fetch(self, crew, n, _registry):
        with crew.lock:
            crew.stats["reqs"] += 1
        time.sleep(0.2)
        return ("live", "W%d" % n)

    def classify(self, value):
        return "filled"

    def feed(self, crew, ctx):
        while crew.q.qsize() < crew.width * 3:
            self.next += 1
            crew.q.put((self.next, None, 0))

    def land(self, crew, ctx):
        with crew.lock:
            rows, crew.results = crew.results, []
            crew.failed = []
        self.landed.extend([time.time()] * len(rows))

    def status(self):
        return "landed %d" % len(self.landed)


args = types.SimpleNamespace(lane="documentation", host="SIM-HOST", width=4, stagger=0.5, claim=10, ttl="5 seconds",
                             pending_age="1 day", redial_wait=20, tries=3, entry_gap=2, limit=0, log="", unpark=False,
                             tick=2, no_pool_check=True, also=[])
b = B()


def stop_later():
    time.sleep(75)
    (HERE / "documentation.control").write_text("stop\n", encoding="utf-8")


threading.Thread(target=stop_later, daemon=True).start()
t0 = time.time()
code = lane.run([(A(), 4), (b, 4)], args, HERE)
print("exit code", code, "after %.0fs" % (time.time() - t0))

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)

def at(pred):
    return [t for t, l in LINES if pred(l)]

a_in = at(lambda l: l.startswith("documentation: entered"))
b_in = at(lambda l: l.startswith("synchronization: entered"))
a_hang = at(lambda l: l.startswith("documentation: the session closed"))
a_drop = [l for _, l in LINES if l.startswith("documentation:") and "of the cut batch dropped" in l]
a_re = at(lambda l: l.startswith("documentation: re-entered"))
b_hang = at(lambda l: l.startswith("synchronization:") and "hanging up" in l)

check("exit 0 through the control file", code == 0, code)
check("both crews entered, A first", len(a_in) == 1 and len(b_in) == 1 and a_in[0] < b_in[0], (a_in, b_in))
check("B entered only after A's ramp (1.5 s) plus the entry gap (2 s): one ramp at a time", b_in and a_in and b_in[0] - a_in[0] >= 3.4, b_in[0] - a_in[0] if b_in and a_in else None)
check("A hung up on the whole width with nothing landed for 10 s", len(a_hang) >= 1, [l for _, l in LINES if "documentation" in l][:6])
check("A dropped its cut batch (the rebatch)", len(a_drop) >= 1 and "re-entry 1/3" in a_drop[0], a_drop[:1])
check("A re-entered once, after the 20 s wait", len(a_re) >= 1 and a_re[0] - a_hang[0] >= 20, (a_re[:1], a_hang[:1]))
during = [t for t in b.landed if a_hang and a_re and a_hang[0] <= t <= a_re[0]]
check("B kept landing THROUGHOUT A's wait (nothing blocks): %d landings between A's hang-up and re-entry" % len(during), len(during) >= 40, len(during))
check("B was never hung up", not b_hang, b_hang)
check("a PROGRESS line showed A waiting (re-entry in N s)", any("documentation" in l and "re-entry in" in l for _, l in LINES))
check("landed before the hang-up: 3", q("select count(*) from reproduction.acris where doc_id like 'SIM-%' and document is not null")[0][0] == 3)

q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
print("reconcile:", q("select * from reproduction.reconcile('acris')"))
for f in list(HERE.glob("documentation.*")) + list(HERE.glob("synchronization.*")):
    f.unlink()
print("\nMEGA LANE SIMULATION:", "ALL OK" if not fails else "FAILURES: %s" % fails, "- no ACRIS request was made")
sys.exit(1 if fails else 0)
