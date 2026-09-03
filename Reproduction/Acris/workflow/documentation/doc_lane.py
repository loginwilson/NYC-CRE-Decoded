"""doc_lane.py - THE ACRIS DOCUMENTATION LANE, AS CODE (login 2026-09-03: "we risk you forgetting how to do
this documentation lane efficiently").  Everything learned on 09-01..09-03 is in here so it never has to be
re-derived:

  python doc_lane.py status            what is running, last minute, sockets, park, board row
  python doc_lane.py checks            pre-launch checks only (drive, WAL, park, sockets, exit pool)
  python doc_lane.py launch [label]    checks -> clear the lane's OWN park -> rotate log -> 1x40 via WMI
                                       -> follower / watcher / supervisor / board loops -> print minute 1
  python doc_lane.py stop --reason ".."  a PERSON's stop: park entry FIRST, supervisor second, lane last

THE RULES (each one cost a day; see ACRIS REPRODUCTION.md s17):
  * ONE entry: one pooled session, one connection per worker at birth, keep-alive after, ZERO further
    handshakes.  Never a fresh-handshake burst test (40x5 "blocks").  The socket table is the proof of
    shape: 40 ESTABLISHED to 157.188.15.133 and no TIME_WAIT churn.
  * The lane has no IP.  It goes out on whatever ExpressVPN presents; ExpressVPN hands EACH CONNECTION a
    different exit from a pool.  "The current IP" is one draw.  Launch only when the pool sits in ONE block
    (5 draws, one /24); a pool spanning blocks = the app mid-switch.
  * A BLOCK is HTTP 200 + the Bandwidth Notice page (5/5 phrases).  Nothing else is a block.  A redial
    right after a notice is refused within 6 requests; the notice lifts on its own clock (33 min .. 5 h seen).
  * A HANG-UP is the far side closing all 40 keep-alive lines at once (ESTABLISHED -> CLOSE_WAIT in one
    tick), then SSLError on the same process's redials for ~6 min, then the lane's DEAD-TRANSPORT breaker.
    A FRESH PROCESS is served at once.  The supervisor redials (3 tries per incident, wifi waits).
    Its clock is NOT the run's age (refuted 09-03 14:07).  New since ExpressVPN 14 / Lightway.
  * Never manual-kill on a fail count; the lane's own detectors decide.  Never edit running code; edit at a
    stop, keep a .bak, py_compile.
  * Launch via WMI so the process survives a Claude session restart.  DRAIN a multi-GB WAL before launch.
  * A person's park entry is never touched by code; only the lane's own "REFUSED at" / "supervisor" parks
    are cleared by launch.
"""
import sys, os, io, re, json, time, subprocess, sqlite3, tempfile, urllib.request

DEC = r"C:\Users\smile\Downloads\Source Folder (Real Estate Data)\Decoder Prompt\decoder"
UPD = r"D:\CRE Decoding System\Updates"
NAV_DB = r"D:\CRE Decoding System\Legal Instruments.db"
PY = r"C:\Users\smile\AppData\Local\Programs\Python\Python312\python.exe"
OFFICE = r"C:\dev\cre-office"
LANE = "acris_repro_document"
LANE_ARGS = "--floor document --sync-workers 0 --rd-workers 0 --pdf-workers 40 --every 3600 --hi 2014"
ACRIS_IP = "157.188.15.133"
LOG = os.path.join(DEC, "acris_repro_document.log")
PARK = os.path.join(DEC, "_paused_runtime.json")
PROG = re.compile(r"PROGRESS (\d+)m - reqs ([\d,]+) \(([\d.]+)/s\).*?- ([\d,]+) pdfs.*?fail (\d+) - repro ([\d.]+)")

HELPERS = [  # (script, cwd, args, must-contain)
    ("follow_doc.py", DEC, "", ""),
    ("block_watch.py", OFFICE, "", ""),
    ("night_supervisor.py", OFFICE, "", ""),
    ("board_truth.py", UPD, "--loop --every 60", "--loop"),
    ("routine_update.py", UPD, "--loop", "--loop"),
]


def ps(script, timeout=120):
    """run a PowerShell script from a temp file (no command-line quoting games)"""
    fd, path = tempfile.mkstemp(suffix=".ps1"); os.close(fd)
    io.open(path, "w", encoding="utf-8").write(script)
    try:
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
                              capture_output=True, text=True, timeout=timeout).stdout
    finally:
        try: os.remove(path)
        except OSError: pass


def python_procs():
    out = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.ProcessId.ToString() + ' ' + $_.CommandLine }")
    procs = []
    for l in out.splitlines():
        l = l.strip()
        if l:
            pid, _, cmd = l.partition(" ")
            procs.append((int(pid), cmd))
    return procs


def find(procs, script, must=""):
    return [p for p, c in procs if re.search(r"[\\ /]" + re.escape(script), c) and must in c]


def sockets():
    out = ps("Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $_.RemoteAddress -eq '%s' } | ForEach-Object { $_.State.ToString() + ' ' + $_.OwningProcess }" % ACRIS_IP)
    d = {}
    for l in out.splitlines():
        if l.strip():
            st, pid = l.split()
            d[(st, int(pid))] = d.get((st, int(pid)), 0) + 1
    return d


def fmt_sockets(d):
    return ", ".join("%s x%d (pid %d)" % (st, n, pid) for (st, pid), n in sorted(d.items())) or "none"


def park():
    try:
        return json.load(io.open(PARK, encoding="utf-8")).get(LANE)
    except Exception:
        return None


def set_park(value):
    d = json.load(io.open(PARK, encoding="utf-8"))
    if value is None:
        d.pop(LANE, None)
    else:
        d[LANE] = value
    tmp = PARK + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, indent=1))
    os.replace(tmp, PARK)


def own_park(entry):
    return entry is not None and (str(entry).startswith("REFUSED at") or str(entry).startswith("supervisor"))


def last_progress():
    try:
        lines = io.open(LOG, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return None, ""
    tail = "\n".join(lines[-40:])
    for l in reversed(lines):
        m = PROG.search(l)
        if m:
            return {"min": int(m.group(1)), "reqs": int(m.group(2).replace(",", "")), "rps": float(m.group(3)),
                    "pdfs": int(m.group(4).replace(",", "")), "fail": int(m.group(5)), "dps": float(m.group(6))}, tail
    return None, tail


def exit_draws(n=5):
    seen = []
    for i in range(n):
        try:
            ip = urllib.request.urlopen(urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "curl/8", "Connection": "close"}), timeout=15).read().decode().strip()
        except Exception as e:
            ip = "fail:" + type(e).__name__
        seen.append(ip); time.sleep(1)
    blocks = sorted({".".join(x.split(".")[:3]) for x in seen if x[:1].isdigit()})
    return seen, blocks


def board_row():
    try:
        c = sqlite3.connect(os.path.join(UPD, "Updates.db"))
        r = c.execute("select landed, rate_now, increase_now, rate, increase, pct_of_total, status, as_of from update_floors where source='acris' and phase like 'document%'").fetchone()
        c.close()
        return "landed %s | 60s %s/s %+d | 5m %s/s %+d | %s%% | %s | %s" % (format(r[0] or 0, ","), r[1], int(r[2] or 0), r[3], int(r[4] or 0), r[5], r[6], r[7])
    except Exception as e:
        return "board unreadable (%s)" % type(e).__name__


def wmi(cmd, cwd):
    script = ('$su=([WmiClass]"Win32_ProcessStartup").CreateInstance(); $su.ShowWindow=0; '
              '$r=([WmiClass]"Win32_Process").Create(\'%s\', \'%s\', $su); "pid " + $r.ProcessId + " rc " + $r.ReturnValue'
              % (cmd.replace("'", "''"), cwd.replace("'", "''")))
    return ps(script).strip()


def launch_helper(script, cwd, args):
    cmd = 'cmd.exe /c cd /d "%s" && "%s" -u %s %s >> "%s" 2>> "%s"' % (
        cwd, PY, script, args, os.path.join(cwd, script[:-3] + ".out"), os.path.join(cwd, script[:-3] + ".err"))
    return wmi(cmd, cwd)


def ensure_helpers(procs):
    for script, cwd, args, must in HELPERS:
        if find(procs, script, must):
            print("  %-20s running" % script)
        else:
            print("  %-20s launched %s" % (script, launch_helper(script, cwd, args)))


# ----------------------------------------------------------------------------------------------- commands

def cmd_status():
    procs = python_procs()
    lane = find(procs, "acris_reproduction.py", "--floor document")
    p, tail = last_progress()
    print("time   %s" % time.strftime("%H:%M:%S"))
    print("lane   %s" % ("UP pid %s" % lane if lane else "DOWN"))
    if p:
        print("last   %dm  reqs %s (%.1f/s)  pdfs %s  fail %d  %.2f docs/s" % (p["min"], format(p["reqs"], ","), p["rps"], format(p["pdfs"], ","), p["fail"], p["dps"]))
    for key in ("REFUSED at", "DEAD TRANSPORT", "SELF-PARKED", "run end"):
        if key in tail:
            print("tail   contains: %s" % key)
    print("socks  %s" % fmt_sockets(sockets()))
    print("park   %s" % (park() or "(none)"))
    for script, cwd, args, must in HELPERS:
        print("helper %-20s %s" % (script, "running" if find(procs, script, must) else "DOWN"))
    print("board  %s" % board_row())
    try:
        print("superv " + " | ".join(io.open(os.path.join(DEC, "night_supervisor.log"), encoding="utf-8").read().splitlines()[-2:]))
    except OSError:
        pass


def cmd_checks(strict=True):
    ok = True
    print("checks %s" % time.strftime("%H:%M:%S"))
    if not os.path.exists(NAV_DB):
        print("  FAIL drive: %s missing (One Touch not mounted)" % NAV_DB); return False
    wal = os.path.getsize(NAV_DB + "-wal") if os.path.exists(NAV_DB + "-wal") else 0
    print("  %s WAL %s MB%s" % ("ok  " if wal < 1_000_000_000 else "FAIL", wal // 1_000_000, "" if wal < 1_000_000_000 else " - DRAIN BEFORE LAUNCH (a lane launched onto a multi-GB WAL freezes at its first commit)"))
    ok &= wal < 1_000_000_000
    e = park()
    if e is None:
        print("  ok   park: none")
    elif own_park(e):
        print("  ok   park: the lane's own (%s) - launch clears it" % str(e)[:60])
    else:
        print("  FAIL park: a PERSON's entry - not mine to clear: %s" % str(e)[:100]); ok = False
    s = sockets()
    procs = python_procs()
    lane = find(procs, "acris_reproduction.py", "--floor document")
    others = {pid for (st, pid) in s if st == "Established" and pid not in lane}
    print("  %s sockets to ACRIS: %s%s" % ("ok  " if not others else "WARN", fmt_sockets(s), "" if not others else " - something else holds a line to ACRIS: pids %s" % sorted(others)))
    seen, blocks = exit_draws(5)
    stable = len(blocks) == 1
    print("  %s exit pool: %s -> blocks %s (%s)" % ("ok  " if stable else "FAIL", ", ".join(seen), blocks, "one block" if stable else "SPANS BLOCKS - the VPN app is mid-switch; wait and re-check"))
    ok &= stable or not strict
    return bool(ok)


def cmd_launch(label="", force=False):
    procs = python_procs()
    if find(procs, "acris_reproduction.py", "--floor document"):
        print("lane already running: %s - nothing launched" % find(procs, "acris_reproduction.py", "--floor document")); return 1
    if not cmd_checks() and not force:
        print("checks failed - not launching (use --force only on login's word)"); return 1
    if own_park(park()):
        set_park(None); print("  cleared the lane's own park entry")
    stamp = time.strftime("%Y%m%d-%H%M") + ("-" + label if label else "")
    for name in ("acris_repro_document.log", "acris_repro_document.log.err"):
        p = os.path.join(DEC, name)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            os.replace(p, p.replace(".log", ".log." + stamp, 1) if name.endswith(".log") else p + "." + stamp)
    cmd = 'cmd.exe /c cd /d "%s" && "%s" -u acris_reproduction.py %s > "%s" 2> "%s"' % (DEC, PY, LANE_ARGS, LOG, LOG + ".err")
    t0 = time.strftime("%H:%M:%S")
    print("LAUNCH 1x40 at %s via WMI: %s" % (t0, wmi(cmd, DEC)))
    time.sleep(8)
    print("helpers:")
    ensure_helpers(python_procs())
    print("waiting for minute 1 ...")
    for i in range(20):
        time.sleep(5)
        p, tail = last_progress()
        if p:
            print("minute %d: reqs %s (%.1f/s)  pdfs %s  fail %d  %.2f docs/s" % (p["min"], format(p["reqs"], ","), p["rps"], format(p["pdfs"], ","), p["fail"], p["dps"]))
            print("sockets: %s" % fmt_sockets(sockets()))
            return 0 if p["pdfs"] > 0 else 2
        if "REFUSED at" in tail:
            print("REFUSED on entry - ACRIS served the notice; the lane self-parked. Nothing to redial; the notice lifts on its own clock."); return 3
    print("no PROGRESS line after 100 s - read the log: %s" % LOG); return 2


def cmd_stop(reason):
    if not reason:
        print("stop needs --reason \"...\" (it becomes the park entry, in login's words)"); return 1
    set_park("parked %s - login: %s" % (time.strftime("%Y-%m-%d %H:%M"), reason))
    print("1. park entry written FIRST")
    procs = python_procs()
    for pid in find(procs, "night_supervisor.py"):
        ps("Stop-Process -Id %d -Force" % pid); print("2. supervisor pid %d stopped (so it cannot redial)" % pid)
    for pid in find(procs, "acris_reproduction.py", "--floor document"):
        ps("Stop-Process -Id %d -Force" % pid); print("3. lane pid %d stopped" % pid)
    print("board loops, follower and watcher left running (the board must keep moving)")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:] or ["status"]
    if a[0] == "status":
        cmd_status()
    elif a[0] == "checks":
        sys.exit(0 if cmd_checks() else 1)
    elif a[0] == "launch":
        sys.exit(cmd_launch(next((x for x in a[1:] if not x.startswith("--")), ""), "--force" in a))
    elif a[0] == "stop":
        sys.exit(cmd_stop(a[a.index("--reason") + 1] if "--reason" in a and len(a) > a.index("--reason") + 1 else ""))
    else:
        print(__doc__)
