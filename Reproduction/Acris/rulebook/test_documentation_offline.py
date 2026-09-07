"""Offline proof of the documentation lane's fetch, no source, no drive: `--trust-registry-pages` (PROPOSED 2026-09-07)
skips the viewer fetch only with the flag and a positive registry count; the viewer stays the authority otherwise.

    python test_documentation_offline.py
"""
import importlib.util, pathlib, sys, tempfile, threading

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parent.parent                                        # Reproduction/
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(HERE))
import acris                                                      # noqa: E402

spec = importlib.util.spec_from_file_location("acris_documentation", PHASE / "Acris" / "workflow" / "documentation" / "Acris Documentation.py")
doc = importlib.util.module_from_spec(spec); spec.loader.exec_module(doc)

TIFF = b"II*\x00" + b"\x00" * 64                                  # the TIFF magic; not the placeholder
VIEWER = b"...%7B%22TotalPages%22%3A4%2C..."                      # a viewer page saying 4 pages

class FakeCrew:
    def __init__(self, viewer=VIEWER):
        self.lock = threading.Lock(); self.stats = {"reask": 0}; self.ctx = None
        self.requests = []; self.viewer = viewer
    def get(self, url, referer, timeout=90):
        self.requests.append((url, referer))
        if "DocumentImageView" in url:
            return self.viewer, "text/html"
        return TIFF, "image/tiff"

# the file write: fake pdf bytes, a temp drive, a fixed canonical path
doc.img2pdf.convert = lambda frames: b"%PDF-fake " + bytes(len(frames))
doc.acris.canonical_path = lambda doc_id, registry: "Acris/By Document/2005/08 Aug/17/%s.pdf" % doc_id
doc.acris.is_tiff = lambda data: data.startswith(b"II*\x00")
doc.acris.is_placeholder = lambda data: False
doc.acris.check_refused = lambda body, ct, tag: None

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  <- " + detail))
    if not cond: fails += 1

root = tempfile.mkdtemp()
registry = {"pages": "4", "type": "DEED", "borough": "QUEENS"}

# 1. the proven walk: viewer + 4 pages = 5 requests
role = doc.Documentation(root, 30)
c = FakeCrew(); out = role.fetch(c, "2005081702043001", registry)
check("flag off: viewer + 4 pages = 5 requests", len(c.requests) == 5, str(len(c.requests)))
check("flag off: the first request is the viewer", "DocumentImageView" in c.requests[0][0])
check("flag off: the document lands as its canonical path", out.endswith("2005081702043001.pdf"), str(out))

# 2. the flag with a positive registry count: 4 pages, no viewer = 4 requests
role = doc.Documentation(root, 30, trust_registry_pages=True)
c = FakeCrew(); out = role.fetch(c, "2005081702043002", registry)
check("flag on: 4 pages, no viewer = 4 requests", len(c.requests) == 4, str(len(c.requests)))
check("flag on: no viewer request at all", not any("DocumentImageView" in u for u, _ in c.requests))
check("flag on: GetImage keeps the viewer URL as its Referer", all("DocumentImageView" in r for _, r in c.requests))
check("flag on: pages 1..4 in order", [u.split("page=")[1] for u, _ in c.requests] == ["1", "2", "3", "4"])

# 3. the flag but no usable count: the viewer decides (fallback), 5 requests
for i, bad in enumerate(({"pages": "0"}, {"pages": ""}, {"pages": "n/a"}, {}, {"pages": None})):
    c = FakeCrew(); role.fetch(c, "20050817020430%02d" % (10 + i), dict(bad, type="DEED"))   # a fresh id each: a landed file is never re-fetched
    check("flag on, registry pages=%r: falls back to the viewer (5 requests)" % (bad.get("pages"),), len(c.requests) == 5, str(len(c.requests)))

# 4. registry_pages itself
check("registry_pages('4') == 4", doc.registry_pages({"pages": "4"}) == 4)
check("registry_pages(' 12 ') == 12", doc.registry_pages({"pages": " 12 "}) == 12)
check("registry_pages('0') is None", doc.registry_pages({"pages": "0"}) is None)
check("registry_pages(non-dict) is None", doc.registry_pages("pending") is None)

# 5. the flag never decides 'absent': a zero count goes to the viewer, and the viewer's 0 makes the call
role = doc.Documentation(root, 30, trust_registry_pages=True)
c = FakeCrew(viewer=b"x TotalPages%22%3A0 y"); out = role.fetch(c, "2005081702043004", {"pages": "0", "type": "DEED"})
check("flag on, registry 0, viewer 0: the viewer's verdict (pending/absent), one request", out in ("pending", "absent") and len(c.requests) == 1, "%s / %d" % (out, len(c.requests)))

print("\n%d check(s) failed" % fails if fails else "\nALL OK")
sys.exit(1 if fails else 0)
