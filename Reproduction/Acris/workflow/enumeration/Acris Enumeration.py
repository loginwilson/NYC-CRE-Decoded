"""ACRIS ENUMERATION - the audit, one program.  Not a cycle lane.

It counts the source and compares with the table; the difference must be 0.  It never writes a cell
and has no table: the workflow table is read, the index is read, and everything it finds is written
beside this file for a person to act on.

    python "Acris Enumeration.py"                       the newest --months of the index against the table, and the tail
    python "Acris Enumeration.py" --all                 every band: film FT_ and BK_, every digital month, the odd ids
    python "Acris Enumeration.py" --shard 202408        one shard (a month YYYYMM, FT_<borough><digit>, BK_<yy>); repeatable
    python "Acris Enumeration.py" --census              the counter: per year, the index's CRFN list and the holes named
    python "Acris Enumeration.py" --probe --acris       the named holes and each year's top asked of ACRIS itself:
                                                        login's word only, never beside the cycle

This file's own authority is Acris Enumeration.md beside it; the cycle's is ../reproduction/Acris Reproduction.md.

THE ENUMERATION LAW (login 2026-08-29): BULK BASELINE + LIVE TAIL = TOTAL.  The baseline (the index)
is complete but always stale; the tail (the walk) is live but reaches only so far back; their ranges
must overlap so no filing can hide in a seam.  Acris needs three checks, each honest about what it
cannot see:

  the diff      every id the index holds must be in the table: missing = the difference, must be 0.
                Ids the table holds that the index does not are classified, never counted against it:
                after the index's date (the tail), at the seam (dated inside the index's last three
                months, recorded after it closed), or before it (documents the index omits - the walk
                found them; 201 were proven real in 2016 alone)
  the census    CRFNs are YYYY + a dense per-year counter across both corpora.  The holes - numbers
                in 1..top the index does not hold - are an UPPER bound on documents missed; most are
                void.  Film has no counter, so film completeness rests on the diff alone
  the probe     each hole asked of ACRIS by CRFN: void (the stub), held (its document is in the
                table) or MISSING (a document the table lacks); each year's top confirmed by a gallop
                past the index's highest number.  Identity per year: index + held + missing + void =
                issued, closed only when nothing is unknown
  the tail      the walk's (synchronization): reported from the edge file's age, unproven past it

Rules kept from the programs before this one (acris_census.py, acris_void_walk.py, live_delta.py,
acris_bulk_rd.py, bulk.py):

  an empty denominator is never a pass   the index's own count is read before any zero is believed; a
                                         shard the index answers empty where the table holds rows is
                                         UNPROVEN; a throttled index call answers [] with HTTP 200, so
                                         every pull is held to the index's own count of it
  never repair a number                  a difference is reported, listed and left
  the index is an audit, not a source    the ids it dropped were found by the walk; nothing here
                                         inserts - the lists are for a person
  the probe is a door, on the cycle      one pooled session, --width connections born --stagger (5 s)
                                         apart, no pacer; HTTP 200 + the notice page = refused: stop, no
                                         retry, no rotation, enumeration.parked until --unpark; a number
                                         that fails three asks is UNKNOWN, never void (a wire error is
                                         never an ask); every line hit the wire inside 60 s with nothing
                                         answered for 10 s = the session closed: hang up, wait
                                         --redial-wait (60 s; x2 refused, /2 served), re-enter once on
                                         what is still unanswered; --tries (4) refused re-entries in a row
                                         stop it with exit 3 and the journal resumes on the next run;
                                         refuses to start while any lane's heartbeat is fresh - an
                                         enumeration sweep of the web endpoint never runs beside the cycle

Exit codes: 0 the difference is 0 · 1 a difference (ids or documents missing) · 7 unproven ·
2 refused · 3 hang-up · 5 crash.
"""
import argparse
import collections
import json
import os
import pathlib
import queue
import socket
import sys
import threading
import time

import requests

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # enumeration -> workflow -> Acris -> Reproduction
sys.path.insert(0, str(PHASE))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))

import acris                                                    # noqa: E402
import cloud                                                    # noqa: E402
import lane                                                     # noqa: E402

FIRST_YEAR = 2003                                   # ACRIS's first CRFN year
FIB = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)           # the confirm spread past a candidate top (a hole is not the edge)
SEAM_DAYS = 92                                      # an id dated this close before the index closed may have been recorded after it
BANDS = (("digital", "2", "3", 6), ("FT_", "FT_", "FT`", 5), ("BK_", "BK_", "BK`", 5))
OTHER = (("", "2"), ("3", "BK_"), ("BK`", "FT_"), ("FT`", None))    # every id outside the three bands


# ── the report: printed, logged, and left beside this file ──────────────────────────────
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


def next_prefix(p):
    """The first string above every id that starts with p ('202408' -> '202409', 'FT_19' -> 'FT_1:')."""
    return p[:-1] + chr(ord(p[-1]) + 1)


def band_of(prefix):
    if len(prefix) == 6 and prefix.isdigit() and prefix[0] == "2":
        return "digital"
    if len(prefix) == 5 and prefix[:3] in ("FT_", "BK_"):
        return prefix[:3]
    raise SystemExit("--shard takes a month YYYYMM, FT_<borough><digit> or BK_<yy> (got %r)" % prefix)


def id_date(doc_id):
    """'YYYYMMDD' of a digital id, '' for film or anything else."""
    return doc_id[:8] if len(doc_id) >= 8 and doc_id[:8].isdigit() else ""


def classify_extra(doc_id, band, good_through):
    """Why the table holds an id the index does not: tail (dated after the index closed), seam (dated
    inside the last SEAM_DAYS before it closed - recorded after), omitted (older: the index dropped
    it, the walk found it), odd (no date to judge by)."""
    if band != "digital":
        return "omitted"
    d = id_date(doc_id)
    gt = (good_through or "").replace("-", "")
    if not d or not gt:
        return "odd"
    if d > gt:
        return "tail"
    try:
        dd = time.mktime(time.strptime(d, "%Y%m%d"))
        gg = time.mktime(time.strptime(gt, "%Y%m%d"))
    except (ValueError, OverflowError):
        return "odd"
    return "seam" if (gg - dd) <= SEAM_DAYS * 86400 else "omitted"


def parse_years(spec, last):
    """'2016' · '2016,2024' · '2003-2010' · '' = every CRFN year to date."""
    if not spec:
        return list(range(FIRST_YEAR, last + 1))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


# ── the index's state: the control read before any zero is believed ──────────────────────
def index_state(rep):
    state = {"ids": 0, "good_through": "", "recorded": "", "crfn": ""}
    for name, ds in acris.INDEX:
        s = acris.index_state(ds)
        rep("index: %s master %s - %s distinct ids, recorded through %s, good through %s, highest CRFN %s"
            % (name, ds, "{:,}".format(s["ids"]), s["recorded"] or "?", s["good_through"] or "?", s["crfn"] or "?"))
        state["ids"] += s["ids"]
        state["good_through"] = max(state["good_through"], s["good_through"])
        state["recorded"] = max(state["recorded"], s["recorded"])
        state["crfn"] = max(state["crfn"], s["crfn"])
    if state["ids"] <= 0:
        raise SystemExit("UNPROVEN: the index answered zero ids - nothing it says is believed (exit 7)")
    return state


def pull_index(lo, hi, rep, label):
    """Distinct ids of both masters in [lo, hi) -> (ids, proven).  A Void answer is asked twice more."""
    ids, proven = set(), True
    for name, ds in acris.INDEX:
        for attempt in (1, 2, 3):
            try:
                ids |= acris.index_ids(ds, lo, hi)
                break
            except acris.Void as e:
                rep("  %s: void answer from the %s master (%s) - asking again" % (label, name, e))
                time.sleep(5 * attempt)
        else:
            proven = False
    return ids, proven


def merged_prefixes(lo, hi, n):
    out = collections.Counter()
    for _, ds in acris.INDEX:
        out.update(acris.index_prefixes(ds, lo, hi, n))
    return dict(out)


# ── THE DIFF ─────────────────────────────────────────────────────────────────────────────
def shard_plan(args, c, rep, state):
    """[(label, band, ranges, ask_index)]: the shards this run compares, from the index's own prefixes
    and the table's, never assumed."""
    if args.shard:
        return [(p, band_of(p), [(p, next_prefix(p))], True) for p in args.shard]
    band, lo, hi, n = BANDS[0]
    idx = merged_prefixes(lo, hi, n)
    tab = c.prefixes(lo, hi, n)
    last_index_month = max(idx) if idx else ""
    months = sorted(set(idx) | set(tab))
    if not args.all and idx:
        keep_from = sorted(idx)[-args.months] if len(idx) >= args.months else sorted(idx)[0]
        months = [m for m in months if m >= keep_from]
    plan = [(m, band, [(m, next_prefix(m))], m <= last_index_month) for m in months]
    if args.all:
        for band, lo, hi, n in BANDS[1:]:
            pre = sorted(set(merged_prefixes(lo, hi, n)) | set(c.prefixes(lo, hi, n)))
            plan += [(p, band, [(p, next_prefix(p))], True) for p in pre]
        plan.append(("other", "other", list(OTHER), True))
    return plan


def diff(args, c, rep, state):
    good_through = state["good_through"]
    plan = shard_plan(args, c, rep, state)
    rep("THE DIFF: %d shards, index good through %s; every index id must be in the table" % (len(plan), good_through or "?"))
    missing_path = HERE / "enumeration.missing.txt"
    extra_path = HERE / "enumeration.extra.txt"
    missing_path.write_text("", encoding="utf-8")
    extra_path.write_text("", encoding="utf-8")
    tot = collections.Counter()
    unproven = []
    for label, band, ranges, ask_index in plan:
        t = time.time()
        table = set()
        for lo, hi in ranges:
            table |= c.ids(lo, hi)
        index, proven = set(), True
        if ask_index:
            for lo, hi in ranges:
                got, ok = pull_index(lo, hi, rep, label)
                index |= got
                proven = proven and ok
        missing = sorted(index - table)
        extra = sorted(table - index)
        kinds = collections.Counter(classify_extra(d, band, good_through) for d in extra)
        empty = ask_index and proven and not index and bool(table)          # the index says nothing where the table holds rows
        if not proven or empty:
            unproven.append(label)
        tot["index"] += len(index)
        tot["table"] += len(table)
        tot["missing"] += len(missing)
        for k, v in kinds.items():
            tot[k] += v
        if missing:
            with missing_path.open("a", encoding="utf-8") as f:
                f.write("".join(d + "\n" for d in missing))
        if extra:
            with extra_path.open("a", encoding="utf-8") as f:
                f.write("".join("%s\t%s\t%s\n" % (d, label, classify_extra(d, band, good_through)) for d in extra))
        beyond = ", ".join("%s %s" % (k, "{:,}".format(v)) for k, v in sorted(kinds.items()))
        verdict = ""
        if not proven:
            verdict = "  UNPROVEN (the index never answered its own count)"
        elif empty:
            verdict = "  UNPROVEN (the index answered empty where the table holds rows)"
        elif not ask_index:
            verdict = "  (past the index: the tail)"
        rep("%-8s index %10s  table %10s  missing %8s  beyond %8s%s  %5.1fs%s"
            % (label, "{:,}".format(len(index)) if ask_index else "-", "{:,}".format(len(table)),
               "{:,}".format(len(missing)), "{:,}".format(len(extra)),
               (" (%s)" % beyond) if extra else "", time.time() - t, verdict))
    rep("TOTAL    index %10s  table %10s  missing %8s  beyond %8s (%s)"
        % ("{:,}".format(tot["index"]), "{:,}".format(tot["table"]), "{:,}".format(tot["missing"]),
           "{:,}".format(tot["tail"] + tot["seam"] + tot["omitted"] + tot["odd"]),
           ", ".join("%s %s" % (k, "{:,}".format(tot[k])) for k in ("tail", "seam", "omitted", "odd") if tot[k])))
    if tot["missing"]:
        rep("THE DIFFERENCE IS %s: index ids the table lacks, listed in %s - FAIL" % ("{:,}".format(tot["missing"]), missing_path.name))
        code = 1
    elif unproven:
        rep("UNPROVEN: %d shard(s) could not be held to the index's count (%s) - not a pass"
            % (len(unproven), ", ".join(unproven[:12])))
        code = 7
    else:
        rep("THE DIFFERENCE IS 0 over %d shards - PASS" % len(plan))
        code = 0
    if tot["omitted"] or tot["odd"]:
        rep("beyond the index and older than its seam: %s ids the index omits (the walk found them; listed in %s) - expected, not a defect"
            % ("{:,}".format(tot["omitted"] + tot["odd"]), extra_path.name))
    return code


# ── THE TAIL: the walk's, reported here ──────────────────────────────────────────────────
def tail(c, rep, state):
    rep("THE TAIL (the walk's): index good through %s, highest CRFN %s" % (state["good_through"] or "?", state["crfn"] or "?"))
    newest = c.max_id("2", "3")
    rep("  table's newest digital id: %s%s" % (newest or "none", (" (dated %s)" % id_date(newest)) if newest else ""))
    edge_file = HERE.parent / "synchronization" / "synchronization.edge.json"
    if edge_file.exists():
        try:
            e = json.loads(edge_file.read_text(encoding="utf-8"))
            at = time.mktime(time.strptime(e["at"], "%Y-%m-%dT%H:%M:%S"))
            rep("  edge %s at %s (%.1f hours ago)" % (e["edge"], e["at"], (time.time() - at) / 3600))
        except (ValueError, KeyError, OSError) as ex:
            rep("  edge file unreadable (%s)" % ex)
    else:
        rep("  no edge file on this workstation (synchronization keeps it at home)")
    alive = [r for r in c.alive("3 minutes") if r[0] == "synchronization"]
    if alive:
        rep("  synchronization alive: " + ", ".join("%s (%ds ago, width %s)" % (r[1], r[3], r[2]) for r in alive))
    else:
        rep("  synchronization is not running anywhere (no heartbeat in 3 minutes)")
    rep("  the tail is proven only by the walk: unproven past the edge")


# ── THE CENSUS: the counter, holes named from the index alone ────────────────────────────
def census(args, c, rep):
    this_year = time.localtime().tm_year
    years = parse_years(args.years, this_year)
    path = HERE / "enumeration.holes.json"
    holes = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    rep("THE CENSUS: %d years, the index's CRFN list per year; holes = numbers in 1..top the index does not hold" % len(years))
    tot_index = tot_holes = 0
    unproven = []
    for y in years:
        t = time.time()
        seqs, proven = set(), True
        for name, ds in acris.INDEX:
            for attempt in (1, 2, 3):
                try:
                    seqs |= acris.index_crfns(ds, y)
                    break
                except acris.Void as e:
                    rep("  %d: void answer from the %s master (%s) - asking again" % (y, name, e))
                    time.sleep(5 * attempt)
            else:
                proven = False
        if not proven or not seqs:
            rep("%d  UNPROVEN (%s)" % (y, "the index never answered its own count" if not proven else "the index holds no CRFN for the year"))
            unproven.append(y)
            continue
        top = max(seqs)
        miss = sorted(set(range(1, top + 1)) - seqs)
        holes[str(y)] = {"top": top, "index": len(seqs), "holes": miss, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        tot_index += len(seqs)
        tot_holes += len(miss)
        rep("%d  index %9s  top %9s  holes %6s  %5.1fs%s"
            % (y, "{:,}".format(len(seqs)), "{:,}".format(top), "{:,}".format(len(miss)), time.time() - t,
               "  (this year: capped at the index's own top; the walk owns everything above)" if y == this_year else ""))
        path.write_text(json.dumps(holes), encoding="utf-8")
    rep("TOTAL index %s  holes %s - an upper bound on documents missed; most holes are void (2026-08-21: 6,808 of 7,010 classified)"
        % ("{:,}".format(tot_index), "{:,}".format(tot_holes)))
    rep("named in %s; `--probe --acris` classifies them, on login's word" % path.name)
    if unproven:
        rep("UNPROVEN years: %s - not a pass" % ", ".join(str(y) for y in unproven))
        return 7
    return 0


# ── THE PROBE: the named holes and each year's top, asked of ACRIS itself ─────────────────
class Probe:
    """One pooled session, --width workers born --stagger apart; the main thread classifies against
    the table and keeps the journal.  Stops on the notice page; stops on a hang-up; never guesses."""

    def __init__(self, args, c, rep):
        self.args, self.c, self.rep = args, c, rep
        self.width = max(1, min(args.width, lane.MAX_WIDTH))
        self.session = None
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.answers = {}                 # crfn -> doc_id | None (void) | "unknown"
        self.reasons = {}
        self.reqs = 0
        self.transport_streak = 0
        self.transport_hits = []          # (time, worker) of recent wire errors: every worker inside 60 s is the session closed
        self.last_success = time.time()
        self.refused = None
        self.stop = threading.Event()
        self.workers = []
        self.tries = 0                    # re-entries in the current incident
        self.wait_s = args.redial_wait    # the backoff state: x2 per refused re-entry, /2 per served one
        self.last_redial = 0.0
        self.answered_at_redial = 0
        self.journal_path = HERE / "enumeration.probe.json"
        self.journal = json.loads(self.journal_path.read_text(encoding="utf-8")) if self.journal_path.exists() else {}
        self.journal.setdefault("numbers", {})
        self.journal.setdefault("tops", {})
        self.missing_path = HERE / "enumeration.probe-missing.txt"

    # ── the wire ──
    def get(self, url):
        with self.lock:
            self.reqs += 1
        try:
            r = self.session.get(url, headers={"Referer": acris.BASE + "/"}, timeout=45)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            raise lane.Transport("%s: %s" % (type(e).__name__, lane.reason(e)))
        try:
            if r.status_code >= 400:
                raise lane.HTTPStatus(r.status_code, url)
            return r.content, r.headers.get("Content-Type", "")
        finally:
            r.close()

    def ask(self, crfn):
        """The document id at a number, or None for the stub.  Raises Refused / Transport / HTTPStatus / Retry."""
        body, ct = self.get(acris.crfn_url(crfn))
        acris.check_refused(body, ct, "crfn %d" % crfn)
        doc_id = acris.detail_doc_id(acris.clean_html(body.decode("utf-8", "replace")))
        if doc_id is not None and len(body) < acris.MIN_DETAIL:
            raise lane.Retry("detail parsed from only %d bytes - suspect truncation" % len(body))
        return doc_id

    def worker(self, born):
        while not self.stop.is_set():
            try:
                crfn, attempt = self.q.get(timeout=1)
            except queue.Empty:
                continue
            try:
                doc_id = self.ask(crfn)
                with self.lock:
                    self.answers[crfn] = doc_id
                    self.transport_streak = 0
                    self.last_success = time.time()
            except lane.Refused as e:
                with self.lock:
                    self.refused = str(e)
                self.stop.set()
                return
            except lane.Transport as e:                 # the wire, never an answer: asked again after a pause; every worker hit = the session closed
                now = time.time()
                with self.lock:
                    self.transport_streak += 1
                    self.transport_hits.append((now, born))
                    self.transport_hits = [(t, b) for t, b in self.transport_hits if now - t <= lane.HANGUP_WINDOW_S]
                if not self.stop.is_set():
                    self.q.put((crfn, attempt))
                self.stop.wait(lane.HANGUP_PAUSE_S)
            except Exception as e:                      # HTTPStatus, Retry, anything else: asked again, then unknown
                if attempt + 1 < 3 and not self.stop.is_set():
                    self.q.put((crfn, attempt + 1))
                else:
                    with self.lock:
                        self.answers[crfn] = "unknown"
                        self.reasons[crfn] = "%s: %s" % (type(e).__name__, str(e)[:120])

    def resolve(self, crfn):
        """Synchronous, for the gallop: True when a document sits at the number.  Three asks; three wire failures
        in a row are the session closed for the gallop (the walkers are idle then): one re-entry, three more asks;
        then it is unknown and the year's top cannot be proven (raises)."""
        last = None
        for round_ in (1, 2):
            wire = 0
            for _ in range(3):
                try:
                    doc_id = self.ask(crfn)
                    with self.lock:
                        self.answers[crfn] = doc_id
                        self.last_success = time.time()
                    return doc_id is not None
                except lane.Refused:
                    raise
                except lane.Transport as e:
                    last = e
                    wire += 1
                    time.sleep(lane.HANGUP_PAUSE_S)
                except Exception as e:
                    last = e
                    time.sleep(1)
            if wire < 3 or round_ == 2:
                break
            self._reenter("the session closed under the gallop (three wire failures at crfn %d)" % crfn)
        raise lane.Retry("crfn %d: three asks failed (%s)" % (crfn, str(last)[:120]))

    # ── the cycle for the probe: the whole width, the hang-up, the wait, one re-entry ──
    def hung_up(self):
        now = time.time()
        with self.lock:
            self.transport_hits = [(t, b) for t, b in self.transport_hits if now - t <= lane.HANGUP_WINDOW_S]
            if not self.transport_hits or now - self.last_success <= lane.HANGUP_QUIET_S:
                return False
            return len({b for _, b in self.transport_hits}) >= max(1, self.width) or len(self.transport_hits) >= self.width

    def _enter(self):
        """ONE entry: a fresh pooled session, the connections born --stagger apart."""
        self.stop = threading.Event()
        self.transport_hits = []
        self.transport_streak = 0
        self.last_success = time.time()
        self.session = lane.make_session(self.width, acris.UA)
        self.workers = []
        for i in range(self.width):
            t = threading.Thread(target=self.worker, args=(i + 1,), daemon=True, name="probe-%d" % (i + 1))
            t.start()
            self.workers.append(t)
            if i < self.width - 1:
                self.stop.wait(self.args.stagger)

    def _leave(self):
        self.stop.set()
        for t in self.workers:
            t.join(timeout=60)
        try:
            self.session.close()
        except Exception:
            pass

    def _reenter(self, why):
        """The cycle: hang up at once, wait --redial-wait with no line open (x2 after a refused re-entry, /2 after
        a served one), re-enter once on what is still unanswered (the queue keeps it); --tries refused re-entries
        in a row stop the probe with exit 3 and the journal resumes on the next run."""
        now = time.time()
        answered = len(self.answers) - self.answered_at_redial
        if self.tries and (answered >= lane.SERVED_LANDINGS or now - self.last_redial >= lane.SERVED_S):
            self.tries = 0
            self.wait_s = max(self.wait_s // 2, self.args.redial_wait)
        elif self.tries:
            self.wait_s = min(self.wait_s * 2, 4800)
        if self.tries >= self.args.tries:
            self.stop.set()
            raise lane.Transport("%s; %d re-entries in a row were refused" % (why, self.tries))
        self.rep("PROBE: %s - hanging up; re-entry %d/%d in %ds on what is still unanswered, no line open"
                 % (why, self.tries + 1, self.args.tries, self.wait_s))
        self._leave()
        self.save()
        end = time.time() + self.wait_s
        while time.time() < end:
            time.sleep(min(10, max(0.0, end - time.time())))
        while not lane.net_up():
            self.rep("PROBE: the network is DOWN - waiting a minute, no try spent")
            time.sleep(60)
        self.tries += 1
        self.last_redial = time.time()
        self.answered_at_redial = len(self.answers)
        self._enter()
        self.rep("PROBE: re-entered (%d/%d), %d connections, births %.1fs apart" % (self.tries, self.args.tries, self.width, self.args.stagger))

    # ── the gallop past the index's top (acris_census.year_edge, seeded at the index's own top) ──
    def year_top(self, year, seed):
        base = year * 10 ** 9
        n = [0]

        def r(seq):
            n[0] += 1
            return self.resolve(base + seq)

        if not r(seed):
            return None, n[0]                # the control: the index's own top must resolve, or the probe is broken
        lo = seed
        while True:
            step = 1
            while r(lo + step):
                lo, step = lo + step, step * 2
                if step > 1 << 21:
                    return None, n[0]
            hi = lo + step
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if r(mid):
                    lo = mid
                else:
                    hi = mid
            far = next((k for k in FIB if r(lo + k)), None)   # a small hole fails 1, 2, 3 but resolves at +8 or +21
            if far is None:
                break
            lo += far
        return lo, n[0]

    # ── the walk of a list of numbers, classified against the table on the main thread ──
    def walk(self, numbers, what):
        todo = [n for n in numbers if str(n) not in self.journal["numbers"] or self.journal["numbers"][str(n)]["v"] == "unknown"]
        self.rep("%s: %s numbers, %s already classified, %s to ask" % (what, "{:,}".format(len(numbers)),
                 "{:,}".format(len(numbers) - len(todo)), "{:,}".format(len(todo))))
        if not todo:
            return
        for n in todo:
            self.q.put((n, 0))
        pending = set(todo)
        t0 = last_line = last_save = time.time()
        counts = collections.Counter()
        while pending and not self.stop.is_set():
            time.sleep(2)
            with self.lock:
                fresh = {n: self.answers[n] for n in pending if n in self.answers}
            lives = {n: d for n, d in fresh.items() if d not in (None, "unknown")}
            held = self.c.held(list(lives.values())) if lives else set()
            for n, d in fresh.items():
                if d is None:
                    v = {"v": "void"}
                elif d == "unknown":
                    v = {"v": "unknown", "why": self.reasons.get(n, "")}
                elif d in held:
                    v = {"v": "held", "doc_id": d}
                else:
                    v = {"v": "MISSING", "doc_id": d}
                    self.rep("  !! crfn %d -> %s NOT IN THE TABLE" % (n, d))
                    with self.missing_path.open("a", encoding="utf-8") as f:
                        f.write(d + "\n")
                self.journal["numbers"][str(n)] = v
                counts[v["v"]] += 1
                pending.discard(n)
            now = time.time()
            if now - last_save > 30 or not pending:
                self.save()
                last_save = now
            if now - last_line > 60:
                with self.lock:
                    reqs = self.reqs
                self.rep("PROBE  %s of %s answered (void %s, held %s, MISSING %s, unknown %s) - %.1f req/s"
                         % ("{:,}".format(len(todo) - len(pending)), "{:,}".format(len(todo)), counts["void"], counts["held"],
                            counts["MISSING"], counts["unknown"], reqs / max(1.0, now - t0)))
                last_line = now
            if self.hung_up():
                self._reenter("the session closed (every line hit the wire inside %ds, nothing answered for %ds)"
                              % (lane.HANGUP_WINDOW_S, int(now - self.last_success)))
        with self.lock:
            if self.refused:
                raise lane.Refused(self.refused)

    def save(self):
        tmp = self.journal_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.journal), encoding="utf-8")
        os.replace(tmp, self.journal_path)

    def identity(self, years, holes):
        """Per year: index + held + missing + void (+ unknown) against issued."""
        code = 0
        for y in years:
            h = holes.get(str(y))
            if not h:
                continue
            base = y * 10 ** 9
            top = self.journal["tops"].get(str(y), {})
            issued = top.get("issued")
            n = collections.Counter()
            for k, v in self.journal["numbers"].items():
                k = int(k)
                if base < k < base + 10 ** 9 and k - base <= (issued or h["top"]):
                    n[v["v"]] += 1
            named = h["index"] + n["held"] + n["MISSING"] + n["void"] + n["unknown"]
            closed = issued is not None and n["unknown"] == 0 and named == issued
            self.rep("%d  index %9s  issued %9s  void %6s  held %5s  MISSING %5s  unknown %5s  -> %s"
                     % (y, "{:,}".format(h["index"]), "{:,}".format(issued) if issued else "UNPROVEN", n["void"], n["held"],
                        n["MISSING"], n["unknown"],
                        "IDENTITY CLOSED: index + held + missing + void = issued" if closed
                        else "OPEN (%s)" % ("top unproven" if issued is None else "unknown numbers" if n["unknown"] else "names do not add up")))
            if n["MISSING"]:
                code = 1
            elif not closed and code == 0:
                code = 7
        return code

    def run(self):
        parked = HERE / "enumeration.parked"
        if parked.exists() and not self.args.unpark:
            raise SystemExit("REFUSING TO START: %s - the source declined a probe (%s). A person decides; --unpark to run again."
                             % (parked.name, parked.read_text(encoding="utf-8").strip()[:200]))
        alive = self.c.alive("3 minutes")
        if alive:
            raise SystemExit("REFUSING TO START: the cycle is running - %s. An enumeration sweep of the web endpoint never runs beside the cycle."
                             % ", ".join("%s on %s (%ds ago)" % (r[0], r[1], r[3]) for r in alive))
        holes_path = HERE / "enumeration.holes.json"
        if not holes_path.exists():
            raise SystemExit("no %s yet: run --census first (it names the holes from the index alone, no ACRIS request)" % holes_path.name)
        holes = json.loads(holes_path.read_text(encoding="utf-8"))
        # the years are the census's own (every year it named), narrowed by --years if given
        years = sorted(int(y) for y in holes if y.isdigit())
        if self.args.years:
            wanted = set(parse_years(self.args.years, max(years) if years else time.localtime().tm_year))
            years = [y for y in years if y in wanted]
        if not years:
            raise SystemExit("nothing to probe: %s names no year%s" % (holes_path.name, (" in --years %s" % self.args.years) if self.args.years else ""))
        lock = HERE / "enumeration.lock"
        lane.take_lock(lock)
        self.rep("THE PROBE: %d years, one entry of %d connections, births %.1fs apart - the cycle on a close, stops on the notice page"
                 % (len(years), self.width, self.args.stagger))
        self._enter()
        code = 0
        try:
            # 1. every named hole
            numbers = [y * 10 ** 9 + s for y in years for s in holes[str(y)]["holes"]]
            self.walk(numbers, "the holes")
            # 2. each year's top: a gallop past the index's highest number; what it passes is classified too
            for y in years:
                seed = holes[str(y)]["top"]
                done = self.journal["tops"].get(str(y))
                if done and done.get("issued") and not self.args.retop:
                    continue
                try:
                    issued, reqs = self.year_top(y, seed)
                except lane.Retry as e:
                    self.rep("%d  top UNPROVEN: %s" % (y, e))
                    issued, reqs = None, 0
                if issued is None:
                    self.rep("%d  top UNPROVEN after %d requests (the index's own top %s did not resolve, or nothing confirmed)" % (y, reqs, "{:,}".format(seed)))
                    self.journal["tops"][str(y)] = {"issued": None, "seed": seed, "requests": reqs, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                else:
                    self.rep("%d  issued %s (index top %s, +%s beyond it, %d requests)" % (y, "{:,}".format(issued), "{:,}".format(seed), "{:,}".format(issued - seed), reqs))
                    self.journal["tops"][str(y)] = {"issued": issued, "seed": seed, "requests": reqs, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                    beyond = [y * 10 ** 9 + s for s in range(seed + 1, issued + 1)]
                    self.save()
                    if beyond:
                        self.walk(beyond, "%d beyond the index's top" % y)
                self.save()
            # 3. the identity
            code = self.identity(years, holes)
        except lane.Refused as e:
            self.rep("REFUSED: %s - stopped, nothing retried, nothing rotated. %s written; a person decides." % (e, parked.name))
            parked.write_text("REFUSED %s - %s\n" % (time.strftime("%Y-%m-%d %H:%M"), e), encoding="utf-8")
            code = 2
        except lane.Transport as e:
            self.rep("HANG-UP: %s - stopped; the journal resumes on the next run" % e)
            code = 3
        except KeyboardInterrupt:
            self.rep("stopped by hand; the journal resumes on the next run")
            code = 0
        finally:
            self.stop.set()
            self.save()
            try:
                self.session.close()
            except Exception:
                pass
            try:
                lock.unlink()
            except OSError:
                pass
        return code


# ── main ─────────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="acris enumeration: the audit - count the source, compare with the table, the difference must be 0")
    ap.add_argument("--all", action="store_true", help="every band: film FT_ and BK_, every digital month, the odd ids (a long run)")
    ap.add_argument("--months", type=int, default=3, help="without --all: the newest N months of the index (default 3)")
    ap.add_argument("--shard", action="append", default=[], help="one shard: a month YYYYMM, FT_<borough><digit> or BK_<yy>; repeatable")
    ap.add_argument("--census", action="store_true", help="the counter: per year, the index's CRFN list and the holes named (no ACRIS request)")
    ap.add_argument("--probe", action="store_true", help="ask ACRIS about the named holes and each year's top (needs --acris)")
    ap.add_argument("--acris", action="store_true", help="login's word: this run may make requests to ACRIS itself")
    ap.add_argument("--years", default="", help="census/probe: 2016 · 2016,2024 · 2003-2010 (default: every CRFN year)")
    ap.add_argument("--retop", action="store_true", help="probe: gallop each year's top again even if the journal holds one")
    ap.add_argument("--width", type=int, default=10, help="probe: connections (default 10)")
    ap.add_argument("--stagger", type=float, default=5.0, help="probe: seconds between worker births (the ramp the door serves, 2026-09-04)")
    ap.add_argument("--redial-wait", type=int, default=60, help="probe: seconds of silence after the session closes before the re-entry (x2 refused, /2 served)")
    ap.add_argument("--tries", type=int, default=4, help="probe: refused re-entries in a row before it stops with exit 3 (the journal resumes)")
    ap.add_argument("--unpark", action="store_true", help="probe: run although the source declined last time (a person has decided)")
    ap.add_argument("--host", default="", help="this workstation's name (default: the machine name)")
    args = ap.parse_args()
    host = args.host or socket.gethostname()

    rep = Report(HERE)
    rep("ACRIS ENUMERATION on %s - %s" % (host, "the probe" if args.probe else "the census" if args.census else "the diff"))
    c = cloud.Cloud("acris", "enumeration", host, app="acris enumeration")
    try:
        c.connect()
    except Exception as e:
        raise SystemExit("the cloud is unreachable (%s) - the table cannot be counted" % lane.reason(e))
    code = 5
    try:
        if args.probe:
            if not args.acris:
                raise SystemExit("--probe asks ACRIS itself (one request per named hole, a gallop per year): it runs on login's word only - add --acris")
            code = Probe(args, c, rep).run()
        elif args.census:
            code = census(args, c, rep)
        else:
            rep("table: %s rows" % "{:,}".format(c.count()))
            state = index_state(rep)
            code = diff(args, c, rep, state)
            tail(c, rep, state)
    except SystemExit as e:
        rep(str(e))
        code = 7 if str(e).startswith("UNPROVEN") else 5
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
        rep("exit %d" % code)
        rep.save()
    sys.exit(code)


if __name__ == "__main__":
    main()
