"""SIMULATION of the registration lane against the LIVE cloud with throwaway rows - NO ACRIS request.
The role answers from a synthetic page (parsed by the real parser) instead of the network.

  rows:  SIM-0001..SIM-0010 with registry NULL and document NULL; SIM-0011 with document already a path
  role:  ...03 -> no echo (Retry)   ...05 -> Transport once, then a registry   the rest -> a registry
  run:   width 3, limit 10
  check: registry cells are objects with the parsed keys + at; registration landed +10; the phase landed
         +1 (only SIM-0011 had its document cell filled); 0003's claim held; heartbeat; outbox 0; fails 1
"""
import json, os, pathlib, sys, time, types
PHASE = pathlib.Path(__file__).resolve().parents[2]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
import psycopg2
import cloud, lane, acris

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("registration.*"):
    f.unlink()


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="test_registration_sim")
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
            out = cur.fetchall() if fetch and cur.description else None
        con.commit()
        return out
    finally:
        con.close()


PAGE = """<html><body><table><tr><td>DOCUMENT ID: %s</td><td>CRFN: 2024000123456</td></tr>
<tr><td>DOC. TYPE: MTGE</td><td># of PAGES: 12</td><td>DOC. DATE: 8/9/2024</td></tr>
<tr><td>RECORDED / FILED: 8/15/2024 10:12:03 AM</td><td>DOC. AMOUNT: $900,000.00</td></tr>
<table><tr><td>PARCELS</td></tr><table><tr><th>BOROUGH</th><th>BLOCK</th><th>LOT</th><th>PARTIAL</th></tr>
<tr><td>BROOKLYN</td><td>00123</td><td>0045</td><td>N/A</td></tr></table></table></table></body></html>"""

IDS = ["SIM-%04d" % i for i in range(1, 12)]
_real = q("select count(*) from reproduction.acris where doc_id not like 'SIM-%'")[0][0]
if _real:
    raise SystemExit("reproduction.acris holds %s real rows - this simulation writes into the live table (the lane claims through claim(), which hands out the first empties of the WHOLE table), so on the"
                     " populated table it would touch real documents; it runs on an empty table only (rule of 2026-09-05 19:2x)"
                     % "{:,}".format(_real))
q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
q("insert into reproduction.acris (doc_id) select unnest(%s::text[])", (IDS,), fetch=False)
q("update reproduction.acris set document = %s where doc_id = 'SIM-0011'", (r"D:\NYC CRE Decoded\Reproduction\Acris\By Document\2004\08 Aug\21\SIM-0011.pdf",), fetch=False)
before_lane = q("select landed from reproduction.acris_update_lanes where lane = 'registration'")[0][0]
before_phase = q("select landed from reproduction.acris_update")[0][0]
print("inserted 11 SIM rows (registry empty); registration landed before:", before_lane, "| phase before:", before_phase)


class SimReg:
    source, lane = "acris", "registration"
    ua = "sim/0 (never sent)"
    noun = "registries"
    needs_registry = False
    flaky = set()

    def fetch(self, crew, doc_id, registry):
        with crew.lock:
            crew.stats["reqs"] += 1
        time.sleep(1.0)                                  # long enough that the run crosses a minute tick (tick=2 s)
        n = int(doc_id[-2:])
        if n == 3:
            raise lane.Retry("page does not echo the id after 3 asks (simulated)")
        if n == 5 and doc_id not in self.flaky:
            self.flaky.add(doc_id)
            raise lane.Transport("ConnectionError: RemoteDisconnected (simulated)")
        html = acris.clean_html(PAGE % doc_id)
        assert acris.echoes(html, doc_id)
        rec = acris.parse_acris(html)
        rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return rec


args = types.SimpleNamespace(lane="registration", host="SIM-HOST", width=3, stagger=0.05, claim=6, ttl="20 minutes",
                             pending_age="1 hour", redial_wait=5, tries=3, entry_gap=1, limit=10, log="", unpark=False, tick=2)
t0 = time.time()
code = lane.run([(SimReg(), 3)], args, HERE)
print("run returned exit code", code, "after %.0fs" % (time.time() - t0))

print("--- registry cells in the cloud ---")
for did, reg in q("select doc_id, registry from reproduction.acris where doc_id like 'SIM-%' order by doc_id"):
    print("  ", did, "->", (sorted(reg.keys()) if isinstance(reg, dict) else reg))
after_lane = q("select landed from reproduction.acris_update_lanes where lane = 'registration'")[0][0]
after_phase = q("select landed from reproduction.acris_update")[0][0]
print("registration landed +%d (expect +10: all but 0003)" % (after_lane - before_lane))
print("phase landed +%d (expect +1: only SIM-0011 had its document cell filled)" % (after_phase - before_phase))
print("claims left on SIM rows:", q("select count(*) from reproduction.acris_claims where doc_id like 'SIM-%'")[0][0], "(expect 1: SIM-0003)")
print("heartbeat:", q("select lane, host, width, last_event from reproduction.acris_heartbeats where host = 'SIM-HOST'"))
print("outbox left:", cloud.Outbox(HERE / "registration.outbox.jsonl").count(), "| fails file lines:",
      len((HERE / "registration.fails.jsonl").read_text().splitlines()) if (HERE / "registration.fails.jsonl").exists() else 0)
print("--- cleanup ---")
q("delete from reproduction.acris where doc_id like 'SIM-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host = 'SIM-HOST'", fetch=False)
print("reconcile after cleanup:", q("select * from reproduction.reconcile('acris')"))
print("REGISTRATION SIMULATION DONE - no ACRIS request was made")
