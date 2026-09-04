"""THE RICHMOND RULES every richmond lane shares: the county's listing search, its window cap, the row
parser, the control window, the refusal shapes, and the id namespace.

Richmond County Clerk (Staten Island's recorded instruments, the pre-ACRIS and parallel corpus).
Everything here was measured on the lanes that ran before this repo (RICHMOND REPRODUCTION.md is the
authority); the dates in the comments say when.
"""
import datetime as dt
import re

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


class Refused(RuntimeError):
    """The county declined (captcha, access denied, block page).  Stop; do not retry, do not rotate."""


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
