"""THE RICHMOND RULES every richmond lane shares: the county's listing search, its window cap, the row
parser, the control window, the refusal shapes, and the id namespace.

Richmond County Clerk (Staten Island's recorded instruments, the pre-ACRIS and parallel corpus).
Everything here was measured on the lanes that ran before this repo (RICHMOND REPRODUCTION.md is the
authority); the dates in the comments say when.
"""
import datetime as dt
import re

import lane

BASE = "https://www.richmondcountyclerk.com"

# IDENTIFY HONESTLY.  The county serves the listing identically to any user-agent (measured
# 2026-08-18); this project names itself truthfully and never presents a fake fingerprint.
UA = "nyc-cre-decoded/1.0 (public land records indexing; contact via repo owner)"

# the date-range listing: GET, no session, no token; every row carries the recorded date, the type,
# the INTERNAL id (in the ViewDocumentInfo href) and the instrument number (measured 2026-08-21, the
# redesigned site).  A window longer than WINDOW_DAYS answers a SILENT ZERO (the measured cap).
WINDOW_DAYS = 30
START = dt.date(1850, 1, 1)         # predates organized county recording: the first nonzero window marks the true start
# a window KNOWN to hold documents: page 1 must parse rows or the parser is broken and no zero is believed
CONTROL = ("2026-08-19", "2026-08-20", 315)

_ROW = re.compile(
    r'data-label="Recorded">([^<]*)</td>\s*'
    r'<td[^>]*data-label="Type">([^<]*)</td>.*?'
    r'ViewDocumentInfo/(\d+)"[^>]*>\s*'
    r'<span aria-hidden="true">(\d+)</span>', re.S)
_PAGES = re.compile(r'Page\s*<span[^>]*>(\d+)</span>\s*of\s*(\d+)')


class Refused(lane.Refused):
    """The county declined (captcha, access denied, block page).  Stop; do not retry, do not rotate.
    A lane.Refused, so a crew parks on it exactly as on the ACRIS notice page."""


class ProbeBroken(RuntimeError):
    """The parser sees no rows where rows are KNOWN to exist: no zero from it may be believed."""


def listing_url(start, end, page=1):
    """start, end: ISO dates (YYYY-MM-DD), inclusive."""
    return ("%s/Search/DateRangeSearch?StartSearchDate=%s&EndSearchDate=%s&SelectedDocumentIdentifier=0&pageNumber=%d"
            % (BASE, start, end, int(page)))


def check_refused(html, where=""):
    low = html[:4000].lower()
    if "captcha" in low or "access denied" in low or ("blocked" in low and "ViewDocumentInfo" not in html):
        raise Refused("richmondcountyclerk served a refusal shape at %s - STOP" % (where or "the listing"))


def parse_listing(html):
    """Every document row on a listing page: recorded, type, internal_id, instrument.  Split per <tr> so
    the pattern can never bleed across rows (rc_window.py, 2026-08-21)."""
    out = []
    for chunk in html.split("<tr>"):
        m = _ROW.search(chunk)
        if m:
            out.append({"recorded": m.group(1).strip(), "type": m.group(2).strip(),
                        "internal_id": m.group(3), "instrument": m.group(4)})
    return out


def page_count(html):
    """'Page 1 of 18' -> 18; None when the page carries no pager (an empty window)."""
    m = _PAGES.search(html)
    return int(m.group(2)) if m else None


def doc_id(internal_id):
    """Our id for a county document: RC_ + the INTERNAL id (the ViewDocumentInfo key, unique).  Never the
    instrument number, which repeats across eras (two namespaces, 2026-08-21)."""
    return "RC_%s" % str(internal_id).strip()


# ── THE DETAIL PAGE - the recorded details, behind the grant ─────────────────────────────
# A detail unlocks only after the SAME SESSION fetched the listing page the id appears on (measured
# 2026-08-21): a cold GET answers HTTP 200 and a shell (4,212 bytes) or "INVALID REQUEST: UNAUTHORIZED
# SEARCH ACCESS" (2,180 bytes) - never a refusal, never an absence: our grant did not take.  So a reader
# fetches the page, then the details of that page's ids, in that order, in one session.  The parser is
# the one that landed 2.4M details (rc_rd_walk.parse_detail + rc_source.image_state), kept verbatim.
IMAGE_LAG_DAYS = 7          # "No Image Available At This Time" inside this lag is pending, outside it absent


def detail_url(internal_id):
    return "%s/Search/viewDocumentInfo/%s" % (BASE, str(internal_id).strip())


def is_detail(html):
    """The page carries the recorded details; the shell and the unauthorized answer do not."""
    return "RECORDED DETAILS" in re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def image_state(flat, recorded=""):
    """present | pending | absent | unknown - the ONE definition every reader shares.  The page publishes
    two things; the third state is derived from age against the lag (login 2026-08-25: "the lag determines
    the state").  Unrecognised is unknown, never a conclusion: ask again."""
    if "View Imaged Document" in flat or "ViewVscms" in flat:
        return "present"
    if "No Image Available At This Time" not in flat:
        return "unknown"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(recorded or "").strip())
    if not m:
        return "pending"                      # an unreadable date is always pending, never absent
    try:
        t = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return "pending"
    return "pending" if (dt.date.today() - t).days < IMAGE_LAG_DAYS else "absent"


def parse_detail(html):
    """RECORDED DETAILS + BLOCKS AND LOTS + PARTIES in the corpus schema, or None for a page that is not a
    detail (the shell, the unauthorized answer).  Parcels carry the BBL (borough 5 + block(5) + lot(4));
    parties keep the person/company COLUMN (the page tells where the clerk typed the name, not whether the
    party is a person - inferring the type manufactures a fact)."""
    raw = re.sub(r"&nbsp;?", " ", html)
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))
    if "RECORDED DETAILS" not in flat:
        return None

    def fld(label):
        m = re.search(label + r":\s*([^:]*?)\s*(?=[A-Z][a-z]+ ?[A-Z]?[a-z]*:|BLOCKS)", flat)
        return m.group(1).strip() if m else ""

    rec = {
        # the label is "Document No.:" on modern pages (a PERIOD before the colon) and "Document No:" on old
        # ones; a plain "Document No" + ":" matched only the old form and every same-day 2026 doc froze with
        # instrument '' (2026-08-22)
        "instrument": fld(r"Document No\.?"),
        "book": fld("Book"),
        "page": fld("Page"),
        "doc_type": fld("Document Type"),
        "recorded": fld("Date Recorded"),
        "amount": fld("Consideration Amount"),
        "status": re.sub(r"\s*View Imaged Document.*$", "", fld("Status")),
        "image_state": image_state(flat, fld("Date Recorded")),
        "parcels": [{"bbl": "5%s%s" % (b.zfill(5), l.zfill(4))} for b, l in re.findall(r"Block (\d+), Lot (\d+)", flat)],
        "parties": [],
    }
    in_parties = False
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if not cells:
            continue
        if cells[:3] == ["Name", "Company", "Party"]:
            in_parties = True
            continue
        if in_parties and len(cells) >= 3 and (cells[0] or cells[1]):
            person, company, role = cells[0], cells[1], cells[2]
            rec["parties"].append({"name": person or company, "role": role, "column": "name" if person else "company",
                                   "person": person, "company": company})
    return rec


def premature(rec):
    """A document registered the day it was recorded can carry no instrument number yet: the detail is not
    mature, and the registry is pending until it is (rc_rd_refresh, 2026-08-22)."""
    return not (rec or {}).get("instrument")


def windows(start=START, end=None, days=WINDOW_DAYS):
    """[(start, end)] inclusive date windows of at most `days` days from start to end (today)."""
    end = end or dt.date.today()
    days = max(1, min(int(days), WINDOW_DAYS))
    out = []
    d = start
    while d <= end:
        e = min(d + dt.timedelta(days=days - 1), end)
        out.append((d, e))
        d = e + dt.timedelta(days=1)
    return out
