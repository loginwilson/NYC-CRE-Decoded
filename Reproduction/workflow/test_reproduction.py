"""SIMULATION of the phase program (Reproduction.py) over FAKE fleet programs - no source request, no cloud, no real
lane.  A temp phase dir holds two fake `<Source> Reproduction.py` files that behave like fleets: they write the
arguments they were given, run until their plan says to leave with a code, leave with 0 when told to stop, and answer
`status` / `stop` with a line.  Proves: the sources are found by their fleet program and nothing else; each fleet gets
--drive, --host and its own arguments whole, --source-gap apart; a fleet's exit is its word - a refusal (2) leaves the
other fleet running and the phase leaves with 2 when the last fleet has left; a stop reaches every fleet and the phase
leaves with 0; the lock refuses a second phase; status and stop go through each fleet program."""
import importlib.util, json, pathlib, shutil, sys, tempfile, threading, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("reproduction_phase", HERE / "Reproduction.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

FAKE = r'''
import json, pathlib, signal, sys, time
here = pathlib.Path(__file__).resolve().parent
name = here.parents[1].name.lower()
(here / "argv.txt").write_text(" ".join(sys.argv[1:]), encoding="utf-8")
cmd = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "run"
if cmd != "run":
    print("fake %s: %s %s" % (name, cmd, " ".join(sys.argv[2:])), flush=True)
    sys.exit(0)
plan = json.loads((here / "plan.json").read_text(encoding="utf-8"))
def bye(*a):
    print("fake %s: told to stop" % name, flush=True)
    sys.exit(0)
for s in ("SIGBREAK", "SIGTERM", "SIGINT"):
    if hasattr(signal, s):
        signal.signal(getattr(signal, s), bye)
print("fake %s up" % name, flush=True)
end = time.time() + plan["after"]
while time.time() < end:
    time.sleep(0.2)
sys.exit(plan["exit"])
'''

fails = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)


tmp = pathlib.Path(tempfile.mkdtemp(prefix="phase_sim_"))
try:
    for src in ("Alpha", "Beta"):
        d = tmp / src / "workflow" / "reproduction"
        d.mkdir(parents=True)
        (d / ("%s Reproduction.py" % src)).write_text(FAKE, encoding="utf-8")
    (tmp / "Gamma" / "workflow").mkdir(parents=True)                     # a folder without a fleet program is not a source
    (tmp / "rulebook").mkdir()
    (tmp / "workflow").mkdir()
    (tmp / "Beta" / "workflow" / "reproduction" / "stray.md").write_text("", encoding="utf-8")

    def plan(src, exit_code, after):
        (tmp / src / "workflow" / "reproduction" / "plan.json").write_text(json.dumps({"exit": exit_code, "after": after}), encoding="utf-8")

    def argv_of(src):
        p = tmp / src / "workflow" / "reproduction" / "argv.txt"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def phase_log():
        p = tmp / "workflow" / "reproduction.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    print("=== the sources are the folders with a fleet program, in alphabetical order")
    srcs = P.sources(tmp)
    check("alpha and beta found, gamma / rulebook / workflow not", [n for n, _ in srcs] == ["alpha", "beta"], srcs)
    check("the fleet program is the pair's py", srcs[0][1].name == "Alpha Reproduction.py", srcs[0][1])
    check("pick keeps the order asked", [n for n, _ in P.pick(srcs, "beta,alpha")] == ["beta", "alpha"])
    try:
        P.pick(srcs, "delta")
        check("an unknown source is refused", False)
    except SystemExit as e:
        check("an unknown source is refused", "delta" in str(e), e)

    print("=== run: a refusal at one source leaves the other running; the phase leaves with 2 after the last fleet")
    plan("Alpha", 2, 2)
    plan("Beta", 0, 6)
    args = P.build_parser(srcs).parse_args(["--drive", "NYCCRED9", "--host", "simhost", "--source-gap", "1", "--stop-wait", "5",
                                            "--alpha", "--lanes documentation:4 --mega", "--beta", "--edge 2026-08-25"])
    t0 = time.time()
    rc = P.Phase(args, srcs, here=tmp / "workflow").run()
    took = time.time() - t0
    check("the phase leaves with 2 (the worst word)", rc == 2, rc)
    check("alpha got --drive, --host and its own arguments whole", argv_of("Alpha") == "--drive NYCCRED9 --host simhost --lanes documentation:4 --mega", argv_of("Alpha"))
    check("beta got its own", argv_of("Beta") == "--drive NYCCRED9 --host simhost --edge 2026-08-25", argv_of("Beta"))
    log = phase_log()
    check("alpha's refusal is named and the other fleet runs on", "alpha: fleet pid" in log and "REFUSED" in log and "the other fleets run on" in log, log[-600:])
    check("the phase waited for beta (ran ~7 s, not ~3)", 6 <= took <= 20, "%.1f s" % took)
    check("every fleet has left", "every fleet has left" in log)
    check("no relaunch of a fleet", log.count("alpha: fleet launched") == 1, log.count("alpha: fleet launched"))
    check("the lock is gone", not (tmp / "workflow" / "reproduction.lock").exists())
    check("each fleet's console went to <source>.log beside the phase", "fake alpha up" in (tmp / "workflow" / "alpha.log").read_text(encoding="utf-8"))

    print("=== run then stop: the stop reaches every fleet, the phase leaves with 0; a second phase is refused by the lock")
    plan("Alpha", 0, 60)
    plan("Beta", 0, 60)
    args = P.build_parser(srcs).parse_args(["--drive", "NYCCRED9", "--source-gap", "1", "--stop-wait", "10"])
    ph = P.Phase(args, srcs, here=tmp / "workflow")
    out = {}

    def go():
        out["rc"] = ph.run()
    th = threading.Thread(target=go)
    th.start()
    time.sleep(4)
    second = None
    try:
        P.Phase(args, srcs, here=tmp / "workflow").run()
    except SystemExit as e:
        second = str(e)
    check("a second phase on the same machine is refused (fail closed)", second is not None, second)
    check("both fleets up before the stop", len(ph.children) == 2 and all(c["proc"].poll() is None for c in ph.children.values()), list(ph.children))
    ph.stopping = True
    th.join(40)
    check("the phase left", not th.is_alive())
    check("the phase leaves with 0 after a stop", out.get("rc") == 0, out.get("rc"))
    log = phase_log()
    check("stop sent to both fleets", "stop sent to alpha, beta" in log, log[-400:])
    check("the fakes were told to stop (no termination needed)", "told to stop" in (tmp / "workflow" / "alpha.log").read_text(encoding="utf-8") and "terminating" not in log)

    print("=== status and stop go through each fleet program")
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = P.run_each(srcs, ["status", "--within", "10 minutes"], "simhost")
    check("status: rc 0", rc == 0, rc)
    check("status asked alpha", argv_of("Alpha") == "status --within 10 minutes --host simhost", argv_of("Alpha"))
    check("status asked beta", argv_of("Beta") == "status --within 10 minutes --host simhost", argv_of("Beta"))
    with contextlib.redirect_stdout(buf):
        rc = P.run_each(P.pick(srcs, "beta"), ["stop", "--stop-wait", "90"], "")
    check("stop [source]: only beta asked", argv_of("Beta") == "stop --stop-wait 90" and argv_of("Alpha").startswith("status"), argv_of("Beta"))

    print("=== run without --drive is refused before anything launches")
    try:
        P.main(["run"], phase=tmp, here=tmp / "workflow")
        check("run needs --drive", False)
    except SystemExit as e:
        check("run needs --drive", "--drive" in str(e), e)
finally:
    time.sleep(0.5)
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPHASE: %s - offline, nothing asked of any source" % ("ALL OK" if not fails else "FAILURES: %s" % fails))
sys.exit(1 if fails else 0)
