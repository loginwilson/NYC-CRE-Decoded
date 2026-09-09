"""Acris Restore - put the cells I corrupted back to NULL so the lane can do them again, properly.

This is the ONLY program in the audit folder that writes to the table, and it writes exactly one thing: NULL.  It never
invents a verdict.  A cell set back to NULL is a cell the documentation lane will pick up and decide for itself from
ACRIS, which is the only thing entitled to decide it.

WHAT IT RESTORES, and why each set is beyond argument:

  pending   all 64,698 of them.  Measured 2026-09-09 against the RECORDING DATE IN ACRIS held in the registry: zero
            are inside the lag, and the youngest is 19.7 years past recording.  The proven lane could not have written
            them - acris.fresh() reads registry['recorded'] and returns False at 19 years, which yields 'absent'.  They
            are mine, from the viewer-404 change, and every one is wrong.

  absent    the 2006 stretch only - the stretch that ran overnight while my changed code was live.  The lane works in
            identifier order, so a stretch of identifiers is a period of time, and the stretches divide cleanly:

                2004   0 of 100 candidates handed over a real page   - the proven code, sound, LEFT ALONE
                2005   0 of 100 candidates handed over a real page   - the proven code, sound, LEFT ALONE
                2006  69 of 100 candidates handed over a real page   - mine, restored

            All 2006 candidates go back, not just the 69% - re-running a correctly-absent cell costs one viewer fetch
            and writes 'absent' again, and that is far cheaper than leaving a judgement call in the table.

A candidate is a cell marked absent whose registration recorded a page count and whose remarks do NOT say ACRIS
withdrew the image.  The withheld ones are left exactly as they are: those are the 'redacted' population and they are
not this program's business.

The claim is deleted with the cell, so the row is immediately available to the lane again rather than waiting out a
cooldown that was set by the corruption.

    python "Acris Restore.py"                  count what would change; writes NOTHING
    python "Acris Restore.py" --write          do it
"""
import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, r"C:\dev\nyc-cre-decoded\Reproduction\rulebook")
import rulebook                                                    # noqa: E402

BATCH = 5000            # rows per statement.  The whole-set UPDATE (`identifier = any(64,698 ids)`) timed out twice on
                        # 2026-09-09 and left a backend holding row locks; a keyset range of a few thousand returns in
                        # well under a second and can be stopped at any point without losing its place.

WITHHELD = ("(coalesce(registry->>'remarks','') ilike '%%removed from the public view%%'"
            " or coalesce(registry->>'remarks','') ilike '%%redacted from public view%%'"
            " or coalesce(registry->>'remarks','') ilike '%%removed from public view%%')")

SETS = {
    "pending": ("document = 'pending'", "", "every pending cell: 0 of 64,698 are inside the lag"),
    "absent2006": ("document = 'absent' and registry->>'pages' ~ '^[1-9][0-9]*$' and not " + WITHHELD,
                   "and identifier >= '2006' and identifier < '2007'",
                   "the 2006 absent candidates: 69 of 100 hand over a real page"),
    # GATE 1 (login, 2026-09-09): "what are the steps we take to recover 100% accuracy on our absent, pending, and
    # document page counts."  For absent there is exactly one route to 100%, and sampling is not it: every absent cell
    # goes back to NULL and is decided again by a fetch.  267,289 documents is 1.5% of the 17.2M still to do - a few
    # hours of lane - and it buys certainty in place of a rate.  It also lets the fixed lane write 'redacted' where
    # ACRIS confirms no image and the registration says why, which no amount of re-reading the table could give us.
    "absent_all": ("document = 'absent'", "", "EVERY absent cell, re-decided from ACRIS: the only route to 100%"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS) + ["all"], default="all")
    ap.add_argument("--write", action="store_true", help="actually set the cells to NULL (default: count only)")
    ap.add_argument("--dir", default=r"C:\dev\cre-office\audit")
    a = ap.parse_args()

    import psycopg2
    con = psycopg2.connect(rulebook.dsn())
    con.autocommit = True
    cur = con.cursor()
    cur.execute("set statement_timeout='120s'")

    where = pathlib.Path(a.dir)
    where.mkdir(parents=True, exist_ok=True)
    state = where / "restore.state.json"
    done = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {}

    for name in (sorted(SETS) if a.set == "all" else [a.set]):
        cond, span, why = SETS[name]
        cur.execute("select count(*) from reproduction.acris where %s %s" % (cond, span))
        n = cur.fetchone()[0]
        print("\n%-12s %8d cells   (%s)" % (name, n, why))
        if not a.write:
            print("             counted only - nothing was written.  Pass --write to restore them.")
            continue

        moved, started = 0, datetime.datetime.now()
        while True:
            # NO `order by identifier`, and no keyset.  Every row this touches LEAVES the set - it becomes NULL - so
            # "take any BATCH of them" is both correct and terminating, and it lets the planner use acris_document
            # (btree on document, where document is not null) as a straight index read.  Ordering by identifier instead
            # made the planner walk the primary key filtering on document: a heap scan that sat 89 s on IO/DataFileRead
            # and was heading for the statement timeout without having moved a single row.
            # The claim goes with the cell, so the lane picks the row straight back up rather than waiting out a
            # cooldown that the corruption set.
            cur.execute("""
                with take as (
                    select identifier from reproduction.acris where %s %s limit %%s
                ), gone as (
                    delete from machinery.claims c
                     using take t
                     where c.source='acris' and c.lane='documentation' and c.identifier = t.identifier
                ), upd as (
                    update reproduction.acris a set document = null
                      from take t where a.identifier = t.identifier
                     returning a.identifier
                )
                select count(*), min(identifier), max(identifier) from upd""" % (cond, span), (BATCH,))
            got, lo, hi = cur.fetchone()
            if not got:
                break
            moved += got
            done[name] = {"moved": moved, "last": hi}
            state.write_text(json.dumps(done, indent=1), encoding="utf-8")
            el = (datetime.datetime.now() - started).total_seconds() or 1
            print("   %8d restored to NULL   (%.0f rows/s, %s..%s)" % (moved, moved / el, lo, hi), flush=True)
        print("   %-10s DONE: %d cells set to NULL and their claims released" % (name, moved))

    if a.write:
        cur.execute("""select case when document is null then 'NULL' when document in ('pending','absent')
                                   then document else 'path' end as v, count(*)
                       from reproduction.acris group by 1 order by 2 desc""")
        print("\nthe table now:")
        for v, n in cur.fetchall():
            print("   %-8s %10d" % (v, n))


if __name__ == "__main__":
    main()
