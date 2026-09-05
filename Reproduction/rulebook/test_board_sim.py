"""SIMULATION of the board against the LIVE cloud with throwaway counters and heartbeats - the workflow table
stays empty, no lane runs, no ACRIS request.  The counters are moved by hand the way land() would move them,
the board ticks, and the two tabs are read back.  reconcile() restores the empty table's zeros at the end.

  tick 1   counters set (phase 100/1000; sync 1000/1000; registration 600/1000; documentation 100/1000), two
           fresh heartbeats -> written rows: pct, pending (no movement yet), sync complete, hosts folded
  tick 2   documentation +60 in a minute (readings backdated) -> active, 1.00/s, +60; 5 m kit from a 300 s reading
  tick 3   the documentation heartbeat's last word becomes a refusal -> stalled, eta paused; the phase stalled
  tick 4   documentation landed = needed -> complete
  restart  a new Board instance reads the ring from update.state.json and still has the windows
  reconcile the empty table -> every counter back to 0 / 0, the drift printed
  cleanup  heartbeats deleted; a last tick writes the truth (0 / 0, pending, no hosts)
"""
import json, pathlib, sys, time, types
PHASE = pathlib.Path(__file__).resolve().parents[1]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
import psycopg2
import board, cloud

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("update.*"):
    f.unlink()


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="test_board_sim")
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


def tabs():
    p = q("select landed, needed, pct, rate_60s, increase_60s, eta_60s, rate_5m, increase_5m, eta_5m, status, as_of from reproduction.acris_update")[0]
    lanes = {r[0]: r[1:] for r in q("select lane, landed, needed, pct, rate_60s, increase_60s, eta_60s, rate_5m, increase_5m, eta_5m, status, as_of, hosts, width, heartbeat_at, last_event from reproduction.acris_update_lanes")}
    return p, lanes


assert q("select count(*) from reproduction.acris")[0][0] == 0, "the workflow table must be empty for this simulation"
q("delete from reproduction.acris_heartbeats where host like 'SIM-%'", fetch=False)

print("=== tick 1: counters set, two fresh heartbeats")
q("update reproduction.acris_update set landed = 100, needed = 1000", fetch=False)
q("update reproduction.acris_update_lanes set landed = case lane when 'synchronization' then 1000 when 'registration' then 600 else 100 end, needed = 1000", fetch=False)
q("insert into reproduction.acris_heartbeats (lane, host, width, heartbeat_at, last_event) values ('documentation', 'SIM-HOST', 40, now(), 'started 1x40 at 2026-09-04 09:00'), ('registration', 'SIM-2', 20, now(), 'started 1x20 at 2026-09-04 09:00')", fetch=False)
args = types.SimpleNamespace(every=2, once=False, fresh=180, host="SIM-BOARD")
b = board.Board("acris", ("synchronization", "registration", "documentation"), HERE, args)
b.cloud.connect()
rows = b.tick()
p, lanes = tabs()
check("phase row written: 100/1000 = 10.00%, pending, as_of stamped", p[0] == 100 and p[1] == 1000 and float(p[2]) == 10.0 and p[9] == "pending" and p[10] is not None, p)
check("first tick has no kit yet (no reading a minute back)", p[3] is None and p[6] is None)
d = lanes["documentation"]
check("documentation row: 10.00%, pending, hosts SIM-HOST:40, width 40, last word", float(d[2]) == 10.0 and d[9] == "pending" and d[11] == "SIM-HOST:40" and d[12] == 40 and d[14].startswith("started"), d)
check("synchronization complete with eta complete", lanes["synchronization"][9] == "complete" and lanes["synchronization"][5] == "complete", lanes["synchronization"])
check("registration pending, hosts SIM-2:20", lanes["registration"][9] == "pending" and lanes["registration"][11] == "SIM-2:20")

print("=== tick 2: documentation +60 in a minute (readings backdated), +120 over five minutes")
now = time.time()
b.readings = [(now - 300, {"phase": 70, "synchronization": 1000, "registration": 600, "documentation": 40}),
              (now - 60, {"phase": 100, "synchronization": 1000, "registration": 600, "documentation": 100})]
q("update reproduction.acris_update_lanes set landed = 160 where lane = 'documentation'", fetch=False)
q("update reproduction.acris_update set landed = 130", fetch=False)
rows = b.tick()
p, lanes = tabs()
d = lanes["documentation"]
t2 = b.readings[-1][0]                                        # the board's own reading time: the real span is 60 / 300 s plus the cloud's round trips
r60, r5 = 60 / (t2 - (now - 60)), 120 / (t2 - (now - 300))
check("documentation active: +60 over the real minute span and +120 over the real window span, the rates and etas the board computes from them",
      d[9] == "active" and d[4] == 60 and abs(float(d[3]) - r60) < 0.015 and d[5] == board.eta_text(840, r60)
      and d[7] == 120 and abs(float(d[6]) - r5) < 0.015 and d[8] == board.eta_text(840, r5), (d, round(r60, 3), round(r5, 3)))
check("phase active: +30 by the minute, +60 by the window", p[9] == "active" and p[4] == 30 and p[7] == 60, p)
check("registration still pending with +0", lanes["registration"][9] == "pending" and lanes["registration"][4] == 0)

print("=== tick 3: the documentation heartbeat's last word becomes a refusal")
q("update reproduction.acris_heartbeats set heartbeat_at = now(), last_event = 'REFUSED at 2004113001335001 2026-09-04 09:10 - Bandwidth Notice' where host = 'SIM-HOST'", fetch=False)
b.tick()
p, lanes = tabs()
check("documentation stalled, eta paused, last word carried", lanes["documentation"][9] == "stalled" and lanes["documentation"][8] == "paused" and lanes["documentation"][14].startswith("REFUSED"), lanes["documentation"])
check("the phase stalled with it", p[9] == "stalled")

print("=== tick 4: documentation landed = needed")
q("update reproduction.acris_heartbeats set last_event = 'started 1x40 at 2026-09-04 09:20' where host = 'SIM-HOST'", fetch=False)
q("update reproduction.acris_update_lanes set landed = 1000 where lane = 'documentation'", fetch=False)
b.tick()
p, lanes = tabs()
check("documentation complete, eta complete", lanes["documentation"][9] == "complete" and lanes["documentation"][5] == "complete" and float(lanes["documentation"][2]) == 100.0)
b.cloud.close()

print("=== restart: a new Board reads the ring")
b2 = board.Board("acris", ("synchronization", "registration", "documentation"), HERE, args)
check("the ring survived the restart", len(b2.readings) >= 3 and b2._then(time.time(), 60, "documentation") is not None, len(b2.readings))
b2.cloud.connect()
b2.tick()
p, lanes = tabs()
check("after the restart the kits are present", lanes["registration"][4] is not None and p[7] is not None, (lanes["registration"], p))
b2.cloud.close()

print("=== show (nothing written)")
before = tabs()
b3 = board.Board("acris", ("synchronization", "registration", "documentation"), HERE, args)
b3.cloud.connect()
b3.show()
check("show wrote nothing", tabs() == before)

print("=== reconcile: the empty table -> zeros, drift printed")
b4 = board.Board("acris", ("synchronization", "registration", "documentation"), HERE, args)
b4.cloud.connect()
b4.reconcile()
p, lanes = tabs()
check("counters back to 0 / 0 everywhere", p[0] == 0 and p[1] == 0 and all(v[0] == 0 and v[1] == 0 for v in lanes.values()), (p, lanes))

print("=== cleanup: heartbeats deleted, a last tick writes the truth")
q("delete from reproduction.acris_heartbeats where host like 'SIM-%'", fetch=False)
for f in HERE.glob("update.*"):
    f.unlink()
b5 = board.Board("acris", ("synchronization", "registration", "documentation"), HERE, args)
b5.cloud.connect()
b5.tick()
b5.cloud.close()
p, lanes = tabs()
check("the truth: 0 / 0, pct null, pending, no hosts", p[0] == 0 and p[2] is None and p[9] == "pending" and all(v[11] is None and v[9] == "pending" for v in lanes.values()), (p, lanes))
print("\nBOARD SIMULATION:", "ALL OK" if not fails else "FAILURES: %s" % fails, "- no ACRIS request, the workflow table untouched")
sys.exit(1 if fails else 0)
