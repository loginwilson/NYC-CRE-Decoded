"""OFFLINE checks of the enumeration lane: no index request, no cloud, no ACRIS.
The index client is exercised against a fake Socrata (paging with $order=:id, the count control, Void);
the gallop against a fake counter with holes; the classification, the shard plan and the identity math."""
import collections, importlib.util, json, pathlib, sys, types, time
PHASE = pathlib.Path(__file__).resolve().parents[2]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
import acris, lane
spec = importlib.util.spec_from_file_location("acris_enumeration", str(PHASE / "Acris" / "workflow" / "enumeration" / "Acris Enumeration.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)

# ── prefixes, bands, dates, years ──
check("next_prefix month", E.next_prefix("202408") == "202409")
check("next_prefix FT_19 -> FT_1:", E.next_prefix("FT_19") == "FT_1:" and "FT_19999" < "FT_1:" < "FT_20")
check("band_of", (E.band_of("202408"), E.band_of("FT_30"), E.band_of("BK_66")) == ("digital", "FT_", "BK_"))
try:
    E.band_of("2024"); check("band_of rejects a bad prefix", False)
except SystemExit:
    check("band_of rejects a bad prefix", True)
check("id_date", E.id_date("2024080100123001") == "20240801" and E.id_date("FT_3040005269504") == "")
gt = "2026-07-31"
check("classify tail", E.classify_extra("2026080500001001", "digital", gt) == "tail")
check("classify seam", E.classify_extra("2026072900001001", "digital", gt) == "seam")
check("classify omitted (old digital)", E.classify_extra("2016051200001001", "digital", gt) == "omitted")
check("classify film = omitted", E.classify_extra("FT_3040005269504", "FT_", gt) == "omitted")
check("classify odd", E.classify_extra("--51e970bd--", "digital", gt) == "odd")
check("parse_years", E.parse_years("2016,2003-2005", 2026) == [2003, 2004, 2005, 2016] and E.parse_years("", 2005) == [2003, 2004, 2005])

# ── the index client against a fake Socrata ──
class FakeSocrata:
    """rows = list of dicts; answers $select document_id / crfn / count(distinct ..) / substring group; honours $where on
    document_id ranges and crfn ranges; pages by $offset/$limit; can be told to answer [] once (the throttle)."""
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.throttle_once = False
    def __call__(self, dataset, params, timeout=180, tries=4):
        self.calls.append(dict(params))
        where = params.get("where", "")
        rows = [r for r in self.rows if self._match(r, where)]
        sel = params["select"]
        if self.throttle_once and not sel.startswith("count("):
            self.throttle_once = False
            return []
        if sel.startswith("count(distinct document_id)"):
            return [{"n": str(len({r["document_id"] for r in rows if r.get("document_id")}))}]
        if sel.startswith("count(distinct crfn)"):
            return [{"n": str(len({r["crfn"] for r in rows if r.get("crfn")}))}]
        if sel.startswith("count(distinct document_id) as ids"):
            raise AssertionError("state query not expected here")
        if sel.startswith("substring"):
            n = int(sel.split(",")[2].split(")")[0])
            c = collections.Counter(r["document_id"][:n] for r in rows)
            return [{"p": k, "n": str(v)} for k, v in sorted(c.items())]
        key = sel.strip()
        assert params.get("order") == ":id", "paging without $order=:id"
        off, lim = int(params.get("offset", 0)), int(params["limit"])
        return [{key: r[key]} for r in rows[off:off + lim] if r.get(key)]
    @staticmethod
    def _match(r, where):
        if not where:
            return True
        ok = True
        for part in where.split(" and "):
            col, op, val = part.split(" ", 2)
            val = val.strip("'")
            v = r.get(col) or ""
            ok = ok and ((v >= val) if op == ">=" else (v < val))
        return ok

rows = [{"document_id": "20240801%05d001" % i, "crfn": "2024%09d" % (100 + i)} for i in range(1, 8)]
rows += [{"document_id": "2024080100002001", "crfn": "2024000000102"}]            # a duplicate row: counted once
rows += [{"document_id": "2024090100001001", "crfn": "2024000000200"}]            # next month
fake = FakeSocrata(rows)
acris.socrata = fake
acris.SOCRATA_PAGE = 3                                                             # tiny pages: the walk must page
ids = acris.index_ids("x", "202408", "202409")
check("index_ids distinct, paged, complete (7 of 8 rows: one duplicate)", ids == {"20240801%05d001" % i for i in range(1, 8)}, ids)
check("index_ids paged with $order=:id", all(c.get("order") == ":id" for c in fake.calls if "offset" in c))
fake.throttle_once = True
try:
    acris.index_ids("x", "202408", "202409"); check("throttled [] is Void", False)
except acris.Void as e:
    check("throttled [] is Void", "pulled 0, counted 7" in str(e), e)
crfns = acris.index_crfns("x", 2024)
check("index_crfns sequences", crfns == set(range(101, 108)) | {200}, crfns)
pre = acris.index_prefixes("x", "2", "3", 6)
check("index_prefixes", pre == {"202408": 8, "202409": 1}, pre)
acris.SOCRATA_PAGE = 50000

# ── the gallop against a fake counter ──
class FakeCounter:
    def __init__(self, live, fail=()):
        self.live, self.fail, self.asked = set(live), set(fail), []
    def ask(self, crfn):
        self.asked.append(crfn)
        if crfn in self.fail:
            raise lane.Transport("SSLError (simulated)")
        return ("SIM-%013d" % crfn) if crfn in self.live else None

def probe_with(counter, width=2):
    args = types.SimpleNamespace(width=width, stagger=0.01, years="", retop=False, unpark=False, redial_wait=60, tries=4)
    here = pathlib.Path(r"C:\Users\smile\AppData\Local\Temp\claude\C--Users-smile\5d1473bc-bb54-490c-8d66-326f7b72067b\scratchpad\simlane")
    here.mkdir(exist_ok=True)
    E.HERE = here
    for f in here.glob("enumeration.*"):
        f.unlink()
    rep = E.Report(here, "offline")
    p = E.Probe(args, None, rep)
    p.ask = counter.ask
    return p

base = 2099 * 10 ** 9
# index top 30; live beyond: 31, 32; hole at 33-34 (void), then 35 live? no: 35 void. so issued = 32.
counter = FakeCounter(live={base + s for s in range(1, 33) if s not in (5, 9, 17)})
p = probe_with(counter)
issued, reqs = p.year_top(2099, 30)
check("gallop finds the top past the index (32)", issued == 32, (issued, reqs))
check("the gallop's control: the seed resolved first", counter.asked[0] == base + 30)
# the seed not resolving = the probe is broken = UNPROVEN, not a top
counter2 = FakeCounter(live=set())
p2 = probe_with(counter2)
check("a seed that does not resolve is UNPROVEN", p2.year_top(2099, 30) == (None, 1))
# a small hole past the top is not the edge: 33 void, 34 void, 35 live (FIB +3), then 36 live, 37 void... issued 36
counter3 = FakeCounter(live={base + s for s in range(1, 31)} | {base + 35, base + 36})
p3 = probe_with(counter3)
check("a hole past the top is climbed over (36)", p3.year_top(2099, 30)[0] == 36)
# three failed asks -> Retry (the year's top unproven), never a void
counter4 = FakeCounter(live={base + 30}, fail={base + 31})
p4 = probe_with(counter4)
try:
    p4.year_top(2099, 30); check("three failed asks raise, never read as void", False)
except lane.Retry as e:
    check("three failed asks raise, never read as void", "three asks failed" in str(e))

# ── identity math on a hand-made journal ──
p5 = probe_with(FakeCounter(live=set()))
p5.journal = {"numbers": {str(base + 5): {"v": "void"}, str(base + 9): {"v": "held", "doc_id": "a"},
                          str(base + 17): {"v": "MISSING", "doc_id": "b"}, str(base + 31): {"v": "held", "doc_id": "c"},
                          str(base + 32): {"v": "MISSING", "doc_id": "d"}},
              "tops": {"2099": {"issued": 32}}}
holes = {"2099": {"top": 30, "index": 27, "holes": [5, 9, 17]}}
code = p5.identity([2099], holes)
check("identity closed: 27 + 2 held + 2 missing + 1 void = 32, MISSING -> exit 1", code == 1 and "IDENTITY CLOSED" in p5.rep.lines[-1], p5.rep.lines[-1])
p5.journal["numbers"][str(base + 5)] = {"v": "unknown"}
check("an unknown number leaves the identity OPEN (exit 7 when nothing missing)", "OPEN (unknown numbers)" in (p5.identity([2099], holes), p5.rep.lines[-1])[1])

print("\nOFFLINE:", "ALL OK" if not fails else "FAILURES: %s" % fails)
sys.exit(1 if fails else 0)
