"""Acris Audit - prove, document by document, that what the table says is what ACRIS actually holds.

Written 2026-09-09, after changes I made to the documentation lane wrote verdicts it had no business writing.  There
are exactly three ways this table can be wrong, and each one is fatal in its own way:

  paths    a pdf on the drive with FEWER PAGES than the document really has - seven pages of a nine-page instrument.
           It looks complete, it passes every count we keep, and the missing pages are the exhibits and riders.
  absent   a document ACRIS DOES hold, marked as though it holds nothing.  Nothing ever asks for it again.
  pending  a document parked as "wait and see" when its recording date is years past the scanning lag, so it can never
           resolve to a path either.  'pending' is only ever legal INSIDE the lag from the RECORDING DATE IN ACRIS -
           never from the date we happened to look.

Every answer here comes from ACRIS through a door, never from our own records.  Nothing is repaired: the audit reports
and writes the offending identifiers to a file, so that a repair is a separate, deliberate act on a list a person has
read.

    python "Acris Audit.py" paths   --port 1080 --since "2026-09-09 01:35"  [--limit N]
    python "Acris Audit.py" absent  --port 1080  [--limit N]
    python "Acris Audit.py" pending --port 1080  [--limit N]
"""
import argparse
import datetime
import json
import pathlib
import re
import socket
import sys
import urllib.request

sys.path.insert(0, r"C:\dev\nyc-cre-decoded\Reproduction\rulebook")
import rulebook                                                    # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE = "https://a836-acris.nyc.gov/DS/DocumentSearch"

# THE LANE'S OWN PATTERN, AND THE ONLY CORRECT ONE.  A looser "TotalPages\D+(\d+)" matches the %22 of the URL encoding
# and reads 22 for every document on earth - which is exactly the mistake that had me telling login the count was a
# constant.  The real token is hid_TotalPages%22%3A<n>.
TOTAL = re.compile(r"TotalPages%22%3A(-?\d+)")
NOTICE_BYTES = 25103            # ACRIS's bandwidth refusal: the DOOR is blocked, and says nothing about the document
LAG_DAYS = 7                    # the scanning lag.  Only inside this window is 'pending' a legal verdict.


def door(port):
    """Route every request in this process through a door's socks tunnel."""
    import socks
    socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", port, rdns=True)
    socket.socket = socks.socksocket


def get(url, referer=BASE, timeout=45):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": referer})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return f.status, f.read()


def acris_pages(doc_id):
    """(TotalPages, note) straight from ACRIS.  None means ACRIS would not say - which is never a verdict."""
    try:
        st, body = get("%s/DocumentImageView?doc_id=%s" % (BASE, doc_id))
    except Exception as e:
        return None, "viewer %s" % getattr(e, "code", type(e).__name__)
    if len(body) == NOTICE_BYTES:
        return None, "the bandwidth notice - this DOOR is refused, nothing to do with the document"
    m = TOTAL.search(body.decode("utf-8", "ignore"))
    return (int(m.group(1)), "") if m else (None, "no TotalPages token (%d bytes)" % len(body))


def recorded(registry):
    """The RECORDING DATE IN ACRIS, from the registry - not the date we looked at it."""
    for key in ("recorded", "recorded_datetime", "document_date", "doc_date"):
        v = (registry or {}).get(key)
        if not v:
            continue
        for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(str(v).strip(), fmt)
            except ValueError:
                pass
    return None


def pdf_pages(path):
    """Pages in the pdf on the drive, counted from its own page objects - no library, no trust in our records."""
    try:
        b = pathlib.Path(path).read_bytes()
    except OSError as e:
        return None, "unreadable (%s)" % type(e).__name__
    n = len(re.findall(rb"/Type\s*/Page[^s]", b))
    return (n or None), ("" if n else "no page objects found")


def rows(cur, what, limit, prefixes=None):
    if what == "absent":
        sql = "select identifier, registry, document from reproduction.acris where document = 'absent'"
    elif what == "pending":
        sql = "select identifier, registry, document from reproduction.acris where document = 'pending'"
    else:
        sql = ("select identifier, registry, document from reproduction.acris"
               " where document is not null and document not in ('pending','absent')")
    # oldest-first judges the ORIGINAL code (the lowest ids certainly predate any change).  --prefixes takes slices of
    # the corpus by identifier range on the primary key - never order by random(), which scans all 21M rows and times
    # out.  Each prefix is year+month+day of the id.
    if prefixes:
        out, per = [], max(4, (limit * 3) // len(prefixes))
        for pre in prefixes:
            hi = pre[:-1] + chr(ord(pre[-1]) + 1)
            cur.execute(sql + " and identifier >= %s and identifier < %s order by identifier limit %s", (pre, hi, per))
            out += cur.fetchall()
        return out
    cur.execute(sql + " order by identifier limit %s", (limit,))
    return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["paths", "absent", "pending"])
    ap.add_argument("--port", type=int, required=True, help="a live door's socks port (cloud_doors.py keepers)")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--since", default="", help="paths only: only pdfs written after this local time (YYYY-MM-DD HH:MM)")
    ap.add_argument("--out", default="")
    ap.add_argument("--prefixes", default="", help="comma-separated identifier prefixes (year+month+day) to sample")
    a = ap.parse_args()
    a.prefixes = [p.strip() for p in a.prefixes.split(",") if p.strip()]
    door(a.port)

    import psycopg2
    con = psycopg2.connect(rulebook.dsn())
    con.autocommit = True
    cur = con.cursor()
    cur.execute("set statement_timeout='120s'")

    since = datetime.datetime.strptime(a.since, "%Y-%m-%d %H:%M") if a.since else None
    bad, checked, quiet = [], 0, 0

    for ident, registry, doc in rows(cur, a.what, a.limit, a.prefixes):
        if a.what == "paths":
            p = pathlib.Path(doc)
            if not p.is_file():
                bad.append((ident, "the table names a file that is not on the drive"))
                continue
            if since and datetime.datetime.fromtimestamp(p.stat().st_mtime) < since:
                continue
            said, note = acris_pages(ident)
            checked += 1
            if said is None:
                quiet += 1
                continue
            have, why = pdf_pages(p)
            if have is None:
                bad.append((ident, "pdf unreadable: %s" % why))
            elif said > 0 and have != said:
                bad.append((ident, "pdf holds %d pages, ACRIS says %d" % (have, said)))

        elif a.what == "absent":
            said, note = acris_pages(ident)
            checked += 1
            if said is None:
                quiet += 1
                continue
            if said > 0:
                bad.append((ident, "marked absent, but ACRIS holds %d pages" % said))

        else:                                          # pending
            checked += 1
            when = recorded(registry)
            if when is None:
                bad.append((ident, "marked pending with no recording date to justify it"))
                continue
            age = (datetime.datetime.now() - when).days
            if age > LAG_DAYS:
                bad.append((ident, "marked pending, recorded %d days ago - far outside the %d-day lag"
                            % (age, LAG_DAYS)))

    print("%s: %d checked, %d ACRIS would not answer, %d WRONG" % (a.what, checked, quiet, len(bad)))
    for ident, why in bad[:25]:
        print("   %-20s %s" % (ident, why))
    if bad:
        out = pathlib.Path(a.out or ("audit.%s.json" % a.what))
        out.write_text(json.dumps([b[0] for b in bad], indent=1), encoding="utf-8")
        print("   %d identifiers written to %s - nothing was repaired" % (len(bad), out))


if __name__ == "__main__":
    main()
