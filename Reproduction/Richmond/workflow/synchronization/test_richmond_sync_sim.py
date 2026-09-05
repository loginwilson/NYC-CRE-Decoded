"""SIMULATION of the richmond synchronization lane against the LIVE cloud with throwaway ids - NO county request.
A fake county stands in for the listing:

  the edge is 40 days back, so one catch-up window exists (holding ids 990000001..3); the heal window holds
  990000010..12; today lists 990000020 and, from second 8 on, 990000021 (a new filing); the control window
  parses rows; the window starting 35 days back fails every ask (a hole).

  expect: rows RC_990000001..3, 10..12, 20, 21 inserted; counters up by 8 (phase needed, sync landed, documentation
          needed); the edge file = the day BEFORE the holed window (the contiguity rule: the edge never jumps a window
          still open or holed - it moves to today only when that window answers); the hole recorded; the day probe cadence; the heartbeat; no county request.
"""
import datetime as dt, importlib.util, json, pathlib, sys, threading, time, types
PHASE = pathlib.Path(__file__).resolve().parents[3]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))
import psycopg2
import cloud, lane, richmond
spec = importlib.util.spec_from_file_location("richmond_synchronization", str(PHASE / "Richmond" / "workflow" / "synchronization" / "Richmond Synchronization.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("synchronization.*"):
    f.unlink()


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="test_richmond_sync_sim")
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
            out = cur.fetchall() if fetch and cur.description else None
        con.commit()
        return out
    finally:
        con.close()


q("delete from reproduction.richmond where doc_id like 'RC_9900000%%'", fetch=False)
q("delete from reproduction.richmond_heartbeats where host = 'SIM-HOST'", fetch=False)
before = q("select (select needed from reproduction.richmond_update), (select landed from reproduction.richmond_update_lanes where lane='synchronization'), (select needed from reproduction.richmond_update_lanes where lane='documentation')")[0]
print("counters before (phase needed, sync landed, documentation needed):", before)
T0 = time.time()
TODAY = dt.date.today()
EDGE = TODAY - dt.timedelta(days=40)
FAIL_START = (TODAY - dt.timedelta(days=34)).isoformat()      # the second catch-up window starts here (5-day windows from 39 days back)


def rows(ids):
    return [{"recorded": TODAY.strftime("%m/%d/%Y"), "type": "DEED", "internal_id": str(i), "instrument": "1"} for i in ids]


class FakeCounty(S.Synchronization):
    ua = "sim/0 (never sent)"

    def fetch(self, crew, key, _registry):
        with crew.lock:
            crew.stats["reqs"] += 1
        time.sleep(0.05)
        kind, a, b = key
        if kind == S.CONTROL:
            return (kind, rows([1, 2, 3]))
        if a == FAIL_START:
            raise lane.Transport("SSLError (simulated, every time)")
        if kind == "catch-up":
            return (kind, rows([990000001, 990000002, 990000003]))
        if kind == "heal":
            return (kind, rows([990000010, 990000011, 990000012, 990000020]))
        ids = [990000020] + ([990000021] if time.time() - T0 > 8 else [])
        return (kind, rows(ids))


args = types.SimpleNamespace(lane="synchronization", host="SIM-HOST", width=2, stagger=0.05, claim=0, ttl="20 minutes", pending_age="1 hour",
                             redial_wait=5, tries=3, entry_gap=1, limit=0, log="", unpark=False, tick=2,
                             edge=EDGE.isoformat(), every=2, heal_every=8, heal_days=30, pace=0.0, also=[])
role = FakeCounty(HERE, args)
# the catch-up window must include the failing one: make the edge such that windows are [edge+1 .. today-31] -> one window of 10 days;
# the failing window is a separate heal-era window? no: FAIL_START is inside the catch-up span (35 days back) - the single catch-up
# window starts at edge+1 (39 days back), so it does not fail. Give the failing window its own start by splitting: use richmond.WINDOW_DAYS = 5
richmond.WINDOW_DAYS = 5


def stop_later():
    time.sleep(24)
    (HERE / "synchronization.control").write_text("stop\n", encoding="utf-8")


threading.Thread(target=stop_later, daemon=True).start()
code = lane.run([(role, 2)], args, HERE)
print("exit code", code, "after %.0fs" % (time.time() - T0))

print("--- what landed ---")
got = sorted(int(r[0][3:]) for r in q("select doc_id from reproduction.richmond where doc_id like 'RC_9900000%%'"))
want = [990000001, 990000002, 990000003, 990000010, 990000011, 990000012, 990000020, 990000021]
print("   rows inserted:", got)
print("   expected     :", want, "->", "OK" if got == want else "MISMATCH")
state = json.loads((HERE / "synchronization.edge.json").read_text())
HELD_AT = (dt.date.fromisoformat(FAIL_START) - dt.timedelta(days=1)).isoformat()      # the contiguity rule: the edge waits behind the holed window
print("   edge file:", state["edge"], "(expect %s: the day before the holed window - the edge never jumps a hole)" % HELD_AT, "->", "OK" if state["edge"] == HELD_AT else "MISMATCH")
holes = [json.loads(l) for l in (HERE / "synchronization.holes.jsonl").read_text().splitlines()] if (HERE / "synchronization.holes.jsonl").exists() else []
print("   holes:", [(h["kind"], h["window"][0]) for h in holes], "(expect the window starting %s, once per heal)" % FAIL_START)
after = q("select (select needed from reproduction.richmond_update), (select landed from reproduction.richmond_update_lanes where lane='synchronization'), (select needed from reproduction.richmond_update_lanes where lane='documentation')")[0]
print("   counters moved by:", tuple(a - b for a, b in zip(after, before)), "(expect %d each)" % len(want))
print("   heartbeat:", q("select width, last_event from reproduction.richmond_heartbeats where host = 'SIM-HOST'"))
print("--- cleanup ---")
q("delete from reproduction.richmond where doc_id like 'RC_9900000%%'", fetch=False)
q("delete from reproduction.richmond_heartbeats where host = 'SIM-HOST'", fetch=False)
print("reconcile after cleanup:", q("select * from reproduction.reconcile('richmond')"))
print("RICHMOND SYNC SIMULATION DONE - no county request was made")
