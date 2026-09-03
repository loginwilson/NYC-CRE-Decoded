"""NIGHT SUPERVISOR for the acris 1x40 documentation lane + the board loops.

login 2026-09-03 01:0x: "if the wifi crashes, don't just give up like usual. the
wifi cutting out is not the same as a block. and even if we get blocked, i rather
you try 3 times to make sure than give up and it not actually be a block."
and: "updates should always move with any lane movement so those shouldn't ever
stop."

What it does, every 30 s:
  1. If the lane (acris_reproduction.py --floor document) is not running:
       - if the network is down (no neutral host answers) -> WAIT. A wifi outage
         consumes no attempts and is never called a block.
       - else relaunch it under the current IP: unpark its own self-park (only
         the lane's own "REFUSED at ..." entry - a human's park is never
         touched), rotate the log, start it detached. Up to 3 relaunches per
         incident; an incident closes when the lane stays up 3 minutes and
         lands. After 3 failed relaunches: park with the reason and stop trying
         (a human decides in the morning). Nothing else is ever launched.
  2. If board_truth / routine_update / follow_doc are not running, relaunch them
     (the board must move with the lane).
Everything it does is written to night_supervisor.log beside the lane.
"""
import json, os, re, subprocess, sys, time, urllib.request

DEC = r"C:\Users\smile\Downloads\Source Folder (Real Estate Data)\Decoder Prompt\decoder"
UPD = r"D:\CRE Decoding System\Updates"
PY = sys.executable
LANE_ARGS = ["--floor", "document", "--sync-workers", "0", "--rd-workers", "0",
             "--pdf-workers", "40", "--every", "3600", "--hi", "2014"]
LANE_NAME = "acris_repro_document"
LOG = os.path.join(DEC, "night_supervisor.log")
DETACHED = 0x00000008 | 0x00000200        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
MAX_TRIES = 3
SETTLE_S = 180


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def python_cmdlines():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=60).stdout
        return [l for l in out.splitlines() if l.strip()]
    except Exception as e:
        log("process listing failed (%s) - assuming everything is alive" % type(e).__name__)
        return None


def running(cmdlines, script, must=""):
    if cmdlines is None:
        return True
    return any(re.search(r"[\\ /]" + re.escape(script), c) and must in c for c in cmdlines)


def net_up():
    for host in ("https://www.nyc.gov/", "https://github.com/"):
        try:
            urllib.request.urlopen(urllib.request.Request(host, method="HEAD",
                                   headers={"User-Agent": "Mozilla/5.0"}), timeout=10)
            return True
        except urllib.error.HTTPError:
            return True                       # any HTTP answer = the wire is up
        except Exception:
            continue
    return False


def public_ip():
    try:
        return urllib.request.urlopen(urllib.request.Request(
            "https://api.ipify.org", headers={"User-Agent": "curl/8"}), timeout=10).read().decode().strip()
    except Exception:
        return "unknown"


def lane_log_tail(n=60):
    p = os.path.join(DEC, "acris_repro_document.log")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except FileNotFoundError:
        return []


def lane_state():
    tail = "\n".join(lane_log_tail())
    if "SELF-PARKED" in tail or "REFUSED at" in tail:
        return "refused"
    if "DEAD TRANSPORT" in tail:
        return "dead_transport"
    return "gone"


def lane_landed():
    for l in reversed(lane_log_tail()):
        m = re.search(r"PROGRESS (\d+)m - reqs ([\d,]+).*?- ([\d,]+) pdfs", l)
        if m:
            return int(m.group(1)), int(m.group(3).replace(",", ""))
    return 0, 0


def park_entry():
    p = os.path.join(DEC, "_paused_runtime.json")
    try:
        return json.load(open(p, encoding="utf-8")).get(LANE_NAME)
    except Exception:
        return None


def set_park(value):
    p = os.path.join(DEC, "_paused_runtime.json")
    d = json.load(open(p, encoding="utf-8"))
    if value is None:
        d.pop(LANE_NAME, None)
    else:
        d[LANE_NAME] = value
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, p)


def rotate(name):
    p = os.path.join(DEC, name)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        os.replace(p, p.replace(".log", ".log." + time.strftime("%Y%m%d-%H%M"), 1))


def launch_lane():
    rotate("acris_repro_document.log")
    rotate("acris_repro_document.log.err")
    out = open(os.path.join(DEC, "acris_repro_document.log"), "w")
    err = open(os.path.join(DEC, "acris_repro_document.log.err"), "w")
    p = subprocess.Popen([PY, "-u", "acris_reproduction.py"] + LANE_ARGS, cwd=DEC,
                         stdout=out, stderr=err, creationflags=DETACHED)
    return p.pid


def launch_board(name, cwd, args):
    out = open(os.path.join(cwd, name + ".out"), "a")
    err = open(os.path.join(cwd, name + ".err"), "a")
    p = subprocess.Popen([PY, "-u"] + args, cwd=cwd, stdout=out, stderr=err, creationflags=DETACHED)
    return p.pid


BOARD = [("board_truth", UPD, ["board_truth.py", "--loop", "--every", "60"]),
         ("routine_update", UPD, ["routine_update.py", "--loop"]),
         ("follow_doc", DEC, ["follow_doc.py"])]


def main():
    log("supervisor up - lane %s, %d tries per incident, wifi outages wait" % (LANE_NAME, MAX_TRIES))
    tries, launched_at, gave_up, last_beat = 0, None, False, time.time()
    while True:
        cl = python_cmdlines()
        lane_up = running(cl, "acris_reproduction.py", "--floor document")
        if lane_up:
            if launched_at and time.time() - launched_at >= SETTLE_S:
                mins, pdfs = lane_landed()
                if pdfs > 0 and tries:
                    log("lane settled: %dm, %s pdfs - incident closed, tries reset" % (mins, format(pdfs, ",")))
                    tries = 0
                launched_at = None
        elif not gave_up:
            state = lane_state()
            entry = park_entry()
            human_park = entry is not None and not str(entry).startswith("REFUSED at")
            if human_park:
                log("lane is down and parked by a person (%s) - not mine to relaunch" % str(entry)[:60])
                gave_up = True
            elif not net_up():
                log("lane down (%s) and the network is DOWN - waiting, no attempt consumed" % state)
            elif tries >= MAX_TRIES:
                set_park("supervisor 2026-09-03: %d relaunches in a row ended in %s - stopped trying; a person decides" % (MAX_TRIES, state))
                log("GAVE UP after %d tries (last state %s) - parked with the reason" % (MAX_TRIES, state))
                gave_up = True
            else:
                tries += 1
                if entry is not None:
                    set_park(None)
                ip = public_ip()
                pid = launch_lane()
                launched_at = time.time()
                log("lane was %s -> relaunched (try %d/%d) under IP %s, pid %d" % (state, tries, MAX_TRIES, ip, pid))
                time.sleep(20)
        for name, cwd, args in BOARD:
            if not running(cl, args[0]):
                pid = launch_board(name, cwd, args)
                log("board process %s was down -> relaunched pid %d" % (name, pid))
        if time.time() - last_beat >= 600:
            mins, pdfs = lane_landed()
            log("heartbeat: lane %s (%dm, %s pdfs), tries %d, gave_up %s" % ("UP" if lane_up else "DOWN", mins, format(pdfs, ","), tries, gave_up))
            last_beat = time.time()
        time.sleep(30)


if __name__ == "__main__":
    main()
