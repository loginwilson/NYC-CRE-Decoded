"""Acris Page Floor - check every landed pdf against a page count that is NOT the viewer and NOT our own code.

login: "how do we know or check the viewer count without accessing acris since we could be wrong in our code and never
know."  The right question, and it has exactly one answer, arrived at by elimination:

  the viewer          is ACRIS, and it is the thing under suspicion.  It cannot audit itself.
  our pdf             is what our code produced.  It cannot audit our code.
  Socrata             ACRIS's own published extract on NYC Open Data - checked 2026-09-09, and NEITHER master carries a
                      page count.  bnx9-e6tj holds crfn, doc_type, amounts, dates, reel; sv7x-dduq the same plus ucc
                      collateral.  There is no page count anywhere in the published city data.
  THE REGISTRY        the registration we pulled in August, held offline, one row per document.  A different pipeline
                      from the image viewer - it is the clerk's own record of what was handed in.

So the registry is the only page count we have that neither our code nor the viewer produced, and this program is the
whole-corpus check that needs no door, no request, and no ACRIS at all.

IT IS A FLOOR, NOT AN EQUALITY.  Registration counts the instrument and misses title pages, covers and riders, so a
nine-page document can register as seven (login).  A pdf with MORE pages than the registry is the normal, healthy case
and is not reported.  The one thing the floor can prove is the fatal direction:

    pdf pages < registry pages   ->  THE PDF IS SHORT.  Whatever the viewer said, the document has pages we do not hold.

A run is resumable: the last identifier judged is kept in a state file beside the report, so a sweep of the whole 4.1M
can be stopped and picked up.

    python "Acris Page Floor.py"                  the whole corpus, from where the last run stopped
    python "Acris Page Floor.py" --restart        from the beginning
    python "Acris Page Floor.py" --stop-after 50000
"""
import argparse
import datetime
import json
import pathlib
import re
import sys

sys.path.insert(0, r"C:\dev\nyc-cre-decoded\Reproduction\rulebook")
import rulebook                                                    # noqa: E402

PAGE = 20000                     # rows per keyset page; keyset on the primary key, never OFFSET or order by random()
COUNT = re.compile(rb"/Count\s+(\d+)")
TYPE_PAGE = re.compile(rb"/Type\s*/Page[^s]")


def pdf_pages(b):
    """Pages in the pdf, from its own /Pages /Count, falling back to counting page objects."""
    m = COUNT.search(b)
    if m:
        return int(m.group(1))
    n = len(TYPE_PAGE.findall(b))
    return n or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=r"C:\dev\cre-office\audit")
    ap.add_argument("--restart", action="store_true", help="ignore the state file and sweep from the first identifier")
    ap.add_argument("--stop-after", type=int, default=0, help="judge at most this many pdfs, then stop (resumable)")
    a = ap.parse_args()

    where = pathlib.Path(a.dir)
    where.mkdir(parents=True, exist_ok=True)
    state = where / "page_floor.state.json"
    report = where / "wrong.short_pdfs.json"

    seen = {"last": "", "judged": 0, "short": 0, "no_count": 0, "unreadable": 0, "over": 0}
    if state.is_file() and not a.restart:
        seen.update(json.loads(state.read_text(encoding="utf-8")))
        print("resuming after %s (%s pdfs judged so far, %s short)"
              % (seen["last"], "{:,}".format(seen["judged"]), "{:,}".format(seen["short"])))
    short = json.loads(report.read_text(encoding="utf-8")) if (report.is_file() and not a.restart) else []

    import psycopg2
    con = psycopg2.connect(rulebook.dsn())
    con.autocommit = True
    cur = con.cursor()
    cur.execute("set statement_timeout='600s'")

    started, at_start = datetime.datetime.now(), seen["judged"]
    while True:
        cur.execute("select identifier, document, registry->>'pages' from reproduction.acris"
                    " where document is not null and document not in ('pending','absent')"
                    "   and identifier > %s order by identifier limit %s", (seen["last"], PAGE))
        rows = cur.fetchall()
        if not rows:
            break
        for ident, doc, reg in rows:
            seen["last"] = ident
            want = int(reg) if reg and str(reg).strip().isdigit() else 0
            if want <= 0:
                seen["no_count"] += 1                    # registration recorded no count: the floor cannot judge it
                continue
            try:
                have = pdf_pages(pathlib.Path(doc).read_bytes())
            except OSError:
                seen["unreadable"] += 1
                continue
            if have is None:
                seen["unreadable"] += 1
                continue
            seen["judged"] += 1
            if have < want:
                seen["short"] += 1
                short.append({"identifier": ident, "pdf": have, "registry": want, "path": doc})
            elif have > want:
                seen["over"] += 1                        # the normal healthy case: the pdf holds the covers and riders
        state.write_text(json.dumps(seen, indent=1), encoding="utf-8")
        if short:
            report.write_text(json.dumps(short, indent=1), encoding="utf-8")
        el = (datetime.datetime.now() - started).total_seconds() or 1
        print("   %s judged  %s SHORT  %s over  %s no registry count  %s unreadable   (%.0f pdfs/s, at %s)"
              % ("{:,}".format(seen["judged"]), "{:,}".format(seen["short"]), "{:,}".format(seen["over"]),
                 "{:,}".format(seen["no_count"]), "{:,}".format(seen["unreadable"]),
                 (seen["judged"] - at_start) / el, seen["last"]), flush=True)
        if a.stop_after and seen["judged"] - at_start >= a.stop_after:
            print("   (--stop-after reached; the state file keeps the place)")
            break

    print("\nPAGE FLOOR  %s pdfs held against the registry's count, with no request to ACRIS"
          % "{:,}".format(seen["judged"]))
    print("  %10s  pdf holds MORE pages than registration - normal (covers, titles, riders)"
          % "{:,}".format(seen["over"]))
    print("  %10s  pdf holds FEWER pages than registration - THE PDF IS SHORT" % "{:,}".format(seen["short"]))
    print("  %10s  registration recorded no count - the floor cannot judge these" % "{:,}".format(seen["no_count"]))
    print("  %10s  pdf unreadable or not on the drive" % "{:,}".format(seen["unreadable"]))
    for s in short[:15]:
        print("        %-20s pdf holds %d pages, registration says %d" % (s["identifier"], s["pdf"], s["registry"]))
    if short:
        print("        %s written to %s - NOTHING WAS REPAIRED" % ("{:,}".format(len(short)), report))


if __name__ == "__main__":
    main()
