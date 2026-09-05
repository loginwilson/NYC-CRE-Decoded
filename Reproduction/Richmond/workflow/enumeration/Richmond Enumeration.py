"""RICHMOND ENUMERATION - the audit, one program.  Not a cycle lane.

It counts the source and compares with the table; the difference must be 0.  It never writes a cell
and has no table in the cloud: the county's own listing is read window by window, every internal id
it lists is checked against the table, and what it finds is written beside this file.

    python "Richmond Enumeration.py"                    the trailing --days 30 of the county's listing against the table (the tail)
    python "Richmond Enumeration.py" --from 2026-06-01 --to 2026-08-31     a date range, in windows of at most 30 days
    python "Richmond Enumeration.py" --all              the census: every window from 1850 to today, resumable (the baseline)
    python "Richmond Enumeration.py" report             the census ledger against the table: listed / held / MISSED / void

This file's own authority is Richmond Enumeration.md beside it; the cycle's is ../reproduction/Richmond Reproduction.md.

THE ENUMERATION LAW (login 2026-08-29): BULK BASELINE + LIVE TAIL = TOTAL.  For richmond the baseline
is the census window sweep (1850 to the last swept day) and the tail is the trailing date window; the
county's date-range listing is the one surface it answers unconditionally (a detail unlocks only after
its listing page in the same session, so a cold per-id probe can classify nothing).  The two ranges
overlap: the trailing window reaches weeks back past the census's last swept day, so no filing hides
in a seam.

Rules kept from the programs before this one (rc_window.py, rc_census.py, richmond_audit.py):

  windows are 30 days or shorter    a longer ask answers a SILENT ZERO (the measured cap); every window
                                    is clamped
  control first, every run          page 1 of a window KNOWN to hold documents (2026-08-19..20, 315
                                    recorded) must parse rows, or the parser is broken and no zero from
                                    it is believed: the run stops (exit 3) instead of recording false
                                    empties
  an empty denominator is never a   a trailing window the county lists as empty is UNPROVEN, never a
  pass                              pass (--days 45 once printed "held 0/0 · MISSING 0" on a window
                                    that held hundreds)
  the trailing window is re-swept   the window covering today is never done: the census re-opens it
                                    every run (2026-08-25: four days were silently omitted)
  a failed window is left unswept   never marked swept; the next run asks it again.  The retry unit is
                                    the page, never the window
  two namespaces                    the internal id (ViewDocumentInfo) is ours: RC_<internal>; the
                                    instrument number repeats across eras and is never a key
  the sweep is polite               --workers 10 at --pace 0.3 s between pages: the concurrency the
                                    county served 2.4M requests at without one trip; keep-alive, one
                                    pooled session; stop on any refusal shape (exit 2, enumeration.parked)
  never repair a number             a difference is reported, listed and left; nothing here inserts

Exit codes: 0 the difference is 0 · 1 a difference (ids missing) · 7 unproven · 2 refused ·
3 the probe is broken or the wire died · 5 crash.
"""
import argparse
import datetime as dt
import json
import pathlib
import queue
import socket
import sqlite3
import sys
import threading
import time

import requests

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # enumeration -> workflow -> Richmond -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))

import cloud                                                    # noqa: E402
import lane                                                     # noqa: E402
import richmond                                                 # noqa: E402

LO, HI = "RC_", "RC`"                          # the richmond ids' range in the table


class Report:
    def __init__(self, here, name="report"):
        self.here = pathlib.Path(here)
        self.lines = []
        self.log = self.here / "enumeration.log"
        self.path = self.here / ("enumeration.%s.txt" % name)

    def __call__(self, msg):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        self.lines.append(line)
        try:
            with self.log.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def save(self):
        try:
            self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        except OSError:
            pass


# ── the census ledger: every window swept, every id the county listed (a working file, rebuildable) ──
class Ledger:
    def __init__(self, path):
        self.con = sqlite3.connect(str(path), timeout=600, check_same_thread=False)
        self.con.executescript("""
            create table if not exists listing (internal_id integer primary key, instrument text, recorded text, type text, window_start text);
            create table if not exists window (start text primary key, "end" text, rows integer, pages integer, missing text, swept_at text);
        """)
        self.lock = threading.Lock()

    def swept(self):
        return {r[0] for r in self.con.execute("select start from window")}

    def reopen(self, start):
        with self.lock:
            self.con.execute("delete from window where start = ?", (start.isoformat(),))
            self.con.commit()

    def record(self, start, end, rows, pages, missing):
        with self.lock:
            for r in rows:
                self.con.execute("insert or ignore into listing values (?,?,?,?,?)",
                                 (int(r["internal_id"]), r["instrument"], r["recorded"], r["type"], start.isoformat()))
            self.con.execute("insert or replace into window values (?,?,?,?,?,?)",
                             (start.isoformat(), end.isoformat(), len(rows), pages, json.dumps(missing), time.strftime("%Y-%m-%dT%H:%M:%S")))
            self.con.commit()

    def listed(self):
        return {r[0] for r in self.con.execute("select internal_id from listing")}

    def summary(self):
        return self.con.execute("select count(*), min(start), max(\"end\"), coalesce(sum(rows), 0) from window").fetchone()

    def close(self):
        self.con.close()


# ── the county: one pooled session, the listing by window ─────────────────────────────────
class County:
    def __init__(self, width, pace, rep):
        self.session = lane.make_session(width, richmond.UA)
        self.pace, self.rep = pace, rep
        self.lock = threading.Lock()
        self.reqs = 0
        self.stop = threading.Event()

    def get(self, url, where):
        with self.lock:
            self.reqs += 1
        last = None
        for attempt in range(3):                                # the retry unit is the page
            try:
                r = self.session.get(url, timeout=60)
                try:
                    if r.status_code >= 400:
                        raise lane.HTTPStatus(r.status_code, url)
                    html = r.text
                finally:
                    r.close()
                richmond.check_refused(html, where)
                return html
            except richmond.Refused:
                self.stop.set()
                raise
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError, lane.HTTPStatus) as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise lane.Transport("%s: %s" % (where, lane.reason(last)))

    def control(self):
        """A known-nonzero window must parse rows before any zero is believed."""
        a, b, n = richmond.CONTROL
        got = richmond.parse_listing(self.get(richmond.listing_url(a, b, 1), "control %s..%s" % (a, b)))
        if not got:
            raise richmond.ProbeBroken("control window %s..%s parsed 0 rows (it holds %d): the markup changed; no zero is believed" % (a, b, n))
        return len(got)

    def window(self, start, end):
        """Every row the county lists for [start, end]: all pages, deduped on the internal id -> (rows, pages)."""
        a, b = start.isoformat(), end.isoformat()
        rows, seen, n, total = [], set(), 1, 1
        while n <= total and not self.stop.is_set():
            html = self.get(richmond.listing_url(a, b, n), "%s..%s page %d" % (a, b, n))
            pages = richmond.page_count(html)
            if pages:
                total = pages
            got = richmond.parse_listing(html)
            if not got:
                break
            for r in got:
                if r["internal_id"] not in seen:
                    seen.add(r["internal_id"])
                    rows.append(r)
            n += 1
            if n <= total:
                time.sleep(self.pace)
        return rows, total


# ── the comparison: the county's ids against the table ────────────────────────────────────
def compare(c, rows):
    ids = [richmond.doc_id(r["internal_id"]) for r in rows]
    held = set()
    for i in range(0, len(ids), 20000):
        held |= c.held(ids[i:i + 20000])
    missing = [d for d in ids if d not in held]
    return len(ids) - len(missing), missing


def clamp_days(days, rep):
    if days > richmond.WINDOW_DAYS:
        rep("--days %d exceeds the county's %d-day window cap (a longer ask answers a silent zero) - clamped to %d"
            % (days, richmond.WINDOW_DAYS, richmond.WINDOW_DAYS))
        return richmond.WINDOW_DAYS
    return max(1, days)


def audit_windows(args, c, rep, county, wins, what):
    """Sweep the given windows live and compare each; returns (listed, held, missing ids, unproven windows)."""
    missing_path = HERE / "enumeration.missing.txt"
    missing_path.write_text("", encoding="utf-8")
    tot_listed = tot_held = 0
    missing_all, unproven = [], []
    for start, end in wins:
        t = time.time()
        rows, pages = county.window(start, end)
        held, missing = compare(c, rows)
        tot_listed += len(rows)
        tot_held += held
        missing_all += missing
        if missing:
            with missing_path.open("a", encoding="utf-8") as f:
                f.write("".join(d + "\n" for d in missing))
        verdict = ""
        if not rows:
            unproven.append((start, end))
            verdict = "  UNPROVEN (the county listed nothing: the probe asked, nothing answered)"
        rep("%s..%s  county %6s  held %6s  MISSING %5s  pages %3s  %5.1fs%s"
            % (start, end, "{:,}".format(len(rows)), "{:,}".format(held), "{:,}".format(len(missing)), pages, time.time() - t, verdict))
    rep("%s: county %s  held %s  MISSING %s" % (what, "{:,}".format(tot_listed), "{:,}".format(tot_held), "{:,}".format(len(missing_all))))
    return tot_listed, tot_held, missing_all, unproven


def verdict(rep, listed, missing, unproven, missing_name="enumeration.missing.txt"):
    if missing:
        rep("THE DIFFERENCE IS %s: county ids the table lacks, listed in %s - FAIL" % ("{:,}".format(len(missing)), missing_name))
        return 1
    if not listed:
        rep("UNPROVEN: the county listed 0 rows - the probe asked nothing; do not read this as coverage")
        return 7
    if unproven:
        rep("UNPROVEN: %d window(s) answered empty - not a pass for them" % len(unproven))
        return 7
    rep("THE DIFFERENCE IS 0 - PASS")
    return 0


# ── the census: every window from 1850, resumable ─────────────────────────────────────────
def census(args, c, rep, county):
    ledger = Ledger(HERE / "enumeration.census.db")
    today = dt.date.today()
    wins = richmond.windows(richmond.START, today, richmond.WINDOW_DAYS)
    for s, e in wins:
        if s <= today <= e:
            ledger.reopen(s)                                    # the window covering NOW is never done
    done = ledger.swept()
    todo = [(s, e) for s, e in wins if s.isoformat() not in done]
    rep("THE CENSUS: %d windows of %d days from %s; %d swept before, %d to sweep; %d workers, %.1f s between pages"
        % (len(wins), richmond.WINDOW_DAYS, richmond.START, len(done), len(todo), args.workers, args.pace))
    missing_path = HERE / "enumeration.missing.txt"
    if not done:
        missing_path.write_text("", encoding="utf-8")
    q = queue.Queue()
    for w in todo:
        q.put(w)
    n = [len(done)]
    found = [0]
    missing_n = [0]
    failed = []
    t0 = time.time()
    errors = []

    def worker():
        while not county.stop.is_set():
            try:
                s, e = q.get_nowait()
            except queue.Empty:
                return
            try:
                rows, pages = county.window(s, e)
            except richmond.Refused as ex:
                errors.append(ex)
                return
            except Exception as ex:
                failed.append((s, e, "%s: %s" % (type(ex).__name__, str(ex)[:100])))
                continue
            if county.stop.is_set():
                failed.append((s, e, "stopped mid-window"))       # a cut window returned PARTIAL rows: never recorded as swept
                return
            held, missing = compare(c, rows)
            ledger.record(s, e, rows, pages, missing)
            with county.lock:
                n[0] += 1
                found[0] += len(rows)
                missing_n[0] += len(missing)
                if missing:
                    with missing_path.open("a", encoding="utf-8") as f:
                        f.write("".join(d + "\n" for d in missing))
                if rows or n[0] % 25 == 0:
                    rep("PROGRESS %d/%d windows - %s..%s +%s rows, MISSING %d - %.0f min"
                        % (n[0], len(wins), s, e, "{:,}".format(len(rows)), len(missing), (time.time() - t0) / 60))

    threads = [threading.Thread(target=worker, daemon=True, name="census-%d" % i) for i in range(max(1, args.workers))]
    for i, th in enumerate(threads):
        th.start()
        time.sleep(0.4)                                          # staggered first handshakes
    try:
        while any(th.is_alive() for th in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        county.stop.set()
        rep("stopped by hand - the ledger resumes on the next run")
    if errors:
        raise errors[0]
    for s, e, why in failed:
        rep("  %s..%s failed (%s) - left unswept; the next run asks it again" % (s, e, why))
    rep("swept %d of %d windows this run: %s rows listed, MISSING %s%s"
        % (n[0] - len(done), len(todo), "{:,}".format(found[0]), "{:,}".format(missing_n[0]),
           "" if not failed else " - %d windows failed" % len(failed)))
    code = report(args, c, rep, ledger)
    ledger.close()
    if failed and code == 0:
        code = 7
    return code


def report(args, c, rep, ledger=None):
    own = ledger is None
    if own:
        p = HERE / "enumeration.census.db"
        if not p.exists():
            raise SystemExit("no %s yet: run --all first (the census)" % p.name)
        ledger = Ledger(p)
    swept, first, last, rows = ledger.summary()
    total = len(richmond.windows(richmond.START, dt.date.today(), richmond.WINDOW_DAYS))
    listed = ledger.listed()
    t = time.time()
    held_ids = c.ids(LO, HI)
    held = set()
    for d in held_ids:
        s = d[3:]
        if s.isdigit():
            held.add(int(s))
    missed = sorted(listed - held)
    phantom = sorted(held - listed)
    rep("THE CENSUS LEDGER: %d/%d windows swept (%s .. %s), %s rows listed" % (swept, total, first, last, "{:,}".format(rows)))
    rep("  county lists %s distinct ids; the table holds %s (%.1f s)" % ("{:,}".format(len(listed)), "{:,}".format(len(held)), time.time() - t))
    rep("  MISSED (listed, not held): %s%s" % ("{:,}".format(len(missed)), ("  e.g. %s" % missed[:5]) if missed else ""))
    rep("  held, never listed: %s (windows not swept yet explain these until the sweep completes)" % "{:,}".format(len(phantom)))
    code = 0
    if missed:
        (HERE / "enumeration.missed.txt").write_text("".join(richmond.doc_id(i) + "\n" for i in missed), encoding="utf-8")
        rep("  listed in enumeration.missed.txt - FAIL")
        code = 1
    if swept == total:
        hi = max(held | listed) if (held | listed) else 0
        void = hi - len(held | set(missed))
        rep("  VOID by the county's own testimony: %s - %s = %s" % ("{:,}".format(hi), "{:,}".format(len(held | set(missed))), "{:,}".format(void)))
        rep("  held + missed + void = range -> 100% COVERAGE" if not missed else "  land the MISSED first, then the identity closes")
    else:
        rep("  the sweep is not complete: the identity waits for every window")
        if code == 0:
            code = 7
    if own:
        ledger.close()
    return code


def main():
    ap = argparse.ArgumentParser(description="richmond enumeration: the audit - the county's own listing against the table, the difference must be 0")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "report"])
    ap.add_argument("--days", type=int, default=30, help="the trailing window checked live (clamped to the county's 30-day cap)")
    ap.add_argument("--from", dest="date_from", default="", help="a date range instead of the trailing window (YYYY-MM-DD)")
    ap.add_argument("--to", dest="date_to", default="", help="the range's end (default today)")
    ap.add_argument("--all", action="store_true", help="the census: every window from 1850 to today, resumable")
    ap.add_argument("--workers", type=int, default=10, help="census: windows swept at once (default 10, the proven concurrency)")
    ap.add_argument("--pace", type=float, default=0.3, help="seconds between pages of one window")
    ap.add_argument("--unpark", action="store_true", help="run although the county declined last time (a person has decided)")
    ap.add_argument("--host", default="")
    args = ap.parse_args()
    host = args.host or socket.gethostname()

    rep = Report(HERE)
    rep("RICHMOND ENUMERATION on %s - %s" % (host, "the census ledger report" if args.command == "report" else "the census" if args.all else "the trailing window" if not args.date_from else "a date range"))
    parked = HERE / "enumeration.parked"
    if parked.exists() and not args.unpark and args.command != "report":
        rep("REFUSING TO START: %s - the county declined (%s). A person decides; --unpark to run again." % (parked.name, parked.read_text(encoding="utf-8").strip()[:200]))
        rep.save()
        sys.exit(2)
    c = cloud.Cloud("richmond", "enumeration", host, app="richmond enumeration")
    try:
        c.connect()
    except Exception as e:
        rep("the cloud is unreachable (%s) - the table cannot be counted" % lane.reason(e))
        rep.save()
        sys.exit(5)
    code = 5
    county = None
    try:
        rep("table: %s richmond rows" % "{:,}".format(c.count(LO, HI)))
        if args.command == "report":
            code = report(args, c, rep)
        else:
            county = County(max(1, args.workers) if args.all else 1, args.pace, rep)
            n = county.control()
            rep("control: %s..%s page 1 parsed %d rows (the window holds %d across its pages) - the parser reads the live markup" % (richmond.CONTROL[0], richmond.CONTROL[1], n, richmond.CONTROL[2]))
            if args.all:
                code = census(args, c, rep, county)
            else:
                if args.date_from:
                    a = dt.date.fromisoformat(args.date_from)
                    b = dt.date.fromisoformat(args.date_to) if args.date_to else dt.date.today()
                    wins = richmond.windows(a, b, richmond.WINDOW_DAYS)
                    what = "range %s..%s" % (a, b)
                else:
                    days = clamp_days(args.days, rep)
                    b = dt.date.today()
                    wins = [(b - dt.timedelta(days=days - 1), b)]          # `days` inclusive days, as the walkers and richmond.windows() count them
                    what = "the trailing %d days" % days
                listed, held, missing, unproven = audit_windows(args, c, rep, county, wins, what)
                code = verdict(rep, listed, missing, unproven)
    except richmond.Refused as e:
        rep("REFUSED: %s - stopped, nothing retried, nothing rotated. %s written; a person decides." % (e, parked.name))
        parked.write_text("REFUSED %s - %s\n" % (time.strftime("%Y-%m-%d %H:%M"), e), encoding="utf-8")
        code = 2
    except richmond.ProbeBroken as e:
        rep("PROBE BROKEN: %s" % e)
        code = 3
    except lane.Transport as e:
        rep("the wire died: %s - stopped; run again later" % e)
        code = 3
    except SystemExit as e:
        rep(str(e))
        code = 5
    except KeyboardInterrupt:
        rep("stopped by hand")
        code = 0
    except Exception as e:
        rep("CRASH %s: %s" % (type(e).__name__, lane.reason(e)))
        import traceback
        traceback.print_exc()
        code = 5                                     # the process leaves with 5 (a raise made it exit 1)
    finally:
        c.close()
        if county is not None:
            try:
                county.session.close()
            except Exception:
                pass
        rep("exit %d" % code)
        rep.save()
    sys.exit(code)


if __name__ == "__main__":
    main()
