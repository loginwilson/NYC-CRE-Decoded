"""OFFLINE checks of the richmond registration lane: the detail parser on a page in the county's shape (the modern
"Document No.:" label, the premature detail, the shell, the image states), the walker's order (page, then details, in
one session; the shell asked again; the wire and the wall raised as the crew's exceptions), and the monitor's feed and
land against a fake crew and a fake cloud - the control first, the catch-up from the edge, pages 2..N fanned out, the
details only for ids the table says need work, registries landed through the outbox, the edge moving only after a
window's pages and details are all in, holes after three asks, a broken control parking the lane.  No request, no cloud."""
import datetime as dt, importlib.util, json, pathlib, queue, sys, threading, types
PHASE = pathlib.Path(__file__).resolve().parents[2]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))
import requests
import cloud, lane, richmond
spec = importlib.util.spec_from_file_location("richmond_registration", str(PHASE / "Richmond" / "workflow" / "registration" / "Richmond Registration.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("registration.*"):
    f.unlink()

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)

# ── the detail page in the county's shape ────────────────────────────────────────────────
def detail_html(instrument="1008999", recorded="8/19/2026", image="present", label="Document No.:"):
    img = {"present": '<a href="/ViewVscmsDocument/ViewContent?p_endorsementId=1008999">View Imaged Document</a>',
           "none": "<span>No Image Available At This Time</span>", "odd": "<span>Image status unavailable</span>"}[image]
    return """<html><body><div class="panel"><h3>RECORDED DETAILS</h3>
<div class="row"><span class="lbl">%s</span>&nbsp;<span class="val">%s</span></div>
<div class="row"><span class="lbl">Book:</span> <span class="val"></span></div>
<div class="row"><span class="lbl">Page:</span> <span class="val"></span></div>
<div class="row"><span class="lbl">Document Type:</span> <span class="val">DEED</span></div>
<div class="row"><span class="lbl">Date Recorded:</span> <span class="val">%s</span></div>
<div class="row"><span class="lbl">Consideration Amount:</span> <span class="val">$500,000.00</span></div>
<div class="row"><span class="lbl">Status:</span> <span class="val">Recorded</span></div>
%s
<h3>BLOCKS AND LOTS</h3><div>Block 1234, Lot 56</div><div>Block 7, Lot 8</div>
<h3>PARTIES</h3><table>
<tr><th>Name</th><th>Company</th><th>Party</th></tr>
<tr><td>SMITH, JOHN</td><td></td><td>GRANTOR</td></tr>
<tr><td></td><td>ACME HOLDINGS LLC</td><td>GRANTEE</td></tr>
<tr><td></td><td></td><td></td></tr>
</table></div></body></html>""" % (label, instrument, recorded, img)

SHELL = "<html><head><title>Richmond County Clerk</title></head><body><div id='app'></div></body></html>"
UNAUTH = "<html><body><h2>INVALID REQUEST: UNAUTHORIZED SEARCH ACCESS</h2></body></html>"

print("=== the parser: the corpus schema from a page in the county's shape")
rec = richmond.parse_detail(detail_html())
check("instrument read past the modern 'Document No.:' label", rec["instrument"] == "1008999", rec)
check("type, date, amount, status (the image link stripped from the status)", (rec["doc_type"], rec["recorded"], rec["amount"], rec["status"]) == ("DEED", "8/19/2026", "$500,000.00", "Recorded"), rec)
check("blank book and page stay blank (never the next label)", rec["book"] == "" and rec["page"] == "", rec)
check("parcels as BBLs, borough 5 + block(5) + lot(4)", [p["bbl"] for p in rec["parcels"]] == ["5012340056", "5000070008"], rec["parcels"])
check("parties keep the column the clerk typed in; the blank row dropped", rec["parties"] == [
    {"name": "SMITH, JOHN", "role": "GRANTOR", "column": "name", "person": "SMITH, JOHN", "company": ""},
    {"name": "ACME HOLDINGS LLC", "role": "GRANTEE", "column": "company", "person": "", "company": "ACME HOLDINGS LLC"}], rec["parties"])
check("image present", rec["image_state"] == "present")
check("the old 'Document No:' label (no period) still parses", richmond.parse_detail(detail_html(label="Document No:"))["instrument"] == "1008999")
prem = richmond.parse_detail(detail_html(instrument=""))
check("a same-day detail with no instrument yet is premature", prem["instrument"] == "" and richmond.premature(prem) and not richmond.premature(rec))
check("the shell and the unauthorized answer are not details (None, never a verdict)", richmond.parse_detail(SHELL) is None and richmond.parse_detail(UNAUTH) is None
      and not richmond.is_detail(SHELL) and richmond.is_detail(detail_html()))
today = dt.date.today()
young = "%d/%d/%d" % (today.month, today.day, today.year)
old = today - dt.timedelta(days=30)
check("no image + young = pending; no image + old = absent; unrecognised = unknown", (
    richmond.parse_detail(detail_html(recorded=young, image="none"))["image_state"],
    richmond.parse_detail(detail_html(recorded="%d/%d/%d" % (old.month, old.day, old.year), image="none"))["image_state"],
    richmond.parse_detail(detail_html(image="odd"))["image_state"]) == ("pending", "absent", "unknown"))
check("an unreadable date with no image is pending, never absent", richmond.image_state("No Image Available At This Time", "") == "pending")
check("detail_url is the walker's route", richmond.detail_url(" 1008999 ") == "https://www.richmondcountyclerk.com/Search/viewDocumentInfo/1008999")
json.dumps(rec)
check("the registry is JSON", True)

# ── fakes ────────────────────────────────────────────────────────────────────────────────
class FakeCloud:
    def __init__(self):
        self.need = set(); self.landed = []; self.todo_calls = []; self.fail_land = False
    def todo(self, ids):
        self.todo_calls.append(sorted(ids))
        return {i for i in ids if i in self.need}
    def land(self, rows, pending_age="1 hour"):
        self.pending_ages = getattr(self, "pending_ages", []) + [pending_age]
        if self.fail_land:
            raise RuntimeError("cloud down (simulated)")
        self.landed.extend(rows)
        return len(rows)

class FakeCrew:
    def __init__(self):
        self.q = queue.Queue(); self.results = []; self.failed = []; self.lock = threading.Lock(); self.cloud = FakeCloud(); self.width = 4
        self.stats = {"reqs": 0}; self.outbox = cloud.Outbox(HERE / "registration.outbox.jsonl")

class FakeCtx:
    def __init__(self):
        self.parked = None; self.args = types.SimpleNamespace(log=""); self.lines = []
    def park(self, why, code):
        self.parked = (code, why)

class FakeResp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status
    def close(self):
        pass

class FakeSession:
    """Answers by URL; records the order; the grant: a detail answers the shell unless this session saw its page."""
    def __init__(self, listing, details, fail_first=0, wall=False):
        self.listing, self.details, self.calls, self.granted = listing, details, [], set()
        self.fail_first, self.wall = fail_first, wall
    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if self.fail_first:
            self.fail_first -= 1
            raise requests.exceptions.ConnectionError("SSLError EOF (simulated)")
        if self.wall:
            return FakeResp("service unavailable", 503)
        if "DateRangeSearch" in url:
            n = int(url.rsplit("pageNumber=", 1)[1])
            html = self.listing.get(n, "<html>no rows</html>")
            self.granted.update(richmond.doc_id(r["internal_id"]) for r in richmond.parse_listing(html))
            return FakeResp(html)
        iid = url.rsplit("/", 1)[1]
        if richmond.doc_id(iid) not in self.granted:
            return FakeResp(SHELL)
        return FakeResp(self.details.get(iid, UNAUTH))

def listing_html(ids, page, of):
    rows = "".join('<tr><td data-label="Recorded">8/19/2026</td> <td data-label="Type">DEED</td> <td><a href="/Search/ViewDocumentInfo/%d"> <span aria-hidden="true">%d</span></a></td></tr>' % (i, 1000 + i) for i in ids)
    return "<table>%s</table><div>Page <span>%d</span> of %d</div>" % (rows, page, of)

def drain(crew):
    items = []
    while True:
        try:
            items.append(crew.q.get_nowait()[0])
        except queue.Empty:
            return items

R.lane._log = lambda ctx, msg: ctx.lines.append(msg)
today = dt.date(2026, 9, 3)
def make_role(edge_days_back=45, every=900):
    args = types.SimpleNamespace(edge=(today - dt.timedelta(days=edge_days_back)).isoformat(), days=30, every=every, pace=0.0, pending_age="1 hour")
    role = R.Registration(HERE, args)
    role.today = lambda: today
    return role

# ── the walker: page then details in one session ─────────────────────────────────────────
print("=== the walker: the page, then the details, in this session; the shell asked again; the wire and the wall")
role = make_role()
crew, ctx = FakeCrew(), FakeCtx()
sess = FakeSession({1: listing_html([990000001, 990000002, 990000003], 1, 2), 2: listing_html([990000004], 2, 2)},
                   {"990000001": detail_html(), "990000002": detail_html(instrument=""), "990000003": detail_html(image="odd")})
role.session = lambda: sess
kind, got = role.fetch(crew, ("page", "2026-08-05", "2026-09-03", 1), None)
check("a page item answers its rows and the page count", kind == "page" and len(got["rows"]) == 3 and got["pages"] == 2 and crew.stats["reqs"] == 1)
kind, got = role.fetch(crew, ("details", "2026-08-05", "2026-09-03", 1, ("RC_990000001", "RC_990000002", "RC_990000003", "RC_990000009")), None)
check("the page was fetched again first, then the details in order", [u.split("/")[-1] for u in sess.calls[1:]] == ["DateRangeSearch?StartSearchDate=2026-08-05&EndSearchDate=2026-09-03&SelectedDocumentIdentifier=0&pageNumber=1", "990000001", "990000002", "990000003"], sess.calls)
got = dict(got)
check("a full detail is a registry dict with the listing row and a timestamp", isinstance(got["RC_990000001"], dict) and got["RC_990000001"]["instrument"] == "1008999" and got["RC_990000001"]["listing"]["type"] == "DEED" and got["RC_990000001"]["at"])
check("a premature detail is pending", got["RC_990000002"] == "pending")
check("an unrecognised image state is asked again (None), never a verdict", got["RC_990000003"] is None)
check("an id the page no longer lists is asked again, not fetched", got["RC_990000009"] is None and "990000009" not in "".join(sess.calls))
check("requests counted for the crew's rate", crew.stats["reqs"] == 5)
cold = FakeSession({1: listing_html([990000001], 1, 1)}, {"990000001": detail_html()})
role.session = lambda: cold
kind, got = role.fetch(crew, ("details", "2026-08-05", "2026-09-03", 1, ("RC_990000001",)), None)
check("with the grant, the detail answers", got == [("RC_990000001", got[0][1])] and isinstance(got[0][1], dict))
cold.granted.clear()
cold.listing = {1: "<html>no rows</html>"}
kind, got = role.fetch(crew, ("details", "2026-08-05", "2026-09-03", 1, ("RC_990000001",)), None)
check("without the grant the shell comes back: asked again (None)", got == [("RC_990000001", None)])
role.session = lambda: FakeSession({1: listing_html([1], 1, 1)}, {}, fail_first=3)
R.time.sleep = lambda s: None
try:
    role.fetch(crew, ("page", "2026-08-05", "2026-09-03", 1), None); check("three wire failures raise Transport", False)
except lane.Transport as e:
    check("three wire failures raise Transport (the crew's hang-up breaker)", "ConnectionError" in str(e))
role.session = lambda: FakeSession({}, {}, wall=True)
try:
    role.fetch(crew, ("page", "2026-08-05", "2026-09-03", 1), None); check("a 503 raises HTTPStatus", False)
except lane.HTTPStatus as e:
    check("a 503 raises HTTPStatus (the crew's wall)", e.code == 503)
refusal = FakeSession({1: "<html><body>Access Denied - your request was blocked</body></html>"}, {})
role.session = lambda: refusal
try:
    role.fetch(crew, ("page", "2026-08-05", "2026-09-03", 1), None); check("a refusal shape raises Refused", False)
except lane.Refused:
    check("a refusal shape raises Refused (the crew parks)", True)
check("classify: a dict lands filled, pendings pending, a page blank", role.classify(("details", [("a", {"x": 1}), ("b", "pending")])) == "filled"
      and role.classify(("details", [("b", "pending")])) == "pending" and role.classify(("page", {})) == "blank" and role.classify(("details", [("a", None)])) == "blank")

# ── the monitor ──────────────────────────────────────────────────────────────────────────
print("=== the first feed: control, the catch-up from the edge, the trailing window")
role = make_role()
crew, ctx = FakeCrew(), FakeCtx()
role.feed(crew, ctx)
items = drain(crew)
check("the control is queued first", items[0] == ("control",) + richmond.CONTROL[:2] + (1,), items[:2])
catch = [k for k in items if k[0] == "page" and k[2] < (today - dt.timedelta(days=29)).isoformat()]
check("the catch-up covers edge+1 .. the day before the trailing window, page 1 of each window",
      catch and catch[0][1] == (today - dt.timedelta(days=44)).isoformat() and catch[-1][2] == (today - dt.timedelta(days=30)).isoformat() and all(k[3] == 1 for k in catch), catch)
trail = [k for k in items if k[0] == "page" and k[2] == today.isoformat()]
check("the trailing 30 days is one window, page 1", trail == [("page", (today - dt.timedelta(days=29)).isoformat(), today.isoformat(), 1)], trail)
check("the keys are JSON-friendly (the crew logs a failed item)", all(json.dumps(k) for k in items))
role.feed(crew, ctx)
check("nothing re-queued while everything is in flight", drain(crew) == [])
a, b = trail[0][1], trail[0][2]

print("=== landing: page 1 fans out the pages; the details only for what the table needs; registries through the outbox")
crew.results = [{"doc_id": ("control",) + richmond.CONTROL[:2] + (1,), "value": ("control", {"rows": richmond.parse_listing(listing_html([1, 2], 1, 18)), "pages": 18})},
                {"doc_id": ("page", a, b, 1), "value": ("page", {"rows": richmond.parse_listing(listing_html([990000001, 990000002, 990000003], 1, 3)), "pages": 3})}]
crew.cloud.need = {"RC_990000001", "RC_990000002"}
role.land(crew, ctx)
items = drain(crew)
check("pages 2 and 3 of the window are queued", ("page", a, b, 2) in items and ("page", a, b, 3) in items, items)
check("the table was asked about the page's ids", crew.cloud.todo_calls == [["RC_990000001", "RC_990000002", "RC_990000003"]], crew.cloud.todo_calls)
check("a details item carries only the ids that need work", ("details", a, b, 1, ("RC_990000001", "RC_990000002")) in items, items)
check("the control is no longer pending; the window knows its pages", not role.control_pending and role.windows[(a, b)]["pages"] == 3 and role.windows[(a, b)]["details"] == 1)
full = richmond.parse_detail(detail_html()); full["at"] = "t"; full["listing"] = {}
crew.results = [{"doc_id": ("details", a, b, 1, ("RC_990000001", "RC_990000002")), "value": ("details", [("RC_990000001", full), ("RC_990000002", "pending")])}]
role.land(crew, ctx)
check("both registries landed through the outbox: the dict and the pending", [(r["doc_id"], r["value"] if r["value"] == "pending" else "dict") for r in crew.cloud.landed] == [("RC_990000001", "dict"), ("RC_990000002", "pending")]
      and role.filled == 1 and role.pending == 1 and crew.outbox.count() == 0, crew.cloud.landed)
check("the edge has not moved: pages 2 and 3 are still out", role.edge == today - dt.timedelta(days=45))
crew.results = [{"doc_id": ("page", a, b, 2), "value": ("page", {"rows": richmond.parse_listing(listing_html([990000004], 2, 3)), "pages": 3})},
                {"doc_id": ("page", a, b, 3), "value": ("page", {"rows": [], "pages": 3})}]
crew.cloud.need = set()
role.land(crew, ctx)
check("the edge has still not moved: the catch-up windows are open (the edge never jumps an open window)", role.edge == today - dt.timedelta(days=45))
crew.results = [{"doc_id": k, "value": ("page", {"rows": [], "pages": 1})} for k in catch]     # the catch-up answers: empty windows
role.land(crew, ctx)
check("no details item when the table needs nothing", not any(k[0] == "details" for k in drain(crew)))
check("the trailing window is complete: the edge moved to today and was saved", role.edge == today and json.loads((HERE / "registration.edge.json").read_text())["edge"] == today.isoformat() and (a, b) not in role.windows)

print("=== a cloud hiccup: the landing waits in the outbox; a table read failure re-asks the page at the next walk")
crew.cloud.fail_land = True
crew.results = [{"doc_id": ("page", "2026-07-06", "2026-08-04", 1), "value": ("page", {"rows": richmond.parse_listing(listing_html([990000010], 1, 1)), "pages": 1})}]
crew.cloud.need = {"RC_990000010"}
role.land(crew, ctx)
drain(crew)
crew.results = [{"doc_id": ("details", "2026-07-06", "2026-08-04", 1, ("RC_990000010",)), "value": ("details", [("RC_990000010", full)])}]
role.land(crew, ctx)
check("the registry is kept in the outbox when the cloud is down", crew.outbox.count() == 1 and any("kept in the outbox" in l for l in ctx.lines))
crew.cloud.fail_land = False
crew.results = []
role.land(crew, ctx)
check("it lands at the next minute", crew.outbox.count() == 0 and crew.cloud.landed[-1]["doc_id"] == "RC_990000010")
crew.cloud.todo = lambda ids, age: (_ for _ in ()).throw(RuntimeError("connection lost (simulated)"))
crew.results = [{"doc_id": ("page", "2026-06-06", "2026-07-05", 1), "value": ("page", {"rows": richmond.parse_listing(listing_html([990000020], 1, 1)), "pages": 1})}]
role.land(crew, ctx)
check("a page whose ids could not be checked is re-asked at the next walk", ("page", "2026-06-06", "2026-07-05", 1) in role.reask)
crew.cloud.todo = FakeCloud.todo.__get__(crew.cloud)

print("=== holes: an item failing three asks; a detail failing three asks; the control")
key = ("page", "2026-05-07", "2026-06-05", 1)
for i in range(3):
    crew.failed = [(key, "SSLError (simulated)")]
    role.land(crew, ctx)
holes = [json.loads(l) for l in (HERE / "registration.holes.jsonl").read_text().splitlines()]
check("the page is asked twice more, then a hole, then on the re-ask list", drain(crew) == [key, key] and role.holes == 1 and holes[0]["item"] == list(key) and key in role.reask, holes)
role.windows[(a, b)] = {"pages": 1, "answered": {1}, "details": 1}
for i in range(3):
    crew.results = [{"doc_id": ("details", a, b, 1, ("RC_990000030",)), "value": ("details", [("RC_990000030", None)])}]
    role.land(crew, ctx)
    items = drain(crew)
    if i < 2:
        check("a detail with no answer is asked again (%d)" % (i + 1), items == [("details", a, b, 1, ("RC_990000030",))], items)
check("after three, the detail is a hole and nothing more is queued; the window's details count is back to zero", role.holes == 2 and items == [] and (a, b) not in role.windows)
ckey = ("control",) + richmond.CONTROL[:2] + (1,)
role.control_pending = True
for i in range(3):
    crew.failed = [(ckey, "timeout (simulated)")]
    role.land(crew, ctx)
check("a control failing three asks is a hole and no longer pending", not role.control_pending and role.holes == 3)

print("=== the cadence: the next walk queues the control, the trailing window and the re-asks")
role.inflight.clear()
role.next_walk = 0
role.feed(crew, ctx)
items = drain(crew)
check("a due walk: control first, the trailing window's page 1, the holes asked again", items[0] == ckey and ("page", a, b, 1) in items and key in items and ("page", "2026-06-06", "2026-07-05", 1) in items, items)

print("=== a broken control parks the lane (code 3)")
crew.results = [{"doc_id": ckey, "value": ("control", {"rows": [], "pages": None})}]
role.land(crew, ctx)
check("the control parsing no rows parks with PROBE BROKEN, code 3", ctx.parked and ctx.parked[0] == 3 and "PROBE BROKEN" in ctx.parked[1], ctx.parked)

print("=== the edge file: fail-closed start, mismatch refused, the catch-up skipped when the edge is fresh")
for f in HERE.glob("registration.edge.*"):
    f.unlink()
try:
    R.Registration(HERE, types.SimpleNamespace(edge="", days=30, every=900, pace=0.0, pending_age="1 hour")); check("a first start without --edge is refused", False)
except SystemExit as e:
    check("a first start without --edge is refused", "needs --edge" in str(e))
R.Registration(HERE, types.SimpleNamespace(edge="2026-08-25", days=30, every=900, pace=0.0, pending_age="1 hour"))._save_edge()
try:
    R.Registration(HERE, types.SimpleNamespace(edge="2026-08-01", days=30, every=900, pace=0.0, pending_age="1 hour")); check("an --edge that disagrees with the file is refused", False)
except SystemExit as e:
    check("an --edge that disagrees with the file is refused", "remove the file" in str(e))
for f in HERE.glob("registration.edge.*"):
    f.unlink()
role = make_role(edge_days_back=3)
crew, ctx = FakeCrew(), FakeCtx()
role.feed(crew, ctx)
items = drain(crew)
check("an edge inside the trailing window: no catch-up, just the control and the window", len(items) == 2 and items[1] == ("page", a, b, 1), items)
check("the state file names the run's counters", set(json.loads((HERE / "registration.edge.json").read_text())) >= {"edge", "at", "filled_this_run"} if (HERE / "registration.edge.json").exists() else True)

print("\nRICHMOND REG OFFLINE:", "ALL OK" if not fails else "FAILURES: %s" % fails)
sys.exit(1 if fails else 0)
