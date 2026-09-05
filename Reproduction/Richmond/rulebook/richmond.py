"""THE RICHMOND RULES every richmond lane shares: the county's listing search, its window cap, the row
parser, the control window, the refusal shapes, and the id namespace.

Richmond County Clerk (Staten Island's recorded instruments, the pre-ACRIS and parallel corpus).
Everything here was measured on the lanes that ran before this repo (Richmond Reproduction.md is the
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


# ── THE IMAGE - minted on the clerk, served by the courts ────────────────────────────────
# TWO HOSTS.  The clerk MINTS: GET /ViewVscmsDocument/ViewContent?p_endorsementId=<internal id> with
# redirects OFF answers a 302 whose Location is a self-authenticating token url on the NY State courts
# viewer (iapps.courts.state.ny.us/vscms_public/viewer?token=v2...) - the pdf never lives on the clerk.
# THREE OUTCOMES, never two (login 2026-08-25: "we have the url, if it doesnt show, its absent, if it
# shows a fetch its pdf, and if its absent but the recorded date of the doc id is in the lag period it
# gets pending"), measured 2026-08-26 on one session:
#     RC_2825613 (image up)  -> 302  https://iapps.courts.state.ny.us/vscms_public/viewer?token=v2...
#     RC_2820269 (no image)  -> 302  /Search/SearchError          (the clerk's OWN error page)
# so the test is "an ABSOLUTE url we can fetch", never "any Location at all"; 200 (no redirect) and 404
# are dead ends too; 403/429/5xx say nothing about the DOCUMENT - ours, asked again.  The mint takes a
# bare id: NO grant rule here (the detail's grant is the listing page; the image's is the token).
# The token EXPIRES (~10 min measured 2026-08-22): mint and pull in one breath, never a buffer of tokens.
# THE COURTS HOST GATES ON THE USER-AGENT - measured 2026-08-22, one variable, everything else identical:
#     python-requests/2.34.2 (library default)  -> ReadTimeout at 45 s, 2/2   (a HANG, not a refusal)
#     this project's honest UA                  -> 200 + the full pdf in 1.5 s, 2/2
# so the pull carries the same honest UA (a browser string was measured to buy nothing and would make the
# client dishonest).  A pdf is a pdf only when the body starts with %PDF.
IAPPS = "https://iapps.courts.state.ny.us"
PULL_HEADERS = {"Referer": BASE + "/", "Accept": "application/pdf,*/*"}
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def mint_url(internal_id):
    return "%s/ViewVscmsDocument/ViewContent?p_endorsementId=%s" % (BASE, str(internal_id).strip())


def mint_referer(internal_id):
    return "%s/Search/ViewDocumentInfo/%s" % (BASE, str(internal_id).strip())


def classify_mint(status, location):
    """The mint's answer -> ('present', token url) | ('noimage', None) | ('error', None)."""
    if status in (301, 302, 303, 307, 308):
        loc = (location or "").strip()
        if loc[:8].lower().startswith(("http://", "https://")):
            return "present", loc
        return "noimage", None                     # a relative Location (/Search/SearchError) is the clerk's error page
    if status in (200, 404):
        return "noimage", None                     # the endpoint answered and handed us no image location
    return "error", None                           # 403/429/5xx: about us, never about the document


def is_pdf(data):
    return len(data) >= 5 and data[:4] == b"%PDF"


def recorded_date(registry):
    """The recorded date in the registry (M/D/YYYY, as the clerk prints it) as a date, or None."""
    if not isinstance(registry, dict):
        return None
    m = _DATE.match(str(registry.get("recorded", "") or "").strip())
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def fresh(registry, days=IMAGE_LAG_DAYS):
    """Inside the scan lag: a document with no image yet is pending, not absent.  An UNREADABLE date is
    always inside the lag - guessing wrong here records a scanned document as having no scan forever;
    staying pending costs one re-ask (rc_lane._in_lag, 2026-08-26)."""
    rec = recorded_date(registry)
    if rec is None:
        return True
    return (dt.date.today() - rec).days < int(days)


def canonical_path(doc_id, registry):
    """The One Touch address: richmond has no borough; year and month from the RECORDED date (the id's
    digits are a submission sequence, not a date), else undated."""
    import storage
    rec = recorded_date(registry)
    if rec is None:
        return storage.canonical("richmond", None, "undated", "undated", doc_id)
    return storage.canonical("richmond", None, rec.year, storage.month_folder(rec.month), doc_id)
