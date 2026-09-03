"""THE ACRIS RULES every acris lane shares: URLs minted from the id, the one user-agent, the refusal
detector, the page count, and where a document files in the One Touch layout.

Everything here was measured on the lanes that ran before this repo (ACRIS REPRODUCTION.md is the
authority); the dates in the comments say when.
"""
import hashlib
import html as _html
import pathlib
import re
import time

import storage
from lane import Refused

BASE = "https://a836-acris.nyc.gov/DS/DocumentSearch"

# ONE user-agent, set deliberately, never rotated (fetch_pages.py's history: the edge flipped four
# times between 08-24 and 08-31; this string is the one that has served the 1x40 ever since).
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      " (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# GetImage past the last page answers HTTP 200 with a fixed placeholder image: the end marker.
PLACEHOLDER_MD5 = "4081a3f2004d7244a966995c02c730d0"


def detail_url(doc_id):
    return BASE + "/DocumentDetail?doc_id=" + doc_id


def viewer_url(doc_id):
    return BASE + "/DocumentImageView?doc_id=" + doc_id


def image_url(doc_id, page):
    return "%s/GetImage?doc_id=%s&page=%d" % (BASE, doc_id, page)


# ── the refusal: HTTP 200 carrying the Bandwidth Notice page (never a status code) ──────────

NOTICE_SIGNALS = ("further access to acris is denied", "acris bandwidth notice",
                  "automated scripts/robots", "exceeded the bandwidth limits", "subscription data services")
REFUSALS_DIR = pathlib.Path(__file__).resolve().parent / "refusals"


def visible_text(data):
    """Markup stripped, entities resolved: the notice is Word-generated HTML whose sentences are
    split across tags, so the raw bytes never contain the phrase (measured 2026-08-06)."""
    t = data.decode("utf-8", "ignore")
    t = re.sub(r"<script.*?</script>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S | re.I)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def check_refused(data, ctype, where):
    """Raise Refused on the notice page; pass images and every other page.  The body is preserved
    beside this file so the verdict can be audited (2026-08-26: a detector that halted a night on
    a wifi interstitial had thrown its evidence away).  Two shapes are refusals: the notice's own
    phrases, or the word bandwidth at the top of a page that carries NO document."""
    if data[:2] in (b"II", b"MM") or data[:4] == b"%PDF":
        return
    text = visible_text(data)
    low = text.lower()
    hits = [s for s in NOTICE_SIGNALS if s in low]
    soft = "bandwidth" in low[:2000] and "document id" not in low
    if hits or "Bandwidth Notice" in text or soft:
        try:
            REFUSALS_DIR.mkdir(parents=True, exist_ok=True)
            (REFUSALS_DIR / ("refusal-%s.html" % time.strftime("%Y%m%d-%H%M%S"))).write_bytes(data)
        except Exception:
            pass
        raise Refused("ACRIS served its Bandwidth Notice at %s (%d/%d signals, %d bytes, ct=%s)"
                      % (where, len(hits), len(NOTICE_SIGNALS), len(data), ctype))


# ── the page count ──────────────────────────────────────────────────────────────────────────

_TOTAL = re.compile(r"TotalPages%22%3A(-?\d+)")


def total_pages(data):
    """TotalPages from the viewer page.  <= 0 is the source saying 'no image' (a true imageless
    document identifies itself).  None = a page without the token: an unknown shape, never a
    verdict (2026-08-28: a fixed 4,922-byte error page read as 0 produced thousands of false
    imageless verdicts in ten minutes)."""
    m = _TOTAL.search(data.decode("utf-8", "ignore"))
    return int(m.group(1)) if m else None


def is_placeholder(data):
    return hashlib.md5(data).hexdigest() == PLACEHOLDER_MD5


def is_tiff(data):
    return data[:2] in (b"II", b"MM")


# ── where a document files: borough / year / month from the registry ────────────────────────

_BORO_NAMES = {"MANHATTAN": 1, "BRONX": 2, "BROOKLYN": 3, "QUEENS": 4, "STATEN ISLAND": 5}
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _ym(text):
    m = _DATE.match((text or "").strip())
    if not m:
        return None
    mm, yy = int(m.group(1)), int(m.group(3))
    return (yy, mm) if 1 <= mm <= 12 else None


def borough_of(doc_id, registry):
    """The registry's own BOROUGH line, else the first parcel's bbl digit, else the microfilm id's
    borough digit (FT_<borough>...), else Unknown."""
    if isinstance(registry, dict):
        b = str(registry.get("borough", "")).upper().split("/")[0].strip()
        if b in _BORO_NAMES:
            return storage.BOROUGHS[_BORO_NAMES[b]]
        for p in registry.get("parcels") or []:
            bbl = str(p.get("bbl", ""))
            if bbl[:1].isdigit() and int(bbl[0]) in storage.BOROUGHS:
                return storage.BOROUGHS[int(bbl[0])]
    m = re.match(r"FT_(\d)", doc_id)
    if m and int(m.group(1)) in storage.BOROUGHS:
        return storage.BOROUGHS[int(m.group(1))]
    return "Unknown"


def recorded_ym(doc_id, registry):
    """(year, month) of the RECORDED date - the axis that aligns every source; the id's embedded date
    is the submission date and can lag recording by days.  Fallbacks: the document date, then a
    digital id's own date.  None for undated microfilm."""
    if isinstance(registry, dict):
        ym = _ym(registry.get("recorded")) or _ym(registry.get("doc_date"))
        if ym:
            return ym
    if len(doc_id) >= 8 and doc_id[:8].isdigit():
        yy, mm = int(doc_id[:4]), int(doc_id[4:6])
        if 1 <= mm <= 12 and 1900 < yy < 2100:
            return (yy, mm)
    return None


def canonical_path(doc_id, registry):
    """The One Touch address for this document."""
    borough = borough_of(doc_id, registry)
    ym = recorded_ym(doc_id, registry)
    if ym:
        return storage.canonical("acris", borough, ym[0], storage.month_folder(ym[1]), doc_id)
    return storage.canonical("acris", borough, "undated", "undated", doc_id)


def fresh(registry, days):
    """Recorded within the last `days`: a document without an image yet is pending, not absent."""
    if not isinstance(registry, dict):
        return False
    m = _DATE.match(str(registry.get("recorded", "")).strip())
    if not m:
        return False
    try:
        rec = time.mktime(time.strptime("%s/%s/%s" % m.groups(), "%m/%d/%Y"))
    except (ValueError, OverflowError):
        return False
    return (time.time() - rec) < days * 86400
