"""Acris Absent Proof - stop asking ACRIS what it has and make it hand the page over.

login: "the viewer amount may actually be right.  it is possible those crfn that we have absent dont have documents?
but still i dont trust it."  Correct on both counts, so this program removes the question.  Neither the registration nor
the viewer is asked to be believed here: for each cell marked 'absent', GetImage is called for page 1 and the BYTES
decide.

    a real TIFF (II/MM)      THE DOCUMENT EXISTS.  We marked absent a document ACRIS will hand to anyone who asks.
    the end marker (13,684)  ACRIS's end-of-document placeholder standing in for a page: no image.  Absent is right.
    404 / no image           no such page.  Absent is right.
    the notice (25,103)      the DOOR is refused; no verdict, the sample shrinks rather than guesses.

A TIFF that comes back is not an opinion about a document - it IS the document, and it is decisive on its own.

    python "Acris Absent Proof.py" --port 1200 --sample 120
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
TOTAL = re.compile(r"TotalPages%22%3A(-?\d+)")
MARKER = 13684                                   # ACRIS's end-of-document placeholder
NOTICE = 25103                                   # the bandwidth refusal: the DOOR is refused


def door(port):
    import socks
    socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", port, rdns=True)
    socket.socket = socks.socksocket


def get(url, referer):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": referer})
    try:
        with urllib.request.urlopen(r, timeout=45) as f:
            return f.status, f.read()
    except Exception as e:
        return getattr(e, "code", 0), b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--sample", type=int, default=120)
    ap.add_argument("--list", default=r"C:\dev\cre-office\audit\wrong.absent.json")
    # THE ATTRIBUTION TEST: the lane works in identifier order, so restricting the draw to one stretch of the corpus
    # asks whether the stretch run at a particular time is broken while the rest of the corpus is sound.
    ap.add_argument("--prefix", default="", help="draw only from identifiers starting with this (e.g. 2004)")
    a = ap.parse_args()
    door(a.port)

    ids = json.loads(pathlib.Path(a.list).read_text(encoding="utf-8"))
    if a.prefix:
        ids = [i for i in ids if i.startswith(a.prefix)]
        print("drawing only from the %s stretch: %d candidates" % (a.prefix, len(ids)))
    random.seed(a.port + 991)
    pick = random.sample(ids, min(a.sample, len(ids)))

    real, marker, none, quiet, bytes_seen = [], 0, 0, 0, 0
    for i, ident in enumerate(pick, 1):
        st, body = get("%s/GetImage?doc_id=%s&page=1" % (BASE, ident), "%s/DocumentImageView?doc_id=%s" % (BASE, ident))
        if len(body) == NOTICE:
            quiet += 1
        elif st == 404 or not body:
            none += 1
        elif len(body) == MARKER:
            marker += 1
        elif body[:2] in (b"II", b"MM"):
            real.append((ident, len(body)))
            bytes_seen += len(body)
        else:
            quiet += 1
        if i % 20 == 0:
            print("   ... %d asked: %d REAL PAGES, %d end marker, %d no image, %d no verdict"
                  % (i, len(real), marker, none, quiet), flush=True)

    judged = len(real) + marker + none
    print("\nABSENT PROOF  page 1 fetched for %d candidates, through the door on port %d" % (len(pick), a.port))
    print("  %5d  the door would not answer            - no verdict" % quiet)
    print("  %5d  end marker instead of a page         - absent is CORRECT" % marker)
    print("  %5d  404 / no image at all                - absent is CORRECT" % none)
    print("  %5d  A REAL TIFF CAME BACK                - THE DOCUMENT EXISTS AND WE MARKED IT ABSENT" % len(real))
    if judged:
        print("\n  %.1f%% of judged cells handed over a real page" % (100.0 * len(real) / judged))
        print("  over the %s-cell candidate list that is about %s documents we lost"
              % ("{:,}".format(len(ids)), "{:,}".format(int(round(len(ids) * len(real) / float(judged))))))
    for ident, n in real[:12]:
        print("        %-20s page 1 is a %s-byte TIFF" % (ident, "{:,}".format(n)))


if __name__ == "__main__":
    main()
