"""OFFLINE checks of the richmond enumeration lane: the listing parser on the county's markup shape, the window
arithmetic, the id namespace, the refusal shapes, the ledger, the comparison, the trailing-window verdicts and the
census sweep - against a FAKE county and a FAKE cloud.  No request, no cloud."""
import datetime as dt, importlib.util, json, pathlib, sys, types
PHASE = pathlib.Path(__file__).resolve().parents[2]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))
import lane, richmond
spec = importlib.util.spec_from_file_location("richmond_enumeration", str(PHASE / "Richmond" / "workflow" / "enumeration" / "Richmond Enumeration.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

HERE = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
HERE.mkdir(exist_ok=True)
for f in HERE.glob("enumeration.*"):
    f.unlink()
E.HERE = HERE

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)


def page(rows, n, total):
    """a listing page in the county's markup shape (rc_window.py, 2026-08-21)"""
    body = ""
    for rec, typ, iid, inst in rows:
        body += ('<tr><td data-label="Recorded">%s</td>\n<td class="x" data-label="Type">%s</td><td data-label="Instrument">'
                 '<a href="/Search/ViewDocumentInfo/%s" class="btn"> <span aria-hidden="true">%s</span></a></td></tr>' % (rec, typ, iid, inst))
    return '<html><table><tr><th>Recorded</th></tr>%s</table><div>Page <span class="fw-bold">%d</span> of %d</div></html>' % (body, n, total)


# ── the parser, the pager, the namespace, the refusal shapes ──
html = page([("8/19/2026", "DEED", "2826001", "1008999"), ("8/19/2026", "MTGE", "2826002", "1009000")], 1, 18)
rows = richmond.parse_listing(html)
check("parse_listing: two rows with recorded, type, internal id, instrument", rows == [
    {"recorded": "8/19/2026", "type": "DEED", "internal_id": "2826001", "instrument": "1008999"},
    {"recorded": "8/19/2026", "type": "MTGE", "internal_id": "2826002", "instrument": "1009000"}], rows)
check("page_count 18; none on a page without a pager", richmond.page_count(html) == 18 and richmond.page_count("<html>nothing</html>") is None)
check("doc_id is RC_ + the internal id", richmond.doc_id("2826001") == "RC_2826001" and richmond.doc_id(7) == "RC_7")
try:
    richmond.check_refused("<html><body>Access Denied</body></html>", "x"); check("access denied is a refusal", False)
except richmond.Refused:
    check("access denied is a refusal", True)
try:
    richmond.check_refused(html, "x"); check("a listing page is not a refusal", True)
except richmond.Refused:
    check("a listing page is not a refusal", False)
w = richmond.windows(dt.date(2026, 1, 1), dt.date(2026, 3, 15), 30)
check("windows: 30-day spans, inclusive, the last clamped to the end", w[0] == (dt.date(2026, 1, 1), dt.date(2026, 1, 30)) and w[1][0] == dt.date(2026, 1, 31)
      and w[-1][1] == dt.date(2026, 3, 15) and all((e - s).days <= 29 for s, e in w), w)
check("windows never exceed the cap even if asked", all((e - s).days <= 29 for s, e in richmond.windows(dt.date(2026, 1, 1), dt.date(2026, 3, 1), 45)))
check("the whole history is about 2,150 windows", 2100 < len(richmond.windows()) < 2200, len(richmond.windows()))

# ── a fake county and a fake cloud ──
class FakeCounty:
    """windows -> rows; a window may fail (Transport) or refuse; the control parses rows"""
    def __init__(self, listing, fail=(), refuse=()):
        self.listing, self.fail, self.refuse = listing, set(fail), set(refuse)
        self.stop = __import__("threading").Event()
        self.lock = __import__("threading").Lock()
        self.reqs = 0
        self.session = types.SimpleNamespace(close=lambda: None)
    def control(self):
        return 315
    def window(self, s, e):
        self.reqs += 1
        if s in self.refuse:
            self.stop.set()
            raise richmond.Refused("captcha (simulated) at %s" % s)
        if s in self.fail:
            raise lane.Transport("SSLError (simulated) at %s" % s)
        rows = [r for r in self.listing if s <= r["date"] <= e]
        return [{"recorded": r["date"].strftime("%m/%d/%Y"), "type": "DEED", "internal_id": str(r["id"]), "instrument": "1"} for r in rows], max(1, len(rows) // 18 + 1)

class FakeCloud:
    def __init__(self, held):
        self.held_ids = set(held)
    def held(self, ids):
        return {i for i in ids if i in self.held_ids}
    def ids(self, lo, hi=None):
        return {i for i in self.held_ids if i >= lo and (hi is None or i < hi)}
    def count(self, lo=None, hi=None):
        return len(self.ids(lo or "", hi))

listing = [{"date": dt.date(2026, 8, 10) + dt.timedelta(days=i % 20), "id": 990000000 + i} for i in range(100)]
held = {"RC_%d" % (990000000 + i) for i in range(100) if i != 42 and i != 77}
county = FakeCounty(listing)
c = FakeCloud(held)
args = types.SimpleNamespace(days=30, workers=2, pace=0.0)

print("=== the trailing window against the table")
rep = E.Report(HERE)
wins = [(dt.date(2026, 8, 1), dt.date(2026, 8, 30))]
listed, heldn, missing, unproven = E.audit_windows(args, c, rep, county, wins, "the trailing 30 days")
code = E.verdict(rep, listed, missing, unproven)
check("100 listed, 98 held, 2 missing -> exit 1, both listed", (listed, heldn, len(missing), code) == (100, 98, 2, 1) and missing == ["RC_990000042", "RC_990000077"]
      and (HERE / "enumeration.missing.txt").read_text().split() == missing, (listed, heldn, missing, code))
c.held_ids |= set(missing)
listed, heldn, missing, unproven = E.audit_windows(args, c, rep, county, wins, "again")
check("everything held -> the difference is 0, exit 0", E.verdict(rep, listed, missing, unproven) == 0 and not missing)
listed, heldn, missing, unproven = E.audit_windows(args, c, rep, county, [(dt.date(1850, 1, 1), dt.date(1850, 1, 30))], "an empty window")
check("an empty window is UNPROVEN (exit 7), never a pass", E.verdict(rep, listed, missing, unproven) == 7 and unproven)
check("clamp_days clamps 45 to 30", E.clamp_days(45, rep) == 30 and E.clamp_days(7, rep) == 7)

print("=== the census against the fake county: sweep, a failed window left unswept, resume, the report")
for f in HERE.glob("enumeration.*"):
    f.unlink()
richmond.START = dt.date(2026, 7, 1)                      # a short history for the test
today = dt.date.today()
wins_all = richmond.windows(richmond.START, today, 30)
fail_win = wins_all[0][0]                                 # the empty first window fails; the rows sit in the second
county = FakeCounty(listing, fail={fail_win})
c = FakeCloud({"RC_%d" % (990000000 + i) for i in range(100)} | {"RC_990009999"})     # one phantom: held, never listed
code = E.census(types.SimpleNamespace(days=30, workers=2, pace=0.0), c, rep, county)
led = E.Ledger(HERE / "enumeration.census.db")
swept = led.swept()
check("every window swept but the failed one; the failed one left unswept", len(swept) == len(wins_all) - 1 and fail_win.isoformat() not in swept, (len(swept), len(wins_all)))
check("the sweep's report: incomplete -> exit 7 (the identity waits)", code == 7, code)
check("listed ids recorded in the ledger", len(led.listed()) == 100, len(led.listed()))
led.close()
county = FakeCounty(listing)                                # the failed window answers now
code = E.census(types.SimpleNamespace(days=30, workers=2, pace=0.0), c, rep, county)
led = E.Ledger(HERE / "enumeration.census.db")
check("resume swept only the failed window and the trailing one", county.reqs == 2, county.reqs)
check("complete sweep: MISSED 0, one phantom named, the identity closes -> exit 0", code == 0 and any("100% COVERAGE" in l for l in rep.lines) and any("held, never listed: 1" in l for l in rep.lines), [l for l in rep.lines[-8:]])
led.close()

print("=== a refusal stops the sweep")
for f in HERE.glob("enumeration.*"):
    f.unlink()
county = FakeCounty(listing, refuse={wins_all[0][0]})
try:
    E.census(types.SimpleNamespace(days=30, workers=2, pace=0.0), c, rep, county)
    check("a refusal is raised out of the sweep", False)
except richmond.Refused as e:
    check("a refusal is raised out of the sweep", "captcha" in str(e))

print("\nRICHMOND ENUMERATION OFFLINE:", "ALL OK" if not fails else "FAILURES: %s" % fails)
sys.exit(1 if fails else 0)
