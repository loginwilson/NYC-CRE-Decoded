"""SIMULATION of the two stop policies against the live cloud with throwaway rows - NO ACRIS request.

  A. hang-up: after 3 landings every fetch raises Transport.  The 5-quiet-ticks detector must hang up,
     wait --redial-wait, re-enter (incident 1); the fetches keep failing, so incident 2 follows; with
     --tries 2 the lane must PARK with exit code 3, write the parked file, and leave the word in the
     heartbeat.  Ticks shortened to 2 s, redial wait 3 s.
  B. refusal: the first fetch raises Refused.  The lane must park at once with exit code 2, no redial,
     the parked file written, the word 'REFUSED at ...' in the heartbeat.
Every number here is about SIM rows.
"""
import json, os, pathlib, sys, time, types
PHASE = pathlib.Path(__file__).resolve().parents[1]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
import psycopg2
import cloud, lane, acris

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)


def clean():
    for f in HERE.glob("documentation.*"):
        f.unlink()


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="test_lane_policies")
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


def seed():
    _real = q("select count(*) from reproduction.acris where doc_id not like 'SIM-%'")[0][0]
    if _real:
        raise SystemExit("reproduction.acris holds %s real rows - this simulation claims through claim(), which hands out the first"
                         " empties of the WHOLE table, so it would take real documents; it runs on an empty table only (it did so"
                         " once on the populated table, 2026-09-05 19:2x: 28 real rows claimed for a moment, released, nothing landed)"
                         % "{:,}".format(_real))
    q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
    q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
    q("insert into reproduction.acris (doc_id, registry) select unnest(%s::text[]), %s::jsonb", (IDS, json.dumps(REG)), fetch=False)


def args(**kw):
    a = types.SimpleNamespace(lane="documentation", host="SIM-HOST", width=4, stagger=0.05, claim=10, ttl="5 seconds",
                              pending_age="1 day", redial_wait=3, tries=2, entry_gap=1, limit=0, log="", unpark=False, tick=2)
    for k, v in kw.items():
        setattr(a, k, v)
    return a


class HangUp:
    source, lane = "acris", "documentation"
    ua = "sim/0 (never sent)"
    n = 0

    def fetch(self, crew, doc_id, registry):
        with crew.lock:
            crew.stats["reqs"] += 1
            self.n += 1
            k = self.n
        time.sleep(0.3)
        if k <= 3:
            return acris.canonical_path(doc_id, registry)
        raise lane.Transport("SSLError: UNEXPECTED_EOF_WHILE_READING (simulated hang-up)")


class Notice:
    source, lane = "acris", "documentation"
    ua = "sim/0 (never sent)"

    def fetch(self, crew, doc_id, registry):
        with crew.lock:
            crew.stats["reqs"] += 1
        raise lane.Refused("ACRIS served its Bandwidth Notice at %s (simulated)" % doc_id)


print("=== A. hang-up -> redial -> redial -> park ===")
clean(); seed()
t0 = time.time()
code = lane.run([(HangUp(), 4)], args(), HERE)
print("exit code", code, "(expect 3) after %.0fs" % (time.time() - t0))
print("parked file:", (HERE / "documentation.parked").read_text().strip()[:90] if (HERE / "documentation.parked").exists() else "MISSING")
print("heartbeat:", q("select width, last_event from reproduction.acris_heartbeats where host = 'SIM-HOST'"))
print("landed before the hang-up:", q("select count(*) from reproduction.acris where doc_id like 'SIM-%' and document is not null")[0][0], "(expect 3)")
print("lock removed:", not (HERE / "documentation.lock").exists())

print("=== B. refusal -> park at once ===")
clean(); seed()
t0 = time.time()
code = lane.run([(Notice(), 4)], args(), HERE)
print("exit code", code, "(expect 2) after %.0fs" % (time.time() - t0))
print("parked file:", (HERE / "documentation.parked").read_text().strip()[:90] if (HERE / "documentation.parked").exists() else "MISSING")
print("heartbeat:", q("select width, last_event from reproduction.acris_heartbeats where host = 'SIM-HOST'"))
print("requests made before the park (must be about one per worker, never a retry storm):", "see reqs in the lines above")
try:
    lane.run([(Notice(), 4)], args(), HERE)
    print("FAIL: restarted into the park")
except SystemExit as e:
    print("restart refused while parked:", str(e).splitlines()[0][:60])

print("=== cleanup ===")
q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
print("reconcile:", q("select * from reproduction.reconcile('acris')"))
clean()
print("POLICY SIMULATION DONE - no ACRIS request was made")
