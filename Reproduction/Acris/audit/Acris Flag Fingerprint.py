"""Acris Flag Fingerprint - pin, to the minute and without asking ACRIS anything, when the lane went faulty.

login: "we either delete the faulty time frame or look into the time frame to pin when the code went faulty."  It can
be pinned, and the pdfs on the drive do it themselves.

--trust-registry-pages set `total` from registration, and the lane writes exactly `total` pages or nothing at all.  So
while the flag was on, EVERY pdf it wrote holds exactly as many pages as registration recorded - 100%, by construction,
not by tendency.  With the viewer as the authority the pdf holds what the VIEWER said, which agrees with registration
only about 70% of the time (measured over 20,000 pdfs: 5,945 held MORE pages than registration, 28 fewer).

    equality rate ~70%    the viewer was the authority - these pulls are sound
    equality rate ~100%   registration was the authority - THE FLAG WAS ON, and any pdf here may be short

Bucketed by clock, the rate steps up when the flag went in and back down when it came out.  That names the faulty
window from the evidence rather than from a commit time or a memory of when a knob was turned.

Reads paths_by_write_time.jsonl (written by Acris Bad Window.py) so no second walk of the drive is needed.

    python "Acris Flag Fingerprint.py"                     every recent write, bucketed by 10 minutes
    python "Acris Flag Fingerprint.py" --bucket 30
"""
import argparse
import collections
import datetime
import json
import pathlib
import re
import sys

sys.path.insert(0, r"C:\dev\nyc-cre-decoded\Reproduction\rulebook")
import rulebook                                                    # noqa: E402

COUNT = re.compile(rb"/Count\s+(\d+)")
TYPE_PAGE = re.compile(rb"/Type\s*/Page[^s]")


def pdf_pages(b):
    m = COUNT.search(b)
    if m:
        return int(m.group(1))
    return len(TYPE_PAGE.findall(b)) or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=r"C:\dev\cre-office\audit")
    ap.add_argument("--bucket", type=int, default=10, help="minutes per bucket")
    # NO BASELINE (login: "stop using 74% since that's a small sample ... the moment everything is just 100% in
    # registry constantly, that's the point we know it changed").  Right, and for a better reason than sample size: a
    # fixed reference assumes the overage rate is constant across the corpus, and it need not be - cover-page
    # conventions can differ by era and document type, so a number measured on 2003 documents may not describe 2006.
    #
    # Sustained 100% needs no reference.  Under the viewer, SOME pdfs must hold more pages than registration recorded
    # (registration misses covers and riders).  That class cannot vanish by chance: at any plausible overage rate a run
    # of hundreds with no overage at all is impossible.  When it vanishes AND STAYS vanished, registration is driving.
    ap.add_argument("--locked-at", type=float, default=99.5,
                    help="a bucket at or above this %% equality, sustained, is registry-locked")
    ap.add_argument("--run", type=int, default=2, help="consecutive buckets needed before calling it a change")
    # Reading 420,000 pdfs off a USB drive costs the better part of an hour and buys nothing: telling a bucket with no
    # overage from one with a quarter of its pdfs over needs dozens of samples, not thousands.  Cap the reads per
    # bucket and the whole fingerprint runs in a couple of minutes.
    ap.add_argument("--per-bucket", type=int, default=120, help="pdfs to read per bucket (0 = every one)")
    a = ap.parse_args()

    where = pathlib.Path(a.dir)
    src = where / "paths_by_write_time.jsonl"
    # tolerate a half-written last line: the scan may still be running, and its final buffer is not our business
    rows, torn = [], 0
    for line in src.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            torn += 1
    if torn:
        print("(%d unreadable line%s skipped - the scan is still writing)" % (torn, "" if torn == 1 else "s"))
    print("%s recent writes to fingerprint" % "{:,}".format(len(rows)))
    if not rows:
        return

    import psycopg2
    con = psycopg2.connect(rulebook.dsn())
    con.autocommit = True
    cur = con.cursor()
    cur.execute("set statement_timeout='600s'")

    reg = {}
    ids = [r["identifier"] for r in rows]
    for i in range(0, len(ids), 5000):
        cur.execute("select identifier, registry->>'pages' from reproduction.acris where identifier = any(%s)",
                    (ids[i:i + 5000],))
        for ident, pages in cur.fetchall():
            reg[ident] = int(pages) if pages and str(pages).strip().isdigit() else 0

    buckets = collections.defaultdict(lambda: [0, 0, 0, 0])       # bucket -> [written, equal, unreadable, read]
    for r in rows:                                                # first pass: how many were written in each bucket
        when = datetime.datetime.fromisoformat(r["written"])
        key = when.replace(minute=(when.minute // a.bucket) * a.bucket, second=0, microsecond=0)
        buckets[key][0] += 1
        r["_b"] = key

    for r in rows:                                                # second pass: read up to --per-bucket of each
        b = buckets[r["_b"]]
        if a.per_bucket and b[3] >= a.per_bucket:
            continue
        b[3] += 1
        want = reg.get(r["identifier"], 0)
        try:
            have = pdf_pages(pathlib.Path(r["path"]).read_bytes())
        except OSError:
            b[2] += 1
            continue
        if have is None:
            b[2] += 1
        elif want > 0 and have == want:
            b[1] += 1

    print("\n%-18s %8s %8s %8s   %s" % ("bucket (local)", "written", "== reg", "rate", "reading"))
    flagged = []
    for k in sorted(buckets):
        w, eq, bad, read = buckets[k]
        judged = read - bad
        rate = (100.0 * eq / judged) if judged else 0.0
        over = judged - eq                       # pdfs holding MORE pages than registration: only the viewer does this
        if judged < 20:
            mark = "(too few to judge)"
        elif rate >= a.locked_at:
            mark = "NO OVERAGE - registration is driving"
            flagged.append(k)
        else:
            mark = "%s pdfs hold more than registration - the viewer is driving" % "{:,}".format(over)
        print("%-18s %9s %7s %7s %6.1f%%   %s" % (k.strftime("%m-%d %H:%M"), "{:,}".format(w),
                                                   "{:,}".format(read), "{:,}".format(eq), rate, mark))
    # a lone 100% bucket is a quiet minute, not a code change; the change is the RUN that starts and does not stop
    runs, cur_run = [], []
    for k in sorted(buckets):
        if k in flagged:
            cur_run.append(k)
        else:
            if len(cur_run) >= a.run:
                runs.append(cur_run)
            cur_run = []
    if len(cur_run) >= a.run:
        runs.append(cur_run)

    if runs:
        print("\nSUSTAINED runs with no overage at all (%d+ buckets):" % a.run)
        total = 0
        for r in runs:
            n = sum(buckets[k][0] for k in r)
            total += n
            print("   %s -> %s   %s pdfs, every one counted by registration"
                  % (r[0].strftime("%m-%d %H:%M"), (r[-1] + datetime.timedelta(minutes=a.bucket)).strftime("%H:%M"),
                     "{:,}".format(n)))
        print("\n  %s pdfs to delete.  Everything outside these runs shows overage, so the viewer was driving there"
              % "{:,}".format(total))
    else:
        print("\nno sustained run without overage - nothing here was registry-locked")


if __name__ == "__main__":
    main()
