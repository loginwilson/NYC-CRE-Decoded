"""SIMULATION - proves the lane loop against the LIVE cloud with throwaway rows and NO ACRIS request.
The role below never touches the network: it answers from the id.  Every number printed here is
about TEST rows, not about the reproduction.

  rows:  SIM-0001..SIM-0012 with a registry; SIM-0013 with registry 'pending' (cannot be placed)
  role:  ...01/02/03 -> a path      ...04 -> absent     ...05 -> pending
         ...06 -> Retry (short)     ...07 -> Transport (a failed document stays claimed for a LATER
         pass, so it lands nothing in this run)      ...08-12 -> paths     ...13 -> no registry
  run:   width 4, claim 6, limit 10 (the ten that can succeed), 3 s per document, the tick shortened to
         5 s, a control file lowering the width to 2 after 4 s
  check: cells in the cloud, counters moved, claims released, heartbeat row, outbox empty, fails file
"""
import json, os, pathlib, sys, threading, time, types
PHASE = pathlib.Path(__file__).resolve().parents[1]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
import psycopg2
import cloud, lane, storage, acris

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("documentation.*"):
    f.unlink()


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="test_lane_sim")
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
            out = cur.fetchall() if fetch and cur.description else None
        con.commit()
        return out
    finally:
        con.close()


IDS = ["SIM-%04d" % i for i in range(1, 13)]
REG = {"recorded": "8/21/2004 7:56:37 PM", "type": "DEED", "parcels": [{"bbl": "300450012"}]}
_real = q("select count(*) from reproduction.acris where doc_id not like 'SIM-%'")[0][0]
if _real:
    raise SystemExit("reproduction.acris holds %s real rows - this simulation claims through claim(), which hands out the first"
                     " empties of the WHOLE table, so it would take real documents; it runs on an empty table only (it did so"
                     " once on the populated table, 2026-09-05 19:2x: 28 real rows claimed for a moment, released, nothing landed)"
                     % "{:,}".format(_real))
q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
q("insert into reproduction.acris (doc_id, registry) select unnest(%s::text[]), %s::jsonb", (IDS, json.dumps(REG)), fetch=False)
q("insert into reproduction.acris (doc_id, registry) values ('SIM-0013', '\"pending\"'::jsonb)", fetch=False)
before_lane = q("select landed from reproduction.acris_update_lanes where lane = 'documentation'")[0][0]
before_phase = q("select landed from reproduction.acris_update")[0][0]
print("inserted 13 SIM rows; documentation landed before:", before_lane, "| phase landed before:", before_phase)


class SimRole:
    source, lane = "acris", "documentation"
    ua = "sim/0 (never sent)"
    flaky = set()

    def fetch(self, crew, doc_id, registry):
        with crew.lock:
            crew.stats["reqs"] += 1                     # counted like a request, none is made
        time.sleep(3)
        n = int(doc_id[-2:])
        if registry in (None, "pending", "absent"):
            raise lane.Retry("no registry to place the document")
        if n == 4:
            return "absent"
        if n == 5:
            return "pending"
        if n == 6:
            raise lane.Retry("short: 2/3 pages - placeholder at page 3")
        if n == 7 and doc_id not in self.flaky:
            self.flaky.add(doc_id)
            raise lane.Transport("SSLError: UNEXPECTED_EOF_WHILE_READING (simulated)")
        return acris.canonical_path(doc_id, registry)


args = types.SimpleNamespace(lane="documentation", host="SIM-HOST", width=4, stagger=0.1, claim=6, ttl="20 minutes",
                             pending_age="1 day", redial_wait=5, tries=3, entry_gap=1, limit=11, log="", unpark=False, tick=5)


def lower_width_later():
    time.sleep(4)
    (HERE / "documentation.control").write_text("width=2\n", encoding="utf-8")


print("--- the one-door lock and the park file ---")
(HERE / "documentation.lock").write_text(str(os.getpid()), encoding="utf-8")     # "another" live process
try:
    lane.run([(SimRole(), 4)], args, HERE)
    print("   FAIL: a second start was allowed")
except SystemExit as e:
    print("   second start refused:", str(e)[:70])
(HERE / "documentation.lock").unlink()
(HERE / "documentation.parked").write_text("REFUSED at SIM-0000 (test)\n", encoding="utf-8")
try:
    lane.run([(SimRole(), 4)], args, HERE)
    print("   FAIL: a parked lane started")
except SystemExit as e:
    print("   parked lane refused:", str(e).splitlines()[0][:70])
(HERE / "documentation.parked").unlink()
try:
    lane.run([(SimRole(), 0)], args, HERE)
    print("   FAIL: a zero-width crew was allowed")
except SystemExit as e:
    print("   zero width refused:", str(e)[:70])

threading.Thread(target=lower_width_later, daemon=True).start()
t0 = time.time()
code = lane.run([(SimRole(), 4)], args, HERE)
print("lock removed after the run:", not (HERE / "documentation.lock").exists())
print("run returned exit code", code, "after %.0fs" % (time.time() - t0))

print("--- cells in the cloud ---")
for did, doc in q("select doc_id, document from reproduction.acris where doc_id like 'SIM-%' order by doc_id"):
    print("  ", did, "->", doc)
after_lane = q("select landed from reproduction.acris_update_lanes where lane = 'documentation'")[0][0]
after_phase = q("select landed from reproduction.acris_update")[0][0]
print("documentation landed +%d (expect +11: 9 paths incl. 0007 on its second try + absent + pending; 0006 short and 0013 unplaceable stay empty)" % (after_lane - before_lane))
print("phase landed +%d (expect +11: those rows had a registry object)" % (after_phase - before_phase))
print("claims left on SIM rows:", q("select count(*) from reproduction.acris_claims where doc_id like 'SIM-%'")[0][0], "(expect 2: 0006 and 0013 - held until they expire, then a later pass)")
print("heartbeat:", q("select lane, host, width, last_event from reproduction.acris_heartbeats where host = 'SIM-HOST'"))
print("outbox left:", cloud.Outbox(HERE / "documentation.outbox.jsonl").count(), "| fails file lines:",
      len((HERE / "documentation.fails.jsonl").read_text().splitlines()) if (HERE / "documentation.fails.jsonl").exists() else 0)
print("--- cleanup ---")
q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
print("reconcile after cleanup:", q("select * from reproduction.reconcile('acris')"))
print("SIMULATION DONE - no ACRIS request was made")
