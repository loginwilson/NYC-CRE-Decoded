"""LIVE-CLOUD simulation of the richmond documentation lane, no request to the clerk or the courts: throwaway RC_9900000xx
rows with registries; one worker's fetch against a fake two-host session lands a path, a pending and an absent through
reproduction.land as the documentation lane; the lane counter moves by the newly filled cells and the phase counter by the
rows that are now complete (registry + document); cleanup + reconcile restore the counters."""
import datetime as dt, importlib.util, pathlib, queue, shutil, sys, threading, types
PHASE = pathlib.Path(__file__).resolve().parents[3]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))
import cloud, lane, richmond, storage
spec = importlib.util.spec_from_file_location("richmond_documentation", str(PHASE / "Richmond" / "workflow" / "documentation" / "Richmond Documentation.py"))
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
ROOT = HERE / "fakedrive"
shutil.rmtree(ROOT, ignore_errors=True); ROOT.mkdir(parents=True)
for f in HERE.glob("documentation.*"):
    f.unlink()

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)

IDS = ["RC_9900000%02d" % i for i in range(71, 75)]
today = dt.date.today()
def mdy(d):
    return "%d/%d/%d" % (d.month, d.day, d.year)
REGS = {IDS[0]: {"instrument": "1", "recorded": "8/19/2026", "image_state": "present", "parcels": [], "parties": []},
        IDS[1]: {"instrument": "2", "recorded": mdy(today), "image_state": "pending", "parcels": [], "parties": []},
        IDS[2]: {"instrument": "3", "recorded": mdy(today - dt.timedelta(days=40)), "image_state": "absent", "parcels": [], "parties": []},
        IDS[3]: None}
REG = cloud.Cloud("richmond", "registration", "SIM-HOST", app="richmond registration SIM")
DOC = cloud.Cloud("richmond", "documentation", "SIM-HOST", app="richmond documentation SIM")

def counters():
    lanes = {r[0]: (r[1], r[2]) for r in DOC._run("select lane, landed, needed from reproduction.richmond_update_lanes order by lane", (), True)}
    phase = DOC._run("select landed, needed from reproduction.richmond_update", (), True)[0]
    return lanes, tuple(phase)

def cleanup():
    DOC._run("delete from reproduction.richmond where doc_id = any(%s)", (IDS,), False)
    DOC._run("delete from reproduction.richmond_claims where doc_id = any(%s)", (IDS,), False)

class FakeResp:
    def __init__(self, status, content=b"", location=None):
        self.status_code, self.content, self.headers = status, content, ({"Location": location} if location else {})
    def close(self):
        pass
PDF = b"%PDF-1.4\n%sim\n%%EOF"
class FakeSession:
    def __init__(self):
        self.mounts = []
    def mount(self, prefix, adapter):
        self.mounts.append(prefix)
    def get(self, url, headers=None, timeout=None, allow_redirects=True, stream=False):
        if url == richmond.BASE + "/":
            return FakeResp(200, b"front door")
        if "p_endorsementId=" in url:
            iid = url.rsplit("=", 1)[1]
            if iid == "990000071":
                return FakeResp(302, b"", "https://iapps.courts.state.ny.us/vscms_public/viewer?token=v2.sim")
            return FakeResp(302, b"", "/Search/SearchError")
        return FakeResp(200, PDF)
class FakeCrew:
    def __init__(self):
        self.session = FakeSession(); self.lock = threading.Lock(); self.stats = {"reqs": 0}; self.q = queue.Queue(); self.stop = threading.Event()
        self.ctx = types.SimpleNamespace(args=types.SimpleNamespace(log=""), lines=[])
    def get(self, url, referer, timeout=90):
        with self.lock:
            self.stats["reqs"] += 1
        r = self.session.get(url, headers={"Referer": referer}, timeout=timeout)
        return r.content, ""
D.lane._log = lambda ctx, msg: ctx.lines.append(msg)

try:
    cleanup()
    before_lanes, before_phase = counters()
    print("=== four throwaway rows: three with registries, one without")
    n = DOC.insert_ids(IDS)
    REG.land([{"doc_id": i, "value": REGS[i]} for i in IDS if REGS[i]])
    regs = DOC.registries(IDS)
    check("rows inserted and three registries landed", n == 4 and all(isinstance(regs[i], dict) for i in IDS[:3]) and regs[IDS[3]] is None)
    lanes, phase = counters()
    check("registration's counter moved by three, the phase by none yet (documents empty)", lanes["registration"][0] == before_lanes["registration"][0] + 3 and phase[0] == before_phase[0])

    print("=== one worker's fetch against the fake two-host session, landed as the documentation lane")
    role = D.Documentation(HERE, str(ROOT), richmond.IMAGE_LAG_DAYS, cooldown=0)
    crew = FakeCrew()
    values = {}
    for i in IDS:
        try:
            values[i] = role.fetch(crew, i, regs[i])
        except lane.Retry as e:
            values[i] = ("retry", str(e))
    canon = richmond.canonical_path(IDS[0], regs[IDS[0]])
    check("a path, a pending, an absent, and a retry for the row without a registry",
          values[IDS[0]] == canon and values[IDS[1]] == "pending" and values[IDS[2]] == "absent" and values[IDS[3]][0] == "retry", values)
    check("the pdf is on the fake drive under the One Touch layout", storage.local(str(ROOT), canon).read_bytes() == PDF and "\\richmond\\2026\\08 Aug\\" in canon)
    landed = DOC.land([{"doc_id": i, "value": values[i]} for i in IDS[:3]])
    cells = {r[0]: r[1] for r in DOC._run("select doc_id, document from reproduction.richmond where doc_id = any(%s)", (IDS,), True)}
    check("the cloud took the three cells: the path, the word pending, the word absent; the fourth stays empty",
          landed == 3 and cells[IDS[0]] == canon and cells[IDS[1]] == "pending" and cells[IDS[2]] == "absent" and cells[IDS[3]] is None, cells)
    lanes, phase = counters()
    check("documentation's counter moved by three newly filled cells; the phase by three completes (registry + document)",
          lanes["documentation"][0] == before_lanes["documentation"][0] + 3 and phase[0] == before_phase[0] + 3, (lanes, phase, before_lanes, before_phase))
    landed = DOC.land([{"doc_id": IDS[1], "value": canon.replace(IDS[0], IDS[1])}])
    lanes, phase = counters()
    check("a pending upgraded to a path counts nothing more (the cell was already landed)", landed == 1 and lanes["documentation"][0] == before_lanes["documentation"][0] + 3 and phase[0] == before_phase[0] + 3)
    try:
        DOC.land([{"doc_id": IDS[3], "value": "garbage"}]); check("the cell rule rejects a bad word", False)
    except Exception as e:
        check("the cell rule rejects a value that is not a path or a verdict word", "violates" in str(e) or "check" in str(e).lower(), str(e)[:120])
finally:
    print("=== cleanup + reconcile")
    cleanup()
    print("   reconcile:", DOC._run("select * from reproduction.reconcile('richmond')", (), True))
    lanes, phase = counters()
    check("the counters are back where they started", lanes == before_lanes and phase == before_phase, (lanes, before_lanes, phase, before_phase))
    check("no throwaway row left", DOC.count("RC_99000007", "RC_99000008") == 0)
    REG.close(); DOC.close()

print("\nRICHMOND DOC SIM:", "ALL OK" if not fails else "FAILURES: %s" % fails)
sys.exit(1 if fails else 0)
