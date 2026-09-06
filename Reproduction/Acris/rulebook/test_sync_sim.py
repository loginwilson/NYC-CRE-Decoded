"""SIMULATION of the synchronization lane against the LIVE cloud with throwaway numbers - NO ACRIS request.
A fake counter stands in for ACRIS:

  edge 9000000000000; live documents at +1..+30 except personal-property blanks at +3,+4,+11..+13 and a
  number (+17) that fails three asks (a hole); +31.. blank (unissued).  Later, at second 8, a filing
  appears at +33 (so +31,+32 are personal-property blanks), then nothing more.

  expect: bites walked while behind; rows SIM-... inserted for every live number; the edge at +30, then
          +33 after the second filing; the hole recorded; needed/landed counters up by the rows inserted;
          the level watch cadence with the wider look after 5 empty watches; no request to ACRIS.
"""
import json, os, pathlib, sys, time, types
PHASE = pathlib.Path(__file__).resolve().parents[2]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "workflow" / "synchronization"))
import psycopg2
import cloud, lane
import importlib.util
spec = importlib.util.spec_from_file_location("acris_synchronization", str(PHASE / "Acris" / "workflow" / "synchronization" / "Acris Synchronization.py"))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("synchronization.*"):
    f.unlink()


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="test_sync_sim")
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
            out = cur.fetchall() if fetch and cur.description else None
        con.commit()
        return out
    finally:
        con.close()


EDGE = 9000000000000
BLANKS = {3, 4, 11, 12, 13, 31, 32}
HOLE = 17
_real = q("select count(*) from reproduction.acris where doc_id not like 'SIM-%'")[0][0]
if _real:
    raise SystemExit("reproduction.acris holds %s real rows - this simulation writes into the live table (the lane inserts its throwaway ids and moves the counters), so on the"
                     " populated table it would touch real documents; it runs on an empty table only (rule of 2026-09-05 19:2x)"
                     % "{:,}".format(_real))
q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
before = q("select (select needed from reproduction.acris_update), (select landed from reproduction.acris_update_lanes where lane='synchronization'), (select needed from reproduction.acris_update_lanes where lane='documentation')")[0]
print("counters before (phase needed, sync landed, documentation needed):", before)
T0 = time.time()


class FakeCounter(sync.Synchronization):
    ua = "sim/0 (never sent)"

    def fetch(self, crew, crfn, _registry):
        with crew.lock:
            crew.stats["reqs"] += 1
        time.sleep(0.05)
        k = crfn - EDGE
        if k == HOLE:
            raise lane.Transport("SSLError (simulated, every time)")
        if k <= 30 and k not in BLANKS:
            return ("live", "SIM-%013d" % k)
        if k == 33 and time.time() - T0 > 8:
            return ("live", "SIM-%013d" % k)
        return ("blank", None)


class Args(types.SimpleNamespace):
    pass


args = Args(lane="synchronization", host="SIM-HOST", width=4, stagger=0.05, claim=0, ttl="20 minutes", pending_age="1 hour",
            redial_wait=5, tries=3, entry_gap=1, limit=0, log="", unpark=False, tick=2,
            edge=EDGE, every=2, watch=8, bite=20, widen=16, widen_after=3, also=[])
role = FakeCounter(HERE, args)


def stop_later():
    time.sleep(30)
    (HERE / "synchronization.control").write_text("stop\n", encoding="utf-8")


import threading
threading.Thread(target=stop_later, daemon=True).start()
code = lane.run([(role, 4)], args, HERE)
print("exit code", code, "after %.0fs" % (time.time() - T0))

print("--- what landed ---")
rows = q("select doc_id from reproduction.acris where doc_id like 'SIM-%' order by doc_id")
got = sorted(int(r[0][4:]) for r in rows)
want = sorted(k for k in range(1, 34) if k not in BLANKS and k != HOLE)
print("   rows inserted:", got)
print("   expected     :", want, "->", "OK" if got == want else "MISMATCH")
state = json.loads((HERE / "synchronization.edge.json").read_text())
print("   edge file:", state["edge"], "(expect %d = +33)" % (EDGE + 33), "->", "OK" if state["edge"] == EDGE + 33 else "MISMATCH")
holes = [json.loads(l) for l in (HERE / "synchronization.holes.jsonl").read_text().splitlines()] if (HERE / "synchronization.holes.jsonl").exists() else []
print("   holes:", [h["crfn"] - EDGE for h in holes], "(expect [17])")
after = q("select (select needed from reproduction.acris_update), (select landed from reproduction.acris_update_lanes where lane='synchronization'), (select needed from reproduction.acris_update_lanes where lane='documentation')")[0]
print("   counters moved by:", tuple(a - b for a, b in zip(after, before)), "(expect %d each)" % len(want))
print("   heartbeat:", q("select width, last_event from reproduction.acris_heartbeats where host = 'SIM-HOST'"))
print("--- cleanup ---")
q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
print("reconcile after cleanup:", q("select * from reproduction.reconcile('acris')"))
print("SYNC SIMULATION DONE - no ACRIS request was made")
