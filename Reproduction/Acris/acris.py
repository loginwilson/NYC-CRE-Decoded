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


def crfn_url(crfn):
    """The detail page reached by CRFN instead of by id: one GET, no session, no token (measured
    2026-08-23: hid_CRFN works as a query parameter on this route).  A live CRFN answers the same
    ~131 KB detail page as by id; an unissued one answers a ~10 KB stub with no document id."""
    return "%s/DocumentDetail?hid_CRFN=%d&SearchType=DocID" % (BASE, int(crfn))


MIN_DETAIL = 20_000     # a detail parsed from fewer bytes is suspect truncation, never reported live
_DOC_ID = re.compile(r"DOCUMENT ID:\s*([A-Za-z0-9_]{10,})")


def detail_doc_id(html):
    """The document id a detail page prints, or None for the stub (no document at that number)."""
    m = _DOC_ID.search(flat_text(html))
    return m.group(1) if m else None


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


# ── THE RECORDED DETAILS PAGE - the one place its format is known ─────────────────────────
# login, 2026-08-20: "all 4 url paths result in the exact same format so just figure it out once and
# you are good for all 24,039,303".  A second regex for the same page is how the same page gets
# learned wrong twice (a fresh regex once truncated MCON to "M" while this one read it right).
# Copied verbatim from rd_parse.py, which registered every document; not rewritten.
#
# Copy-paste rule: capture the page verbatim; omit only N/A, blank, or a flag-column N.  Tables
# classify themselves by their own header row, never by position (position bounding failed twice in
# one evening); the page nests 32 tables, so a real parser tracks the nesting and every table yields
# its own rows.  The caller asserts the id echo BEFORE parsing; parse_acris only reads.
from html.parser import HTMLParser

SECTIONS = ("PARTY 1", "PARTY 2", "PARTY 3", "PARCELS", "REFERENCES", "REMARKS")
GHOST = {"", "NAME", "PARTY 2", "PARTY 3/OTHER", "PARCELS", "BOROUGH", "REMARKS", "REFERENCES", "CRFN"}
# scalar labels, exactly as the page prints them (used verbatim in the next-label lookahead so a value
# can never swallow the following label)
LABELS = ("DOCUMENT ID", "CRFN", "COLLATERAL", "# of PAGES", "REEL-PAGE", "EXPIRATION DATE", "DOC. TYPE",
          "FILE NUMBER", "ASSESSMENT DATE", "DOC. DATE", "RECORDED / FILED", "SLID #", "DOC. AMOUNT",
          "BOROUGH", "% TRANSFERRED", "RPTT #", "MAP SEQUENCE #", "MESSAGE")
_NEXT = "|".join(re.escape(x) for x in LABELS)
FIELD_KEYS = (("DOC. TYPE", "type"), ("# of PAGES", "pages"), ("DOC. DATE", "doc_date"), ("CRFN", "crfn"),
              ("RECORDED / FILED", "recorded"), ("BOROUGH", "borough"), ("DOC. AMOUNT", "amount"),
              ("% TRANSFERRED", "pct"), ("SLID #", "slid"), ("ASSESSMENT DATE", "assessment"),
              ("EXPIRATION DATE", "expiration"), ("COLLATERAL", "collateral"), ("FILE NUMBER", "file_nbr"),
              ("RPTT #", "rptt"), ("MAP SEQUENCE #", "map_seq"), ("MESSAGE", "message"), ("REEL-PAGE", "reel_page"))
_TABLE_SIGS = {"party": ("NAME", "ADDRESS 1"), "parcels": ("BOROUGH", "BLOCK", "LOT"), "references": ("CRFN", "DOCUMENT ID")}


def clean_html(body_text):
    """entities unescaped BEFORE any parsing - '&nbsp;' is data-shaped noise"""
    return _html.unescape(body_text).replace("\xa0", " ")


def flat_text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def echoes(html, doc_id):
    """The page is about the requested document: it prints DOCUMENT ID: <id>.  A page that does not is
    a re-ask, not a failure and never a verdict (2026-08-28: 63% of a floor's requests under load)."""
    return re.search(r"DOCUMENT ID:\s*" + re.escape(doc_id), flat_text(html)) is not None


class _Tables(HTMLParser):
    """Every table yields its OWN rows regardless of depth; rows of inner tables are excluded from the
    outer table's rows - each cell text belongs to exactly one table."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # per open table: {"rows":[], "row":None, "pos"}
        self.cell = None
        self.done = []           # (rows, start_pos) in document order

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "pos": self.getpos()})
        elif tag == "tr" and self.stack:
            self.stack[-1]["row"] = []
        elif tag in ("td", "th") and self.stack:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.stack:
            t = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            if self.stack[-1]["row"] is not None:
                self.stack[-1]["row"].append(t)
            self.cell = None
        elif tag == "tr" and self.stack:
            row = self.stack[-1]["row"]
            if row is not None and any(row):
                self.stack[-1]["rows"].append(row)
            self.stack[-1]["row"] = None
        elif tag == "table" and self.stack:
            t = self.stack.pop()
            if t["rows"]:
                self.done.append((t["rows"], t["pos"]))

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def classified_tables(html):
    """[(kind, header_index_map, data_rows, char_pos)] for every table the page declares.  Twin-table
    layout handled: a header-only table's signature carries to the headerless data table after it."""
    p = _Tables()
    p.feed(html)
    starts = [0]
    for line in html.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    out = []
    pending = None
    for rows, (ln, col) in p.done:
        pos = starts[ln - 1] + col
        hdr = [c.upper().strip() for c in rows[0]]
        sig = next((k for k, s in _TABLE_SIGS.items() if all(x in hdr for x in s)), None)
        if sig:
            ix = {name: i for i, name in enumerate(hdr)}
            if len(rows) > 1:
                out.append((sig, ix, rows[1:], pos))
                pending = None
            else:
                pending = (sig, ix)
        elif pending:
            out.append((pending[0], pending[1], rows, pos))
            pending = None
    return out


def _panel_of(html, pos):
    """which PARTY panel a table belongs to: the nearest preceding title"""
    cands = [(html.upper().rfind(pn, 0, pos), pn[-1]) for pn in ("PARTY 1", "PARTY 2", "PARTY 3/OTHER")]
    k, panel = max(cands)
    return panel if k >= 0 else "?"


def parse_acris(html):
    """the WHOLE page -> the registry dict, copy-paste rule applied."""
    flat = flat_text(html)
    rec = {}
    for lab, key in FIELD_KEYS:
        g = re.search(re.escape(lab) + r":\s*(.{0,60}?)\s*(?=(?:" + _NEXT + r"):|$)", flat)
        v = (g.group(1) if g else "").strip()
        if v and v.upper() not in ("N/A", "N/A-N/A"):
            rec[key] = v
    parties, pcls, refs = [], [], []
    for kind, ix, rows, pos in classified_tables(html):
        get = lambda cs, col: (cs[ix[col]].strip() if col in ix and len(cs) > ix[col] else "")
        if kind == "party":
            panel = _panel_of(html, pos)
            for cs in rows:
                name = get(cs, "NAME")
                if not name or name.upper() in GHOST:
                    continue
                p = {"panel": panel, "name": name}
                for col, k in (("ADDRESS 1", "address"), ("ADDRESS 2", "address2"), ("CITY", "city"),
                               ("STATE", "state"), ("ZIP", "zip"), ("COUNTRY", "country")):
                    v = get(cs, col)
                    if v:
                        p[k] = v
                parties.append(p)
        elif kind == "parcels":
            for cs in rows:
                b = get(cs, "BOROUGH").upper().split("/")[0].strip()
                blk, lot = get(cs, "BLOCK"), get(cs, "LOT")
                if b in _BORO_NAMES and blk.isdigit() and lot.isdigit():
                    d = {"bbl": f"{_BORO_NAMES[b]}{int(blk):05d}{int(lot):04d}"}
                    for col, k in (("PARTIAL", "partial"), ("PROPERTY TYPE", "use"), ("PROPERTY ADDRESS", "address"),
                                   ("UNIT", "unit"), ("REMARKS", "remarks")):
                        v = get(cs, col)
                        if v and v.upper() != "N/A":
                            d[k] = v
                    for col, k in (("EASEMENT", "easement"), ("AIR RIGHTS", "air_rights"), ("SUBTERRANEAN RIGHTS", "subterranean")):
                        if get(cs, col).upper() == "Y":
                            d[k] = "Y"
                    pcls.append(d)
        elif kind == "references":
            # each value must LOOK like its column claims (a title cell or stray text can never
            # impersonate a crfn/doc id this way)
            _VALID = {"crfn": r"\d{13}", "doc_id": r"(FT_|BK_)?\d{8,20}", "borough": r"[A-Z ]{2,15}", "year": r"\d{2,4}",
                      "reel": r"\d{1,6}", "page": r"\d{1,5}", "file_nbr": r"[A-Z0-9-]{4,15}"}
            for cs in rows:
                r = {}
                for col, k in (("CRFN", "crfn"), ("DOCUMENT ID", "doc_id"), ("BOROUGH", "borough"), ("YEAR", "year"),
                               ("REEL", "reel"), ("PAGE", "page"), ("FILE NBR", "file_nbr")):
                    v = get(cs, col).replace(" ", "")
                    if v and v.upper() != "N/A" and re.fullmatch(_VALID[k], v, re.I):
                        r[k] = v
                if r and ("crfn" in r or "doc_id" in r or "file_nbr" in r):
                    refs.append(r)
    if parties:
        rec["parties"] = parties
    if pcls:
        rec["parcels"] = pcls
    if refs:
        rec["references"] = refs
    # REMARKS is a text box, not a table: take the textarea's own content
    m = re.search(r"<textarea[^>]*>(.*?)</textarea>", html, re.S | re.I)
    if m:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        if t:
            rec["remarks"] = t
    return rec
