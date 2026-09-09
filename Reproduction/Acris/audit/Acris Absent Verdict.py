"""Acris Absent Verdict - how many of the registry's absent CANDIDATES are really documents we missed.

`Acris Cross Reference.py absent` asks the registration whether a document has pages.  That is a candidate list, not a
verdict, and it over-flags in one specific way we have measured: registration records the page count of the PAPER
INSTRUMENT the clerk received, and ACRIS may hold no image of it at all.  2006010300637001 is the type case - the
registry says 2 pages, the viewer says TotalPages=0, and 'absent' is the correct verdict for that cell.

So the candidate list goes to the only authority there is:

    viewer TotalPages > 0    ACRIS HOLDS THE DOCUMENT - the absent is a document we lost
    viewer TotalPages <= 0   ACRIS holds no image - the absent is right, registration was describing paper
    the door is refused      no verdict; the sample shrinks, it never guesses

A sample is enough to size the damage, because what is being measured is a RATE over 137,986 cells, not a list.  Run it
across two doors on different providers so one refused block cannot colour the answer.

    python "Acris Absent Verdict.py" --port 1200 --sample 200
"""
import argparse
import json
import pathlib
import random
import re
import socket
import sys
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE = "https://a836-acris.nyc.gov/DS/DocumentSearch"
TOTAL = re.compile(r"TotalPages%22%3A(-?\d+)")   # the lane's own token; a looser one matches the %22 of the encoding
NOTICE = 25103                                   # the bandwidth refusal: the DOOR is refused, says nothing of the doc


def door(port):
    import socks
    socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", port, rdns=True)
    socket.socket = socks.socksocket


def viewer_pages(doc_id):
    r = urllib.request.Request("%s/DocumentImageView?doc_id=%s" % (BASE, doc_id),
                               headers={"User-Agent": UA, "Accept": "*/*", "Referer": BASE})
    try:
        with urllib.request.urlopen(r, timeout=45) as f:
            body = f.read()
    except Exception as e:
        return None
    if len(body) == NOTICE:
        return None
    m = TOTAL.search(body.decode("utf-8", "ignore"))
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--list", default=r"C:\dev\cre-office\audit\wrong.absent.json")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    door(a.port)

    ids = json.loads(pathlib.Path(a.list).read_text(encoding="utf-8"))
    random.seed(a.seed or a.port)
    pick = random.sample(ids, min(a.sample, len(ids)))

    lost, right, quiet, pages = [], 0, 0, 0
    for i, ident in enumerate(pick, 1):
        n = viewer_pages(ident)
        if n is None:
            quiet += 1
        elif n > 0:
            lost.append((ident, n))
            pages += n
        else:
            right += 1
        if i % 25 == 0:
            print("   ... %d asked: %d lost, %d correctly absent, %d no answer"
                  % (i, len(lost), right, quiet), flush=True)

    judged = len(lost) + right
    print("\nABSENT CANDIDATES  %d of %d in the list, through the door on port %d" % (len(pick), len(ids), a.port))
    print("  %6d  the door would not answer - no verdict" % quiet)
    print("  %6d  viewer says 0 pages  - ABSENT IS CORRECT (registration described paper ACRIS never imaged)" % right)
    print("  %6d  viewer HOLDS PAGES   - ABSENT IS WRONG, a document we lost" % len(lost))
    if judged:
        rate = len(lost) / float(judged)
        print("\n  %.1f%% of judged candidates are real misses" % (100 * rate))
        print("  over the whole candidate list that is about %s cells, holding roughly %s pages"
              % ("{:,}".format(int(round(rate * len(ids)))),
                 "{:,}".format(int(round(rate * len(ids) * (pages / float(len(lost)) if lost else 0))))))
    for ident, n in lost[:12]:
        print("        %-20s viewer says %d pages" % (ident, n))


if __name__ == "__main__":
    main()
