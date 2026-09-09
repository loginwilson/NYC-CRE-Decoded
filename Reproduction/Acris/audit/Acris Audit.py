"""ACRIS AUDIT - one program: does the `document` cell say what ACRIS actually holds?

Its authority is Acris Audit.md beside it.  Every answer comes from ACRIS or from the registration we already hold,
never from our own records of what we did.  Nothing is repaired except by `restore` and `window`, which both default
to counting and both need --write, so a repair is a deliberate act on a list a person has read.

    python "Acris Audit.py" absent                    every absent cell against the registry's page count
    python "Acris Audit.py" pending                   every pending cell against the recording date
    python "Acris Audit.py" pages   --port 1200       landed pdfs against the viewer's count
    python "Acris Audit.py" proof   --port 1200       absent candidates: make ACRIS hand page 1 over
    python "Acris Audit.py" scan                      write time of every recent path (one walk, every window)
    python "Acris Audit.py" fingerprint               which source drove the page count, bucketed by clock
    python "Acris Audit.py" restore --set pending     put corrupted cells back to NULL            (--write)
    python "Acris Audit.py" window  --from T --to T   delete the pdfs written in a window         (--write)

THE THREE RULES THIS PROGRAM IS BUILT ON, each of them paid for:

  the viewer is the only page authority   registration undercounts (misses covers and riders) AND overcounts
                                          (2003012101793002: registers 39, the viewer says 3, the pdf holds 3)
  a non-answer is never a verdict         a refused door, a 404, an unreadable page: the cell stays as it was
  never `order by random()`               a full scan and a sort over 21.6M rows; it cancelled on the statement
                                          timeout twice.  Keyset the primary key, or take an identifier range.
"""
import argparse
import collections
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
COUNT = re.compile(rb"/Count\s+(\d+)")           # a pdf's own page count, from its /Pages object
TYPE_PAGE = re.compile(rb"/Type\s*/Page[^s]")
MARKER = 13684                                   # ACRIS's end-of-document placeholder.  It IS a TIFF: rule it out first
NOTICE = 25103                                   # the bandwidth refusal: the DOOR is refused, says nothing of the doc
PAGE = 20000                                     # rows per keyset window
BATCH = 5000                                     # rows per write statement

WITHHELD = ("(coalesce(registry->>'remarks','') ilike '%%removed from the public view%%'"
            " or coalesce(registry->>'remarks','') ilike '%%redacted from public view%%'"
            " or coalesce(registry->>'remarks','') ilike '%%removed from public view%%')")

DATES = ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")


# ── the wire ────────────────────────────────────────────────────────────────────────────────────

def door(port):
    """Route every request in this process through a door's socks tunnel."""
    import socks
    socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", port, rdns=True)
    socket.socket = socks.socksocket


def get(url, referer=BASE, timeout=45):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": referer})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            return f.status, f.read()
    except Exception as e:
        return getattr(e, "code", 0), b""


def viewer_pages(doc_id):
    """hid_TotalPages from the viewer - the ONLY authority on how many pages a document has.

    None means ACRIS would not say (the notice, an unreadable page): never a verdict."""
    st, body = get("%s/DocumentImageView?doc_id=%s" % (BASE, doc_id))
    if not body or len(body) == NOTICE:
        return None
    m = TOTAL.search(body.decode("utf-8", "ignore"))
    return int(m.group(1)) if m else None


def page_one(doc_id):
    """('real'|'marker'|'none'|'refused') for GetImage page 1 - the bytes, not an opinion about them."""
    st, img = get("%s/GetImage?doc_id=%s&page=1" % (BASE, doc_id), "%s/DocumentImageView?doc_id=%s" % (BASE, doc_id))
    if len(img) == NOTICE:
        return "refused"
    if st == 404 or not img:
        return "none"
    if len(img) == MARKER:
        return "marker"
    return "real" if img[:2] in (b"II", b"MM") else "refused"


# ── the drive and the clock ─────────────────────────────────────────────────────────────────────

def pdf_pages(b):
    """Pages in a pdf, from its own /Pages /Count, falling back to counting page objects."""
    m = COUNT.search(b)
    if m:
        return int(m.group(1))
    return len(TYPE_PAGE.findall(b)) or None


def read_pdf(path):
    try:
        return pdf_pages(pathlib.Path(path).read_bytes())
    except OSError:
        return None


def recorded(text):
    """The RECORDING DATE IN ACRIS, off the registry - never the date we happened to look."""
    for fmt in DATES:
        try:
            return datetime.datetime.strptime(str(text).strip(), fmt)
        except ValueError:
            pass
    return None


# ── the table ───────────────────────────────────────────────────────────────────────────────────

def connect(timeout="600s"):
    import psycopg2
    con = psycopg2.connect(rulebook.dsn())
    con.autocommit = True
    cur = con.cursor()
    cur.execute("set statement_timeout='%s'" % timeout)
    return con, cur


def walk(cur, verdict, fields):
    """Every row with this verdict, in identifier order, a page at a time - keyset on the primary key."""
    sql = ("select identifier, %s from reproduction.acris"
           " where document = %%s and identifier > %%s order by identifier limit %%s" % fields)
    last = ""
    while True:
        cur.execute(sql, (verdict, last, PAGE))
        rows = cur.fetchall()
        if not rows:
            return
        for r in rows:
            yield r
        last = rows[-1][0]


def out(where, name, ids):
    if not ids:
        return
    f = where / ("wrong.%s.json" % name)
    f.write_text(json.dumps(sorted(ids), indent=1), encoding="utf-8")
    print("        %s identifiers written to %s - NOTHING WAS REPAIRED" % ("{:,}".format(len(ids)), f))


# ── absent: the registry names the candidates, ACRIS convicts them ──────────────────────────────

def cmd_absent(a, where):
    """A page count in the registration means ACRIS holds the document.  That is a CANDIDATE list, never a verdict:
    registration records the paper the clerk received, and ACRIS may hold no image of it (2006010300637001 registers
    2 pages and the viewer says 0).  `proof` is what convicts."""
    con, cur = connect()
    wrong, nocount, withheld, total = [], 0, 0, 0
    for ident, pages, remarks in walk(cur, "absent", "registry->>'pages', registry->>'remarks'"):
        total += 1
        n = int(pages) if pages and str(pages).strip().isdigit() else 0
        low = (remarks or "").lower()
        if n <= 0:
            nocount += 1                      # the registration itself says there is nothing to fetch
        elif "removed from the public view" in low or "redacted from public view" in low \
                or "removed from public view" in low:
            withheld += 1                     # ACRIS withdrew the image; the count is real, the image is not
        else:
            wrong.append(ident)
    print("\nABSENT  %s cells" % "{:,}".format(total))
    print("  %10s  registry shows no page count      - absent is correct" % "{:,}".format(nocount))
    print("  %10s  image withheld by ACRIS (remarks) - absent is correct" % "{:,}".format(withheld))
    print("  %10s  REGISTRY SHOWS PAGES              - candidates, put them to `proof`" % "{:,}".format(len(wrong)))
    out(where, "absent", wrong)


# ── pending: the recording date is the whole test ───────────────────────────────────────────────

def cmd_pending(a, where):
    """'pending' is legal only inside the lag from the RECORDING DATE IN ACRIS.  Outside it the cell can never
    resolve: claim() re-checks pendings, so a wrong one cycles for ever without becoming a path or an absent."""
    con, cur = connect()
    now = datetime.datetime.now()
    wrong, inside, undated, total = [], 0, [], 0
    for ident, rec in walk(cur, "pending", "registry->>'recorded'"):
        total += 1
        when = recorded(rec) if rec else None
        if when is None:
            undated.append(ident)             # no clock at all: nothing justifies the verdict
        elif (now - when).days > a.lag:
            wrong.append(ident)
        else:
            inside += 1
    print("\nPENDING %s cells" % "{:,}".format(total))
    print("  %10s  recorded inside the %d-day lag    - pending is correct" % ("{:,}".format(inside), a.lag))
    print("  %10s  no recording date at all          - WRONG, nothing justifies it" % "{:,}".format(len(undated)))
    print("  %10s  RECORDED OUTSIDE THE LAG          - WRONG, must be redone" % "{:,}".format(len(wrong)))
    out(where, "pending", wrong + undated)


# ── pages: our pdf against the viewer, the only authority ───────────────────────────────────────

def cmd_pages(a, where):
    """The registry's count is not admissible here - it is wrong in both directions.  Only the viewer can say."""
    con, cur = connect()
    picked, per = [], max(4, (a.limit * 2) // max(1, len(a.prefixes)))
    for pre in a.prefixes:
        hi = pre[:-1] + chr(ord(pre[-1]) + 1)          # "2010" -> "2011": the next slice, exclusive
        cur.execute("select identifier, document from reproduction.acris"
                    " where identifier >= %s and identifier < %s"
                    "   and document is not null and document not in ('pending','absent')"
                    " order by identifier limit %s", (pre, hi, per))
        picked += cur.fetchall()

    wrong, same, quiet, gone = [], 0, 0, 0
    for ident, doc in picked:
        if same + len(wrong) + quiet >= a.limit:
            break
        have = read_pdf(doc)
        if have is None:
            gone += 1
            continue
        said = viewer_pages(ident)
        if said is None or said <= 0:
            quiet += 1                                 # no authority answered; never a verdict
        elif have == said:
            same += 1
        else:
            wrong.append((ident, have, said))
    print("\nPAGES   %s pdfs judged against the viewer" % "{:,}".format(same + len(wrong) + quiet))
    print("  %10s  pdf matches the viewer - the pull was complete" % "{:,}".format(same))
    print("  %10s  no verdict (door refused / viewer silent)" % "{:,}".format(quiet))
    print("  %10s  named a file that is not on the drive" % "{:,}".format(gone))
    print("  %10s  PDF DIFFERS FROM THE VIEWER - the wrong page count was pulled" % "{:,}".format(len(wrong)))
    for ident, have, said in wrong[:15]:
        print("        %-20s pdf holds %d pages, viewer says %d" % (ident, have, said))
    out(where, "pages", [w[0] for w in wrong])


# ── proof: stop asking what ACRIS has, make it hand the page over ───────────────────────────────

def cmd_proof(a, where):
    """A real TIFF is not an opinion about a document, it IS the document.  The end marker confirms an absence only
    from a door that is otherwise serving - it can stand in for every page of a refused block."""
    import random
    ids = json.loads((where / "wrong.absent.json").read_text(encoding="utf-8"))
    if a.prefix:
        ids = [i for i in ids if i.startswith(a.prefix)]
        print("drawing only from the %s stretch: %s candidates" % (a.prefix, "{:,}".format(len(ids))))
    random.seed(a.port + 991)
    pick = random.sample(ids, min(a.limit, len(ids)))

    real, marker, none, quiet = [], 0, 0, 0
    for i, ident in enumerate(pick, 1):
        k = page_one(ident)
        if k == "real":
            real.append(ident)
        elif k == "marker":
            marker += 1
        elif k == "none":
            none += 1
        else:
            quiet += 1
        if i % 25 == 0:
            print("   ... %d asked: %d REAL, %d marker, %d no image, %d no verdict"
                  % (i, len(real), marker, none, quiet), flush=True)
    judged = len(real) + marker + none
    print("\nPROOF   page 1 fetched for %s candidates through port %d" % ("{:,}".format(len(pick)), a.port))
    print("  %10s  the door would not answer            - no verdict" % "{:,}".format(quiet))
    print("  %10s  end marker instead of a page         - absent is CORRECT" % "{:,}".format(marker))
    print("  %10s  404 / no image at all                - absent is CORRECT" % "{:,}".format(none))
    print("  %10s  A REAL TIFF CAME BACK                - THE DOCUMENT EXISTS" % "{:,}".format(len(real)))
    if judged:
        print("\n  %.1f%% of judged cells handed over a real page; over the %s-cell list that is about %s documents"
              % (100.0 * len(real) / judged, "{:,}".format(len(ids)),
                 "{:,}".format(int(round(len(ids) * len(real) / float(judged))))))
    out(where, "proof", real)


# ── scan: one walk of the drive, every window ───────────────────────────────────────────────────

def cmd_scan(a, where):
    """The table records no time, so a pdf's own mtime is the only honest way to date it.  Statting 4.1M files costs
    the better part of an hour, so this records EVERY recent write once and every window afterwards is a slice."""
    con, cur = connect()
    since = datetime.datetime.strptime(a.since, "%Y-%m-%d %H:%M")
    era, last, seen, recent, gone = where / "paths_by_write_time.jsonl", "", 0, 0, 0
    started = datetime.datetime.now()
    with era.open("w", encoding="utf-8") as f:
        while True:
            cur.execute("select identifier, document from reproduction.acris"
                        " where document is not null and document not in ('pending','absent')"
                        "   and identifier > %s order by identifier limit %s", (last, PAGE))
            rows = cur.fetchall()
            if not rows:
                break
            for ident, doc in rows:
                last, seen = ident, seen + 1
                try:
                    when = datetime.datetime.fromtimestamp(pathlib.Path(doc).stat().st_mtime)
                except OSError:
                    gone += 1                   # the cell names a file that is not on the drive
                    continue
                if when >= since:
                    f.write(json.dumps({"identifier": ident, "path": doc,
                                        "written": when.isoformat(timespec="seconds")}) + "\n")
                    recent += 1
            el = (datetime.datetime.now() - started).total_seconds() or 1
            print("   %s checked, %s written since %s, %s missing   (%.0f/s, at %s)"
                  % ("{:,}".format(seen), "{:,}".format(recent), a.since, "{:,}".format(gone), seen / el, last),
                  flush=True)
    print("\nSCAN    %s paths; %s written since %s recorded in %s; %s name a file that is not there"
          % ("{:,}".format(seen), "{:,}".format(recent), a.since, era, "{:,}".format(gone)))


# ── fingerprint: which source drove the page count, read off the pdfs themselves ────────────────

def cmd_fingerprint(a, where):
    """--trust-registry-pages set `total` from registration, and the lane writes exactly `total` pages or nothing.
    So while it was on, the class of pdfs holding MORE pages than registration cannot exist.  Under the viewer that
    class is always there.  When it vanishes AND STAYS vanished, registration was driving - no baseline needed, and
    no reliance on when anyone remembers turning a knob."""
    src = where / "paths_by_write_time.jsonl"
    rows, torn = [], 0
    for line in src.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            torn += 1
    print("%s recent writes to fingerprint%s"
          % ("{:,}".format(len(rows)), (" (%d torn lines skipped)" % torn) if torn else ""))
    if not rows:
        return

    con, cur = connect()
    reg, ids = {}, [r["identifier"] for r in rows]
    for i in range(0, len(ids), BATCH):
        cur.execute("select identifier, registry->>'pages' from reproduction.acris where identifier = any(%s)",
                    (ids[i:i + BATCH],))
        for ident, pages in cur.fetchall():
            reg[ident] = int(pages) if pages and str(pages).strip().isdigit() else 0

    buckets = collections.defaultdict(lambda: [0, 0, 0, 0])       # [written, equal, unreadable, read]
    for r in rows:
        when = datetime.datetime.fromisoformat(r["written"])
        r["_b"] = when.replace(minute=(when.minute // a.bucket) * a.bucket, second=0, microsecond=0)
        buckets[r["_b"]][0] += 1
    for r in rows:                                                # read only a sample per bucket: 0% vs 26% is loud
        b = buckets[r["_b"]]
        if a.per_bucket and b[3] >= a.per_bucket:
            continue
        b[3] += 1
        have, want = read_pdf(r["path"]), reg.get(r["identifier"], 0)
        if have is None:
            b[2] += 1
        elif want > 0 and have == want:
            b[1] += 1

    print("\n%-18s %9s %7s %7s %7s   %s" % ("bucket (local)", "written", "read", "== reg", "rate", "reading"))
    flagged = []
    for k in sorted(buckets):
        w, eq, bad, read = buckets[k]
        judged = read - bad
        rate = (100.0 * eq / judged) if judged else 0.0
        if judged < 20:
            mark = "(too few to judge)"
        elif rate >= a.locked_at:
            mark, _ = "NO OVERAGE - registration is driving", flagged.append(k)
        else:
            mark = "%s hold more than registration - the viewer is driving" % "{:,}".format(judged - eq)
        print("%-18s %9s %7s %7s %6.1f%%   %s" % (k.strftime("%m-%d %H:%M"), "{:,}".format(w),
                                                  "{:,}".format(read), "{:,}".format(eq), rate, mark))

    runs, cur_run = [], []                    # a lone bucket is a quiet minute; the change is the run that persists
    for k in sorted(buckets):
        if k in flagged:
            cur_run.append(k)
        else:
            if len(cur_run) >= a.run:
                runs.append(cur_run)
            cur_run = []
    if len(cur_run) >= a.run:
        runs.append(cur_run)
    if not runs:
        print("\nno sustained run without overage - nothing here was registry-driven")
        return
    print("\nSUSTAINED runs with no overage at all (%d+ buckets):" % a.run)
    for r in runs:
        n = sum(buckets[k][0] for k in r)
        print("   %s -> %s   %s pdfs, every one counted by registration"
              % (r[0].strftime("%m-%d %H:%M"),
                 (r[-1] + datetime.timedelta(minutes=a.bucket)).strftime("%m-%d %H:%M"), "{:,}".format(n)))
    print("\n  put those bounds to `window --write` to delete them")


# ── restore: put corrupted cells back to NULL ───────────────────────────────────────────────────

SETS = {
    "pending": ("document = 'pending'", "every pending cell"),
    "absent":  ("document = 'absent'", "EVERY absent cell, to be decided again from ACRIS"),
    "absent_candidates": ("document = 'absent' and registry->>'pages' ~ '^[1-9][0-9]*$' and not " + WITHHELD,
                          "absent cells whose registration recorded pages"),
}


def cmd_restore(a, where):
    """The only thing this writes is NULL.  It never invents a verdict: a cell set back to NULL is one the lane will
    decide again from ACRIS, which is the only thing entitled to decide it.  The claim goes with the cell so the row
    is available at once rather than waiting out a cooldown the corruption set."""
    con, cur = connect(timeout="600s")        # 600s, not the project's two minutes: a batch behind another writer
    cond, why = SETS[a.set]                   # must finish rather than cancel.  RUN THE SETS ONE AT A TIME.
    cur.execute("select count(*) from reproduction.acris where %s" % cond)
    print("\n%-18s %s cells   (%s)" % (a.set, "{:,}".format(cur.fetchone()[0]), why))
    if not a.write:
        print("             counted only - nothing written.  Pass --write.")
        return
    moved, started = 0, datetime.datetime.now()
    while True:
        # no `order by`: every row touched LEAVES the set, so "take any BATCH" is correct and terminating, and it
        # lets the planner read acris_document straight.  Ordering by identifier made it a heap scan that sat 89 s
        # on IO/DataFileRead without moving a row.
        cur.execute("""
            with take as (select identifier from reproduction.acris where %s limit %%s),
                 gone as (delete from machinery.claims c using take t
                           where c.source='acris' and c.lane='documentation' and c.identifier = t.identifier),
                 upd  as (update reproduction.acris a set document = null
                            from take t where a.identifier = t.identifier returning a.identifier)
            select count(*) from upd""" % cond, (BATCH,))
        got = cur.fetchone()[0]
        if not got:
            break
        moved += got
        el = (datetime.datetime.now() - started).total_seconds() or 1
        print("   %s restored to NULL   (%.0f rows/s)" % ("{:,}".format(moved), moved / el), flush=True)
    print("   DONE: %s cells set to NULL and their claims released" % "{:,}".format(moved))


# ── window: delete the pdfs written between two times ───────────────────────────────────────────

def cmd_window(a, where):
    """A short pdf is worse than no pdf: it is a document we believe we hold, and it passes every count we keep.
    The FILE must go, not just the cell - the lane's first act is `if path.is_file(): return canon`, so leaving it
    would make the re-pull a silent no-op."""
    lo = datetime.datetime.strptime(a.lo, "%Y-%m-%d %H:%M")
    hi = datetime.datetime.strptime(a.hi, "%Y-%m-%d %H:%M")
    src = where / "paths_by_write_time.jsonl"
    hits = []
    for line in src.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if lo <= datetime.datetime.fromisoformat(r["written"]) <= hi:
            hits.append(r)
    print("\nWINDOW  %s to %s: %s pdfs" % (lo, hi, "{:,}".format(len(hits))))
    if not a.write:
        print("        counted only - nothing deleted.  Pass --write.")
        return
    con, cur = connect()
    killed, failed, nulled = 0, 0, 0
    for i in range(0, len(hits), 2000):
        chunk = hits[i:i + 2000]
        for h in chunk:
            try:
                pathlib.Path(h["path"]).unlink()
                killed += 1
            except OSError:
                failed += 1
        ids = [h["identifier"] for h in chunk]
        cur.execute("update reproduction.acris set document = null where identifier = any(%s)", (ids,))
        cur.execute("delete from machinery.claims where source='acris' and lane='documentation'"
                    " and identifier = any(%s)", (ids,))
        nulled += len(ids)
        print("   %s pdfs deleted, %s cells set to NULL" % ("{:,}".format(killed), "{:,}".format(nulled)), flush=True)
    print("\n  %s pdfs deleted (%s could not be), %s cells NULLed and their claims released"
          % ("{:,}".format(killed), "{:,}".format(failed), "{:,}".format(nulled)))


# ── the one command ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="acris audit: does the document cell say what ACRIS holds?")
    ap.add_argument("what", choices=["absent", "pending", "pages", "proof", "scan", "fingerprint",
                                     "restore", "window"])
    ap.add_argument("--dir", default=r"C:\dev\cre-office\audit", help="where the lists are written")
    ap.add_argument("--port", type=int, default=0, help="pages/proof: a live door's socks port")
    ap.add_argument("--limit", type=int, default=200, help="pages/proof: how many to judge")
    ap.add_argument("--prefixes", default="2003,2006,2010,2014,2018,2022,2025", help="pages: identifier slices")
    ap.add_argument("--prefix", default="", help="proof: draw only from this identifier stretch")
    ap.add_argument("--lag", type=int, default=30, help="pending: days from the recording date a scan may still land")
    ap.add_argument("--since", default="2026-09-08 00:00", help="scan: record every write after this")
    ap.add_argument("--bucket", type=int, default=30, help="fingerprint: minutes per bucket")
    ap.add_argument("--per-bucket", type=int, default=120, help="fingerprint: pdfs read per bucket (0 = all)")
    ap.add_argument("--locked-at", type=float, default=99.5, help="fingerprint: %% equality that reads as registry")
    ap.add_argument("--run", type=int, default=2, help="fingerprint: consecutive buckets before calling it a change")
    ap.add_argument("--set", choices=sorted(SETS), default="pending", help="restore: which cells")
    ap.add_argument("--from", dest="lo", default="", help="window: local time it opens")
    ap.add_argument("--to", dest="hi", default="", help="window: local time it closes")
    ap.add_argument("--write", action="store_true", help="restore/window: actually change things")
    a = ap.parse_args()
    a.prefixes = [p.strip() for p in a.prefixes.split(",") if p.strip()]

    where = pathlib.Path(a.dir)
    where.mkdir(parents=True, exist_ok=True)
    if a.what in ("pages", "proof"):
        if not a.port:
            sys.exit("%s needs --port: ACRIS is the authority and it lives behind a door" % a.what)
        door(a.port)
    if a.what == "window" and not (a.lo and a.hi):
        sys.exit("window needs --from and --to (take them from `fingerprint`)")

    started = datetime.datetime.now()
    {"absent": cmd_absent, "pending": cmd_pending, "pages": cmd_pages, "proof": cmd_proof,
     "scan": cmd_scan, "fingerprint": cmd_fingerprint, "restore": cmd_restore, "window": cmd_window}[a.what](a, where)
    print("\n(%s elapsed)" % (datetime.datetime.now() - started))


if __name__ == "__main__":
    main()
