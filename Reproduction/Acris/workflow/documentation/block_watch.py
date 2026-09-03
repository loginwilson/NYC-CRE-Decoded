"""BLOCK WATCH - a correlation record beside the acris 1x40 documentation lane.

login 2026-09-03 07:4x: "make sure to check if anything causes the block."

Every 60 s it writes ONE line to block_watch.log (in the decoder dir):
  - the lane's own counters from its last PROGRESS line (reqs/pdfs/fails and
    their per-minute deltas),
  - sockets to ACRIS (157.188.15.133) by state and by owning pid - the lane's
    pid should be the ONLY owner and ESTABLISHED should sit near the worker
    count,
  - every process BORN since the previous tick (name + pid), so anything that
    starts on this machine is on the record with a time,
and every 10 min:
  - one draw of the exit pool (api.ipify.org - never ACRIS) and the scheduled
    tasks whose last run fell inside the last 10 min.
When the lane log shows a stop (REFUSED / DEAD TRANSPORT / STOPPING ALL) it
writes a SNAPSHOT block: the last 15 ticks, current sockets, every process
born in the last 30 min, tasks run in the last 30 min, one exit draw.
It launches nothing, touches ACRIS never, and only reads.
"""
import os, re, subprocess, sys, time, urllib.request

DEC = r"C:\Users\smile\Downloads\Source Folder (Real Estate Data)\Decoder Prompt\decoder"
LANE_LOG = os.path.join(DEC, "acris_repro_document.log")
LOG = os.path.join(DEC, "block_watch.log")
ACRIS_IP = "157.188.15.133"
TICK = 60
SLOW_EVERY = 600


def log(msg):
    line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def lane_tail(n=40):
    try:
        with open(LANE_LOG, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except OSError:
        return []


PROG = re.compile(r"PROGRESS (\d+)m - reqs ([\d,]+) \(([\d.]+)/s\).*?- ([\d,]+) pdfs - ([\d,]+) imageless.*?fail (\d+)")


def lane_counters(tail):
    for l in reversed(tail):
        m = PROG.search(l)
        if m:
            g = lambda i: int(m.group(i).replace(",", ""))
            return {"min": g(1), "reqs": g(2), "pdfs": g(4), "imageless": g(5), "fail": g(6)}
    return None


def sockets():
    """netstat -ano: rows to ACRIS -> {(state, pid): n}"""
    out = {}
    try:
        txt = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=30).stdout
    except Exception as e:
        return {("netstat-failed:" + type(e).__name__, 0): 1}
    for l in txt.splitlines():
        if ACRIS_IP + ":" in l:
            parts = l.split()
            if len(parts) >= 5:
                k = (parts[3], int(parts[4]))
                out[k] = out.get(k, 0) + 1
    return out


def fmt_sockets(s):
    if not s:
        return "acris sockets: none"
    by_pid = {}
    for (state, pid), n in s.items():
        by_pid.setdefault(pid, {})[state] = n
    return "acris sockets: " + "; ".join(
        "pid %d %s" % (pid, ",".join("%s=%d" % (st, n) for st, n in sorted(d.items()))) for pid, d in sorted(by_pid.items()))


def processes():
    """tasklist csv -> {pid: name}"""
    try:
        txt = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None
    d = {}
    for l in txt.splitlines():
        parts = [p.strip('"') for p in l.split('","')]
        if len(parts) >= 2:
            try:
                d[int(parts[1])] = parts[0]
            except ValueError:
                pass
    return d


def exit_draw():
    try:
        return urllib.request.urlopen(urllib.request.Request(
            "https://api.ipify.org", headers={"User-Agent": "curl/8"}), timeout=15).read().decode().strip()
    except Exception as e:
        return "draw failed: " + type(e).__name__


def tasks_ran_since(minutes):
    ps = ("$t=(Get-Date).AddMinutes(-%d); Get-ScheduledTask | ForEach-Object { $i=$_ | Get-ScheduledTaskInfo; "
          "if ($i.LastRunTime -ge $t) { '{0:HH:mm:ss} {1}{2} rc {3}' -f $i.LastRunTime, $_.TaskPath, $_.TaskName, $i.LastTaskResult } }" % minutes)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120).stdout
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return lines or ["none"]
    except Exception as e:
        return ["task query failed: " + type(e).__name__]


def main():
    log("block watch up - tick %ds, slow checks every %ds, acris %s, reads only" % (TICK, SLOW_EVERY, ACRIS_IP))
    prev = None
    known = processes() or {}
    births = []                       # (time, pid, name)
    ticks = []                        # last tick lines for the snapshot
    last_slow = 0
    reported_stop = None
    while True:
        t0 = time.time()
        tail = lane_tail()
        c = lane_counters(tail)
        s = sockets()
        now = processes()
        new = []
        if now is not None:
            new = [(pid, name) for pid, name in now.items() if pid not in known]
            known = now
            for pid, name in new:
                births.append((time.time(), pid, name))
            births = [b for b in births if time.time() - b[0] <= 1800]
        if c and prev:
            d = "reqs +%d pdfs +%d fail +%d" % (c["reqs"] - prev["reqs"], c["pdfs"] - prev["pdfs"], c["fail"] - prev["fail"])
        elif c:
            d = "first tick"
        else:
            d = "no PROGRESS line yet"
        head = ("lane %dm reqs %s pdfs %s fail %d | %s" % (c["min"], format(c["reqs"], ","), format(c["pdfs"], ","), c["fail"], d)) if c else "lane: " + d
        line = head + " | " + fmt_sockets(s) + (" | BORN: " + ", ".join("%s(%d)" % (n, p) for p, n in new) if new else "")
        log(line)
        ticks = (ticks + [time.strftime("%H:%M:%S") + "  " + line])[-15:]
        prev = c or prev
        if time.time() - last_slow >= SLOW_EVERY:
            last_slow = time.time()
            log("slow: exit draw %s | tasks ran last 10 min: %s" % (exit_draw(), " || ".join(tasks_ran_since(10))))
        stop = None
        for l in tail:
            if "REFUSED at" in l or "DEAD TRANSPORT" in l or "STOPPING ALL" in l:
                stop = l.strip()[:120]
        if stop and stop != reported_stop:
            reported_stop = stop
            log("=== SNAPSHOT: lane stop seen: %s" % stop)
            for t in ticks:
                log("   tick  " + t)
            log("   sockets now: " + fmt_sockets(sockets()))
            log("   born last 30 min: " + (", ".join("%s %s(%d)" % (time.strftime("%H:%M:%S", time.localtime(b[0])), b[2], b[1]) for b in births) or "none"))
            log("   tasks ran last 30 min: " + " || ".join(tasks_ran_since(30)))
            log("   exit draw: " + exit_draw())
            log("=== END SNAPSHOT")
        time.sleep(max(1, TICK - (time.time() - t0)))


if __name__ == "__main__":
    main()
