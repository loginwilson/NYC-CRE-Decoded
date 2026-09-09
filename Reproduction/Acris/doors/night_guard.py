#!/usr/bin/env python3
# night_guard.py - THE ONE PROCESS THAT PUTS THE OTHERS BACK (login 2026-09-08 21:5x: "I'm going to leave you to it for
# the night ... You need to figure out how to get them all running and accessing without a problem").
#
# Four station supervisors, the board and the budget watchdog all have to survive a night with nobody watching.  Each of
# them already recovers from anything that happens to a DOOR; none of them recovers from anything that happens to
# ITSELF.  A supervisor that dies at 2 AM takes its whole station off the board until morning, and there is no evidence
# in the morning that it ever died.  So this checks every --every seconds that each is running, starts back any that is
# not, and writes what it did.
#
# It never starts a station whose stop file exists: `do_station.stop` (and the per-provider ones) are how a station is
# taken down ON PURPOSE, and a guard that overrides them is worse than no guard.  spend.py's halt writes exactly those
# files before it destroys anything, so a budget halt stays halted.
#
#   python night_guard.py run                 keep everything up, forever
#   python night_guard.py status              what is up right now
#   python night_guard.py run --every 120
import argparse, os, pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
PY = sys.executable
NOWIN = 0x08000000
DETACH = 0x00000008 | 0x00000200 | 0x08000000
REPO_DOC = pathlib.Path(r"C:\dev\nyc-cre-decoded\Reproduction\Acris\workflow\documentation")
REPO_UPDATE = pathlib.Path('C:\\dev\\nyc-cre-decoded\\Reproduction\\Acris\\update')
LOG = HERE / "night_guard.log"
PARENT = {}                         # pid -> parent pid, filled by running()

# --max 6 and 20 creations an hour (22:5x).  ACRIS TIGHTENS WITH CADENCE - the documented law of this source, and
# tonight proved it again: ~380 instances created in ninety minutes, and by 22:46 every fresh address on all four
# providers was answered with either the 25,103-byte refusal page or a canned stub image.  The board had been at
# 9.55 docs/s at 22:20, before the hardest churn.  A gentle cadence is not caution here, it is throughput.
# The other cap is a HOME limit, not a provider one.  Each door needs a lane process at home (~65-100 MB), and this
# workstation has about 5 GB free, so ~50 lanes is the real ceiling; doors kept past it would bill without a lane
# to earn on.  do_station also refuses to launch a lane below 900 MB free.  The PROVIDER refusing a create is the
# real limit and it costs nothing to hit; the other real limit is home memory, which do_station now checks before it
# launches each lane (login 22:0x: "Whatever the provider allows for doors get running and pulling").
# --min-rate is a REQUESTS/s gate, and request-side measures all lie in the same direction: a refused address
# answers instantly, so a dying door's request rate goes UP.  It is kept only low enough to catch a door that
# has stopped answering at all; the real judge is lane_now(), which reads DOCUMENTS ON THE DRIVE.  20 creations
# an hour so a station that loses its door can actually hunt for the next one.
# --max 3.  A door's LIFE IS SHORT: ACRIS allows a block a few hundred documents and then refuses it (the best
# door of the night did 239 in its first minute at 9.84 docs/s and took the notice about a hundred seconds in).
# So throughput is churn, not tenure, and one door per provider leaves a station idle most of every cycle -
# it hunts for ~8 minutes to hold an address for ~2.  Three lets a station try three candidates a round and
# keep producing on one while another is being replaced.  Every one of them is still destroyed the instant it
# refuses; nothing is held for the sake of holding it.
# 15 creations an hour a station, 60 across the fleet.  PRICED FROM THE PROVIDER, not from the rate card: Vultr
# reports $1.27 for 30 instances = $0.0423 each, six times the $0.0070 hourly figure (and still nothing like the
# $5.00 monthly fear).  60 tries an hour is about $2.50 an hour, which is the most this hunt is worth while only
# a minority of cloud blocks are served at all.
# 6 an hour a station - A SAMPLING RATE, NOT A HUNT.  Between 00:15 and 01:45 the four stations tried ~310 blocks
# at $0.0423 each (~$13) and landed almost no documents: ACRIS is currently refusing nearly all cloud address
# space, serving it page 1 of a document and nothing after.  Every Vultr block probed at 01:24-01:26 read 1.21 to
# 1.78 pages a document.  Meanwhile this machine's own line serves normally and produces for free.  So the
# stations keep sampling - a block's standing does come back, and two did pass at 01:12 - but at a quarter of the
# rate, about $1 an hour, while the home lane does the actual work.
# ONE DOOR A PROVIDER until all four are proven producing together (login 2026-09-09: "Get the code right first,
# and see if you can get it all working before you try adding more doors").  40 creations an hour so the cycle -
# create, run the lane, delete on a block, create again - never sits waiting for budget.
STATION_ARGS = "run --max 1 --every 40 --creations-per-hour 40 --min-rate 0 --box 9000"

# name: (match this in the command line, argv to start it, working directory, stop file that means "leave it down")
JOBS = {
    # (must contain, must NOT contain): DigitalOcean's supervisor is the one with no --provider, and matching it on
    # spacing would be a duplicate-spawn loop the moment the guard restarts it with its own argv (one space, not two).
    "station digitalocean": (("do_station.py", "--provider"),
                             [PY, "-u", str(HERE / "do_station.py")] + STATION_ARGS.split() + ["--width", "12", "--lines", "1", "--stagger", "0.6"],
                             HERE, "do_station.stop"),
    "station vultr":        ("do_station.py --provider vultr",
                             [PY, "-u", str(HERE / "do_station.py"), "--provider", "vultr"] + STATION_ARGS.split() + ["--width", "12", "--lines", "1", "--stagger", "0.6"],
                             HERE, "do_station.vultr.stop"),
    "station linode":       ("do_station.py --provider linode",
                             [PY, "-u", str(HERE / "do_station.py"), "--provider", "linode"] + STATION_ARGS.split() + ["--width", "12", "--lines", "1", "--stagger", "0.6"],
                             HERE, "do_station.linode.stop"),
    "station hetzner":      ("do_station.py --provider hetzner",
                             [PY, "-u", str(HERE / "do_station.py"), "--provider", "hetzner"] + STATION_ARGS.split() + ["--width", "12", "--lines", "1", "--stagger", "0.6"],
                             HERE, "do_station.hetzner.stop"),
    # THE BOARD LIVES IN update/, NOT documentation/.  It was only up tonight because it had been started by
    # hand from the right folder; had it died, the guard would have relaunched it where no such file exists
    # and the board would have stayed dark until morning.
    "board":                ("Acris Update.py",
                             [PY, "-u", "Acris Update.py", "run", "--every", "60"],
                             REPO_UPDATE, ""),
    # THE REAPER IS OFF.  At 08:20 it destroyed nine live instances - three Hetzner and two Vultr among them, all
    # serving real scans - because it treats any door without a ledger row as an orphan, and a door being adopted or
    # hand-tested has no row yet.  It was deleting doors that were never blocked, which is the one thing that must
    # not happen.  Orphans are handled by the stations themselves now (a fill that finds the account full adopts).
    "spend watchdog":       ("spend.py watch",
                             [PY, "-u", str(HERE / "spend.py"), "watch", "--budget", "50", "--max-alive", "24", "--every", "300"],
                             HERE, ""),
}


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def running():
    """Every python command line alive right now.  The Name filter matters: without it the query matches the very
    powershell command doing the asking, and every job looks like it is already running (13:5x, that false positive is
    why two stations were never started)."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' } | "
                          "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine + '|' + $_.ParentProcessId.ToString() }"],
                         capture_output=True, text=True, timeout=120, creationflags=NOWIN).stdout
    rows = []
    for l in out.splitlines():
        l = l.strip()
        if "|" in l:
            pid, cmd = l.split("|", 1)
            parts = cmd.rsplit("|", 1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                cmd, ppid = parts[0], parts[1].strip()
                PARENT[pid.strip()] = ppid
            rows.append((pid.strip(), cmd))
    return rows


def orphan_fills(rows, station_pids):
    """A fill runs as a CHILD of its station.  Kill the station mid-round - a restart, a crash, a budget halt - and the
    fill keeps going: it creates, probes and keeps on its own, with nobody to launch a lane on what it finds.  22:19:
    eight orphaned fills were creating at once across four accounts, which is how 55 instances came to be alive against
    4 doors, and it is what tripped the runaway ceiling.  A fill whose station is gone is killed here."""
    killed = []
    for pid, cmd in rows:
        if ("cloud_doors.py" in cmd or "do_doors.py" in cmd) and " fill" in cmd:
            ppid = PARENT.get(pid)
            if ppid and ppid not in station_pids:
                subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, creationflags=NOWIN)
                killed.append(pid)
    return killed


def check(start_missing):
    rows = running()
    station_pids = {pid for pid, cmd in rows if "do_station.py" in cmd and " run" in cmd}
    gone = orphan_fills(rows, station_pids)
    if gone:
        log("killed %d orphaned fill(s) whose station is gone: %s" % (len(gone), ", ".join(gone)))
    up, started = [], []
    for name, (needle, argv, cwd, stopfile) in JOBS.items():
        inc, exc = needle if isinstance(needle, tuple) else (needle, None)
        hit = [pid for pid, cmd in rows if inc in cmd and not (exc and exc in cmd)]
        if hit:
            up.append("%s (pid %s)" % (name, hit[0]))
            continue
        if stopfile and (HERE / stopfile).exists():
            up.append("%s DOWN ON PURPOSE (%s)" % (name, stopfile))
            continue
        if not start_missing:
            up.append("%s DOWN" % name)
            continue
        try:
            # DOORS_LIMIT is what the fill believes the account allows.  Vultr, Linode and Hetzner expose no limit
            # endpoint, so the manager used a hardcoded 10; 30 lets the fill keep asking until the PROVIDER refuses,
            # which is the only limit that is really theirs.  A refused create bills nothing.
            env = dict(os.environ, DOORS_LIMIT="30")
            p = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, creationflags=DETACH, close_fds=True, env=env)
            started.append("%s (pid %d)" % (name, p.pid))
        except Exception as e:
            log("could not start %s: %s: %s" % (name, type(e).__name__, str(e)[:90]))
    return up, started


ap = argparse.ArgumentParser(description=__doc__)
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("status")
p = sub.add_parser("run")
p.add_argument("--every", type=int, default=120)
a = ap.parse_args()

if a.cmd == "status":
    up, _ = check(False)
    for u in up:
        print(" ", u)
else:
    log("night guard up: %d jobs watched, every %ds" % (len(JOBS), a.every))
    first = True
    while True:
        up, started = check(True)
        if started:
            log("STARTED " + ", ".join(started))
        elif first:
            log("all %d up: %s" % (len(up), "; ".join(up)))
        first = False
        time.sleep(a.every)
