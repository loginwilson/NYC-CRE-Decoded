# do_station.py - STATION 2 = DigitalOcean, unattended (login 2026-09-08 12:5x: "why run 7 doors when we can run 10? ... just
# keep trying ... if it doesn't enter, you delete it, but you just keep going with the 10 max").  Every door runs at once -
# they are independent (the stop-four test) - and each cycles on its own notice.
#
#   python C:/dev/cre-office/do_station.py run [--max 10] [--width 60] [--every 60]
#   python C:/dev/cre-office/do_station.py status | stop
#
# THE LOOP, every --every seconds:
#   1. BURN: a slot whose log ends in 'run end ... REFUSED' (the notice) -> `do_doors.py burn <port>` (destroy = billing stops,
#      keeper down, ledger row out).  A slot that ended or died WITHOUT a notice (drive park, crash) is relaunched on its door.
#   2. FILL: fewer than --max kept doors -> `do_doors.py fill --until <max>` (create up to the account's limit, probe SERVED,
#      pace <= 2,500 ms, else destroyed) - the fill's own "two rounds without gain" stop just returns here; the next tick tries again.
#   3. LAUNCH: every kept door without a live slot gets one: the documentation lane, --host DigitalOcean, --slot N (N >= 2;
#      slot 1 is the ExpressVPN station's), --door socks5h://127.0.0.1:<port>, the sprint band.  A door keeps its slot number.
# State: do_station.json (port -> slot, launched_at, pid), do_station.log.  Never touches a --host ExpressVPN process.
import argparse, json, os, pathlib, re, subprocess, sys, time
import requests

HERE = pathlib.Path(__file__).resolve().parent
NOWIN = 0x08000000          # CREATE_NO_WINDOW: a helper (powershell, do_doors.py) never pops a console on login's screen
PY = sys.executable
DOC = pathlib.Path(r"C:\dev\nyc-cre-decoded\Reproduction\Acris\workflow\documentation")
# ONE SUPERVISOR PER PROVIDER (login 14:3x: "2 more stations doing cloud ... 36 maybe"): --provider digitalocean|vultr|linode
# (pre-scanned from argv so the file names are right before anything runs).  DigitalOcean keeps do_doors.py and its files;
# the others run cloud_doors.py (derived, provider-generic) with DOORS_PROVIDER set, their own ledger/state/log/stop, their own
# station name on the board and their own slot range (slots key the lane's lock/log files, so ranges never overlap).
PROVIDER = os.environ.get("DOORS_PROVIDER", "digitalocean").lower()
if "--provider" in sys.argv:
    PROVIDER = sys.argv[sys.argv.index("--provider") + 1].lower()
_P = {"digitalocean": ("cloud_doors.json", "do_station", "DigitalOcean", "do_doors.py", "do_doors.log", 2),
      "vultr":        ("cloud_doors.vultr.json", "do_station.vultr", "Vultr", "cloud_doors.py", "cloud_doors.vultr.log", 20),
      "linode":       ("cloud_doors.linode.json", "do_station.linode", "Linode", "cloud_doors.py", "cloud_doors.linode.log", 40),
      "hetzner":      ("cloud_doors.hetzner.json", "do_station.hetzner", "Hetzner", "cloud_doors.py", "cloud_doors.hetzner.log", 60)}
# Each station owns a SLOT RANGE (2, 20, 40, 60) because every lane's lock, control and log file lives in ONE directory
# beside the lane: two stations sharing a slot number would share documentation.<n>.lock and one would refuse to start.
if PROVIDER not in _P:
    raise SystemExit("--provider must be one of %s" % ", ".join(_P))
_ledger, _base, STATION, MANAGER, MANAGER_LOG, SLOT_BASE = _P[PROVIDER]
LEDGER = HERE / _ledger
STATE = HERE / (_base + ".json")
LOG = HERE / (_base + ".log")
STOP = HERE / (_base + ".stop")
MANAGER_ENV = dict(os.environ, DOORS_PROVIDER=PROVIDER)
# --trust-registry-pages: THE VIEWER PAGE IS HOW ACRIS REFUSES A CLOUD BLOCK.  01:20, every failure in every lane
# read "HTTP 404 at .../DocumentImageView" while the same doors' probes were pulling 2.8-3.7 REAL PAGES a document:
# ACRIS 404s the viewer for a refused block and keeps serving GetImage.  The lane needed the viewer only for the
# page count, and registration already recorded it, so the count comes from the registry and the viewer URL stays
# on as a Referer header - which is all GetImage ever wanted (verified from home 00:59: pages fetched with no
# preceding viewer request returned real scans, 69,058 / 40,636 / 83,828 bytes).  It also saves one request per
# document, 10-25% of a block's allowance.  A row with no recorded count still falls back to the viewer.
BAND = ["--trust-registry-pages", "--pooler", "transaction", "--entry-gap", "8", "--pending-age", "1 day", "--stagger", "5", "--drive", "OneTouch",
        "--fresh-days", "30", "--unpark", "--manage", "1", "--ramp-to-rate", "1", "--adjust-every", "60", "--adjust-step", "5",
        "--rate-floor", "6", "--rate-ideal-lo", "7", "--rate-ideal-hi", "10", "--dps-ceiling", "20", "--rps-ceiling", "0",
        "--session-max-requests", "1000000"]


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def state_read():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def state_write(s):
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def ledger():
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else []


def live_slots():
    """{slot: (pid, port)} for this station's lane processes (never the ExpressVPN station's)."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*Acris Documentation.py*'"
          " -and $_.CommandLine -like '*--host %s*' } | ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }" % STATION)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, creationflags=NOWIN, text=True, timeout=90)
    out = {}
    for l in r.stdout.splitlines():
        # the FIRST --door is the door's own port (its lines follow on port+1000, +2000): a greedy match took the last
        # one and every three-line lane read as "gone" - launched twice over (13:59, 18 processes on 9 doors)
        m = re.match(r"(\d+) .*?--slot (\d+) .*?--door socks5h://127\.0\.0\.1:(\d+)", l)
        if m:
            out[int(m.group(2))] = (int(m.group(1)), int(m.group(3)))
    return out


def doors_cmd(*args, timeout=1500):
    r = subprocess.run([PY, str(HERE / MANAGER), *args], capture_output=True, creationflags=NOWIN, text=True, timeout=timeout, cwd=str(HERE), env=MANAGER_ENV)
    return (r.stdout + r.stderr).strip()


def creations_last_hour():
    """Droplets created in the last 60 minutes, from do_doors.log ('fill created' / 'replace' lines carry the timestamp)."""
    p = HERE / MANAGER_LOG
    if not p.exists():
        return 0
    cutoff = time.time() - 3600
    n = 0
    for l in p.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]:
        if " created " in l:
            try:
                t = time.mktime(time.strptime(l[:19], "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                continue
            if t >= cutoff:
                n += 1
    return n


def lane_parked(slot):
    """True when the lane has parked itself: it writes documentation.<slot>.parked and then keeps its process alive,
    which is exactly how a blocked door went untracked for twenty minutes at 23:38."""
    return (DOC / ("documentation.%d.parked" % slot)).exists()


def log_verdict(slot, since):
    """('spent'|'ended'|None, line): the slot's log's last 'run end' written after `since` (an HH:MM:SS prefix, same day)."""
    p = DOC / ("documentation.%d.log" % slot)
    if not p.exists():
        return None, ""
    last = None
    for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if "run end" in l and l[:8] >= since:
            last = l
    if not last:
        return None, ""
    # CASE-INSENSITIVE, AND EVERY WORD THE LANE ACTUALLY USES FOR A BLOCK.  23:38 - the lane wrote
    #   run end 25.6 min - PARKED: 4 re-entries in a row refused (documentation@door1)
    # and this test asked for "REFUSED" in capitals, so a plainly blocked door read as "ended normally" and was
    # RELAUNCHED onto the dead address instead of being destroyed and replaced.  The whole cycle turns on this line.
    low = last.lower()
    spent = any(w in low for w in ("refused", "bandwidth", "parked", "the wall", "notice", "blocked"))
    return ("spent" if spent else "ended"), last[:150]


def slot_rate(slot):
    """(requests/s over the slot's last two PROGRESS intervals - the lower of the two - and its width), or (None, 0)."""
    p = DOC / ("documentation.%d.log" % slot)
    if not p.exists():
        return None, 0
    rows = []
    for l in p.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]:
        m = re.match(r"^(\d\d):(\d\d):(\d\d)\s+PROGRESS .*?reqs ([\d,]+) .*?width (\d+)/", l)
        if m:
            rows.append((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), int(m.group(4).replace(",", "")), int(m.group(5))))
    if len(rows) < 3:
        return None, 0
    (t0, r0, _), (t1, r1, _), (t2, r2, w) = rows[-3:]
    if t2 < t0:                                            # a midnight wrap: skip this reading
        return None, 0
    return min((r1 - r0) / max(1, t1 - t0), (r2 - r1) / max(1, t2 - t1)), w


def box_rate(port):
    """THE DOOR'S OWN RATE, read off its box (requests/s over the manager's last window, and its requests in flight),
    or (None, 0).  This is the true measure and the lane's log is not: with --box the lane makes ONE call per document,
    so its PROGRESS "reqs" counts documents, not the requests ACRIS actually served.

    WHY THIS DECIDES A DOOR'S WORTH (measured 2026-09-08 17:18, ten doors all AT their gate cap, so none was starved):
    ACRIS served them at 14, 28, 42, 51, 56, 60, 68, 70, 77 and 81 seconds a request - an 8x spread, address by
    address.  Nine of the ten were being served four to six times slower than the best.  Piling more requests into a
    throttled door only lengthens its queue; the only cure is a different address.  Had every door matched the best
    one, the same ten would have carried 323 requests/s instead of 118.  The probe's idle pace does NOT predict this
    (1088 probed at 1.8 s and delivered 56 s under load), so the rate must be read under load, here."""
    prx = {"http": "socks5h://127.0.0.1:%d" % port, "https": "socks5h://127.0.0.1:%d" % port}
    try:
        s = requests.get("http://127.0.0.1:%d/stats" % BOX_PORT, proxies=prx, timeout=20).json()
    except Exception:
        return None, 0, 0
    notice = int(s.get("notice", 0) or 0)
    for line in reversed(s.get("manager") or []):
        if "MANAGER " in line:
            try:
                raw = float(line.split("MANAGER ")[1].split(" req/s")[0])
            except (ValueError, IndexError):
                return None, 0, notice
            # COUNT WHAT WAS SERVED, NOT WHAT WAS ASKED.  A refusal returns in milliseconds, so an address ACRIS has
            # started refusing reads FASTER than a healthy one: fsn1 read 195.4 req/s at 96.1% errors while it was
            # dying.  The gate must see 7.6, not 195.4.
            bad = 0.0
            m = re.search(r"([\d.]+)% errors", line)
            if m:
                bad = min(100.0, float(m.group(1))) / 100.0
            return raw * (1.0 - bad), int(s.get("inflight", 0)), notice
    return None, int(s.get("inflight", 0)), notice


MEM_FLOOR_MB = 900      # a lane is ~65 MB at 60 workers and grows with the band; below this, launching another one
                        # only makes every lane slower.  THE MEMORY IS THE CAP, not a door count (22:0x).


def free_mb():
    """Free physical memory in MB, or None if it cannot be read (in which case nothing is held back)."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
                             capture_output=True, text=True, timeout=60, creationflags=NOWIN).stdout.strip()
        return int(float(out)) // 1024
    except Exception:
        return None


def lane_now(slot, since="00:00:00"):
    """(documents/s, failure share, requests) off a PROGRESS line THIS RUN wrote, or (None, 0, 0).

    THE ONLY TEST A DEAD DOOR CANNOT PASS.  A refused address does not always park and does not always write a run
    end: at 23:59 one was making 306 requests a second, failing 137,525 of 371,667, and landing 0.10 documents a
    second, while every other signal read "running"."""
    p = DOC / ("documentation.%d.log" % slot)
    if not p.exists():
        return None, 0.0, 0
    try:
        tail = p.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    except OSError:
        return None, 0.0, 0
    for l in reversed(tail):
        if "PROGRESS" not in l or l[:8] < since:
            continue                       # the previous run's line, on the previous door - not this door's verdict
        d = re.search(r"([\d.]+) docs/s", l)
        r = re.search(r"reqs ([\d,]+)", l)
        f = re.search(r"fail ([\d,]+)", l)
        if not (d and r):
            continue
        reqs = int(r.group(1).replace(",", ""))
        fails = int(f.group(1).replace(",", "")) if f else 0
        return float(d.group(1)), (fails / reqs if reqs else 0.0), reqs
    return None, 0.0, 0


def lane_landed(slot, since="00:00:00"):
    """(pdfs landed, requests made) off PROGRESS lines THIS RUN wrote - one per crew, summed.

    THE ONLY MEASURE THAT MATTERS.  A door's request rate can be superb while it lands nothing: ACRIS answers a refused
    address with a constant stub image (HTTP 200, image/tiff, the same 13,684 bytes for every page of every document),
    which the box scores as served and the lane rejects as short.  22:37 - 266.9 served requests a second across the
    fleet, 0.35 documents a second onto the drive."""
    p = DOC / ("documentation.%d.log" % slot)
    if not p.exists():
        return None, 0
    try:
        tail = p.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
    except OSError:
        return None, 0
    seen, pdfs, reqs = set(), 0, 0
    for l in reversed(tail):
        if "PROGRESS" not in l or l[:8] < since:
            continue                       # the previous run's line, on the previous door - not this door's verdict
        m = re.search(r"documentation@(\S+) - reqs ([\d,]+).*?- ([\d,]+) pdfs", l)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        reqs += int(m.group(2).replace(",", ""))
        pdfs += int(m.group(3).replace(",", ""))
    return (pdfs if seen else None), reqs


def kill_pid(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=NOWIN)


def launch(slot, port, width, lines=1, box=0):
    """One lane process for the door: `lines` crews, one per tunnel (ports port, port+1000, ...), `width` workers in all."""
    for name in ("documentation.%d.lock" % slot, "documentation.%d.control" % slot,
                 "documentation.%d.parked" % slot):
        try:
            (DOC / name).unlink()
        except FileNotFoundError:
            pass
    # THE PREVIOUS RUN'S LOG IS MOVED ASIDE, NOT APPENDED TO.  Every gate that judges a door reads this file, and the
    # only thing separating this run's lines from the last one's was an HH:MM:SS string compare with no date - which
    # inverts at midnight, so from 00:00 the gates read ONLY the previous run and burned every fresh door on the
    # strength of a corpse (00:26:48, a door destroyed by a "PARKED" line written at 23:38 the night before).  With
    # the file moved aside there is no previous run to confuse: the log holds this lane's lines from its first breath.
    cur = DOC / ("documentation.%d.log" % slot)
    if cur.exists():
        try:
            prev = DOC / ("documentation.%d.prev.log" % slot)
            if prev.exists():
                prev.unlink()
            cur.rename(prev)
        except OSError:
            try:
                cur.write_text("", encoding="utf-8")
            except OSError:
                pass
    per = max(20, width // max(1, lines))                  # width is per crew in the lane
    doors = []
    for j in range(max(1, lines)):
        doors += ["--door", "socks5h://127.0.0.1:%d" % (port + 1000 * j)]
    band = list(BAND)
    if STAGGER is not None and "--stagger" in band:      # the station's own stagger wins over the band's default
        band[band.index("--stagger") + 1] = str(STAGGER)
    args = [PY, "-u", "Acris Documentation.py", "--width", str(per), "--host", STATION, "--slot", str(slot),
            "--log", "documentation.%d.log" % slot, "--width-min", "20", "--width-max", str(per)] + band + doors
    if box:
        args += ["--box", str(box)]                         # the on-box fetch (2026-09-08): box_fetch.py on the droplet, through each door
    out = open(HERE / ("sprint.%d.out" % slot), "a", encoding="utf-8")
    err = open(HERE / ("sprint.%d.err" % slot), "a", encoding="utf-8")
    flags = 0x00000008 | 0x00000200 | 0x08000000
    p = subprocess.Popen(args, cwd=str(DOC), stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    return p.pid


BOX_PORT = 9000                    # the port box_fetch.py listens on; set from --box at startup
STAGGER = None                     # seconds between worker births; None = the band's 5.  With --box a worker connects
                                   # to the DROPLET, not to ACRIS, so the 5 s that once kept ACRIS from seeing a
                                   # handshake burst now only costs a 150-wide lane 12.5 minutes to reach its width.
RAMPED_S = 360                     # a box-path door is judged six minutes in: its gate is full by then


SHUT = {"at": 0.0, "closed": False, "said": False}
SHUT_TTL = 90.0


def site_closed():
    """Is ACRIS shut to EVERY client right now?  Asked for free from this machine (do_doors.py `reference` follows the
    307 chain; no droplet, no allowance).  Cached SHUT_TTL seconds.

    Why this gates the WHOLE tick and not just the fill: during a maintenance window ACRIS serves its bandwidth page
    from a redirect loop, so a lane that is already running reads it as ITS OWN door's notice and parks.  The supervisor
    then sees 'run end REFUSED' and destroys a door that was never spent.  That is precisely what happened at 17:48 -
    nine good doors gone inside 29 seconds - so while the service is shut nothing is burned, relaunched, recycled or
    created, and every slot's verdict clock is re-stamped when it reopens."""
    if time.time() - SHUT["at"] < SHUT_TTL:
        return SHUT["closed"]
    try:
        out = doors_cmd("reference", timeout=240) or ""
    except Exception as e:
        out = ""
        log("the reference check itself failed (%s: %s) - holding" % (type(e).__name__, str(e)[:70]))
    flat = " ".join(out.split())                # one line, no CR, no runs of spaces: the only form we ever match against
    # FAIL CLOSED, ON SUBSTANCE RATHER THAN SHAPE.  Only an explicit all-clear lifts the hold - a check that timed out,
    # crashed or answered nothing is NOT evidence the site is serving (19:56:41: a silent reference lifted the hold three
    # seconds before the fill reported the site still shut).  But any ONE of three independent all-clears is enough, and
    # the match is a plain substring on flattened text: on 21:26-21:39 an anchored regex carrying an invisible backspace
    # byte held all four stations through thirteen minutes of a plainly open ACRIS.
    live = ("service LIVE" in flat) or ("reference SERVING" in flat) or ("- SERVED" in flat)
    closed = ("MAINTENANCE" in flat) or not live
    if closed and "MAINTENANCE" not in flat:
        log("the reference check gave no clear answer (%s) - holding, because a silent check is not an all-clear"
            % (flat[:120] or "no output"))
    SHUT.update(at=time.time(), closed=closed)
    return closed


def box_ready(a, port, ip):
    """With --box: the droplet's box_fetch.py must answer /stats through this door before a lane is launched on it; a silent
    box is deployed by do_doors.py `box <ip>` (idempotent).  Returns True when it answers."""
    if not a.box:
        return True
    url = "http://127.0.0.1:%d/stats" % a.box
    prx = {"http": "socks5h://127.0.0.1:%d" % port, "https": "socks5h://127.0.0.1:%d" % port}
    for attempt in (1, 2):
        try:
            r = requests.get(url, proxies=prx, timeout=15)
            if r.status_code == 200 and '"limit"' in r.text:
                return True
        except requests.RequestException:
            pass
        if attempt == 1:
            out = doors_cmd("box", ip, timeout=180)
            log("box_fetch on %s (door %d): %s" % (ip, port, " | ".join(l.strip() for l in out.splitlines() if "box_fetch" in l)[:160] or out.strip()[-160:]))
    log("box_fetch on %s (door %d) does not answer through the door - launching WITHOUT --box" % (ip, port))
    return False




def launch_missing(a, st):
    """Give every kept door without a live lane its slot.  Called BEFORE the fill (doors that were waiting on
    memory, or whose lane was killed with a burn) and AGAIN right after it, because a door found by the fill is
    idle until its lane starts and an address only lives twenty to thirty minutes before ACRIS refuses it."""
    # 2. LAUNCH a slot for every kept door without one - BEFORE the fill (a fill round takes minutes; 14:02 the
    #    lanes waited behind a probe) - after making sure each door has its lines (tunnels) up
    kept = ledger()                                           # RE-READ after the burns of step 1 (14:55 race: a door burned on
    by_port = {row["port"]: row for row in kept}              # its notice was still in the top-of-tick `kept`, so LAUNCH put a
    for port_s in list(st):                                   # lane back on the destroyed droplet). Drop state for burned doors.
        if int(port_s) not in by_port:
            st.pop(port_s, None)
    state_write(st)
    if a.lines > 1:
        out = doors_cmd("lines", "--lines", str(a.lines), timeout=900)
        for l in out.splitlines():
            if "line" in l and ("-> up" in l or "NOT LISTENING" in l):
                log("lines: " + l.strip()[:120])
    live = live_slots()
    used = {rec["slot"] for rec in st.values()} | set(live.keys()) | {1}
    for row in kept:
        port = row["port"]
        if str(port) in st and st[str(port)]["slot"] in live:
            continue
        if port in {p for _, p in live.values()}:
            continue
        free = free_mb()
        if free is not None and free < MEM_FLOOR_MB:
            log("holding: %d MB free, under the %d MB a new lane needs - door %d stays kept, its lane starts when memory frees"
                % (free, MEM_FLOOR_MB, port))
            break
        slot = SLOT_BASE
        while slot in used:
            slot += 1
        used.add(slot)
        pid = launch(slot, port, a.width, a.lines, a.box if box_ready(a, port, row["ip"]) else 0)
        st[str(port)] = {"slot": slot, "ip": row["ip"], "pid": pid, "launched_at": time.strftime("%H:%M:%S"), "relaunches": 0}
        state_write(st)
        log("slot %d launched on door %d (%s, pace %s ms), pid %d" % (slot, port, row["ip"], row.get("pace_ms", "-"), pid))
        time.sleep(3)

    return st


def tick(a, st):
    if site_closed():
        if not SHUT["said"]:
            SHUT["said"] = True
            log("HOLD: ACRIS is shut to every client - nothing burned, recycled, relaunched or created until it reopens")
        return
    if SHUT["said"]:
        SHUT["said"] = False
        now = time.strftime("%H:%M:%S")
        for rec in st.values():                                # a refusal written during the outage is not a verdict
            rec["launched_at"] = now
            rec["relaunches"] = 0
        state_write(st)
        log("ACRIS is answering again - the hold is lifted, %d slot(s) re-stamped, nothing was burned for the outage" % len(st))
    kept = ledger()
    by_port = {row["port"]: row for row in kept}
    live = live_slots()
    live_ports = {port for _, port in live.values()}
    # 1. BURN / RELAUNCH: known slots (state) whose process is gone
    for port_s, rec in list(st.items()):
        port, slot = int(port_s), rec["slot"]
        verdict, line = log_verdict(slot, rec.get("launched_at", "00:00:00"))
        alive = slot in live and live[slot][1] == port
        if alive and verdict != "spent" and not lane_parked(slot):
            continue                                                   # running and not blocked
        if alive:
            # A PARKED LANE IS A BLOCKED DOOR WITH A LIVE PROCESS.  Parking stops the work, not the process, so this
            # slot would otherwise read as "running" for ever while its address serves nobody and its droplet bills.
            log("slot %d door %d: the lane is parked/blocked while still running - killing it and burning the door. %s"
                % (slot, port, line or "parked marker"))
            kill_pid(live[slot][0])
            verdict = "spent"
        if verdict == "spent":
            log("slot %d door %d (%s): the notice - burning. %s" % (slot, port, by_port.get(port, {}).get("ip", "?"), line))
            out = doors_cmd("burn", str(port), timeout=300)
            log("burn: " + " | ".join(l.strip() for l in out.splitlines() if "burnt" in l or "no such" in l)[:200])
            st.pop(port_s, None); state_write(st)
        elif port in by_port:
            rec["relaunches"] = rec.get("relaunches", 0) + 1
            if rec["relaunches"] > 3:
                log("slot %d door %d: relaunched 3 times without a notice - burning the door as unusable" % (slot, port))
                doors_cmd("burn", str(port), timeout=300); st.pop(port_s, None); state_write(st); continue
            pid = launch(slot, port, a.width, a.lines, a.box if box_ready(a, port, by_port[port]["ip"]) else 0)
            rec.update(pid=pid, launched_at=time.strftime("%H:%M:%S")); state_write(st)
            log("slot %d door %d (%s): ended without a notice (%s) - relaunched, pid %d" % (slot, port, by_port[port]["ip"], line or "no run end line", pid))
        else:
            st.pop(port_s, None); state_write(st)                          # the door is gone from the ledger (burnt by hand)
    # 1c. THE SECOND GATE (login 2026-09-08: "not only do we keep doors that enter, but they must be reasonably decent
    #     doors themselves").  A door passes TWO gates, not one.  ENTRY: the probe - created, asked once, kept only if
    #     ACRIS serves it.  WORTH: its rate READ UNDER LOAD off its own box - below --min-rate requests/s it is destroyed
    #     and replaced exactly like a burned one.  The second gate is not a refinement, it is most of the throughput:
    #     measured 17:18 with all ten doors AT their gate limit (none starved), ACRIS served them at 14, 28, 42, 51, 56,
    #     60, 68, 70, 77 and 81 seconds a request - eight-fold, address by address - so ten doors carried 118 requests/s
    #     where ten of the best would have carried 323.  The probe cannot see it (an address that probed at 1.8 s
    #     delivered 56 s under load) and more workers cannot cure it: a throttled address only grows a longer queue.
    if a.min_rate > 0 and a.creations_per_hour - creations_last_hour() >= 3:
        live = live_slots()
        now_s = time.strftime("%H:%M:%S")
        for port_s, rec in list(st.items()):
            port, slot = int(port_s), rec["slot"]
            if slot not in live or live[slot][1] != port or port not in by_port:
                continue
            la = rec.get("launched_at", now_s)
            age = (int(now_s[:2]) * 3600 + int(now_s[3:5]) * 60 + int(now_s[6:8])) - (int(la[:2]) * 3600 + int(la[3:5]) * 60 + int(la[6:8]))
            rate = w = notice = None
            if a.box:
                rate, w, notice = box_rate(port)            # the SERVED rate off the box; w is its requests in flight
            # THE NOTICE IS NOT SUBJECT TO THE RAMP CLOCK.  A rate needs a ramped lane before it means anything; a
            # refusal means the same thing one minute in as ten, and a door carrying one earns nothing for as long as
            # it keeps its port.  So this is asked BEFORE the age test (22:17: two doors sat on notices through several
            # ticks because the burn was behind a six-minute clock that every station restart re-stamped).
            if notice:
                # THE NOTICE IS THE VERDICT: the box saw ACRIS refuse this address.  The lane is killed with it, because a
                # lane on a refused door only re-enters and re-enters.
                log("slot %d door %d (%s): its box has seen the notice - burning now, not waiting for the gate"
                    % (slot, port, by_port[port]["ip"]))
                kill_pid(live[slot][0])
                doors_cmd("burn", str(port), timeout=300)
                st.pop(port_s, None)
                state_write(st)
                continue
            # LANDED NOTHING?  Then it is not a door, whatever its request rate says - and this is asked BEFORE the ramp
            # clock, because a healthy lane lands its first document inside a minute while a stubbing one can burn
            # 25,000 requests waiting for a six-minute verdict.  A refused address is answered with a constant stub
            # image that scores as a success on the box and is rejected at home as short, so the question goes to the
            # LANE, the only thing that knows a document reached the drive.
            # ONLY A BLOCK BURNS A DOOR (login 2026-09-09: "you only delete when you get blocked").  Everything that
            # stood here judged a door by its RATE - under 0.5 docs/s, or 1,500 requests with nothing landed, or
            # under --min-rate requests a second - and each of them burned doors that were still producing, leaving
            # an empty slot that produced nothing at all.  ACRIS says plainly when a block is spent: the lane writes
            # REFUSED with its Bandwidth Notice, and the door's own box sees the same notice.  Both are handled
            # above, and they are now the only two ways a door dies.  A slow door keeps its slot.
            continue
    st = launch_missing(a, st)

    # 3. FILL to the maximum - within the creation budget (DigitalOcean bills every droplet a minimum of ONE HOUR, ~$0.006:
    #    a refused block costs the same as an hour of a serving door, and three of four fresh blocks were refused today)
    kept = ledger()
    if len(kept) < a.max:
        made = creations_last_hour()
        left = a.creations_per_hour - made
        if left <= 0:
            log("%d of %d doors kept - %d created in the last hour, budget %d/h spent; waiting" % (len(kept), a.max, made, a.creations_per_hour))
        else:
            n = max(1, min(3, a.max - len(kept), left))    # THREE at a time (22:2x).  Judged together the round is ~2 min, and
                                                          # three in flight per station bounds the pile at twelve across the fleet -
            log("%d of %d doors kept - filling: one round of %d (%d of %d/h used)" % (len(kept), a.max, n, made, a.creations_per_hour))
            out = doors_cmd("fill", "--until", str(a.max), "--count", str(n), "--rounds", "1", timeout=1500)
            for l in out.splitlines():
                if l.startswith(("KEPT", "BURNT")) or "two rounds" in l or "no free slot" in l or "round limit" in l:
                    log("fill: " + l.strip()[:170])
                # THE ESCALATION GUARD (do_doors.py): fresh blocks refused at their first request are the standing,
                # not spent doors - the manager rests and creates nothing until it is over (2026-09-08 17:47-18:1x)
                if "RESTING" in l or "THE WALL" in l or "CLOSED TO EVERYONE" in l:
                    log("guard: " + l.strip()[:170])
            if "no free slot" in out:
                # 13:39: the account's ten were full while the ledger held eight - probe droplets left behind by an
                # interrupted fill.  `adopt` probes every untracked droplet: kept if it serves at pace, else destroyed.
                log("the account is full but the ledger is not - adopting the untracked droplets")
                out = doors_cmd("adopt", timeout=900)
                for l in out.splitlines():
                    if l.startswith(("KEPT", "BURNT")):
                        log("adopt: " + l.strip()[:170])
        kept = ledger()

    st = launch_missing(a, st)      # the door the fill just found starts earning now, not next tick

def cmd_run(a):
    if STOP.exists():
        STOP.unlink()
    st = state_read()
    # adopt the slots already running (launched by slots_lane.ps1): port -> slot from their command lines
    # 13:06 BUG: adopted slots were given launched_at 00:00:00, so a 'run end REFUSED' line from an EARLIER door on the same
    # slot number counted as this door's notice and two good doors were destroyed.  An adopted slot's clock starts NOW: only
    # a run end written from here on is its verdict.
    for slot, (pid, port) in live_slots().items():
        st.setdefault(str(port), {"slot": slot, "pid": pid, "launched_at": time.strftime("%H:%M:%S"), "relaunches": 0})
    state_write(st)
    log("station 2 = %s: max %d doors, width %d, every %ds; %d slots adopted" % (STATION, a.max, a.width, a.every, len(st)))
    while not STOP.exists():
        try:
            tick(a, st)
        except Exception as e:
            log("tick failed: %s: %s" % (type(e).__name__, str(e)[:200]))
        for _ in range(a.every):
            if STOP.exists():
                break
            time.sleep(1)
    log("station 2: stopped by the stop file (the lanes keep running)")


def cmd_status(a):
    st = state_read(); live = live_slots(); kept = ledger()
    print("kept doors: %d   live slots: %d   %s" % (len(kept), len(live), sorted(live.keys())))
    for row in kept:
        rec = st.get(str(row["port"]), {})
        s = rec.get("slot")
        print("  port %d  %-14s %-16s pace %-6s slot %s %s" % (row["port"], row["name"], row["ip"], row.get("pace_ms", "-"), s or "-",
                                                             "running" if s in live else "NO SLOT"))


def cmd_stop(a):
    STOP.write_text("stop", encoding="utf-8")
    print("stop requested - the supervisor exits at its next tick; the lanes keep running")


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--provider", default=PROVIDER, choices=sorted(_P), help="the station: digitalocean (do_doors.py) | vultr | linode (cloud_doors.py)")
sub = ap.add_subparsers(dest="cmd", required=True)
p = sub.add_parser("run"); p.add_argument("--max", type=int, default=10); p.add_argument("--width", type=int, default=60)
p.add_argument("--every", type=int, default=60)
p.add_argument("--creations-per-hour", type=int, default=10, help="the churn budget: droplets created per hour (each ~$0.006, a one-hour minimum); 10/h = ~$1.40/day")
p.add_argument("--min-rate", type=float, default=20.0, help="requests/s a door must reach at full width (12 min after launch) or be recycled; 0 = never recycle")
p.add_argument("--box", type=int, default=0, help="the on-box fetch: launch every lane with --box PORT (box_fetch.py on each droplet, deployed by do_doors.py box); 0 = the tunnel fetch")
p.add_argument("--stagger", type=float, default=None, help="seconds between worker births in this station's lanes (default: the band's 5). On the box path a worker connects to the DROPLET, not to ACRIS, so a smaller number reaches the door's real rate minutes sooner")
p.add_argument("--lines", type=int, default=3, help="tunnels per door (one TCP connection each; the lane runs one crew per line); --width is the door's total")
p.set_defaults(f=cmd_run)
sub.add_parser("status").set_defaults(f=cmd_status)
sub.add_parser("stop").set_defaults(f=cmd_stop)
a = ap.parse_args()
if getattr(a, 'box', 0):
    BOX_PORT = a.box
STAGGER = getattr(a, 'stagger', None)   # only the run parser defines it; status/stop must not crash on it
a.f(a)
