"""Acris Bad Window - find every pdf written while the lane trusted the registry's page count, and undo it.

On 2026-09-09 the lane ran with --trust-registry-pages: the page count came from registration instead of the viewer.
Registration UNDERCOUNTS - it counts the instrument and misses title pages, covers and riders - so the walk stopped
early and the file was written whole and short.  It looks complete.  Nothing in the table can tell you otherwise.

Measured through a door: 9 of 142 pdfs in that stretch hold fewer pages than the viewer reports - 4 where there are 7,
3 where there are 7, 5 where there are 11 - and every one of the nine was written between 03:41 and 08:33 on 09-09.
That is the window, and the file's own mtime is the only honest way to name its members: the table records no time.

  the window   pdfs written between --from and --to (local time), whatever their identifier
  the undo     the pdf is DELETED and its cell set to NULL, so the lane fetches it again from the viewer's count

A short pdf is worse than no pdf: it is a document we believe we hold.  Deleting it is the point, not a side effect.

    python "Acris Bad Window.py"                    count what is in the window; writes and deletes NOTHING
    python "Acris Bad Window.py" --write            delete those pdfs and NULL their cells
"""
import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, r"C:\dev\nyc-cre-decoded\Reproduction\rulebook")
import rulebook                                                    # noqa: E402

PAGE = 20000                    # rows per keyset window on the primary key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", default="2026-09-09 01:00",
                    help="local time the bad window opens (the flag went in ~01:20)")
    ap.add_argument("--to", dest="hi", default="2026-09-09 10:00",
                    help="local time it closes (the last station run ended 09:31)")
    ap.add_argument("--write", action="store_true", help="delete the pdfs and NULL the cells (default: count only)")
    ap.add_argument("--dir", default=r"C:\dev\cre-office\audit")
    a = ap.parse_args()

    lo = datetime.datetime.strptime(a.lo, "%Y-%m-%d %H:%M")
    hi = datetime.datetime.strptime(a.hi, "%Y-%m-%d %H:%M")
    where = pathlib.Path(a.dir)
    where.mkdir(parents=True, exist_ok=True)
    found = where / "wrong.bad_window.json"

    import psycopg2
    con = psycopg2.connect(rulebook.dsn())
    con.autocommit = True
    cur = con.cursor()
    cur.execute("set statement_timeout='600s'")

    last, seen, hits, gone, started = "", 0, [], 0, datetime.datetime.now()
    while True:
        cur.execute("select identifier, document from reproduction.acris"
                    " where document is not null and document not in ('pending','absent')"
                    "   and identifier > %s order by identifier limit %s", (last, PAGE))
        rows = cur.fetchall()
        if not rows:
            break
        for ident, doc in rows:
            last = ident
            seen += 1
            p = pathlib.Path(doc)
            try:
                when = datetime.datetime.fromtimestamp(p.stat().st_mtime)
            except OSError:
                gone += 1                       # the cell names a file that is not on the drive
                continue
            if lo <= when <= hi:
                hits.append({"identifier": ident, "path": doc, "written": when.isoformat(timespec="seconds")})
        el = (datetime.datetime.now() - started).total_seconds() or 1
        print("   %s paths checked, %s in the window, %s missing   (%.0f/s, at %s)"
              % ("{:,}".format(seen), "{:,}".format(len(hits)), "{:,}".format(gone), seen / el, last), flush=True)

    found.write_text(json.dumps(hits, indent=1), encoding="utf-8")
    print("\nBAD WINDOW  %s to %s" % (lo, hi))
    print("  %s paths checked" % "{:,}".format(seen))
    print("  %s written inside the window - every one took its page count from registration" % "{:,}".format(len(hits)))
    print("  %s cells name a file that is not on the drive" % "{:,}".format(gone))
    print("  written to %s" % found)

    if not a.write:
        print("\n  counted only - nothing deleted, nothing changed.  Pass --write to undo them.")
        return

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


if __name__ == "__main__":
    main()
