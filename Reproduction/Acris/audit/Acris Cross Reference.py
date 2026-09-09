"""Acris Cross Reference - hold every verdict in the document column against the registry we already hold.

Three cross-references, exactly as login set them out.  The first two need no door and no request to ACRIS at all: the
registration we pulled months ago already contains the answer, and it covers EVERY row, not a sample.

  absent   the registry carries a page count.  If a document is marked 'absent' and its registration says the document
           has pages, the absent is WRONG - we missed a document ACRIS holds.  The mere PRESENCE of a count is the
           signal; the VALUE of that count is not trusted for anything (see below).

  pending  the registry carries the RECORDING DATE IN ACRIS.  'pending' is only legal inside the scanning lag from that
           date.  If a document is marked 'pending' and it was recorded outside the lag, the pending is WRONG - it is
           either a path or an absent, and for as long as it sits pending it never gets the chance to become one.

  pages    THE REGISTRY'S PAGE COUNT CANNOT JUDGE OUR PDFs.  Registration undercounts: it counts the instrument and
           misses title pages, covers and riders, so a nine-page document can register as seven.  A pdf that differs
           from the registry is the NORMAL case and proves nothing.  The only authority for how many pages a document
           has is the viewer's hid_TotalPages, so that comparison runs through a door, on a sample, in `pages` mode.

Nothing is ever repaired here.  Each mode counts, prints, and writes the offending identifiers to a file, so that a
repair is a separate and deliberate act on a list a person has read.

    python "Acris Cross Reference.py" absent
    python "Acris Cross Reference.py" pending
    python "Acris Cross Reference.py" pages --port 1081 --limit 200
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
TOTAL = re.compile(r"TotalPages%22%3A(-?\d+)")   # the lane's own token; a looser one matches the %22 of the encoding
NOTICE = 25103                                   # the bandwidth refusal: the DOOR is refused, says nothing of the doc
LAG_DAYS = 7                                     # the scanning lag; only inside it is 'pending' a legal verdict
PAGE = 50000                                     # keyset page size: small enough that no statement hits a timeout

DATES = ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")

WITHHELD = "removed from the public view"        # ACRIS's own words when it pulls an image it still has a count for


def connect():
    import psycopg2
    con = psycopg2.connect(rulebook.dsn())
    con.autocommit = True
    cur = con.cursor()
    cur.execute("set statement_timeout='600s'")
    return con, cur


def walk(cur, verdict, fields):
    """Every row with this verdict, in identifier order, a page at a time.

    Keyset pagination on the primary key, never OFFSET and never `order by random()`: both scan the whole 21M-row table
    and cancel on the statement timeout, which is what killed two earlier attempts at this audit.  Only the few small
    text fields we actually judge on come back - never the whole registry blob, 21 million times.
    """
    sql = ("select identifier, %s from reproduction.acris"
           " where document = %%s and identifier > %%s order by identifier limit %%s" % fields)
    last, seen = "", 0
    while True:
        cur.execute(sql, (verdict, last, PAGE))
        rows = cur.fetchall()
        if not rows:
            return
        for r in rows:
            yield r
        last, seen = rows[-1][0], seen + len(rows)
        print("      ... %d %s rows read" % (seen, verdict), flush=True)


def recorded(text):
    """The RECORDING DATE IN ACRIS, off the registry - never the date we happened to look at the document."""
    for fmt in DATES:
        try:
            return datetime.datetime.strptime(str(text).strip(), fmt)
        except ValueError:
            pass
    return None


def do_absent(cur, out):
    """A page count in the registration means ACRIS holds the document.  'absent' over that is a document we lost."""
    wrong, nocount, withheld, total = [], 0, 0, 0
    for ident, pages, remarks in walk(cur, "absent", "registry->>'pages', registry->>'remarks'"):
        total += 1
        n = int(pages) if pages and str(pages).strip().isdigit() else 0
        if n <= 0:
            nocount += 1                      # the registration itself says there is nothing to fetch: absent is right
        elif remarks and WITHHELD in remarks:
            withheld += 1                     # ACRIS itself withdrew the image; the count is real, the image is not
        else:
            wrong.append((ident, n))
    print("\nABSENT  %d cells" % total)
    print("  %8d  registry shows no page count      - absent is correct" % nocount)
    print("  %8d  image withheld by ACRIS (remarks) - absent is correct" % withheld)
    print("  %8d  REGISTRY SHOWS PAGES              - ABSENT IS WRONG, the document was missed" % len(wrong))
    for ident, n in wrong[:15]:
        print("        %-20s registry says %d pages" % (ident, n))
    out("absent", [w[0] for w in wrong])
    return len(wrong)


def do_pending(cur, out):
    """'pending' is legal only inside the lag from the RECORDING DATE.  Outside it the cell can never resolve."""
    now = datetime.datetime.now()
    wrong, inside, undated, total = [], 0, [], 0
    for ident, rec in walk(cur, "pending", "coalesce(registry->>'recorded', registry->>'document_date')"):
        total += 1
        when = recorded(rec) if rec else None
        if when is None:
            undated.append(ident)             # pending with nothing at all to justify it
            continue
        age = (now - when).days
        if age > LAG_DAYS:
            wrong.append((ident, age))
        else:
            inside += 1
    print("\nPENDING %d cells" % total)
    print("  %8d  recorded inside the %d-day lag     - pending is correct" % (inside, LAG_DAYS))
    print("  %8d  no recording date at all          - PENDING IS WRONG, nothing justifies it" % len(undated))
    print("  %8d  RECORDED OUTSIDE THE LAG          - PENDING IS WRONG, must be redone as path or absent"
          % len(wrong))
    for ident, age in wrong[:15]:
        print("        %-20s recorded %d days ago (%.1f years)" % (ident, age, age / 365.0))
    out("pending", [w[0] for w in wrong] + undated)
    return len(wrong) + len(undated)


def door(port):
    import socks
    socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", port, rdns=True)
    socket.socket = socks.socksocket


def viewer_pages(doc_id):
    """hid_TotalPages from the viewer - THE ONLY authority on how many pages a document has."""
    r = urllib.request.Request("%s/DocumentImageView?doc_id=%s" % (BASE, doc_id),
                               headers={"User-Agent": UA, "Accept": "*/*", "Referer": BASE})
    try:
        with urllib.request.urlopen(r, timeout=45) as f:
            body = f.read()
    except Exception as e:
        return None, "viewer %s" % getattr(e, "code", type(e).__name__)
    if len(body) == NOTICE:
        return None, "bandwidth notice - the DOOR is refused"
    m = TOTAL.search(body.decode("utf-8", "ignore"))
    return (int(m.group(1)), "") if m else (None, "no TotalPages token")


def pdf_pages(path):
    """Pages in the pdf on the drive, counted from its own page objects - no library, no trust in our records."""
    try:
        b = pathlib.Path(path).read_bytes()
    except OSError:
        return None
    return len(re.findall(rb"/Type\s*/Page[^s]", b)) or None


def do_pages(cur, out, limit, prefixes):
    """Our pdf against the VIEWER's count.  The registry's count is not admissible here - it undercounts by design."""
    picked, per = [], max(4, (limit * 2) // max(1, len(prefixes)))
    for pre in prefixes:
        hi = pre[:-1] + chr(ord(pre[-1]) + 1)          # "2010" -> "2011": the next slice of the corpus, exclusive
        cur.execute("select identifier, document from reproduction.acris"
                    " where identifier >= %s and identifier < %s"
                    "   and document is not null and document not in ('pending','absent')"
                    " order by identifier limit %s", (pre, hi, per))
        picked += cur.fetchall()

    wrong, same, quiet, gone = [], 0, 0, 0
    for ident, doc in picked:
        if same + len(wrong) + quiet >= limit:
            break
        have = pdf_pages(doc)
        if have is None:
            gone += 1
            continue
        said, note = viewer_pages(ident)
        if said is None or said <= 0:
            quiet += 1                                 # no authority answered; never a verdict
            continue
        if have == said:
            same += 1
        else:
            wrong.append((ident, have, said))
    print("\nPAGES   %d pdfs judged against the viewer" % (same + len(wrong) + quiet))
    print("  %8d  pdf page count MATCHES the viewer - the pull was complete" % same)
    print("  %8d  no verdict (door refused / viewer silent)" % quiet)
    print("  %8d  named a file that is not on the drive" % gone)
    print("  %8d  PDF DIFFERS FROM THE VIEWER       - WE PULLED THE WRONG PAGE COUNT" % len(wrong))
    for ident, have, said in wrong[:15]:
        print("        %-20s pdf holds %d pages, viewer says %d" % (ident, have, said))
    out("pages", [w[0] for w in wrong])
    return len(wrong)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["absent", "pending", "pages"])
    ap.add_argument("--port", type=int, default=0, help="pages only: a live door's socks port")
    ap.add_argument("--limit", type=int, default=200, help="pages only: how many pdfs to judge")
    ap.add_argument("--prefixes", default="2006,2010,2014,2018,2022,2025",
                    help="pages only: identifier prefixes to sample across, via the primary key")
    ap.add_argument("--dir", default=r"C:\dev\cre-office\audit")
    a = ap.parse_args()

    where = pathlib.Path(a.dir)
    where.mkdir(parents=True, exist_ok=True)

    def out(name, ids):
        if not ids:
            return
        f = where / ("wrong.%s.json" % name)
        f.write_text(json.dumps(sorted(ids), indent=1), encoding="utf-8")
        print("        %d identifiers written to %s - NOTHING WAS REPAIRED" % (len(ids), f))

    if a.what == "pages":
        if not a.port:
            sys.exit("pages mode needs --port: the viewer is the only authority and it lives behind a door")
        door(a.port)
    con, cur = connect()
    started = datetime.datetime.now()
    if a.what == "absent":
        do_absent(cur, out)
    elif a.what == "pending":
        do_pending(cur, out)
    else:
        do_pages(cur, out, a.limit, [p.strip() for p in a.prefixes.split(",") if p.strip()])
    print("\n(started %s, %s elapsed)" % (started.strftime("%H:%M:%S"), datetime.datetime.now() - started))


if __name__ == "__main__":
    main()
