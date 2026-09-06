"""OFFLINE checks of the board: the rate / increase / percentage / eta math over synthetic readings, the four
statuses, the fold of heartbeats, the out-of-bounds gate, the printed line.  No cloud."""
import pathlib, sys, time, types, datetime
PHASE = pathlib.Path(__file__).resolve().parents[1]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
import board

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("update.*"):
    f.unlink()
args = types.SimpleNamespace(every=60, once=False, fresh=180, host="SIM-BOARD")
b = board.Board("acris", ("synchronization", "registration", "documentation"), HERE, args)
now = time.time()
ts = datetime.datetime.now(datetime.timezone.utc)
b.readings = [(now - 300, {"phase": 1000, "synchronization": 10000, "registration": 5000, "documentation": 2000}),
              (now - 60, {"phase": 1100, "synchronization": 10000, "registration": 5000, "documentation": 2100})]
counters = {"phase": (1150, 10000), "synchronization": (10000, 10000), "registration": (5000, 10000), "documentation": (2150, 10000)}
beats = [("documentation", "H1", 40, ts, 30, "started 1x40 at 2026-09-04 09:00"),
         ("documentation", "H2", 20, ts, 600, "REFUSED at 2004113001335001"),          # stale: not alive, not the freshest
         ("registration", "H1", 40, ts, 45, "started 1x40 at 2026-09-04 09:01")]
rows = b.compute(now, counters, beats)
d = rows["documentation"]
check("60s kit: +50 over 60 s = 0.83/s, 0.5%", d["increase_60s"] == 50 and abs(d["rate_60s"] - 0.83) < 0.01 and d["pct_60s"] == 0.5, d)
check("5m kit: +150 over 300 s = 0.5/s, 1.5%, eta 4.4 hours", d["increase_5m"] == 150 and d["rate_5m"] == 0.5 and d["pct_5m"] == 1.5 and d["eta_5m"] == "4.4 hours", d)
check("documentation active on movement", d["status"] == "active")
check("fold: alive hosts only, width summed, freshest last word", d["hosts"] == "H1:40" and d["width"] == 40 and d["last_event"].startswith("started"), d)
check("registration pending: alive, nothing landing", rows["registration"]["status"] == "pending" and rows["registration"]["eta_5m"] == "paused" and rows["registration"]["increase_5m"] == 0)
check("synchronization complete, eta complete", rows["synchronization"]["status"] == "complete" and rows["synchronization"]["eta_60s"] == "complete")
p = rows["phase"]
check("phase: 11.50%, active, +50 / +150", p["pct"] == 11.5 and p["status"] == "active" and p["increase_60s"] == 50 and p["increase_5m"] == 150, p)
# a refusal as the freshest last word -> stalled, even with movement
beats2 = [("documentation", "H1", 40, ts, 30, "REFUSED at 2004113001335001 2026-09-04 09:10 - Bandwidth Notice")]
rows2 = b.compute(now, counters, beats2)
check("a refusal as the last word -> stalled, eta paused; the phase stalled too", rows2["documentation"]["status"] == "stalled" and rows2["documentation"]["eta_5m"] == "paused" and rows2["phase"]["status"] == "stalled")
# out of bounds
rows3 = b.compute(now, {"phase": (20000, 10000), "documentation": (2150, 10000)}, [])
check("landed > needed -> metrics null, why says reconcile", rows3["phase"]["rate_60s"] is None and rows3["phase"]["status"] is None and "reconcile" in rows3["phase"]["why"])
# no readings old enough -> null kits, pending
b.readings = [(now - 20, {"phase": 1140, "documentation": 2140})]
rows4 = b.compute(now, {"phase": (1150, 10000), "documentation": (2150, 10000)}, [])
check("a reading only 20 s old gives no kit yet; status pending", rows4["documentation"]["rate_60s"] is None and rows4["documentation"]["status"] == "pending")
check("eta_text", (board.eta_text(86400 * 2.5, 1.0), board.eta_text(7200, 1.0), board.eta_text(600, 1.0), board.eta_text(30, 1.0), board.eta_text(0, 1.0), board.eta_text(10, 0))
      == ("2.5 days", "2.0 hours", "10 min", "under a minute", None, None))
for key in rows:
    line = b.line(key, rows[key])
    ok = line.startswith("UPDATE acris") and ("ACTIVE" in line or "PENDING" in line or "COMPLETE" in line)
    if not ok:
        check("line renders for " + key, False, line)
check("lines render", True)
# the workstation rows (0007): each machine's own count and rate from the same subtraction, its own status
b.readings = [(now - 300, {"documentation": 2000, "documentation@H1": 1200, "documentation@H2": 800}),
              (now - 60, {"documentation": 2100, "documentation@H1": 1280, "documentation@H2": 800})]
beats5 = [("documentation", "H1", 40, ts, 30, "started 1x40 at 2026-09-04 09:00", 1320),
          ("documentation", "H2", 20, ts, 600, "REFUSED at 2004113001335001", 800)]
rows5 = b.compute(now, {"phase": (1150, 10000), "documentation": (2150, 10000)}, beats5)
w1, w2 = rows5["documentation@H1"], rows5["documentation@H2"]
check("workstation H1: landed 1,320, +40 in 60 s = 0.67/s, +120 in 5 min, active, no pct", w1["landed"] == 1320 and w1["increase_60s"] == 40 and abs(w1["rate_60s"] - 0.67) < 0.01 and w1["increase_5m"] == 120 and w1["status"] == "active" and w1["pct"] is None, w1)
check("workstation H2: refused -> stalled, eta paused, nothing moved", w2["status"] == "stalled" and w2["eta_5m"] == "paused" and w2["increase_5m"] == 0, w2)
check("a workstation line renders with lane @ machine", "documentation @ H1" in b.line("documentation@H1", w1) and "ACTIVE" in b.line("documentation@H1", w1), b.line("documentation@H1", w1))
print(b.line("documentation", rows["documentation"]))
print(b.line("phase", rows3["phase"]))
print("\nBOARD OFFLINE:", "ALL OK" if not fails else "FAILURES: %s" % fails)
sys.exit(1 if fails else 0)
