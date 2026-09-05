"""OFFLINE checks of the richmond documentation lane: the mint's three outcomes, the path rule, the lag, and one worker's
fetch against a fake crew and a fake two-host session - a pdf minted and pulled in one breath and written whole; no image
-> pending inside the lag / absent past it / asked again when the registry disagrees; the courts host's 401/403 arbitrated
by one probe of a different document (restricted -> absent + evidence, or the lane refused); the wall, the wire, a
refusal shape on the mint; the session prepared once (its own pool for the courts host, the clerk's front door).
No request, no cloud."""
import datetime as dt, importlib.util, json, pathlib, queue, sys, threading, types
PHASE = pathlib.Path(__file__).resolve().parents[3]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))
import requests
import lane, richmond, storage
spec = importlib.util.spec_from_file_location("richmond_documentation", str(PHASE / "Richmond" / "workflow" / "documentation" / "Richmond Documentation.py"))
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
ROOT = HERE / "fakedrive"
import shutil
shutil.rmtree(ROOT, ignore_errors=True)
ROOT.mkdir()
for f in HERE.glob("documentation.*"):
    f.unlink()

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)

today = dt.date.today()
def mdy(d):
    return "%d/%d/%d" % (d.month, d.day, d.year)
REG_NEW = {"instrument": "1009001", "recorded": mdy(today), "image_state": "pending"}
REG_OLD = {"instrument": "1008999", "recorded": mdy(today - dt.timedelta(days=30)), "image_state": "absent"}
REG_OLD_PRESENT = {"instrument": "1008998", "recorded": mdy(today - dt.timedelta(days=30)), "image_state": "present"}

print("=== the rules in richmond.py")
check("302 + an absolute courts url is present", richmond.classify_mint(302, "https://iapps.courts.state.ny.us/vscms_public/viewer?token=v2.abc") == ("present", "https://iapps.courts.state.ny.us/vscms_public/viewer?token=v2.abc"))
check("302 + the clerk's own error page is no image", richmond.classify_mint(302, "/Search/SearchError") == ("noimage", None))
check("200 and 404 are dead ends (no image)", richmond.classify_mint(200, "") == ("noimage", None) and richmond.classify_mint(404, "") == ("noimage", None))
check("403 / 429 / 503 are about us", all(richmond.classify_mint(c, "")[0] == "error" for c in (403, 429, 503)))
check("a pdf starts with %PDF", richmond.is_pdf(b"%PDF-1.4 ...") and not richmond.is_pdf(b"<html>") and not richmond.is_pdf(b"%PD"))
check("the path: Richmond / By Document / year / month / day from the recorded date", richmond.canonical_path("RC_1", {"recorded": "8/19/2026"}) == "D:\\NYC CRE Decoded\\Reproduction\\Richmond\\By Document\\2026\\08 Aug\\19\\RC_1.pdf", richmond.canonical_path("RC_1", {"recorded": "8/19/2026"}))
check("no readable date: the id split, no empty folder", richmond.canonical_path("RC_2", {"recorded": ""}).endswith("\\Richmond\\By Document\\RC_2\\RC_2.pdf") and richmond.canonical_path("RC_1900390", {}).endswith("\\By Document\\RC_1\\9003\\RC_1900390.pdf"), richmond.canonical_path("RC_2", {"recorded": ""}))
check("fresh: inside the 7-day lag / past it / an unreadable date is inside", richmond.fresh(REG_NEW) and not richmond.fresh(REG_OLD) and richmond.fresh({"recorded": "garbage"}) and richmond.fresh(None))
check("the mint url and its referer", richmond.mint_url(" 123 ") == "https://www.richmondcountyclerk.com/ViewVscmsDocument/ViewContent?p_endorsementId=123"
      and richmond.mint_referer("123") == "https://www.richmondcountyclerk.com/Search/ViewDocumentInfo/123")
check("the pull carries the honest UA (the session's) with the clerk referer and a pdf accept", richmond.PULL_HEADERS == {"Referer": "https://www.richmondcountyclerk.com/", "Accept": "application/pdf,*/*"})

# ── fakes ────────────────────────────────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, status, content=b"", location=None):
        self.status_code, self.content, self.headers = status, content, ({"Location": location} if location else {})
    def close(self):
        pass

TOKEN = "https://iapps.courts.state.ny.us/vscms_public/viewer?token=v2.%s"
PDF = b"%PDF-1.4\n%fake pdf body\n%%EOF"

class FakeSession:
    """Two hosts: the clerk (front door, mints) and the courts (token urls). Programmable per id."""
    def __init__(self):
        self.mint = {}        # iid -> (status, location) or Exception
        self.pull = {}        # iid -> (status, content) or Exception
        self.calls = []
        self.mounts = []
    def mount(self, prefix, adapter):
        self.mounts.append(prefix)
    def get(self, url, headers=None, timeout=None, allow_redirects=True, stream=False):
        self.calls.append((url, allow_redirects, stream, dict(headers or {})))
        if url == richmond.BASE + "/":
            return FakeResp(200, b"<html>front door</html>")
        if "p_endorsementId=" in url:
            iid = url.rsplit("=", 1)[1]
            spec = self.mint.get(iid, (302, "/Search/SearchError"))
            if isinstance(spec, Exception):
                raise spec
            status, loc = spec
            return FakeResp(status, b"<html>" + (loc or "").encode() + b"</html>" if status == 200 else b"", loc)
        if url.startswith(richmond.IAPPS):
            iid = url.rsplit(".", 1)[1]
            spec = self.pull.get(iid, (200, PDF))
            if isinstance(spec, Exception):
                raise spec
            return FakeResp(spec[0], spec[1])
        raise AssertionError("unexpected url " + url)

class FakeCrew:
    def __init__(self):
        self.session = FakeSession(); self.lock = threading.Lock(); self.stats = {"reqs": 0, "reask": 0}
        self.q = queue.Queue(); self.stop = threading.Event(); self.ctx = types.SimpleNamespace(args=types.SimpleNamespace(log=""), lines=[])
    def get(self, url, referer, timeout=90):
        with self.lock:
            self.stats["reqs"] += 1
        r = self.session.get(url, headers={"Referer": referer}, timeout=timeout)
        if r.status_code >= 400:
            raise lane.HTTPStatus(r.status_code, url)
        return r.content, ""

D.lane._log = lambda ctx, msg: ctx.lines.append(msg)
role = D.Documentation(HERE, str(ROOT), richmond.IMAGE_LAG_DAYS, cooldown=0)
crew = FakeCrew()

print("=== no registry, no request; a file already on the drive, no request")
try:
    role.fetch(crew, "RC_990000051", None); check("no registry -> Retry", False)
except lane.Retry as e:
    check("no registry -> Retry, no request", "no registry" in str(e) and crew.stats["reqs"] == 0)
canon = richmond.canonical_path("RC_990000052", REG_OLD)
p = storage.local(str(ROOT), canon); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(PDF)
check("a file already under this drive is recorded without a request", role.fetch(crew, "RC_990000052", REG_OLD) == canon and crew.stats["reqs"] == 0)

print("=== the pdf: minted and pulled in one breath, written whole")
crew.session.mint["990000053"] = (302, TOKEN % "990000053")
canon = richmond.canonical_path("RC_990000053", REG_OLD)
got = role.fetch(crew, "RC_990000053", REG_OLD)
local = storage.local(str(ROOT), canon)
check("returns the canonical One Touch path and the file is there, whole", got == canon and local.is_file() and local.read_bytes() == PDF and not local.with_name(local.name + ".part").exists(), got)
calls = [c[0] for c in crew.session.calls]
check("the session was prepared once: the courts host got its own pool, the clerk's front door was fetched first",
      crew.session.mounts == [richmond.IAPPS] and calls[0] == richmond.BASE + "/" and "p_endorsementId=990000053" in calls[1] and calls[2].startswith(richmond.IAPPS), calls)
check("the mint went out with redirects OFF and the detail page as referer; the pull followed with the pdf headers",
      crew.session.calls[1][1] is False and crew.session.calls[1][3]["Referer"].endswith("/Search/ViewDocumentInfo/990000053")
      and crew.session.calls[2][1] is True and crew.session.calls[2][2] is True and crew.session.calls[2][3]["Accept"] == "application/pdf,*/*")
n = len(crew.session.calls)
crew.session.mint["990000054"] = (302, TOKEN % "990000054")
role.fetch(crew, "RC_990000054", REG_OLD)
check("the second document does not prepare again (two requests: mint + pull)", len(crew.session.calls) == n + 2 and crew.session.mounts == [richmond.IAPPS])

print("=== no image: pending inside the lag, absent past it, asked again when the registry disagrees")
crew.session.mint["990000055"] = (302, "/Search/SearchError")
check("recorded today + no image = pending", role.fetch(crew, "RC_990000055", REG_NEW) == "pending")
check("recorded 30 days ago + no image = absent", role.fetch(crew, "RC_990000055", REG_OLD) == "absent")
try:
    role.fetch(crew, "RC_990000055", REG_OLD_PRESENT); check("registry says present: asked again", False)
except lane.Retry as e:
    check("registry says present but the mint says no image: two sources disagree -> asked again", "disagree" in str(e))
check("an unreadable recorded date + no image = pending, never absent", role.fetch(crew, "RC_990000055", {"recorded": "??", "image_state": "absent"}) == "pending")
crew.session.mint["990000056"] = (200, None)
check("a 200 from the mint is a dead end (no image)", role.fetch(crew, "RC_990000056", REG_OLD) == "absent")
crew.session.mint["990000057"] = (404, None)
check("a 404 from the mint is a dead end (no image)", role.fetch(crew, "RC_990000057", REG_OLD) == "absent")

print("=== ours, never the document's: 503 / 403 on the mint, the wire, a refusal shape")
crew.session.mint["990000058"] = (503, None)
try:
    role.fetch(crew, "RC_990000058", REG_OLD); check("503 on the mint raises HTTPStatus", False)
except lane.HTTPStatus as e:
    check("503 on the mint raises HTTPStatus (the crew's wall counts it)", e.code == 503)
crew.session.mint["990000058"] = (403, None)
try:
    role.fetch(crew, "RC_990000058", REG_OLD); check("403 on the mint raises HTTPStatus", False)
except lane.HTTPStatus as e:
    check("403 on the mint is about us: HTTPStatus, the document stays for a later pass", e.code == 403)
crew.session.mint["990000058"] = requests.exceptions.ConnectionError("EOF (simulated)")
try:
    role.fetch(crew, "RC_990000058", REG_OLD); check("a wire failure raises Transport", False)
except lane.Transport as e:
    check("a wire failure raises Transport (the hang-up detector counts it)", "ConnectionError" in str(e))
crew.session.mint["990000059"] = (200, "Access Denied - your request was blocked")
try:
    role.fetch(crew, "RC_990000059", REG_OLD); check("a refusal shape on the mint raises Refused", False)
except lane.Refused:
    check("a refusal shape on the mint raises Refused (the crew parks)", True)

print("=== the pull: not a pdf, 500, 429")
crew.session.mint["990000060"] = (302, TOKEN % "990000060")
crew.session.pull["990000060"] = (200, b"<html>viewer</html>")
try:
    role.fetch(crew, "RC_990000060", REG_OLD); check("html from the courts host is not a pdf", False)
except lane.Retry as e:
    check("html from the courts host is never written: Retry", "not a pdf" in str(e) and not storage.local(str(ROOT), richmond.canonical_path("RC_990000060", REG_OLD)).exists())
crew.session.pull["990000060"] = (500, b"")
try:
    role.fetch(crew, "RC_990000060", REG_OLD); check("500 from the courts host is a retry", False)
except lane.Retry as e:
    check("500 from the courts host: Retry", "HTTP 500" in str(e))
crew.session.pull["990000060"] = (429, b"")
try:
    role.fetch(crew, "RC_990000060", REG_OLD); check("429 from the courts host is the wall", False)
except lane.HTTPStatus as e:
    check("429 from the courts host: HTTPStatus (the wall)", e.code == 429)

print("=== the verdict on a 403 from the courts host: one probe of a different document decides")
crew.session.mint["990000061"] = (302, TOKEN % "990000061")
crew.session.pull["990000061"] = (403, b"")
crew.session.mint["990000062"] = (302, TOKEN % "990000062")
crew.q.put(("RC_990000062", REG_OLD, 0))
got = role.fetch(crew, "RC_990000061", REG_OLD)
rows = [json.loads(l) for l in (HERE / "documentation.restricted.jsonl").read_text().splitlines()]
check("the probe returned a pdf: the document is RESTRICTED -> recorded absent, evidence written, the probe put back in the queue",
      got == "absent" and rows[-1]["id"] == "RC_990000061" and rows[-1]["probe"] == "RC_990000062" and rows[-1]["code"] == 403 and crew.q.qsize() == 1 and crew.q.get()[0] == "RC_990000062", (got, rows))
check("the hold was released and the log says so", not role.hold.is_set() and any("RESTRICTED" in l for l in crew.ctx.lines))
n = crew.stats["reqs"]
check("a restricted document is never asked again", role.fetch(crew, "RC_990000061", REG_OLD) == "absent" and crew.stats["reqs"] == n)
role2 = D.Documentation(HERE, str(ROOT), richmond.IMAGE_LAG_DAYS, cooldown=0)
check("the restricted list survives a restart (read from the evidence file)", "RC_990000061" in role2.restricted)
crew.session.mint["990000063"] = (302, TOKEN % "990000063")
crew.session.pull["990000063"] = (403, b"")
crew.session.mint["990000064"] = (302, TOKEN % "990000064")
crew.session.pull["990000064"] = (403, b"")
crew.q.put(("RC_990000064", REG_OLD, 0))
try:
    role.fetch(crew, "RC_990000063", REG_OLD); check("probe also refused -> Refused", False)
except lane.Refused as e:
    check("the probe was refused too: the LANE is refused -> Refused (park, exit 2)", "probe RC_990000064" in str(e) and crew.q.qsize() == 1)
crew.q.get()
try:
    role.fetch(crew, "RC_990000063", REG_OLD); check("no probe available -> Retry", False)
except lane.Retry as e:
    check("no probe document available: the hold is released unproven, asked again later", "no probe" in str(e) and not role.hold.is_set())
role.arbiter.acquire()
try:
    role.fetch(crew, "RC_990000063", REG_OLD); check("a verdict in progress -> Retry", False)
except lane.Retry as e:
    check("a second 403 while a verdict is in progress is asked again later", "in progress" in str(e))
finally:
    role.arbiter.release()

print("=== the lane's arguments and role hook")
r = D.role(str(ROOT), types.SimpleNamespace(fresh_days=7, cooldown=600))
check("role() builds the lane for --also with the drive root", isinstance(r, D.Documentation) and r.cooldown == 600 and r.fresh_days == 7)
try:
    D.role("", types.SimpleNamespace()); check("role() without a drive is refused", False)
except SystemExit as e:
    check("role() without a drive is refused", "--drive" in str(e))

print("\nRICHMOND DOC OFFLINE:", "ALL OK" if not fails else "FAILURES: %s" % fails)
sys.exit(1 if fails else 0)
