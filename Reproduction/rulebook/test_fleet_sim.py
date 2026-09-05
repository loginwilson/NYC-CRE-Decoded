"""SIMULATION of the fleet (Acris Reproduction.py) over FAKE lane programs - no ACRIS request, no cloud write.
A temp workflow dir holds three fake `Acris <Lane>.py` files that behave like lanes: they take the lane's
arguments, take their own lock, write a log, honour `stop` in their control file, and exit with the code a plan
file tells them to (per launch number), writing a parked file where a real lane would.

  run 1   the whole cycle launched in order with the gap; all three exit 0 (limit) -> fleet done, exit 0
  run 2   registration crashes (5) twice then runs clean; the fleet relaunches after --relaunch-wait; the cap parks a
          lane that keeps crashing (documentation crashes every time -> parked by the fleet after the cap)
  run 3   synchronization is REFUSED (2) -> the others get `stop`, the fleet exits 2; a parked lane is not relaunched
  run 4   documentation loses its drive (6) -> the fleet waits for the drive (find_drive fails twice) and relaunches with --unpark
  run 5   a lane already running by hand (its lock held) is refused (1) and left alone
  run 6   --mega: one child with --also for the others; `stop` reaches it through the control file
  plus    stop / width / status commands against the fake lanes
"""
import importlib.util, json, os, pathlib, subprocess, sys, textwrap, threading, time, types
PHASE = pathlib.Path(__file__).resolve().parents[1]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
SRC = os.environ.get("FLEET_SOURCE", "Acris")
sys.path.insert(0, os.path.join(str(PHASE), SRC, "rulebook"))
import lane, storage
spec = importlib.util.spec_from_file_location(SRC.lower() + "_reproduction", str(PHASE / "%s" / "workflow" / "reproduction" / "%s Reproduction.py") % (SRC, SRC))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

SIM = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simfleet")
WF = SIM / "workflow"
FAKE = textwrap.dedent('''
    """a fake lane: behaves like a lane's edges - lock, log, control file, parked file, exit code from the plan"""
    import argparse, json, os, pathlib, sys, time
    HERE = pathlib.Path(__file__).resolve().parent
    NAME = HERE.name
    ap = argparse.ArgumentParser()
    for a in ("--width", "--host", "--stagger", "--entry-gap", "--pending-age", "--redial-wait", "--tries", "--limit", "--drive", "--fresh-days", "--edge", "--claim", "--ttl", "--log"):
        ap.add_argument(a, default="")
    ap.add_argument("--also", action="append", default=[])
    ap.add_argument("--unpark", action="store_true")
    args, _ = ap.parse_known_args()          # the site's manager knobs (--manage, --rps-ceiling, ...) pass through: a fake lane has no manager
    parked = HERE / (NAME + ".parked")
    if parked.exists() and not args.unpark:
        print("this lane is PARKED: " + parked.read_text().strip()); sys.exit(1)
    if parked.exists():
        parked.unlink()
    lock = HERE / (NAME + ".lock")
    if lock.exists():
        try:
            pid = int(lock.read_text().strip() or "0")
        except ValueError:
            pid = 0
        if pid and pid != os.getpid():
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                print("REFUSING TO START: %s is already running as pid %d" % (NAME, pid)); sys.exit(1)
    lock.write_text(str(os.getpid()))
    plan = json.loads((HERE / "plan.json").read_text()) if (HERE / "plan.json").exists() else {}
    n_path = HERE / "launches.json"
    launches = json.loads(n_path.read_text()) if n_path.exists() else []
    launches.append({"at": time.time(), "argv": sys.argv[1:]})
    n_path.write_text(json.dumps(launches))
    step = plan.get(str(len(launches)), plan.get("default", {"rc": 0, "after": 1}))
    print("%s up: width %s host %s also %s unpark %s -> plan %s" % (NAME, args.width, args.host, args.also, args.unpark, step), flush=True)
    ctl = HERE / (NAME + ".control")
    end = time.time() + float(step.get("after", 1))
    rc = int(step.get("rc", 0))
    while time.time() < end:
        if ctl.exists() and "stop" in ctl.read_text():
            ctl.write_text(""); print("stopped by control", flush=True); rc = 0; break
        time.sleep(0.2)
    if rc in (4, 6):
        parked.write_text("parked by the lane: code %d" % rc)
    if rc == 2:
        parked.write_text("REFUSED (simulated notice page)")
    print("leaving with %d" % rc, flush=True)
    try:
        lock.unlink()
    except OSError:
        pass
    sys.exit(rc)
''')


def fresh_workflow():
    import shutil
    if SIM.exists():
        shutil.rmtree(SIM)
    for n in R.LANES:
        d = WF / n
        d.mkdir(parents=True)
        (d / ("%s %s.py" % (R.SOURCE, n.capitalize()))).write_text(FAKE, encoding="utf-8")
    (WF / "reproduction").mkdir()
    R.WORKFLOW = WF
    R.HERE = WF / "reproduction"


def plan(name, p):
    (WF / name / "plan.json").write_text(json.dumps(p))


def launches(name):
    p = WF / name / "launches.json"
    return json.loads(p.read_text()) if p.exists() else []


def args(**kw):
    base = dict(command="run", target="", lanes="", mega=False, drive="SIMDRIVE", fresh_days=30, edge=0, entry_gap=1,
                stagger=0.01, pending_age="1 hour", redial_wait=1, tries=3, limit=0, unpark=False, relaunch_wait=1,
                relaunch_cap=2, stop_wait=5, within="10 minutes", host="SIM-HOST")
    base.update(kw)
    return types.SimpleNamespace(**base)


fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)


def fleet_log():
    p = WF / "reproduction" / "reproduction.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


print("=== run 1: the cycle, in order, with the gap; every lane leaves cleanly")
fresh_workflow()
for n in R.LANES:
    plan(n, {"default": {"rc": 0, "after": 2}})
t0 = time.time()
code = R.Fleet(args()).run()
check("run 1 exit 0", code == 0, code)
starts = {n: launches(n)[0]["at"] for n in R.LANES}
check("launched in the cycle's order with the gap", starts["synchronization"] < starts["registration"] < starts["documentation"]
      and starts["registration"] - starts["synchronization"] >= 0.9 and starts["documentation"] - starts["registration"] >= 0.9, starts)
argv_doc = launches("documentation")[0]["argv"]
check("documentation got --drive and --fresh-days; widths per lane", "--drive" in argv_doc and "SIMDRIVE" in argv_doc
      and launches("synchronization")[0]["argv"][launches("synchronization")[0]["argv"].index("--width") + 1] == str(R.WIDTHS["synchronization"])
      and argv_doc[argv_doc.index("--width") + 1] == str(R.WIDTHS["documentation"]), argv_doc)
check("the lane log was appended with a fleet banner", "=== fleet launch" in (WF / "documentation" / "documentation.log").read_text())
check("fleet done line", "every lane has left" in fleet_log())

print("=== run 2: crashes are relaunched after the wait; the cap parks a lane that keeps crashing")
fresh_workflow()
plan("synchronization", {"default": {"rc": 0, "after": 1}})
plan("registration", {"1": {"rc": 5, "after": 1}, "2": {"rc": 5, "after": 1}, "default": {"rc": 0, "after": 1}})
plan("documentation", {"default": {"rc": 5, "after": 0.5}})
code = R.Fleet(args(relaunch_cap=2)).run()
check("run 2 exit 0 (crashes cured or parked, nothing refused)", code == 0, code)
check("registration relaunched twice then ran clean (3 launches)", len(launches("registration")) == 3, len(launches("registration")))
check("documentation parked by the fleet after the cap (3 launches = cap + 1)", len(launches("documentation")) == 3
      and (WF / "documentation" / "documentation.parked").exists() and "parked by the fleet" in (WF / "documentation" / "documentation.parked").read_text(),
      (len(launches("documentation")), fleet_log()[-500:]))

print("=== run 3: a refusal stills every lane; a parked lane is not relaunched")
fresh_workflow()
plan("synchronization", {"default": {"rc": 2, "after": 3}})
plan("registration", {"default": {"rc": 0, "after": 60}})
plan("documentation", {"default": {"rc": 0, "after": 60}})
t0 = time.time()
code = R.Fleet(args()).run()
check("run 3 exit 2 (refused)", code == 2, code)
check("the others were told to stop and left within the wait", time.time() - t0 < 30 and "stopped by control" in (WF / "documentation" / "documentation.log").read_text(), time.time() - t0)
check("synchronization was not relaunched", len(launches("synchronization")) == 1)
check("REFUSED line in the fleet log", "REFUSED by the source" in fleet_log())

print("=== run 4: the drive goes; the fleet waits for it and relaunches with --unpark")
fresh_workflow()
plan("synchronization", {"default": {"rc": 0, "after": 1}})
plan("registration", {"default": {"rc": 0, "after": 1}})
plan("documentation", {"1": {"rc": 6, "after": 1}, "default": {"rc": 0, "after": 1}})
calls = {"n": 0}
def find_drive(label):
    calls["n"] += 1
    if calls["n"] <= 2:
        raise SystemExit("no drive labelled %s (simulated)" % label)
    return pathlib.Path("D:/")
storage.find_drive = find_drive
code = R.Fleet(args()).run()
check("run 4 exit 0", code == 0, code)
l2 = launches("documentation")
check("documentation relaunched once the drive was back, with --unpark", len(l2) == 2 and "--unpark" in l2[1]["argv"] and calls["n"] >= 3, (len(l2), calls))
check("the drive line in the fleet log", "the drive 'SIMDRIVE' is back" in fleet_log())

print("=== run 5: a lane already running by hand is refused and left alone")
fresh_workflow()
plan("synchronization", {"default": {"rc": 0, "after": 1}})
plan("registration", {"default": {"rc": 0, "after": 1}})
plan("documentation", {"default": {"rc": 0, "after": 1}})
(WF / "registration" / "registration.lock").write_text(str(os.getpid()))          # this test process holds the lock
code = R.Fleet(args()).run()
check("run 5 exit 0", code == 0, code)
check("registration refused to start (1) and was not relaunched", launches("registration") == [] and fleet_log().count("registration: launched") == 1 and "refused to start (1)" in fleet_log(), fleet_log())

print("=== run 6: --mega: one child hosting the crews; stop reaches it")
fresh_workflow()
plan("synchronization", {"default": {"rc": 0, "after": 30}})
f = R.Fleet(args(mega=True, entry_gap=1))
def stop_soon():
    time.sleep(4)
    f.stopping = True
threading.Thread(target=stop_soon, daemon=True).start()
t0 = time.time()
code = f.run()
check("run 6 exit 0 after the stop", code == 0 and time.time() - t0 < 20, (code, time.time() - t0))
l6 = launches("synchronization")
check("one child with --also for the other two, and --drive for documentation", len(l6) == 1 and l6[0]["argv"].count("--also") == 2
      and ("registration:%d" % R.WIDTHS["registration"]) in l6[0]["argv"] and ("documentation:%d" % R.WIDTHS["documentation"]) in l6[0]["argv"] and "--drive" in l6[0]["argv"], l6)
check("the other lanes were never launched on their own", not launches("registration") and not launches("documentation"))
check("stopped through the control file", "stopped by control" in (WF / "synchronization" / "synchronization.log").read_text())

print("=== commands: width, stop, status against a running fake lane")
fresh_workflow()
plan("documentation", {"default": {"rc": 0, "after": 60}})
p = subprocess.Popen([sys.executable, "-u", str(WF / "documentation" / ("%s Documentation.py" % R.SOURCE)), "--width", "40", "--host", "SIM-HOST"],
                     cwd=str(WF / "documentation"), stdout=open(WF / "documentation" / "documentation.log", "ab"), stderr=subprocess.STDOUT)
time.sleep(1.5)
R.width(args(command="width", target="documentation=60"))
check("width written to the control file", (WF / "documentation" / "documentation.control").read_text().strip() == "width=60")
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = R.status(args(command="status"))
out = buf.getvalue()
check("status sees the running lane, the control word, and the cloud heartbeats", ("documentation    RUNNING pid %d" % p.pid) in out and "control: width=60" in out and "heartbeats in the cloud" in out, out)
t0 = time.time()
R.stop(args(command="stop", target="documentation", stop_wait=10))
check("stop left the lane through its control file", p.wait(timeout=10) == 0 and time.time() - t0 < 10)

print("\nFLEET SIMULATION (%s):" % SRC, "ALL OK" if not fails else "FAILURES: %s" % fails, "- no source request")
sys.exit(1 if fails else 0)
