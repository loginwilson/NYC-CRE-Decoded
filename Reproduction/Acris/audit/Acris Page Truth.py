"""Acris Page Truth - is a pdf on the drive COMPLETE?

The documentation lane can only ever write a pdf whose page count equals ACRIS's own hid_TotalPages: it fetches pages
1..total and raises Retry if a single one is missing, then writes the file whole or not at all.  So the entire
question of "have we been pulling seven pages of nine-page documents" reduces to ONE thing:

    IS THE VIEWER'S TotalPages EVER LOWER THAN THE TRUE PAGE COUNT?

And that is decisive to test without trusting anything of ours.  Take a landed pdf, count its pages, and ask ACRIS for
the page AFTER the last one:

    a real TIFF comes back      -> the count UNDERCOUNTED and the pdf on the drive is SHORT
    the end marker (13,684 b)   -> the document ends exactly where the pdf ends: COMPLETE
    404                         -> there is no such page: COMPLETE

Run it against pdfs written BEFORE a given time to judge the original code, and after it to judge a change.

    python "Acris Page Truth.py" --port 1081 --limit 60 --before "2026-09-09 01:35"
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
TOTAL = re.compile(r"TotalPages%22%3A(-?\d+)")     # the lane's own token; a looser pattern reads the %22 of the encoding
MARKER = 13684                                     # ACRIS's end-of-document placeholder
NOTICE = 25103                                     # the bandwidth refusal: the DOOR is blocked, says nothing about pages


def door(port):
    import socks
    socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", port, rdns=True)
    socket.socket = socks.socksocket


def get(url, referer=BASE, timeout=45):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": referer})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return f.status, f.read()


def pdf_pages(path):
    try:
        b = pathlib.Path(path).read_bytes()
    except OSError:
        return None
    return len(re.findall(rb"/Type\s*/Page[^s]", b)) or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--before", default="", help="only pdfs written before this local time (YYYY-MM-DD HH:MM)")
    ap.add_argument("--after", default="", help="only pdfs written after this local time")
    ap.add_argument("--prefixes", default="2010031,2015062,2019091,2022041",
                    help="comma-separated identifier prefixes (year+month+day) to sample from, via the primary key")
    a = ap.parse_args()
    a.prefixes = [p.strip() for p in a.prefixes.split(",") if p.strip()]
    door(a.port)

    import psycopg2
    con = psycopg2.connect(rulebook.dsn())
    con.autocommit = True
    cur = con.cursor()
    cur.execute("set statement_timeout='120s'")
    # SAMPLE BY IDENTIFIER RANGE, NEVER BY random().  order by random() over 21M rows is a full scan and a sort, and
    # timed out at 120 s twice.  A range on the primary key answers in milliseconds.  Each prefix is one slice of the
    # corpus (year+month+day of the id), and the per-prefix limit keeps the sample spread across them.
    picked = []
    per = max(4, (a.limit * 3) // max(1, len(a.prefixes)))
    for pre in a.prefixes:
        hi = pre[:-1] + chr(ord(pre[-1]) + 1)          # "2006052" -> "2006053": the next slice, exclusive
        cur.execute("select identifier, document from reproduction.acris"
                    " where identifier >= %s and identifier < %s"
                    "   and document is not null and document not in ('pending','absent')"
                    " order by identifier limit %s", (pre, hi, per))
        picked += cur.fetchall()
    cur.close()
    rows_out = picked

    before = datetime.datetime.strptime(a.before, "%Y-%m-%d %H:%M") if a.before else None
    after = datetime.datetime.strptime(a.after, "%Y-%m-%d %H:%M") if a.after else None

    short, complete, quiet, missing = [], 0, 0, 0
    for ident, doc in rows_out:
        if complete + len(short) + quiet >= a.limit:
            break
        p = pathlib.Path(doc)
        if not p.is_file():
            missing += 1
            continue
        when = datetime.datetime.fromtimestamp(p.stat().st_mtime)
        if before and when >= before:
            continue
        if after and when < after:
            continue
        have = pdf_pages(p)
        if not have:
            quiet += 1
            continue
        try:
            st, body = get("%s/GetImage?doc_id=%s&page=%d" % (BASE, ident, have + 1),
                           "%s/DocumentImageView?doc_id=%s" % (BASE, ident))
        except Exception as e:
            if getattr(e, "code", 0) == 404:
                complete += 1                       # no such page: the pdf ends where the document ends
            else:
                quiet += 1
            continue
        if len(body) == NOTICE:
            quiet += 1                              # the door is refused; no verdict
        elif len(body) == MARKER:
            complete += 1                           # ACRIS's end marker sits right after the last page
        elif body[:2] in (b"II", b"MM"):
            short.append((ident, have, len(body), str(p)))
        else:
            quiet += 1

    print("pdfs judged: %d complete, %d SHORT, %d no verdict, %d named a file not on the drive"
          % (complete, len(short), quiet, missing))
    for ident, have, n, path in short[:20]:
        print("   %-20s pdf holds %d pages, ACRIS served a real page %d of %d bytes" % (ident, have, have + 1, n))
    if short:
        out = pathlib.Path("audit.short_pdfs.json")
        out.write_text(json.dumps([s[0] for s in short], indent=1), encoding="utf-8")
        print("   %d identifiers written to %s - nothing was repaired" % (len(short), out))


if __name__ == "__main__":
    main()
