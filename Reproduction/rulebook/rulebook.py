"""THE RULEBOOK'S MACHINERY, one file (login 2026-09-07: "why can't it just be one py and one md, like all the other rulebooks").

Six parts, each once the file named in the heading, in dependency order:
  storage        where a document lives: the drive by its label, the One Touch tree, the day folders
  rate_manager   the rate manager (the Governor; next_width is pure arithmetic) - the batch and session managers are the lane's own cycle, in lane
  cloud          the cloud table from a lane's point of view: claim, land, heartbeat, the outbox
  lane           THE ENTRY every cycle lane shares: one pooled session, staggered births, hang-up, rebatch, re-entry, the park
  fleet          the source's lanes together as one program
  board          the update board every source shares: the counters read once a minute, rates / eta / status written back
The rules are in Rulebook.md beside this file.  A lane imports this module: `import rulebook`.
"""
import datetime
import os
import pathlib
import re
import string
import sys
import math
import threading
import time
import json
import urllib.parse
import psycopg2
import queue
import signal
import socket
import traceback
import types
import urllib.error
import urllib.request
import requests
import requests.adapters
import argparse
import subprocess


# ======================================================================================================================
# STORAGE: WHERE A DOCUMENT LIVES - the One Touch layout, the same on every workstation.
# ======================================================================================================================

CANON_ROOT = "D:\\"
LAYOUT = ("NYC CRE Decoded", "Reproduction")
SOURCE_FOLDER = {"acris": "Acris", "richmond": "Richmond"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MDY = re.compile(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})")


def month_folder(m):
    """'08 Aug' - Explorer's alphabetical order is calendar order."""
    return "%02d %s" % (m, MONTHS[m - 1])


def day_folders(doc_id, recorded=None):
    """The folders under By Document for one document: ('2003', '05 May', '13') from the recorded date - a date, or
    the source's own text 'm/d/yyyy[ h:mm:ss AM]' - else a digital id's own date (yyyymmdd at its front), else the
    id split ('FT_4', '4100') with no day folder.  Exactly the old lane's rule, so the moved tree stays true."""
    if isinstance(recorded, (datetime.date, datetime.datetime)):
        return (str(recorded.year), month_folder(recorded.month), "%02d" % recorded.day)
    if recorded:
        m = _MDY.match(str(recorded))
        if m:
            mm, dd, yy = int(m.group(1)), int(m.group(2)), m.group(3)
            if 1 <= mm <= 12 and 1 <= dd <= 31:
                return (yy, month_folder(mm), "%02d" % dd)
    if len(doc_id) >= 8 and doc_id[:8].isdigit():
        mm, dd = int(doc_id[4:6]), int(doc_id[6:8])
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            return (doc_id[:4], month_folder(mm), "%02d" % dd)
    return tuple(part for part in (doc_id[:4], doc_id[4:8]) if part)     # a short id has no second folder (pathlib dropped the empty part in the old rule too)


def canonical(source, doc_id, recorded=None):
    """The One Touch address recorded in the cell: the tree, the source's folder, By Document, the day folders, the file."""
    folder = SOURCE_FOLDER.get(source.lower(), source.capitalize())
    parts = list(LAYOUT) + [folder, "By Document", *day_folders(doc_id, recorded), doc_id + ".pdf"]
    return CANON_ROOT + "\\".join(parts)


def local(root, canonical_path):
    """The same document under THIS workstation's drive root."""
    rel = canonical_path[len(CANON_ROOT):].split("\\")
    return pathlib.Path(root, *rel)


# ── finding the drive by its label ───────────────────────────────────────────────────────────────────────────────────

def _windows_volumes():
    import ctypes
    k = ctypes.windll.kernel32
    k.SetErrorMode(1)                 # SEM_FAILCRITICALERRORS: a drive with no media fails quietly, no dialog
    out = {}
    mask = k.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = letter + ":\\"
        name = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        if k.GetVolumeInformationW(root, name, 261, None, None, None, fs, 261):
            out[root] = name.value
    return out


def volumes():
    """{mount root: label} for every drive this machine can see."""
    if sys.platform == "win32":
        return _windows_volumes()
    if sys.platform == "darwin":
        base = pathlib.Path("/Volumes")
        return {str(p): p.name for p in base.iterdir() if p.is_dir()} if base.is_dir() else {}
    out = {}
    for base in ("/media/%s" % os.environ.get("USER", ""), "/run/media/%s" % os.environ.get("USER", ""), "/mnt"):
        b = pathlib.Path(base)
        if b.is_dir():
            out.update({str(p): p.name for p in b.iterdir() if p.is_dir()})
    return out


def find_drive(label):
    """The mount root of the drive carrying this label (case-insensitive).  On Windows a bare
    letter ('D' or 'D:') is accepted too.  Stops with the labels it can see when nothing matches."""
    vols = volumes()
    if sys.platform == "win32" and len(label.rstrip(":\\")) == 1:
        root = label.rstrip(":\\").upper() + ":\\"
        if root in vols:
            return root
    for root, name in vols.items():
        if name.lower() == label.lower():
            return root
    seen = ", ".join("%s = %r" % (r, n) for r, n in sorted(vols.items())) or "none"
    raise SystemExit("no drive labelled %r is mounted.  Drives seen: %s" % (label, seen))


def documents_root(drive_root):
    """<drive>\\NYC CRE Decoded\\Reproduction - the phase's folder on this drive, created if missing."""
    p = pathlib.Path(drive_root, *LAYOUT)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ======================================================================================================================
# RATE_MANAGER: THE RATE MANAGER - login 2026-09-04: "rate manager adds a worker every 5 seconds to reach sustained rate
# preference and then adjusts based on rate".  next_width() is the one decision, pure arithmetic; the Governor thread calls it.
# ======================================================================================================================

EPS = 1e-9


def _grow(dps, width, aim, wmin, wmax, step):
    """Grow by up to `step`, toward the width that would put dps at `aim`, never overshooting it."""
    per_worker = dps / width if width and dps > 0 else 0.0
    want = int(math.ceil(aim / per_worker)) if per_worker > 0 else width + step
    return max(wmin, min(wmax, width + step, max(width + 1, want)))


def next_width(dps, width, floor, ideal_lo, ideal_hi, hard, wmin, wmax, step):
    """The one decision.  dps = landings per second over the last window.  Returns the new width (== width means hold).
    floor=5, ideal 6..7, hard=8 (login's band)."""
    aim = (ideal_lo + ideal_hi) / 2.0                       # grow toward the middle of the ideal band (6.5)
    half = max(1, math.ceil(step / 2))
    if width < wmin:
        return min(wmax, wmin)
    if dps > hard + EPS:                                    # over the hard line: a full step down, at once
        return max(wmin, width - step)
    if dps > ideal_hi + EPS:                                # above the band (7..8): half a step down
        return max(wmin, width - half)
    if dps < floor - EPS:                                   # below the floor (<5): a full step up
        return _grow(dps, width, aim, wmin, wmax, step)
    if dps < ideal_lo - EPS:                                # below the ideal (5..6): half a step up, gently
        return _grow(dps, width, aim, wmin, wmax, half)
    return width                                            # inside the ideal band (6..7): hold


class Governor(threading.Thread):
    """Every `every` seconds: read the landings counter, compute dps over the window, decide, act.
    spawn(n) births n workers (the caller staggers them); retire(n) asks n workers to finish and leave.
    landings() returns the running total (filled + pending + absent); alive() returns the live worker count."""

    def __init__(self, landings, alive, spawn, retire, stop, log, *, floor=5.0, ideal_lo=6.0, ideal_hi=7.0, hard=8.0,
                 lo=20, hi=120, step=10, every=120, settle=240, knee_windows=2, knee_hold=5, knee_gain=0.15,
                 requests=None, rps_ceiling=0.0, ramp=False, stagger=5.0, ramp_window=60.0):
        super().__init__(daemon=True, name="rate-manager")
        self.landings, self.alive, self.spawn, self.retire = landings, alive, spawn, retire
        self.stop, self.log = stop, log
        self.floor, self.ideal_lo, self.ideal_hi, self.hard = floor, ideal_lo, ideal_hi, hard
        self.lo, self.hi, self.step, self.every, self.settle = lo, hi, step, every, settle
        self.knee_windows, self.knee_hold, self.knee_gain = knee_windows, knee_hold, knee_gain
        # RAMP UNTIL THE RATE IS MET (login 2026-09-04: "rate manager adds a worker every 5 seconds to reach sustained rate
        # preference and then adjusts based on rate ... i like ramp until rate is met and then adjust ... instead of hard setting
        # it"): with ramp=True the lane enters with ONE worker and the manager births one more every `stagger` seconds while
        # the docs/s over the last `ramp_window` seconds sits under ideal_lo and the request rate under 90% of the ceiling;
        # the ramp ends when the rate is met (or width_max), and the windows begin after `settle`.  No starting width to guess.
        self.ramp, self.stagger, self.ramp_window = ramp, stagger, ramp_window
        # THE REQUEST CEILING (the record's meter): docs/s is login's band, but the notices came at 58-81 REQUESTS/s held for
        # hours (the golden day ran ~57), and a stretch of small documents can hold 6 docs/s at a low request rate while a
        # stretch of long ones can push 6 docs/s past 80 requests/s.  requests() returns the lane's running request count;
        # a window above rps_ceiling retires half a step and forbids a grow, whatever the docs/s.  0 = off.
        self.requests, self.rps_ceiling = requests, rps_ceiling
        self.decisions = []          # (dps, width, new) per window
        self.hist = []               # (width, dps) per window, newest last
        self.pending = None          # a grow being judged: {"from": w0, "to": w1, "before": mean dps at w0}
        self.hold_left = 0           # windows left to refuse grows after a knee
        self.knee_hold_now = knee_hold   # the next knee's hold: doubles per repeat (cap 8x), back to the base when a grow buys
        self.per_line_hist = []      # requests/s per line, last three windows: the cap reads the exit's recent speed, not a stall

    def _mean_at(self, width, n):
        xs = [d for w, d in reversed(self.hist) if abs(w - width) <= 2][:n]
        return (sum(xs) / len(xs)) if xs else None

    def _ramp(self):
        """One worker every `stagger` seconds until the docs/s over the last `ramp_window` seconds reaches ideal_lo (or
        width_max, or the request rate nears the ceiling).  The lane enters with one worker already born."""
        t0 = time.time()
        samples = [(t0, self.landings(), self.requests() if self.requests else 0, max(1, self.alive()))]
        births = 0
        while not self.stop.wait(self.stagger):
            now = time.time()
            width = self.alive()
            samples.append((now, self.landings(), self.requests() if self.requests else 0, max(1, width)))
            while len(samples) > 2 and now - samples[0][0] > self.ramp_window:
                samples.pop(0)
            (t_a, l_a, r_a, _), (t_b, l_b, r_b, _) = samples[0], samples[-1]
            span = max(0.01, t_b - t_a)
            # the window's rates describe its AVERAGE width; project them to the width standing now, or the ramp overshoots by
            # half a window of births (live 2026-09-04: done at 66 on 54 requests/s, the first windows then read 58-60 and retired)
            w_avg = sum(s[3] for s in samples) / len(samples)
            scale = max(1, width) / max(1.0, w_avg)
            dps, rps = (l_b - l_a) / span * scale, (r_b - r_a) / span * scale
            warm = now - t0 >= self.ramp_window                  # the rate means something only once a full window has passed
            if width >= self.hi:
                why = "width_max %d reached" % self.hi
            elif warm and dps >= self.ideal_lo - EPS:
                why = "the rate is met"
            elif self.rps_ceiling and warm and rps >= 0.9 * self.rps_ceiling:
                why = "the request rate is within 10%% of the ceiling %.0f/s" % self.rps_ceiling
            else:
                self.spawn(1)
                births += 1
                if births % 10 == 0:
                    self.log("RAMP: %d workers - %.2f docs/s, %.1f requests/s over the last %.0fs - adding one every %.0fs until %.1f docs/s"
                             % (self.alive(), dps, rps, min(self.ramp_window, now - t0), self.stagger, self.ideal_lo))
                continue
            self.log("RAMP DONE at %d workers after %.0fs: %s (%.2f docs/s, %.1f requests/s over the last %.0fs, read at this width) - the rate manager's"
                     " first window in %ds" % (width, now - t0, why, dps, rps, min(self.ramp_window, now - t0), self.settle + self.every))
            return

    def run(self):
        if self.ramp:
            self._ramp()
        # the first window starts only after the ramp has settled (a half-born width reads as a slow one)
        if self.stop.wait(self.settle):
            return
        last, t_last = self.landings(), time.time()
        last_req = self.requests() if self.requests else 0
        while not self.stop.wait(self.every):
            try:
                now, n = time.time(), self.landings()
                dps = (n - last) / max(0.01, now - t_last)
                rps = 0.0
                if self.requests:
                    r = self.requests()
                    rps = (r - last_req) / max(0.01, now - t_last)
                    last_req = r
                last, t_last = n, now
                width = self.alive()
                self.hist.append((width, dps))
                if len(self.hist) > 60:
                    cut = len(self.hist) - 60
                    del self.hist[:cut]
                    if self.pending is not None:
                        self.pending["since"] = max(0, self.pending.get("since", 0) - cut)
                band = "floor %.1f, ideal %.1f-%.1f, ceiling %.1f" % (self.floor, self.ideal_lo, self.ideal_hi, self.hard)
                new = next_width(dps, width, self.floor, self.ideal_lo, self.ideal_hi, self.hard, self.lo, self.hi, self.step)
                # A SLOWING EXIT IS NOT A LACK OF LINES (00:0x): a grow is decided on the mean of the last two windows, a retire on
                # this one (fast on the safety side, slow on the grow side); a slow window pulls the mean down but not to a full step
                dps_smooth = (dps + self.hist[-2][1]) / 2.0 if len(self.hist) >= 2 else dps
                if new > width:
                    new = max(width, next_width(dps_smooth, width, self.floor, self.ideal_lo, self.ideal_hi, self.hard, self.lo, self.hi, self.step))
                per_line = (rps / width) if (width > 0 and rps > EPS) else 0.0
                self.per_line_hist.append(per_line); del self.per_line_hist[:-3]
                per_line_ref = max(self.per_line_hist)          # the exit's recent speed: a stalled window never raises the cap

                # THE REQUEST CEILING comes first, as a PROJECTION (22:4x): this window's requests per line say how many lines
                # put the request rate at 95% of the ceiling - the cap.  Over the ceiling: retire straight to the cap.  A grow the
                # docs band asks for never passes the cap; a move under 3 lines is a hold.  (Before this the manager stepped 5-10
                # lines up on the docs band and 5 back on the ceiling every few windows - two rules fighting, never a hold.)
                cap = None
                if self.rps_ceiling and per_line_ref > EPS:
                    cap = max(self.lo, min(self.hi, int(0.95 * self.rps_ceiling / per_line_ref)))
                if cap is not None and rps > self.rps_ceiling + EPS:
                    new = max(self.lo, min(cap, width - 1))
                    self.pending = None
                    self.decisions.append((round(dps, 2), width, new))
                    if new < width:
                        self.log("RATE MANAGER: %.1f requests/s over the request ceiling %.0f (%.2f docs/s with %d workers) -> RETIRE %d to %d, each"
                                 " after its document - %.2f requests/s per line puts 95%% of the ceiling at %d lines; the record's meter: 58-81"
                                 " requests/s held for hours drew the notices" % (rps, self.rps_ceiling, dps, width, width - new, new, rps / width, cap))
                        self.retire(width - new)
                    else:
                        self.log("RATE MANAGER: %.1f requests/s over the request ceiling %.0f with %d workers - at width_min %d, holding"
                                 % (rps, self.rps_ceiling, width, self.lo))
                    continue
                if cap is not None and new > width:
                    if cap - width < max(3, width // 20):     # a move under 3 lines (5% past 60 lines) is a hold, not a dither
                        self.decisions.append((round(dps, 2), width, width))
                        self.log("RATE MANAGER: %.2f docs/s (two-window mean %.2f) with %d workers asks for more lines, but %.1f requests/s (%.2f per"
                                 " line at the exit's recent speed) puts 95%% of the ceiling %.0f at %d lines - holding"
                                 % (dps, dps_smooth, width, rps, per_line_ref, self.rps_ceiling, cap))
                        continue
                    new = min(new, cap)              # the docs band's grow, no further than the cap

                # THE DOOR CURVE: judge the last grow before allowing another
                if self.pending is not None and abs(width - self.pending["to"]) <= 2:
                    fresh = self.hist[self.pending.get("since", 0):]                 # only the windows since the grow, never an earlier visit
                    seen = [d for w, d in reversed(fresh) if abs(w - self.pending["to"]) <= 2][:self.knee_windows]
                    if len(seen) >= self.knee_windows:
                        after, before, w0 = sum(seen) / len(seen), self.pending["before"], self.pending["from"]
                        self.pending = None
                        if after < before + self.knee_gain:
                            self.hold_left = self.knee_hold_now
                            self.decisions.append((round(dps, 2), width, w0))
                            self.log("RATE MANAGER: growing %d -> %d bought nothing (%.2f -> %.2f docs/s over %d windows): the door curve"
                                     " - back to %d and holding there %d windows" % (w0, width, before, after, self.knee_windows, w0, self.hold_left))
                            self.knee_hold_now = min(self.knee_hold_now * 2, 8 * self.knee_hold)    # each repeat holds twice as long
                            self.retire(width - w0)
                            continue
                        self.knee_hold_now = self.knee_hold      # the grow bought documents: the next knee starts from the base hold
                    elif new > width:
                        self.decisions.append((round(dps, 2), width, width))
                        self.log("RATE MANAGER: %.2f docs/s with %d workers - judging the last grow (%d -> %d), no further grow yet"
                                 % (dps, width, self.pending["from"], self.pending["to"]))
                        continue
                elif self.pending is not None:
                    self.pending = None                     # the width moved away from the judged grow (a cut, a retire): drop the judgment

                if new > width and self.hold_left > 0:
                    self.hold_left -= 1
                    self.decisions.append((round(dps, 2), width, width))
                    self.log("RATE MANAGER: %.2f docs/s with %d workers - below the band, but more lines bought nothing here (the door curve)"
                             " - holding at %d, %d windows before trying again" % (dps, width, width, self.hold_left))
                    continue
                if new > width and width >= self.hi:
                    self.decisions.append((round(dps, 2), width, width))
                    self.log("RATE MANAGER: %.2f docs/s with %d workers - below the band but at width_max %d - holding" % (dps, width, self.hi))
                    continue

                self.decisions.append((round(dps, 2), width, new))
                if new > width:
                    before = self._mean_at(width, self.knee_windows)
                    self.pending = {"from": width, "to": new, "before": before if before is not None else dps, "since": len(self.hist)}
                    self.log("RATE MANAGER: %.2f docs/s (two-window mean %.2f) with %d workers (%s) -> GROW to %d, births staggered" % (dps, dps_smooth, width, band, new))
                    self.spawn(new - width)
                elif new < width:
                    self.pending = None
                    self.log("RATE MANAGER: %.2f docs/s with %d workers (%s) -> RETIRE %d, each after its document" % (dps, width, band, width - new))
                    self.retire(width - new)
                else:
                    self.log("RATE MANAGER: %.2f docs/s with %d workers - in the band, holding" % (dps, width))
            except Exception as e:                          # one bad window must never stop the manager deciding
                self.log("RATE MANAGER: error in this window (%s: %.120s) - still deciding next window" % (type(e).__name__, e))


# ======================================================================================================================
# CLOUD: THE CLOUD TABLE, FROM A LANE'S POINT OF VIEW - claim, land, heartbeat, and a local outbox.
# ======================================================================================================================

def env_path():
    p = os.environ.get("NYC_CRE_DECODED_ENV")
    if p:
        return p
    return "C:/dev/nyc-cre-decoded.env" if sys.platform == "win32" else os.path.expanduser("~/nyc-cre-decoded.env")


def env():
    v = {}
    try:
        for line in open(env_path(), encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, val = line.split("=", 1)
                v[k.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        raise SystemExit("no env file at %s - it needs SUPABASE_DB_URL and SUPABASE_DB_PASSWORD" % env_path())
    if not v.get("SUPABASE_DB_URL"):
        raise SystemExit("SUPABASE_DB_URL missing in %s" % env_path())
    return v


POOLER_PORT = None      # --pooler transaction sets 6543: the TRANSACTION pooler.  The session pooler (5432, the URI's own port) allows
                        # 15 clients in all - each crew is one, the boards ~6 - so a machine running one lane process per core hit
                        # "cloud unreachable" at the ninth (2026-09-08 10:39).  The lane's use is autocommit, one statement at a time,
                        # each a SQL function (claim / land / heartbeat): exactly what transaction mode serves.  The boards keep 5432.


def dsn():
    """The pooler URI with the password from SUPABASE_DB_PASSWORD, percent-encoded (the session pooler, or the transaction
    pooler under --pooler transaction: POOLER_PORT)."""
    v = env()
    m = re.match(r"^(postgres(?:ql)?://)([^:@/]+)(?::(.*))?@([^@]+)$", v["SUPABASE_DB_URL"], re.S)
    if not m:
        raise SystemExit("SUPABASE_DB_URL does not look like postgresql://user:password@host:port/db")
    scheme, user, pw, rest = m.groups()
    pw = v.get("SUPABASE_DB_PASSWORD") or pw or ""
    if not pw or "YOUR-PASSWORD" in pw:
        raise SystemExit("database password missing - add SUPABASE_DB_PASSWORD=<password> to %s" % env_path())
    url = "%s%s:%s@%s" % (scheme, user, urllib.parse.quote(pw, safe=""), rest)
    if POOLER_PORT:
        url = re.sub(r":\d+/", ":%d/" % POOLER_PORT, url, count=1)       # host:5432/db -> host:6543/db
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


NUL_ESCAPE = "\\u0000"        # the JSON escape for NUL: PostgreSQL jsonb refuses it ("unsupported Unicode escape sequence")


class Cloud:
    """claim / registries / land / heartbeat for one source, one lane, one workstation."""

    def __init__(self, source, lane, host, app="lane"):
        self.source, self.lane, self.host, self.app = source, lane, host, app
        self.con = None
        self._lock = threading.RLock()        # one statement at a time: a reconnect never races another thread's statement

    def connect(self):
        self.close()
        self.con = psycopg2.connect(dsn(), connect_timeout=30, application_name=self.app,
                                    keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)
        self.con.autocommit = True
        return self.con

    def close(self):
        if self.con is not None:
            try:
                self.con.close()
            except Exception:
                pass
            self.con = None

    def _run(self, sql, params, fetch):
        """One statement, with one reconnect on a dropped connection.  Raises on a second failure so
        the caller can keep the work local (outbox) and try again later."""
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self.con is None or self.con.closed:
                        self.connect()
                    with self.con.cursor() as cur:
                        cur.execute(sql, params)
                        return cur.fetchall() if fetch else None
                except (psycopg2.OperationalError, psycopg2.InterfaceError):
                    self.close()
                    if attempt == 2:
                        raise
                    time.sleep(2)

    def claim(self, n=500, ttl="20 minutes"):
        """The identifiers now held by this host: pendings whose cooldown has run out first, then empties, both in
        id order (migration 0004: the wait between two checks of a pending is its claim, written by land())."""
        rows = self._run("select reproduction.claim(%s, %s, %s, %s, %s::interval)",
                         (self.source, self.lane, self.host, n, ttl), True)
        return [r[0] for r in rows]

    def registries(self, ids):
        """{identifier: registry} for the claimed ids (registry is a dict, or 'pending'/'absent', or None)."""
        if not ids:
            return {}
        rows = self._run("select identifier, registry from reproduction.%s where identifier = any(%%s)" % self.source,
                         (list(ids),), True)
        return {r[0]: r[1] for r in rows}

    def land(self, rows, pending_age="1 hour"):
        """rows = [{"identifier": ..., "value": ...}] -> cells written.  The cell rule in the table rejects
        any value that is not a fill, 'pending' or 'absent' (the whole batch, so nothing half-lands).  A landed
        pending keeps its claim as a cooldown for pending_age; claim() offers it again after that (migration 0004)."""
        if not rows:
            return 0
        payload = json.dumps(rows).replace(NUL_ESCAPE, "")   # jsonb cannot hold NUL; a source page's stray NUL is dropped, nothing else
        out = self._run("select reproduction.land(%s, %s, %s, %s::jsonb, %s::interval)",
                        (self.source, self.lane, self.host, payload, pending_age), True)
        return out[0][0]

    def heartbeat(self, width, last_event=None):
        self._run("select reproduction.heartbeat(%s, %s, %s, %s, %s)",
                  (self.source, self.lane, self.host, width, last_event), False)

    def insert_ids(self, ids):
        """identification: new document ids into the workflow table - one row per document, nothing
        else filled - and the counters moved in the SAME transaction by exactly the rows that were new:
        needed on the phase and lane rows of machinery.updates, identification's landed, and this
        workstation's own identification row.  Returns the rows inserted."""
        if not ids:
            return 0
        for attempt in (1, 2):
            try:
                if self.con is None or self.con.closed:
                    self.connect()
                self.con.autocommit = False
                try:
                    with self.con.cursor() as cur:
                        cur.execute("insert into reproduction.%s (identifier) select unnest(%%s::text[]) on conflict (identifier) do nothing"
                                    % self.source, (list(ids),))
                        n = cur.rowcount
                        if n:
                            cur.execute("update machinery.updates set needed = needed + %s where source = %s and workstation = ''", (n, self.source))
                            cur.execute("update machinery.updates set landed = landed + %s where source = %s and lane = 'identification' and workstation = ''",
                                        (n, self.source))
                            cur.execute("insert into machinery.updates as u (source, lane, workstation, landed) values (%s, 'identification', %s, %s)"
                                        " on conflict (source, lane, workstation) do update set landed = u.landed + excluded.landed",
                                        (self.source, self.host, n))
                    self.con.commit()
                    return n
                except Exception:
                    self.con.rollback()
                    raise
                finally:
                    if self.con is not None and not self.con.closed:
                        self.con.autocommit = True
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                self.close()
                if attempt == 2:
                    raise
                time.sleep(2)

    # ── reads for the audit: enumeration never writes a cell and has no table ────────────
    def _range(self, lo, hi, after=None):
        parts, params = [], []
        if after is not None:
            parts.append("identifier > %s")
            params.append(after)
        elif lo is not None:
            parts.append("identifier >= %s")
            params.append(lo)
        if hi is not None:
            parts.append("identifier < %s")
            params.append(hi)
        return (" where " + " and ".join(parts)) if parts else "", tuple(params)

    def count(self, lo=None, hi=None):
        """Rows in [lo, hi) of the workflow table (every row when lo is None): a range on the key."""
        where, params = self._range(lo, hi)
        return self._run("select count(*) from reproduction.%s%s" % (self.source, where), params, True)[0][0]

    def ids(self, lo, hi=None, page=50_000):
        """Every identifier in [lo, hi), keyset-paged on the primary key - a range, never a scan."""
        out, after = set(), None
        while True:
            where, params = self._range(lo, hi, after)
            rows = self._run("select identifier from reproduction.%s%s order by identifier limit %%s" % (self.source, where),
                             params + (page,), True)
            out.update(r[0] for r in rows)
            if len(rows) < page:
                return out
            after = rows[-1][0]

    def prefixes(self, lo, hi, n):
        """{prefix: rows} for the n-character id prefixes the table holds in [lo, hi)."""
        where, params = self._range(lo, hi)
        rows = self._run("select left(identifier, %%s) p, count(*) from reproduction.%s%s group by 1 order by 1"
                         % (self.source, where), (n,) + params, True)
        return {r[0]: r[1] for r in rows}

    def todo(self, ids):
        """The subset of ids whose registry needs work: empty, or pending and not held - no live claim for the
        registration lane, neither another workstation's nor the cooldown land() left after the last check
        (migration 0004).  For a lane whose source grants details only behind its listing (richmond), so the lane
        walks the listing and asks the table which of the ids it passes are its work."""
        if not ids:
            return set()
        rows = self._run("select w.identifier from reproduction.%s w where w.identifier = any(%%s) and (w.registry is null or"
                         " (w.registry = '\"pending\"'::jsonb and not exists (select 1 from machinery.claims c"
                         " where c.source = %%s and c.identifier = w.identifier and c.lane = 'registration' and c.until > now())))" % self.source,
                         (list(ids), self.source), True)
        return {r[0] for r in rows}

    def held(self, ids):
        """The subset of ids the table holds."""
        if not ids:
            return set()
        rows = self._run("select identifier from reproduction.%s where identifier = any(%%s)" % self.source, (list(ids),), True)
        return {r[0] for r in rows}

    def max_id(self, lo, hi=None):
        where, params = self._range(lo, hi)
        return self._run("select max(identifier) from reproduction.%s%s" % (self.source, where), params, True)[0][0]

    def alive(self, within="3 minutes"):
        """[(lane, workstation, workers, age_seconds, last_word)] for every lane heard from within the interval - the
        workstation rows of machinery.updates (0007)."""
        return self._run("select lane, workstation, workers, extract(epoch from now() - last_seen)::int, last_word"
                         " from machinery.updates where source = %s and workstation <> '' and last_seen > now() - %s::interval"
                         " order by lane, workstation", (self.source, within), True)


class Outbox:
    """Landings that could not reach the cloud yet, one JSON object per line.  Append first, land
    second, drop what landed: a cloud hiccup never loses a fetched document's path."""

    def __init__(self, path):
        self.path = pathlib.Path(path)

    def append(self, rows):
        with self.path.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")

    def load(self):
        if not self.path.exists():
            return []
        rows, seen = [], set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if "identifier" not in r and "doc_id" in r:      # a line written before 0015 (2026-09-07): the old key
                r["identifier"] = r.pop("doc_id")
            if r["identifier"] in seen:      # a later line for the same id wins
                rows = [x for x in rows if x["identifier"] != r["identifier"]]
            seen.add(r["identifier"])
            rows.append(r)
        return rows

    def count(self):
        if not self.path.exists():
            return 0
        with self.path.open("rb") as f:
            return sum(1 for line in f if line.strip())

    def drain(self, land, chunk=500):
        """Land everything held, in chunks; keep whatever the cloud did not take.  Returns (landed, left)."""
        rows = self.load()
        landed = 0
        left = []
        i = 0
        while i < len(rows):
            part = rows[i:i + chunk]
            try:
                land(part)
                landed += len(part)
            except Exception:
                left.extend(rows[i:])
                break
            i += chunk
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in left:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        os.replace(tmp, self.path)
        return landed, len(left)


# ======================================================================================================================
# LANE: THE ENTRY EVERY CYCLE LANE SHARES: one pooled session per crew, staggered births, workers each on its own keep-alive
# connection; the hang-up, the rebatch, the re-entry on a fresh batch, the park.
# ======================================================================================================================

class Refused(RuntimeError):
    """The source declined (the notice page).  Stop the lane; a person decides."""


class Transport(RuntimeError):
    """The wire failed (EOF, reset, timeout): our side, retryable, counted toward a hang-up."""


class HTTPStatus(RuntimeError):
    def __init__(self, code, url):
        super().__init__("HTTP %d at %s" % (code, url))
        self.code = code
        self.url = url


class Retry(RuntimeError):
    """Leave the document empty for a later pass (short document, unknown page shape)."""


def reason(e):
    t = str(e)
    i = t.rfind("Caused by")
    return (t[i:] if i >= 0 else t[-160:])[:160]


def pid_alive(pid):
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            k.GetExitCodeProcess(h, ctypes.byref(code))
            return code.value == 259                    # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def lane_tag(args):
    """The name this PROCESS's files carry: `<lane>`, or `<lane>.<slot>` under --slot.  One lane process pushes ~100 requests/s
    through its interpreter lock whatever its door count (measured 2026-09-08 10:06: eight doors in one process = one door's
    throughput, the process at 98% of one core), so a machine runs one lane process per core - each its own --slot, its own
    --host (the station name in the cloud, e.g. LoginSurface-3), its own doors, and its own lock/control/parked files here."""
    slot = getattr(args, "slot", "") or ""
    return "%s.%s" % (args.lane, slot) if slot else args.lane


def take_lock(path):
    """One process per lane per machine - per SLOT since 2026-09-08 (lane_tag): two processes on one lane with DISJOINT doors are
    not two doors at the source.  Fail closed: if we cannot prove we are the only door, we do not open one."""
    try:
        if path.exists():
            old = int((path.read_text(encoding="utf-8").strip() or "0"))
            if pid_alive(old):
                raise SystemExit("REFUSING TO START: %s is already running as pid %d on this machine."
                                 " Two processes on one lane = two doors at the source = the ban condition."
                                 " Stop that one first." % (path.stem, old))
            print("stale lock from pid %d (not running) - taking the lane" % old, flush=True)
        path.write_text(str(os.getpid()), encoding="utf-8")
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit("REFUSING TO START: could not take the lock %s (%s) - cannot prove this is the only door."
                         % (path.name, type(e).__name__))


def add_common_args(ap):
    """The knobs every cycle lane shares; a lane file adds its own (documentation: --drive, --fresh-days)."""
    ap.add_argument("--width", type=int, default=40, help="workers = connections (default %(default)s)")
    ap.add_argument("--host", default="", help="this workstation's name in the cloud (default: the machine name)")
    ap.add_argument("--pooler", default="session", choices=["session", "transaction"],
                    help="which Supabase pooler this lane's crews connect through: session (5432, the URI's port; 15 clients in all)"
                         " or transaction (6543; hundreds) - one lane process per core needs transaction (2026-09-08)")
    ap.add_argument("--slot", default="", metavar="N",
                    help="one lane process per core (2026-09-08): this process's number; its lock/control/parked files become <lane>.N.*,"
                         " pair it with --host <station>-N (its own cloud rows and claims) and its own --door set (disjoint across slots)")
    ap.add_argument("--stagger", type=float, default=5.0, help="seconds between worker births (default %(default)s; the richmond lanes set 0.4): a ramp of about 200 s at width 40 (2026-09-04: 0.5-s entries were cut, 5-s and 20-s entries served on the same door)")
    ap.add_argument("--claim", type=int, default=0, help="documents taken per claim (default 12 x width)")
    ap.add_argument("--ttl", default="20 minutes", help="how long a claim is ours before it goes back on the list")
    ap.add_argument("--pending-age", default="1 hour",
                    help="re-check a pending once its last check is this old (its claim stays as a cooldown that long); pendings ride ahead of the backfill, and when"
                         " the lane is up to date every claim is pendings (one request per pending per interval)")
    ap.add_argument("--redial-wait", type=int, default=60, help="seconds of silence after the session closes before the fresh-batch re-entry; a refused re-entry doubles the next wait (cap 4,800 s), a served one halves it back to this base")
    ap.add_argument("--tries", type=int, default=4, help="re-entries per incident before parking (the wait doubles each time: 1, 2, 4, 8 minutes at the base)")
    ap.add_argument("--no-pool-check", action="store_true", help="skip the exit-pool check at entry (tests only)")
    ap.add_argument("--door", action="append", default=[], metavar="URL",
                    help="a door: a proxy this crew's lines go through, e.g. socks5h://127.0.0.1:1080 (an `ssh -N -D 1080` tunnel to a rented address);"
                         " repeatable - one crew per door, each with its own exit check, session and rate manager; `direct` = the machine's own line"
                         " (the VPN's exit). Default: the machine's own line only. A notice on one door retires that door's crew; the lane parks when"
                         " every door has been refused (2026-09-07: a door is a block, ACRIS keeps its standing per address range)")
    ap.add_argument("--entry-gap", type=float, default=20.0, help="seconds between one crew's entry and the next (--also)")
    ap.add_argument("--also", action="append", default=[], metavar="LANE:WIDTH", help="host another lane's crew too, e.g. registration:40")
    ap.add_argument("--one-batch", action="store_true",
                    help="ONE BATCH (login 2026-09-06, the acris rule): every --also crew rides this crew's entry - one ramp across the crews (each crew's births"
                         " start when the previous crew's ramp ends, --stagger apart, no --entry-gap), one exit-pool check, one hang-up for the whole batch and one"
                         " re-entry from the top (this crew first), no rate manager; each crew keeps its own pooled session (08-28 run 3: mixed floors on one"
                         " session served empty viewer pages)")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many documents (a test run)")
    ap.add_argument("--log", default="", help="also append the printed lines to this file")
    ap.add_argument("--unpark", action="store_true", help="start although the lane parked itself (a person has decided)")
    # THE THREE MANAGERS (login 2026-09-04: "batch manager makes sure the batch is good to enter and enters 1 time / rate manager
    # adds a worker every 5 seconds to reach sustained rate preference and then adjusts based on rate / session manager tracks
    # requests until the set limit then ends once reached and tells batch manager to go from the top").  Knobs, not code:
    # --manage 0 (default) = the lane as before, fixed --width; the acris site turns them on for its documentation lane
    # (MANAGE in Acris Reproduction.py).
    ap.add_argument("--manage", type=int, default=0, help="1 = the rate and session managers run this lane (default 0: fixed --width, the cycle only)")
    ap.add_argument("--ramp-to-rate", type=int, default=1, help="managed: 1 = enter with ONE worker and add one every --stagger s until the band; 0 = ramp to --width")
    ap.add_argument("--rate-floor", type=float, default=5.0, help="managed: docs/s under this = a full step up")
    ap.add_argument("--rate-ideal-lo", type=float, default=6.0, help="managed: the band's lower edge (login: around 6)")
    ap.add_argument("--rate-ideal-hi", type=float, default=7.0, help="managed: the band's upper edge")
    ap.add_argument("--dps-ceiling", type=float, default=8.0, help="managed: the hard line - a full step down at once (login: no more than 8 ever)")
    ap.add_argument("--rps-ceiling", type=float, default=60.0, help="managed: REQUESTS/s ceiling, the record's meter (notices at 58-81 held for hours; the golden day ~57); 0 = off")
    ap.add_argument("--width-min", type=int, default=20, help="managed: the manager never retires below this")
    ap.add_argument("--width-max", type=int, default=120, help="managed: the manager never grows above this (the pool's ceiling is %d)" % MAX_WIDTH)
    ap.add_argument("--adjust-every", type=int, default=120, help="managed: seconds per window")
    ap.add_argument("--adjust-step", type=int, default=10, help="managed: workers per full step")
    ap.add_argument("--ramp-window", type=float, default=60.0, help="managed: the ramp reads its docs/s and requests/s over this many seconds (read at the current width)")
    ap.add_argument("--session-max-requests", type=int, default=0, help="managed: end the session at this many requests and re-enter on a fresh batch (login: 1,000,000); 0 = off")
    return ap


def sibling_role(source, name, here, drive_root, args):
    """The role of a sibling lane file, loaded by path (`<Source> <Name>.py` carries a space): its
    module-level role(drive_root, args)."""
    sib = pathlib.Path(here).parent / name / ("%s %s.py" % (source, name.capitalize()))
    if not sib.is_file():
        raise SystemExit("no lane file for --also %s (expected %s)" % (name, sib))
    import importlib.util
    spec = importlib.util.spec_from_file_location("%s_%s" % (source.lower(), name), sib)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.role(drive_root, args)


def role_args(args, shared=(), **defaults):
    """A hosted crew's own arguments (--also): its OWN defaults, overlaid only with the shared names the host
    carries (--edge, --pending-age, --fresh-days ...).  A host's --every is the host's, never the guest's
    (audit 2026-09-03: a guest read its knobs off the host's namespace and crashed at start)."""
    ns = types.SimpleNamespace(**defaults)
    for k in shared:
        if hasattr(args, k):
            setattr(ns, k, getattr(args, k))
    return ns


def roles_for(source, args, here, drive_root, own):
    """[(role, width), ...]: this lane's own role first, then every --also LANE:WIDTH crew."""
    roles = [(own, args.width)]
    for spec in args.also:
        name, _, w = spec.partition(":")
        name = name.strip().lower()
        try:
            w = int(w or 40)
        except ValueError:
            raise SystemExit("--also takes LANE:WIDTH, e.g. registration:40 (got %r)" % spec)
        if name == args.lane:
            raise SystemExit("--also %s: that is this lane" % name)
        roles.append((sibling_role(source, name, here, drive_root, args), w))
    return roles


def net_up():
    """Any HTTP answer from a neutral host = the wire is up.  A wifi outage is never a block."""
    for host in ("https://www.nyc.gov/", "https://github.com/"):
        try:
            urllib.request.urlopen(urllib.request.Request(host, method="HEAD",
                                   headers={"User-Agent": "Mozilla/5.0"}), timeout=10)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            continue
    return False


HANGUP_WINDOW_S, HANGUP_PAUSE_S = 60, 5     # every worker failing inside 60 s is the session closed; a cut worker pauses 5 s then redials
HANGUP_QUIET_S = 10                         # ... and nothing landed for 10 s: a partial close keeps landing on the lines still open
SERVED_LANDINGS, SERVED_S = 300, 300        # a re-entry that landed this many, or lived five minutes, was served then closed by the door; fewer and sooner = refused
MAX_WIDTH = 128          # the pool's ceiling; a connection is opened only when a worker first asks


def exit_pool(draws=5, pause=1.0, proxy=""):
    """Five fresh-connection draws of the public exit (never the source).  The lane has no IP: the VPN
    hands EACH connection an exit from a pool, so one draw is one draw; five in one /24 = the pool is
    settled, five spanning blocks = the VPN app is mid-switch and no entry goes out.  Through a door
    (proxy) the draws go through the tunnel and answer the rented address, one block by construction."""
    seen = []
    hdr = {"User-Agent": "nyc-cre-decoded lane (exit check)", "Connection": "close"}
    for i in range(draws):
        try:
            if proxy:
                seen.append(requests.get("https://api.ipify.org", headers=hdr, proxies={"http": proxy, "https": proxy}, timeout=15).text.strip())
            else:
                r = urllib.request.urlopen(urllib.request.Request("https://api.ipify.org", headers=hdr), timeout=15)
                seen.append(r.read().decode().strip())
        except Exception as e:
            seen.append("fail:" + type(e).__name__)
        if i < draws - 1:
            time.sleep(pause)
    blocks = sorted({".".join(x.split(".")[:3]) for x in seen if x[:1].isdigit()})
    return seen, blocks


def wait_for_pool(ctx, c):
    """No entry while the exit pool spans blocks (the VPN app mid-switch) or answers nothing."""
    if getattr(ctx.args, "no_pool_check", False):
        return
    while not ctx.stopping.is_set():
        seen, blocks = exit_pool(proxy=c.door)
        if len(blocks) == 1 and all(x[:1].isdigit() for x in seen):
            _log(ctx, "%s: exit pool %s - one block %s, entering" % (c.name, ", ".join(seen), blocks[0]))
            return
        _log(ctx, "%s: exit pool %s - %s; waiting 30 s, no entry" % (c.name, ", ".join(seen),
             "SPANS BLOCKS %s (the VPN app is mid-switch)" % blocks if len(blocks) > 1 else "no answer"))
        try:
            c.cloud.heartbeat(0, "waiting for a settled exit pool")
        except Exception:
            pass
        time.sleep(30)


def make_session(width, ua, proxy=""):
    """One pooled session for a crew.  `width` is the crew's width at birth and is not used for sizing: the pool is
    MAX_WIDTH + 4 whatever the width, so a resize (the control file, the rate manager) never needs a new session.  The
    parameter stays because the enumeration and richmond registration programs pass it too.  `proxy` is the crew's
    door (--door): every line of the session leaves through it."""
    s = requests.Session()
    s.headers.update({"User-Agent": ua})
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    s.mount("https://", requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=MAX_WIDTH + 4,
                                                      max_retries=0, pool_block=True))
    return s


class Crew:
    """One role, one session, N workers, its own queue, results, counters and detectors."""

    def __init__(self, role, width, lane_ctx, door="", index=0):
        self.role, self.width, self.ctx = role, width, lane_ctx
        self.door = "" if door in ("", "direct") else door        # --door: the proxy this crew's lines go through; "" = the machine's own line
        self.door_index = index           # the door's number in this process (a door added later takes the next number)
        self.name = role.lane if (not self.door and index <= 1) else "%s@door%d" % (role.lane, index)    # how the log names this crew
        self.retired = False              # a notice on this crew's door: it leaves alone while the other doors go on
        self.session = None
        self.workers = []
        self.stop = threading.Event()
        self.q = queue.Queue()
        self.results = []
        self.lock = threading.Lock()
        self.stats = {"reqs": 0, "ok": 0, "fail": 0, "reask": 0, "short": 0,
                      "filled": 0, "pending": 0, "absent": 0, "blank": 0}
        self.failed = []                  # (item, reason) since the last land - a role that walks a range re-asks these
        self.transport_streak = 0
        self.transport_hits = []          # times of recent transport errors: a burst is a cut line
        self.wall_streak = 0
        self.last_success = time.time()
        self.cloud = Cloud(role.source, role.lane, lane_ctx.host, app="%s %s" % (role.source, role.lane))
        self.outbox = Outbox(lane_ctx.here / ("%s.outbox.jsonl" % role.lane))
        self.fails = lane_ctx.here / ("%s.fails.jsonl" % role.lane)
        self.held = set()                 # claimed, not yet landed
        self.tries = 0                    # redials in the current incident
        self.wait_s = None                # the backoff state: set from --redial-wait at the first hang-up; x2 per refused re-entry, /2 per served one
        self.ok_at_redial = 0             # landings when the last re-entry was made: served or refused is decided by landings, never by age
        self.last_redial = 0.0
        self.reentry_at = None            # set at start and by a hang-up: when the crew may enter; the main loop enters it (nothing blocks)
        self.entries = 0                  # entries made in the life of the process: the first, then every re-entry
        self.ramp = None                  # the births thread of the current entry
        self.ramp_end = 0.0               # when the last ramp completed: the next crew enters --entry-gap after it
        self.entered_at = 0.0             # when this crew last started its ramp: doors enter --entry-gap apart, then ramp CONCURRENTLY
        self.born = 0                     # workers born in the current entry
        self.idle_until = 0.0             # when the to-do list came back empty, do not ask again before this
        self.progress_at = time.time()    # when the last PROGRESS line was printed (the rate divides by real time)
        self.target = width               # the width asked for: a managed crew ramps from one worker and moves on its own, but claims by this
        self.reqs_at_entry = 0            # the session manager counts requests from the entry, not the process
        self.governor = None              # the rate manager of the current entry (managed lanes)
        self.pool_thread, self.pool_ok, self.pool_at = None, False, 0.0     # the exit-pool check of the pending entry runs on its own thread (_await_entry)

    # ── the fetcher every worker uses: counts, closes, classifies ────────────────────────
    def get(self, url, referer, timeout=90):
        with self.lock:
            self.stats["reqs"] += 1
        try:
            r = self.session.get(url, headers={"Referer": referer}, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            raise Transport("%s: %s" % (type(e).__name__, reason(e)))
        try:
            if r.status_code >= 400:
                raise HTTPStatus(r.status_code, url)
            return r.content, r.headers.get("Content-Type", "")
        finally:
            r.close()

    def note_fail(self, doc_id, err):
        with self.lock:
            self.stats["fail"] += 1
            self.failed.append((doc_id, err))
            self.held.discard(doc_id)             # no longer ours to land: the claim expires and the document comes back later
        try:
            with self.fails.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "id": doc_id, "err": err[:160]}) + "\n")
        except OSError:
            pass

    def worker(self, born):
        while not self.stop.is_set():
            try:
                doc_id, registry, attempt = self.q.get(timeout=1)
            except queue.Empty:
                continue
            try:
                value = self.role.fetch(self, doc_id, registry)
                classify = getattr(self.role, "classify", None)
                with self.lock:
                    self.results.append({"identifier": doc_id, "value": value})
                    self.stats["ok"] += 1
                    self.stats[classify(value) if classify else ("filled" if value not in ("pending", "absent") else value)] += 1
                    self.transport_streak = 0
                    self.wall_streak = 0
                    self.last_success = time.time()
            except Refused as e:
                self.ctx.refused(self, "REFUSED at %s %s - %s" % (doc_id, time.strftime("%Y-%m-%d %H:%M"), e))
                return
            except HTTPStatus as e:
                with self.lock:
                    if e.code in (429, 503):             # the wall counts these two only (trap 2)
                        self.wall_streak += 1
                self.note_fail(doc_id, str(e))
            except Transport as e:
                now = time.time()
                with self.lock:
                    self.transport_streak += 1
                    self.transport_hits.append((now, born))
                    self.transport_hits = [(t, b) for t, b in self.transport_hits if now - t <= HANGUP_WINDOW_S]
                if attempt == 0 and not self.stop.is_set():
                    self.q.put((doc_id, registry, 1))     # one more try: a stale keep-alive after an idle spell fails once
                else:
                    self.note_fail(doc_id, str(e))
                self.stop.wait(HANGUP_PAUSE_S)            # a cut line never re-dials at full speed (the 40x5 pattern)
            except Retry as e:
                with self.lock:
                    if str(e).startswith("short"):
                        self.stats["short"] += 1
                self.note_fail(doc_id, str(e))
            except Exception as e:
                self.note_fail(doc_id, "%s: %s" % (type(e).__name__, reason(e)))
            # a parked worker (width lowered) leaves after its document
            if born > self.width:
                return

    def hung_up(self):
        """The far side closed the session: every worker hit the wire inside HANGUP_WINDOW_S and nothing has landed
        for HANGUP_QUIET_S (login 2026-09-04: "you will know its time to rebatch when ALL lanes are closed").  A
        partial close is not this - those workers redial one by one while the other lines keep landing, and the
        crew keeps its width (2026-09-04 12:27: 17 lines closed, all 40 back in 30 s).  A healthy crew fails a
        handful of requests an hour; a closed session fails the whole width inside a minute (measured 2026-09-04
        14:51: 40 errors in 60 s) and lands nothing after.  During a ramp the whole width is the workers born."""
        now = time.time()
        with self.lock:
            self.transport_hits = [(t, b) for t, b in self.transport_hits if now - t <= HANGUP_WINDOW_S]
            if not self.transport_hits or now - self.last_success <= HANGUP_QUIET_S:
                return False
            whole = max(1, min(self.width, self.born))
            return len({b for _, b in self.transport_hits}) >= whole or len(self.transport_hits) >= self.width

    def enter(self, stagger):
        """ONE entry: a fresh pooled session, workers born `stagger` apart on their own thread - one handshake
        each, then keep-alive for the life of the crew.  Returns at once: the main loop keeps feeding and
        landing while the ramp runs (a 40-wide ramp is about 200 s)."""
        self.stop = threading.Event()
        self.transport_hits = []
        self.session = make_session(self.width, self.role.ua, self.door)
        self.workers = []
        self.born = 0
        self.entries += 1
        self.transport_streak = 0
        self.wall_streak = 0
        self.last_success = time.time()
        self.entered_at = time.time()     # the ramp starts now; other doors may enter --entry-gap after this, ramping alongside
        self.reqs_at_entry = self.stats["reqs"]
        a = self.ctx.args
        if getattr(a, "manage", 0) and getattr(a, "ramp_to_rate", 1):
            self.width = 1                # RAMP TO RATE: one worker in, the Governor births the rest one every `stagger` (login: "ramp until rate is met and then adjust")
        self.ramp = threading.Thread(target=self._births, args=(1, self.width, stagger), daemon=True, name="%s-births" % self.role.lane)
        self.ramp.start()

    def _births(self, lo, hi, stagger):
        for i in range(lo, hi + 1):
            if self.stop.is_set() or i > self.width:      # a retire during a grow ends the grow: no birth above the width standing now
                break
            t = threading.Thread(target=self.worker, args=(i,), daemon=True, name="%s-%d" % (self.role.lane, i))
            t.start()
            self.workers.append(t)
            self.born = max(self.born, i)
            if i < hi:
                self.stop.wait(stagger)
        self.ramp_end = time.time()

    def ramping(self):
        return self.ramp is not None and self.ramp.is_alive()

    def leave(self):
        self.stop.set()
        if self.ramp is not None:
            self.ramp.join(timeout=30)
        for t in list(self.workers):
            t.join(timeout=120)
        try:
            self.session.close()
        except Exception:
            pass

    def resize(self, new_width, stagger):
        """Workers above the new width park after their current document; missing ones are born staggered on
        the births thread, never blocking the loop."""
        old, self.width = self.width, new_width
        if new_width > old:
            self.ramp = threading.Thread(target=self._births, args=(old + 1, new_width, stagger), daemon=True, name="%s-births" % self.role.lane)
            self.ramp.start()

    def alive(self):
        return sum(1 for t in list(self.workers) if t.is_alive())


class Context:
    def __init__(self, here, host, args):
        self.here, self.host, self.args = here, host, args
        self.exit_code = None
        self.exit_reason = None
        self.stopping = threading.Event()
        self.crews = []                   # set by run(): every crew of the process, one per role per door

    def refused(self, crew, why):
        """The notice on one crew's door.  With other doors open that crew alone retires (its lines close, the main loop
        lands what it holds, its claims expire); the last open door parks the lane as before (exit 2, a person decides)."""
        others = [c for c in self.crews if c is not crew and not c.retired]
        if not others or self.stopping.is_set():
            self.park(why, code=2)
            return
        crew.retired = True
        crew.stop.set()
        _log(self, "%s: %s - this door is spent: its crew retires, %d door%s open" % (crew.name, why, len(others), "" if len(others) == 1 else "s"))

    def park(self, why, code):
        """Stop the whole process with a written reason; the lane refuses to start again until
        --unpark, so nobody walks it back into a refusal by habit."""
        if self.stopping.is_set():
            return
        self.exit_code, self.exit_reason = code, why
        self.stopping.set()
        try:
            (self.here / ("%s.parked" % lane_tag(self.args))).write_text(why + "\n", encoding="utf-8")
        except OSError:
            pass


def _log(ctx, msg):
    line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    if ctx.args.log:
        try:
            with open(ctx.args.log, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def _control(ctx, crews):
    """<lane>.control: `width=N` / `<lane>=N` per crew, `door=URL` (or `door=direct`) to open one more door on the running lane
    (acted on once), `stop` to stop.  Read once a minute."""
    p = ctx.here / ("%s.control" % lane_tag(ctx.args))
    if not p.exists():
        return
    try:
        lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return
    consumed = []
    for l in lines:
        if l.lower() == "stop":
            ctx.exit_code, ctx.exit_reason = 0, "stopped by %s at %s" % (p.name, time.strftime("%H:%M"))
            ctx.stopping.set()
            try:
                p.write_text("", encoding="utf-8")            # the word is acted on once: a stale `stop` never stops the next start
            except OSError:
                pass
            return
        if "=" in l:
            k, v = [x.strip() for x in l.split("=", 1)]
            if k == "door":
                _add_door(ctx, crews, v)
                consumed.append(l)                            # acted on once: a stale `door=` never re-enters a door spent since
                continue
            for c in crews:
                if (k == "width" and c.role.lane == crews[0].role.lane) or k == c.role.lane:      # every door of that lane
                    try:
                        n = min(int(v), MAX_WIDTH)
                    except ValueError:
                        continue
                    if n != c.width and n > 0:
                        _log(ctx, "%s width %d -> %d (control file)" % (c.name, c.width, n))
                        c.resize(n, ctx.args.stagger)
    if consumed:
        try:
            p.write_text("".join(x + "\n" for x in lines if x not in consumed), encoding="utf-8")
        except OSError:
            pass


def _add_door(ctx, crews, door):
    """HOT-ADD A DOOR (login 2026-09-08 08:0x: "go ahead and write the hot-add door change"): `door=URL` or `door=direct` in the
    control file gives the RUNNING lane one more crew per role on that door, born the way a launched crew is born (its cloud
    row, the outbox landed, a batch claimed, then the ordinary entry: wire up, exit pool settled, one ramp, its own rate
    manager) - so the VPN walk swaps blocks and rented addresses join without a relaunch that would re-enter the other doors.
    A door already open is not opened twice.  A retired door is not re-entered here: the walk moves the VPN to a served block
    first, then writes `door=direct` again, and the new crew takes the next door number.  ONE BATCH takes no doors."""
    d = "" if door in ("", "direct") else door
    shown = door or "direct"
    if _one_batch(ctx, crews):
        _log(ctx, "%s: door=%s ignored - ONE BATCH takes no doors" % (ctx.args.lane, shown))
        return
    for c in crews:
        if c.door == d and not c.retired:
            _log(ctx, "%s: door=%s is already open as %s - nothing added" % (ctx.args.lane, shown, c.name))
            return
    roles = []
    for c in crews:
        if all(c.role is not r for r in roles):
            roles.append(c.role)
    index = 1 + max(getattr(o, "door_index", 1) for o in crews)
    added = []
    for role in roles:
        width = next((o.width for o in crews if o.role is role), getattr(ctx.args, "width", 1)) or 1
        c = Crew(role, width, ctx, d, index)
        try:
            c.cloud.connect()
            c.cloud.heartbeat(c.width, "door%d added 1x%d at %s" % (index, c.width, time.strftime("%Y-%m-%d %H:%M")))
        except Exception as e:
            _log(ctx, "%s: door=%s not added - the cloud table is unreachable (%s); the word is dropped, write it again" % (ctx.args.lane, shown, reason(e)))
            try:
                c.cloud.close()
            except Exception:
                pass
            return
        _land(ctx, c)
        _feed(ctx, c)
        c.reentry_at = time.time()                        # it enters like any crew: the loop takes it one ramp at a time, --entry-gap apart
        crews.append(c)
        added.append(c)
    _log(ctx, "%s: door%d = %s added by the control file - %s waiting to enter; %d door%s open" % (
        ctx.args.lane, index, shown, ", ".join(c.name for c in added),
        len({o.door for o in crews if not o.retired}), "" if len({o.door for o in crews if not o.retired}) == 1 else "s"))


def _feed(ctx, c):
    """Keep the crew's queue a batch ahead: claim when it runs low, fetch the registries, queue.
    A role that walks a range instead (identification) brings its own feed."""
    if hasattr(c.role, "feed"):
        c.role.feed(c, ctx)
        return
    batch = max(c.width, c.target)               # a managed crew ramps from one worker; it still claims a whole batch
    if c.q.qsize() >= batch or time.time() < c.idle_until:
        return
    if ctx.args.limit and c.stats["ok"] + c.q.qsize() >= ctx.args.limit:
        return
    try:
        ids = c.cloud.claim(ctx.args.claim or 12 * batch, ctx.args.ttl)
        regs = c.cloud.registries(ids) if getattr(c.role, "needs_registry", True) else {}
    except Exception as e:
        _log(ctx, "%s: claim failed (%s) - will retry" % (c.name, reason(e)))
        c.idle_until = time.time() + 30
        return
    if not ids:
        c.idle_until = time.time() + 60          # nothing to do: ask again in a minute, not every second
        return
    for i in ids:
        c.held.add(i)
        c.q.put((i, regs.get(i), 0))


def _land(ctx, c):
    if hasattr(c.role, "land"):
        c.role.land(c, ctx)               # a role that walks a range lands its own way (ids + the edge)
        return
    with c.lock:
        rows, c.results = c.results, []
        c.failed = []                     # claim lanes leave a failed document for a later pass
    if rows:
        c.outbox.append(rows)
        for r in rows:
            c.held.discard(r["identifier"])
    if c.outbox.path.exists() and c.outbox.path.stat().st_size > 0:
        landed, left = c.outbox.drain(lambda rows: c.cloud.land(rows, ctx.args.pending_age))
        if left:
            _log(ctx, "%s: cloud did not take %d landings (kept in %s)" % (c.name, left, c.outbox.path.name))


def _progress(ctx, c, t0, last):
    s = dict(c.stats)
    now = time.time()
    el = max(now - t0, 1e-9)
    docs = (s["ok"] - last.get("ok", 0)) / max(now - c.progress_at, 1e-9)   # real window, never an assumed minute
    c.progress_at = now
    fmt = ("PROGRESS %dm %s - reqs %s (%.1f/s) - %s " + getattr(c.role, "noun", "filled")
           + " - %s absent - %s pending - short %d - fail %d - reask %d - width %d/%d - held %d - outbox %d - %.2f docs/s")
    line = fmt % (el / 60, c.name, "{:,}".format(s["reqs"]), s["reqs"] / el, "{:,}".format(s["filled"]),
                  "{:,}".format(s["absent"]), "{:,}".format(s["pending"]), s["short"], s["fail"], s["reask"],
                  c.alive(), c.width, len(c.held), c.outbox.count(), docs)
    if c.reentry_at is not None:
        line += " - re-entry in %ds" % max(0, int(c.reentry_at - now))
    elif c.ramping():
        line += " - ramping %d/%d" % (c.born, c.width)
    status = getattr(c.role, "status", None)
    _log(ctx, line + (" - " + status() if status else ""))
    return s


def _rebatch(ctx, c):
    """THE REBATCH (login 2026-09-04: "pull out, rebatch, then launch"): the cut batch is dropped so the
    re-entry asks for NEW work.  A claim lane empties its queue - the dropped claims expire on their own
    (--ttl) and come back in a later pass; a role that walks a range (identification) brings its own
    rebatch (the window is re-asked from the edge, which never moved past an unanswered number).  Without
    this the re-entry resumed the cut batch from the same queue, which is what the door's closing waves
    refuse (2026-09-04 13:03)."""
    if hasattr(c.role, "rebatch"):
        return c.role.rebatch(c, ctx)
    n = 0
    while True:
        try:
            item = c.q.get_nowait()
        except queue.Empty:
            break
        c.held.discard(item[0])
        n += 1
    return n


def _hangup_batch(ctx, crews, c, why, planned=False):
    """ONE BATCH: what closes one crew closes the batch - the host takes the incident (its tries, its wait, the
    park), every other crew with a line open leaves too, lands what it holds, drops its cut batch and waits for
    the same re-entry (the host first, then each crew after the previous ramp).  Outside ONE BATCH the crew
    hangs up on its own, as before."""
    if not _one_batch(ctx, crews):
        return _hangup(ctx, c, why, planned)
    host = crews[0]
    if c is not host:
        why = "%s - seen on %s" % (why, c.role.lane)
    if host.reentry_at is None:
        _hangup(ctx, host, why, planned)
    if ctx.stopping.is_set():
        return
    due = host.reentry_at if host.reentry_at is not None else time.time() + (host.wait_s or ctx.args.redial_wait)
    for o in crews:
        if o is host or o.reentry_at is not None:
            continue
        o.leave()
        _land(ctx, o)
        dropped = _rebatch(ctx, o)
        o.reentry_at = due
        _log(ctx, "%s: the batch hung up - leaving too, %d of the cut batch dropped, back with the batch at %s"
             % (o.role.lane, dropped, time.strftime("%H:%M:%S", time.localtime(due))))
        try:
            o.cloud.heartbeat(0, "the batch hung up: back at %s" % time.strftime("%H:%M", time.localtime(due)))
        except Exception:
            pass


def _hangup(ctx, c, why, planned=False):
    """The session closed (or the wire died): hang up at once, land what the crew holds, drop the cut batch
    and set the wait; the main loop re-enters the crew when it is due (_await_entry).  Nothing blocks:
    every other crew keeps feeding and landing.  planned=True is the SESSION manager's close at the request
    knob: the same exit and the same re-entry, but no try is spent and the wait stays at the base."""
    now = time.time()
    if c.wait_s is None:
        c.wait_s = ctx.args.redial_wait
    if planned:
        c.tries = 0                      # a session ended on purpose is not an incident: the next entry is the first of a new one
        c.wait_s = ctx.args.redial_wait
    elif c.tries and (c.stats["ok"] - c.ok_at_redial >= SERVED_LANDINGS or now - c.last_redial >= SERVED_S):
        c.tries = 0                      # the last re-entry was SERVED (a real batch landed, or five minutes lived) and the door then closed it: the incident closed
        c.wait_s = max(c.wait_s // 2, ctx.args.redial_wait)
    elif c.tries:
        c.wait_s = min(c.wait_s * 2, 4800)   # the last re-entry was REFUSED at the door (cut inside its ramp): the next wait doubles
    if c.tries >= ctx.args.tries:
        ctx.park("PARKED: %d re-entries in a row refused (%s) at %s" % (c.tries, c.name, time.strftime("%Y-%m-%d %H:%M")), code=3)
        return
    _log(ctx, "%s: %s - hanging up" % (c.name, why))
    c.leave()
    _land(ctx, c)                                       # what the crew had already fetched lands now
    dropped = _rebatch(ctx, c)
    c.reentry_at = time.time() + c.wait_s
    _log(ctx, "%s: %d of the cut batch dropped (their claims expire on their own) - re-entry %d/%d on a fresh batch in %ds, no line open"
         % (c.name, dropped, c.tries + 1, ctx.args.tries, c.wait_s))
    try:
        c.cloud.heartbeat(0, "hang-up: re-entry %d/%d at %s" % (c.tries + 1, ctx.args.tries, time.strftime("%H:%M", time.localtime(c.reentry_at))))
    except Exception:
        pass


def _pool_check(ctx, c):
    """The exit-pool check on its own thread (_await_entry): the verdict and its time land on the crew."""
    wait_for_pool(ctx, c)
    c.pool_at = time.time()
    c.pool_ok = not ctx.stopping.is_set()


def _one_batch(ctx, crews):
    """ONE BATCH (login 2026-09-06): the hosted crews ride the host's entry.  True only with a crew to host."""
    return bool(getattr(ctx.args, "one_batch", False)) and len(crews) > 1


def _join_batch(ctx, crews, c):
    """A hosted crew of ONE BATCH enters right after the previous crew's ramp: the host entered (its pool check
    and its try are the batch's), the crews before it are in, nobody is ramping, the last ramp ended --stagger
    ago - the same beat as the births, so the batch is one ramp from the first worker to the last."""
    now = time.time()
    host = crews[0]
    if host.reentry_at is not None or not host.entries or now < c.reentry_at or ctx.stopping.is_set():
        return
    i = crews.index(c)
    if crews[i - 1].reentry_at is not None or any(o.ramping() for o in crews if o is not c):
        return
    if now - max(o.ramp_end for o in crews) < ctx.args.stagger:
        return
    if not net_up():
        c.reentry_at = now + 60
        _log(ctx, "%s: network is DOWN - waiting a minute, no try spent" % c.role.lane)
        return
    _feed(ctx, c)
    c.enter(ctx.args.stagger)
    c.reentry_at = None
    _log(ctx, "%s: joined the batch right after %s's ramp - %d workers, births %.0fs apart, no entry of its own"
         % (c.role.lane, crews[i - 1].role.lane, c.width, ctx.args.stagger))


def _await_entry(ctx, crews, c):
    """A crew waiting to enter (the first entry, or a re-entry after a hang-up) enters when its wait is over,
    no other crew is ramping, the last ramp ended --entry-gap ago, the wire is up and the exit pool is
    settled.  The fresh batch is claimed right before the ramp so the first-born workers have work; the
    try is spent here, at the re-entry itself - never while the wire is down.  In ONE BATCH the hosted
    crews do not enter on their own: they join (_join_batch)."""
    if _one_batch(ctx, crews) and c is not crews[0]:
        return _join_batch(ctx, crews, c)
    now = time.time()
    if now < c.reentry_at or ctx.stopping.is_set():
        return
    # a burst of handshakes on ONE address is the ban condition, so never two crews ramping on the SAME door at once;
    # DIFFERENT doors are different addresses and ramp CONCURRENTLY (login 2026-09-08: "why wait for door 1 to reach
    # perfection before launching door 2 ... each door ramps to its max and sprints to its allowance before a new one
    # comes in").  Crews with no door (door="") share the machine's own line and still serialize, as before.
    if any(o is not c and o.door == c.door and o.ramping() for o in crews):
        return
    # space ENTRIES so the doors do not all draw their pool and handshake in the same instant: a door enters --entry-gap
    # after the last door started ramping (not after it finished), so eight doors are all ramping within ~8*entry_gap.
    if now - max([o.entered_at for o in crews] + [0.0]) < ctx.args.entry_gap:
        return
    if not net_up():
        c.reentry_at = now + 60
        _log(ctx, "%s: network is DOWN - waiting a minute, no try spent" % c.name)      # wifi is not a block
        return
    if c.pool_thread is None:
        # the exit-pool check draws and waits on its own thread: a crew waiting for the VPN never stalls the others' feeding and landing
        c.pool_ok = False
        c.pool_thread = threading.Thread(target=_pool_check, args=(ctx, c), daemon=True, name="%s-pool" % c.role.lane)
        c.pool_thread.start()
        return
    if c.pool_thread.is_alive():
        return
    c.pool_thread = None
    if not c.pool_ok or ctx.stopping.is_set():
        return
    if time.time() - c.pool_at > 120:
        return                                              # the verdict aged while another crew ramped: drawn again on the next pass
    _feed(ctx, c)                                           # the fresh batch right before the ramp, never before a wait
    if c.entries:
        c.tries += 1
        c.last_redial = time.time()
        c.ok_at_redial = c.stats["ok"]
    c.enter(ctx.args.stagger)
    c.reentry_at = None
    a = ctx.args
    if getattr(a, "manage", 0) and _one_batch(ctx, crews):
        _log(ctx, "%s: --manage ignored in ONE BATCH (login 2026-09-06: no rate manager on the batch; stay low and be patient)" % c.role.lane)
    if getattr(a, "manage", 0) and not _one_batch(ctx, crews):
        c.governor = Governor(lambda: c.stats["ok"], c.alive,
                                 lambda n: c.resize(min(a.width_max, c.alive() + n), a.stagger),      # the manager's n is relative to the live count it read
                                 lambda n: c.resize(max(1, c.alive() - n), a.stagger),
                                 c.stop, lambda m: _log(ctx, "%s: %s" % (c.role.lane, m)),
                                 floor=a.rate_floor, ideal_lo=a.rate_ideal_lo, ideal_hi=a.rate_ideal_hi, hard=a.dps_ceiling,
                                 lo=a.width_min, hi=a.width_max, step=a.adjust_step, every=a.adjust_every,
                                 settle=(a.adjust_every if a.ramp_to_rate else max(a.adjust_every, int(c.target * a.stagger) + a.adjust_every)),
                                 requests=lambda: c.stats["reqs"], rps_ceiling=a.rps_ceiling,
                                 ramp=bool(a.ramp_to_rate), stagger=a.stagger, ramp_window=getattr(a, "ramp_window", 60.0))
        c.governor.start()
        _log(ctx, "%s: %s - %s; RATE MANAGER on: %sfloor %.1f, ideal %.1f-%.1f docs/s, hard %.1f, request ceiling %.0f/s, width %d..%d, step %d every %ds;"
                  " SESSION knob: %s" % (c.name, "entered" if c.entries == 1 else "re-entered (%d/%d)" % (c.tries, a.tries),
                  "one worker in, one more every %.0fs until the band" % a.stagger if a.ramp_to_rate else "%d workers, births %.0fs apart" % (c.width, a.stagger),
                  "RAMP TO RATE - " if a.ramp_to_rate else "", a.rate_floor, a.rate_ideal_lo, a.rate_ideal_hi, a.dps_ceiling, a.rps_ceiling,
                  a.width_min, a.width_max, a.adjust_step, a.adjust_every,
                  ("{:,} requests, then a fresh batch".format(a.session_max_requests)) if a.session_max_requests else "no request cap"))
    else:
        _log(ctx, "%s: %s - %d workers, births %.0fs apart, one entry" % (c.name, "entered" if c.entries == 1 else "re-entered (%d/%d)" % (c.tries, ctx.args.tries), c.width, ctx.args.stagger))


def run(roles, args, here):
    """roles = [(role, width), ...]; the first is the lane's own."""
    here = pathlib.Path(here)
    host = args.host or socket.gethostname()
    global POOLER_PORT
    if getattr(args, "pooler", "session") == "transaction":
        POOLER_PORT = 6543                                   # every Cloud.connect() in this process goes through the transaction pooler
    ctx = Context(here, host, args)
    parked = here / ("%s.parked" % lane_tag(args))
    if parked.exists() and not args.unpark:
        raise SystemExit("this lane is PARKED: %s\n  start it again with --unpark once a person has decided."
                         % parked.read_text(encoding="utf-8").strip())
    if parked.exists():
        parked.unlink()
    for role, width in roles:
        if width <= 0 or width > MAX_WIDTH:
            raise SystemExit("%s: width %d - a crew has 1 to %d workers; a zero-worker floor does not exist" % (role.lane, width, MAX_WIDTH))
    lock = here / ("%s.lock" % lane_tag(args))
    take_lock(lock)
    ctl = here / ("%s.control" % lane_tag(args))
    try:
        if ctl.exists() and any(l.strip().lower() == "stop" for l in ctl.read_text(encoding="utf-8").splitlines()):
            ctl.write_text("", encoding="utf-8")
            _log(ctx, "%s: a stale `stop` in %s cleared at start (a stop is acted on once)" % (args.lane, ctl.name))
    except OSError:
        pass

    def _signalled(signum, _frame):
        ctx.exit_code, ctx.exit_reason = 0, "stopped by signal %d at %s" % (signum, time.strftime("%H:%M"))
        ctx.stopping.set()
    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)):
        if sig is not None:
            try:
                signal.signal(sig, _signalled)
            except Exception:
                pass

    doors = list(getattr(args, "door", None) or []) or [""]
    if len(doors) > 1 and getattr(args, "one_batch", False):
        raise SystemExit("--door with --one-batch: a batch is one entry and doors are separate entries - launch the doors without --one-batch")
    crews = [Crew(role, width, ctx, door, i + 1) for role, width in roles for i, door in enumerate(doors)]
    ctx.crews = crews
    if len(doors) > 1:
        _log(ctx, "%s: %d doors - %s" % (args.lane, len(doors), ", ".join("door%d = %s" % (i + 1, d or "the machine's own line") for i, d in enumerate(doors))))
    if _one_batch(ctx, crews):
        _log(ctx, "%s up on %s - %s - ONE BATCH of %d: the crews ride one entry (%s first, each crew's births right after the previous"
                  " crew's ramp, %.0f s apart), one hang-up and one re-entry for all, no rate manager; a pooled session per crew, keep-alive after"
             % (args.lane, host, ", ".join("%s x%d" % (c.role.lane, c.width) for c in crews), sum(c.width for c in crews), crews[0].role.lane, args.stagger))
    else:
        _log(ctx, "%s up on %s - %s - one pooled session per crew, staggered births, keep-alive after, no pacer"
             % (args.lane, host, ", ".join("%s x%d" % (c.name, c.width) for c in crews)))
    for c in crews:
        try:
            c.cloud.connect()
            c.cloud.heartbeat(c.width, "started 1x%d at %s" % (c.width, time.strftime("%Y-%m-%d %H:%M")))
        except Exception as e:
            raise SystemExit("the cloud table is unreachable (%s) - nothing to claim, not entering ACRIS" % reason(e))
        _land(ctx, c)                                  # anything left in the outbox from last time
        _feed(ctx, c)
        c.reentry_at = time.time()                     # every crew starts waiting to enter: the loop enters them one ramp at a time, --entry-gap apart
    t0 = time.time()
    last = {c.name: dict(c.stats) for c in crews}
    tick = time.time()
    quiet = {c.name: 0 for c in crews}
    try:
        while not ctx.stopping.is_set():
            time.sleep(1)
            for c in crews:
                if c.retired:
                    if c.session is not None:                   # once: the retired door's lines close and what it fetched lands
                        c.leave()
                        _land(ctx, c)
                        c.session = None
                        try:
                            c.cloud.heartbeat(0, "door refused at %s - retired; %d open" % (time.strftime("%H:%M"), sum(1 for o in crews if not o.retired)))
                        except Exception:
                            pass
                    continue
                if c.reentry_at is not None:
                    _await_entry(ctx, crews, c)             # the first entry, or a re-entry after a hang-up: one ramp at a time
                    continue                                # no feed, no detectors while the crew has no line open
                _feed(ctx, c)
                with c.lock:
                    n = len(c.results)
                if n >= 200:
                    _land(ctx, c)
                # detectors
                if c.wall_streak >= 40:
                    ctx.park("wall: %d consecutive 503/429 on %s at %s - not retrying, not rotating"
                             % (c.wall_streak, c.name, time.strftime("%Y-%m-%d %H:%M")), code=4)
                if c.hung_up():                               # at once on a close: no re-handshake storm, the wait, ONE entry on a fresh batch
                    _hangup_batch(ctx, crews, c, "the session closed (every worker hit the wire inside %ds, nothing landed for %ds)"
                                  % (HANGUP_WINDOW_S, int(time.time() - c.last_success)))
                elif c.transport_streak >= 3 * c.width and time.time() - c.last_success > 60:
                    _hangup_batch(ctx, crews, c, "dead transport (%d transport errors in a row, nothing landed for %ds)"
                                  % (c.transport_streak, int(time.time() - c.last_success)))
                if args.limit and c.stats["ok"] >= args.limit and c.q.empty():
                    ctx.exit_code, ctx.exit_reason = 0, "limit %d reached" % args.limit
                    ctx.stopping.set()
            if time.time() - tick >= getattr(args, "tick", 60):     # the minute; shorter only in tests
                tick = time.time()
                _control(ctx, crews)
                for c in crews:
                    if c.retired:
                        continue
                    if hasattr(c.role, "check"):
                        c.role.check(ctx)                         # e.g. the drive is still there
                    _land(ctx, c)
                    s = _progress(ctx, c, t0, last.setdefault(c.name, dict(c.stats)))     # a door added by the control file starts its own count here
                    cap = getattr(args, "session_max_requests", 0) if getattr(args, "manage", 0) else 0
                    one = _one_batch(ctx, crews)
                    reqs_now = sum(o.stats["reqs"] - o.reqs_at_entry for o in crews if o.reentry_at is None) if one else s["reqs"] - c.reqs_at_entry
                    if cap and c.reentry_at is None and (not one or c is crews[0]) and reqs_now >= cap:
                        # THE SESSION MANAGER (login 2026-09-04: "the session manager will track requests in a session and end it when the request
                        # limit is reached and tell the batch manager to repeat"): a planned close, lines alive; the cycle re-enters on a fresh batch
                        _hangup_batch(ctx, crews, c, "SESSION RESET: %s requests this session, the knob is %s - ending on purpose, a fresh batch after the wait"
                                      % ("{:,}".format(reqs_now), "{:,}".format(cap)), planned=True)
                        last[c.name] = s
                        continue
                    asked = s["reqs"] - last[c.name]["reqs"]
                    moved = s["ok"] - last[c.name]["ok"]
                    quiet[c.name] = quiet.get(c.name, 0) + 1 if (asked > 0 and moved == 0) else 0
                    if quiet[c.name] >= 5 and c.reentry_at is None:      # five minutes asking, nothing landing = our wire
                        quiet[c.name] = 0
                        _hangup_batch(ctx, crews, c, "five minutes asking, nothing landing (our wire)")
                    last[c.name] = s
                    try:
                        c.cloud.heartbeat(sum(o.alive() for o in crews if o.role.lane == c.role.lane and not o.retired), None)   # the lane's row: every door's workers
                    except Exception as e:
                        _log(ctx, "%s: heartbeat failed (%s)" % (c.name, reason(e)))
    except KeyboardInterrupt:
        ctx.exit_code, ctx.exit_reason = 0, "stopped by hand (Ctrl+C) at %s" % time.strftime("%H:%M")
        ctx.stopping.set()
    except Exception as e:
        ctx.exit_code, ctx.exit_reason = 5, "CRASH %s: %s at %s" % (type(e).__name__, reason(e), time.strftime("%H:%M"))
        ctx.stopping.set()
        traceback.print_exc()                            # the traceback prints and the process leaves with 5 - a raise here
                                                         # made the interpreter exit 1, which the fleet reads as "refused to start"
    finally:
        for c in crews:
            c.leave()
            _land(ctx, c)
            try:
                c.cloud.heartbeat(0, ctx.exit_reason)
            except Exception:
                pass
            c.cloud.close()
        try:
            lock.unlink()
        except OSError:
            pass
        _log(ctx, "run end %.1f min - %s" % ((time.time() - t0) / 60, ctx.exit_reason or "stopped"))
    return ctx.exit_code or 0


# ======================================================================================================================
# FLEET: THE FLEET EVERY SOURCE RUNS - the source's lanes together, one program per source built on this.
# ======================================================================================================================

WAIT_AFTER = {5: 60}                                             # seconds before a relaunch, by exit code: only a crash is relaunched
MEANING = {0: "stopped cleanly", 1: "refused to start", 2: "REFUSED by the source", 3: "parked itself: --tries re-entries in a row refused",
           4: "wall - parked by the lane", 5: "crash", 6: "drive gone"}


class Site:
    """One source's fleet: its name, its lanes in the cycle's order, their widths, where the lane programs
    live, and which lanes take --edge on a first start."""

    def __init__(self, source, lanes, widths, workflow, here, edge_lanes=("identification",), manage=None, one_batch=False, mega_default=False):
        self.source = source
        self.manage = dict(manage or {})      # lane -> {knob: value}: the three managers' knobs, passed on that lane's command line (see add_common_args)
        self.one_batch = bool(one_batch)      # ONE BATCH (acris): hosted crews ride the host's entry (--one-batch), no manager knobs on the batch
        self.mega_default = bool(mega_default)    # the mega lane without asking (acris: the batch is the only shape)
        self.lanes = tuple(lanes)
        self.widths = dict(widths)
        self.workflow = pathlib.Path(workflow)
        self.here = pathlib.Path(here)
        self.edge_lanes = tuple(edge_lanes)

    @property
    def key(self):
        return self.source.lower()                                # the source's name: the table reproduction.<key> and its source column

    def lane_file(self, name):
        return self.workflow / name / ("%s %s.py" % (self.source, name.capitalize()))

    def lane_dir(self, name):
        return self.workflow / name

    def parse_lanes(self, spec):
        """'registration:40,documentation:40' -> [(name, width)]; '' -> the whole cycle in its order."""
        if not spec:
            return [(n, self.widths[n]) for n in self.lanes]
        out = []
        for part in spec.split(","):
            name, _, w = part.strip().partition(":")
            name = name.strip().lower()
            if name not in self.lanes:
                raise SystemExit("--lanes takes %s (got %r)" % (", ".join(self.lanes), name))
            if any(n == name for n, _ in out):
                raise SystemExit("--lanes names %s twice" % name)
            try:
                w = int(w) if w else self.widths[name]
            except ValueError:
                raise SystemExit("--lanes takes LANE:WIDTH (got %r)" % part)
            if w <= 0 or w > MAX_WIDTH:
                raise SystemExit("%s: width %d - a crew has 1 to %d workers" % (name, w, MAX_WIDTH))
            out.append((name, w))
        return out


class Fleet:
    def __init__(self, site, args):
        self.site = site
        self.args = args
        self.host = args.host or socket.gethostname()
        self.lanes = site.parse_lanes(args.lanes)
        self.mega = (bool(getattr(args, "mega", False)) or site.mega_default) and not getattr(args, "separate", False)
        self.log_path = site.here / "reproduction.log"
        self.children = {}            # name -> dict(proc, width, started, log, launches [times], also)
        self.waiting = {}             # name -> (relaunch_at, why, unpark)
        self.history = {}             # name -> the last child record (launch times, width, also)
        self.stopping = False
        self.exit_code = 0

    # ── the fleet's own words ──
    def log(self, msg):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # ── one lane's command line ──
    def argv(self, name, width, unpark=False, also=(), first=True):
        a = self.args
        argv = [sys.executable, "-u", str(self.site.lane_file(name)), "--width", str(width), "--host", self.host,
                "--entry-gap", str(a.entry_gap), "--pending-age", a.pending_age]
        for flag, val in (("--stagger", a.stagger), ("--redial-wait", a.redial_wait), ("--tries", a.tries)):
            if val is not None:
                argv += [flag, str(val)]                       # only when given: the lane's own defaults are the cycle's
        crews = (name,) + tuple(n for n, _ in also)
        if "documentation" in crews:
            if not a.drive:
                raise SystemExit("documentation needs --drive <label> (the volume label: OneTouch at home, workstation 2's own)")
            argv += ["--drive", a.drive, "--fresh-days", str(a.fresh_days)]
        if first and a.edge and any(n in self.site.edge_lanes for n in crews):     # the edge only on a lane's FIRST launch: afterwards its edge file is the truth, and a disagreeing --edge is refused
            argv += ["--edge", str(a.edge)]
        for n, w in also:
            argv += ["--also", "%s:%d" % (n, w)]
        batch = bool(also) and self.site.one_batch
        if batch:
            argv.append("--one-batch")                    # ONE BATCH: the hosted crews ride this crew's entry
        if a.limit:
            argv += ["--limit", str(a.limit)]
        if unpark or a.unpark:
            argv.append("--unpark")
        if getattr(a, "no_pool_check", False):
            argv.append("--no-pool-check")
        for d in getattr(a, "door", None) or []:
            argv += ["--door", d]                         # the doors: one crew per door in the lane's process
        if getattr(a, "trust_registry_pages", False) and name == "documentation":
            argv.append("--trust-registry-pages")         # only the documentation lane knows the flag
        if not batch:                                     # ONE BATCH runs fixed widths, no manager (login 2026-09-06); a lane alone keeps its managers
            for knob, val in sorted(self.site.manage.get(name, {}).items()):      # the managers' knobs: the site's word for this lane
                argv += ["--" + knob.replace("_", "-"), str(val)]
        return argv

    def launch(self, name, width, unpark=False, also=()):
        first = not (self.children.get(name) or {}).get("launches")
        argv = self.argv(name, width, unpark, also, first)
        log = self.site.lane_dir(name) / ("%s.log" % name)
        with log.open("a", encoding="utf-8") as f:                      # appended, never truncated
            f.write("\n=== fleet launch %s on %s: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), self.host,
                                                          " ".join(argv[2:]).replace(str(self.site.workflow), "...")))
        out = log.open("ab")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        proc = subprocess.Popen(argv, cwd=str(self.site.lane_dir(name)), stdout=out, stderr=subprocess.STDOUT, creationflags=flags)
        c = self.children.get(name) or {"launches": []}
        c.update({"proc": proc, "width": width, "started": time.time(), "log": out, "also": also})
        c["launches"].append(time.time())
        self.children[name] = c
        self.log("%s: launched pid %d, width %d%s%s" % (name, proc.pid, width,
                 (" + " + ", ".join("%s x%d" % (n, w) for n, w in also)) if also else "", " (--unpark)" if unpark else ""))
        return proc

    # ── the watch ──
    def run(self):
        lock = self.site.here / "reproduction.lock"
        take_lock(lock)
        a = self.args
        self.log("fleet up on %s - %s - %s" % (self.host, ", ".join("%s x%d" % (n, w) for n, w in self.lanes),
                                                 ("ONE BATCH of %d in one process" % sum(w for _, w in self.lanes)) if self.mega and self.site.one_batch and len(self.lanes) > 1
                                                 else "one process (mega lane)" if self.mega else "one process per lane, launched %ds apart" % a.entry_gap))

        def _signalled(signum, _frame):
            self.log("signal %d - stopping the lanes" % signum)
            self.stopping = True
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None), getattr(signal, "SIGBREAK", None)):
            if sig is not None:
                try:
                    signal.signal(sig, _signalled)
                except Exception:
                    pass
        try:
            if self.mega:
                first, width = self.lanes[0]
                self.launch(first, width, also=tuple(self.lanes[1:]))
            else:
                for i, (name, width) in enumerate(self.lanes):
                    if i:
                        self._sleep(a.entry_gap)
                        if self.stopping:
                            break
                    self.launch(name, width)
            last_line = time.time()
            while not self.stopping:
                self._sleep(3)
                self._poll()
                self._relaunch_due()
                if not self.children and not self.waiting:
                    self.log("every lane has left - fleet done")
                    break
                if time.time() - last_line >= 60:
                    last_line = time.time()
                    self._status_line()
            if self.stopping:
                self.stop_lanes(a.stop_wait)
        except KeyboardInterrupt:
            self.log("stopped by hand - stopping the lanes")
            self.stop_lanes(a.stop_wait)
        except SystemExit:
            self.stop_lanes(a.stop_wait)
            raise
        except Exception as e:
            self.exit_code = 5
            self.log("CRASH %s: %s - stopping the lanes" % (type(e).__name__, reason(e)))
            self.stop_lanes(a.stop_wait)
            traceback.print_exc()                       # the fleet leaves with 5 (a raise made it exit 1)
        finally:
            for c in self.children.values():
                try:
                    c["log"].close()
                except Exception:
                    pass
            try:
                lock.unlink()
            except OSError:
                pass
            self.log("fleet end - exit %d" % self.exit_code)
        return self.exit_code

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end and not self.stopping:
            time.sleep(min(1.0, end - time.time()))

    def _poll(self):
        for name in list(self.children):
            c = self.children[name]
            rc = c["proc"].poll()
            if rc is None:
                continue
            try:
                c["log"].close()
            except Exception:
                pass
            del self.children[name]
            self._exited(name, c, rc)

    def _exited(self, name, c, rc):
        up = time.time() - c["started"]
        meaning = MEANING.get(rc, "exit %d" % rc)
        parked = self.site.lane_dir(name) / ("%s.parked" % name)
        if c.get("terminated"):
            self.log("%s: pid %d terminated by the fleet after the stop grace (exit %d)" % (name, c["proc"].pid, rc))
            return
        self.log("%s: pid %d left after %.0f min - %s (%d)" % (name, c["proc"].pid, up / 60, meaning, rc))
        if rc == 0 or rc == 1:
            return                                                    # done, or a person's / another door's - left alone
        if rc == 2:
            self.log("%s was REFUSED by the source: stilling every lane; a person decides (%s)" % (name, parked.name))
            self.exit_code = 2
            self.stopping = True
            return
        if rc in (3, 4):
            self.log("%s: parked itself (%s) - not relaunched; a person decides" % (name, parked.name))
            return                                                    # parked by the lane (3: four refused re-entries, 4: the wall) - its word
        self.history[name] = c
        if rc == 6:
            self.waiting[name] = (0, "the drive is gone - waiting for it", True)
            return
        # 5 and anything else: a relaunch is the cure, within the cap
        hour_ago = time.time() - 3600
        n = sum(1 for t in c["launches"] if t > hour_ago)
        if n > self.args.relaunch_cap:
            why = "parked by the fleet %s: %d launches in an hour, the last left with %s (%d)" % (time.strftime("%Y-%m-%d %H:%M"), n, meaning, rc)
            try:
                parked.write_text(why + "\n", encoding="utf-8")
            except OSError:
                pass
            self.log("%s: %s - not relaunched; a person decides" % (name, why))
            return
        wait = WAIT_AFTER.get(rc, WAIT_AFTER[5]) if not self.args.relaunch_wait else self.args.relaunch_wait
        self.waiting[name] = (time.time() + wait, meaning, False)
        self.log("%s: relaunch in %d s (%s; launch %d of %d this hour)" % (name, wait, meaning, n + 1, self.args.relaunch_cap))

    def _relaunch_due(self):
        for name in list(self.waiting):
            at, why, unpark = self.waiting[name]
            hist = self.history.get(name) or {"launches": [], "width": dict(self.lanes).get(name, self.site.widths[name]), "also": ()}
            parked = self.site.lane_dir(name) / ("%s.parked" % name)
            if unpark:
                try:
                    find_drive(self.args.drive)                # the drive: relaunch only when it is back
                except SystemExit:
                    continue
                self.log("%s: the drive %r is back - relaunching with --unpark" % (name, self.args.drive))
            else:
                if time.time() < at:
                    continue
                if parked.exists():
                    self.log("%s: parked meanwhile (%s) - not relaunched" % (name, parked.read_text(encoding="utf-8").strip()[:100]))
                    del self.waiting[name]
                    continue
            del self.waiting[name]
            width = dict(self.lanes).get(name, hist.get("width", self.site.widths[name]))
            self.children[name] = {"launches": hist.get("launches", [])}
            self.launch(name, width, unpark=unpark, also=hist.get("also", ()))

    def _status_line(self):
        parts = []
        for name, c in self.children.items():
            parts.append("%s pid %d up %.0f min" % (name, c["proc"].pid, (time.time() - c["started"]) / 60))
        for name, (at, why, unpark) in self.waiting.items():
            parts.append("%s waiting (%s)" % (name, why))
        self.log("fleet: " + (" - ".join(parts) if parts else "nothing running"))

    # ── stopping ──
    def stop_lanes(self, wait):
        names = list(self.children)
        if not names:
            return
        for name in names:
            write_control(self.site, name, "stop")
        self.log("stop written to %s - waiting up to %d s for the lanes to leave" % (", ".join(names), wait))
        end = time.time() + wait
        while time.time() < end and any(c["proc"].poll() is None for c in self.children.values()):
            time.sleep(1)
        self._poll()
        for name, c in list(self.children.items()):
            if c["proc"].poll() is None:
                self.log("%s: still running after %d s - terminating pid %d" % (name, wait, c["proc"].pid))
                c["terminated"] = True
                try:
                    c["proc"].terminate()
                    c["proc"].wait(timeout=15)
                except Exception:
                    try:
                        c["proc"].kill()
                    except Exception:
                        pass
        self._poll()


# ── the commands that touch running lanes: control files, locks, the cloud ─────────────
def write_control(site, name, text):
    p = site.lane_dir(name) / ("%s.control" % name)
    p.write_text(text + "\n", encoding="utf-8")
    return p


def lock_pid_at(path):
    try:
        pid = int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0
    return pid if pid_alive(pid) else 0


def lock_pid(site, name):
    return lock_pid_at(site.lane_dir(name) / ("%s.lock" % name))


def last_line(path):
    try:
        data = path.read_bytes()[-4000:].replace(b"\x00", b"")
    except OSError:
        return ""
    lines = [l for l in data.decode("utf-8", "replace").splitlines() if l.strip()]
    return lines[-1].strip() if lines else ""


def host_of(site, args, name):
    """The lane whose process runs `name`: itself while its own lock is alive; else, on a mega run, the first lane of
    --lanes while that one's lock is alive (Fleet.run launches it with the rest as --also crews).  A hosted crew takes
    no lock of its own and reads only its host's control file (_control), so stop, width and status go through the host."""
    if lock_pid(site, name):
        return name
    lanes = [n for n, _ in site.parse_lanes(getattr(args, "lanes", ""))]
    mega = (bool(getattr(args, "mega", False)) or site.mega_default) and not getattr(args, "separate", False)
    if mega and name in lanes[1:] and lock_pid(site, lanes[0]):
        return lanes[0]
    return name


def status(site, args):
    host = args.host or socket.gethostname()
    print("%s lanes on %s:" % (site.key, host))
    for name in site.lanes:
        by = host_of(site, args, name)                   # a hosted crew: its host's lock and control file
        pid = lock_pid(site, by)
        parked = site.lane_dir(name) / ("%s.parked" % name)
        ctl = site.lane_dir(by) / ("%s.control" % by)
        state = ("RUNNING pid %d" % pid if by == name else "RUNNING pid %d (a crew of %s)" % (pid, by)) if pid else "not running"
        if parked.exists():
            state += " - PARKED: %s" % parked.read_text(encoding="utf-8").strip()[:90]
        if ctl.exists() and ctl.read_text(encoding="utf-8").strip():
            state += " - control: %s" % ctl.read_text(encoding="utf-8").strip()[:40]
        print("  %-16s %s" % (name, state))
        ll = last_line(site.lane_dir(name) / ("%s.log" % name))
        if ll:
            print("  %-16s   %s" % ("", ll[:150]))
    fleet_pid = lock_pid_at(site.here / "reproduction.lock")
    print("  %-16s %s" % ("fleet", "RUNNING pid %d" % fleet_pid if fleet_pid else "not running"))
    print("heartbeats in the cloud (every workstation, last %s):" % args.within)
    try:
        c = Cloud(site.key, "reproduction", host, app="%s reproduction status" % site.key)
        c.connect()
        rows = c.alive(args.within)
        c.close()
    except Exception as e:
        print("  the cloud is unreachable (%s)" % reason(e))
        return 5
    if not rows:
        print("  none")
    for lane_name, h, width, age, last_event in rows:
        print("  %-16s %-14s width %-4s %4ds ago  %s" % (lane_name, h, width, age, (last_event or "")[:90]))
    return 0


def stop(site, args):
    names = [args.target] if args.target else list(site.lanes)
    for n in names:
        if n not in site.lanes:
            raise SystemExit("stop takes one of %s" % ", ".join(site.lanes))
    running = {}
    for n in names:
        by = host_of(site, args, n)                      # a hosted crew leaves with its host: the stop goes to the host's control file
        pid = lock_pid(site, by)
        if pid and by not in running:
            running[by] = pid
            if by != n:
                print("%s is a crew of %s's process - the stop goes to %s.control (every crew leaves)" % (n, by, by))
    if not running:
        print("nothing running on this machine for %s" % ", ".join(names))
        return 0
    for n in running:
        write_control(site, n, "stop")
    print("stop written for %s - waiting up to %d s for the lanes to leave" % (", ".join(running), args.stop_wait))
    end = time.time() + args.stop_wait
    while time.time() < end and any(pid_alive(p) for p in running.values()):
        time.sleep(1)
    for n, pid in running.items():
        if pid_alive(pid):
            print("  %s: still running after %d s - terminating pid %d" % (n, args.stop_wait, pid))
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        else:
            print("  %s: left" % n)
    return 0


def width(site, args):
    name, _, w = (args.target or "").partition("=")
    name = name.strip().lower()
    if name not in site.lanes or not w.strip().isdigit():
        raise SystemExit("width takes LANE=N, e.g. documentation=60")
    w = int(w)
    if w <= 0 or w > MAX_WIDTH:
        raise SystemExit("a crew has 1 to %d workers" % MAX_WIDTH)
    by = host_of(site, args, name)
    if by != name:                                       # a hosted crew: `<lane>=N` into the host's control file (_control)
        p = write_control(site, by, "%s=%d" % (name, w))
        print("%s=%d written to %s - %s's process reads it within a minute" % (name, w, p.name, by))
        return 0
    p = write_control(site, name, "width=%d" % w)
    print("width=%d written to %s - %s reads it within a minute%s" % (w, p.name, name, "" if lock_pid(site, name) else " (it is not running now)"))
    return 0


def door(site, args):
    """`door LANE=URL` (or LANE=direct): one more door for the RUNNING lane - `door=URL` into its control file, read within a minute
    (_add_door): the crew is born and enters on its own ramp; nothing else is relaunched."""
    name, _, url = (args.target or "").partition("=")
    name, url = name.strip().lower(), url.strip()
    if name not in site.lanes or not url:
        raise SystemExit("door takes LANE=URL, e.g. documentation=socks5h://127.0.0.1:1080, or LANE=direct for the machine's own line")
    if url != "direct" and "://" not in url:
        raise SystemExit("a door is a proxy URL (socks5h://host:port) or the word direct")
    by = host_of(site, args, name)
    p = write_control(site, by, "door=%s" % url)
    print("door=%s written to %s - %s reads it within a minute%s" % (url, p.name, by, "" if lock_pid(site, by) else " (it is not running now: the word waits for the next start)"))
    return 0


def build_parser(site, description, edge_type, edge_help, fresh_days_default):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "status", "stop", "width", "door"])
    ap.add_argument("target", nargs="?", default="", help="stop: a lane name; width: LANE=N; door: LANE=URL or LANE=direct (one more door for the running lane)")
    ap.add_argument("--lanes", default="", help="LANE:WIDTH,... in launch order (default: %s)" % ",".join("%s:%d" % (n, site.widths[n]) for n in site.lanes))
    ap.add_argument("--mega", action="store_true", help="every crew in one process through the first lane's --also%s" % (" (this site's default: ONE BATCH)" if site.mega_default else ""))
    ap.add_argument("--separate", action="store_true", help="one process per lane even on a ONE BATCH site (tests only)")
    ap.add_argument("--drive", default="", help="documentation's drive label (the volume label: OneTouch at home, workstation 2's own)")
    ap.add_argument("--fresh-days", type=int, default=fresh_days_default, help="documentation: a document recorded within this many days with no image is pending, not absent")
    ap.add_argument("--edge", type=edge_type, default=edge_type(), help=edge_help)
    ap.add_argument("--entry-gap", type=int, default=20, help="seconds between lane launches (and between crews inside a mega lane)")
    ap.add_argument("--stagger", type=float, default=None, help="seconds between worker births inside a lane (default: the lane's own)")
    ap.add_argument("--pending-age", default="1 hour")
    ap.add_argument("--redial-wait", type=int, default=None, help="seconds of silence before a re-entry (default: the lane's own, 60 s with the backoff)")
    ap.add_argument("--tries", type=int, default=None, help="re-entries per incident before a lane parks (default: the lane's own, 4)")
    ap.add_argument("--limit", type=int, default=0, help="each lane stops after this many documents (a test run)")
    ap.add_argument("--unpark", action="store_true", help="start parked lanes too (a person has decided)")
    ap.add_argument("--no-pool-check", action="store_true", help="the lanes skip the exit-pool check at entry (tests only)")
    ap.add_argument("--door", action="append", default=[], metavar="URL",
                    help="a door for every lane launched: a proxy its lines go through (socks5h://127.0.0.1:1080, an ssh tunnel to a rented address);"
                         " repeatable - one crew per door; `direct` = the machine's own line; not with ONE BATCH")
    ap.add_argument("--trust-registry-pages", action="store_true",
                    help="documentation: skip the viewer fetch, the page count from the registry (PROPOSED 2026-09-07; A/B first)")
    ap.add_argument("--relaunch-wait", type=int, default=0, help="seconds before relaunching a crashed lane (0 = the fleet's own 60 s)")
    ap.add_argument("--relaunch-cap", type=int, default=3, help="relaunches per lane per hour before the fleet parks it")
    ap.add_argument("--stop-wait", type=int, default=180, help="seconds for the lanes to leave after `stop` (a lane reads its control file on the minute, then joins its workers) before terminating them")
    ap.add_argument("--within", default="10 minutes", help="status: heartbeats this recent")
    ap.add_argument("--host", default="")
    return ap


def main(site, description, edge_type, edge_help, fresh_days_default):
    args = build_parser(site, description, edge_type, edge_help, fresh_days_default).parse_args()
    if args.command == "status":
        return status(site, args)
    if args.command == "stop":
        return stop(site, args)
    if args.command == "width":
        return width(site, args)
    if args.command == "door":
        return door(site, args)
    return Fleet(site, args).run()


# ======================================================================================================================
# BOARD: THE BOARD every source's update program shares: read machinery.updates once a minute - the phase and
# the lanes' counters and every workstation's own - write rate, increase, eta, percentage, status and as-of back.
# What a person opens is reproduction.<source>_update (0017, 0018): three blocks of four rows - the totals (reproduction
# total, identification total, registration total, documentation total), then workstation 1's four, then workstation
# 2's four, a spacer row before each workstation block; columns source, lane, status, as of (Eastern), the 60 s block
# (rate, increase, eta), the 5 min block, landed, needed, percentage.  A workstation's number is the order of its first
# sight; an unclaimed block reads pending.  Every row carries the source: the Table Editor sorts a view by its first column.
# Every column of the view is text and a blank is one space (0019), so a spacer row shows as nothing in the Editor.
# ======================================================================================================================

KEEP = 8 * 60                 # seconds of readings kept for the windows
COLUMNS = ("pct", "rate_60s", "increase_60s", "pct_60s", "eta_60s", "rate_5m", "increase_5m", "pct_5m", "eta_5m", "status")


def eta_text(remaining, rate):
    if rate is None or rate <= 0 or remaining <= 0:
        return None
    s = remaining / rate
    if s >= 86400:
        return "%.1f days" % (s / 86400)
    if s >= 3600:
        return "%.1f hours" % (s / 3600)
    if s >= 60:
        return "%d min" % round(s / 60)
    return "under a minute"


def fmt(n):
    return "{:,}".format(n) if isinstance(n, int) else ("-" if n is None else str(n))


def fmt_signed(n):
    return ("+" + fmt(n)) if isinstance(n, int) and n > 0 else fmt(n)      # an increase reads +288, a hold 0


class Board:
    def __init__(self, source, lanes, here, args):
        self.source, self.lanes = source, tuple(lanes)
        self.here = pathlib.Path(here)
        self.args = args
        self.host = args.host or socket.gethostname()
        self.fresh = getattr(args, "fresh", 180)
        self.state_path = self.here / "update.state.json"
        self.log_path = self.here / "update.log"
        self.readings = self._load()
        self.cloud = Cloud(source, "update", self.host, app="%s update" % source)
        self.stopping = False
        self.failures = 0

    # ── words ──
    def log(self, msg):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # ── the readings ring (the board's own memory of the counters) ──
    def _load(self):
        try:
            d = json.loads(self.state_path.read_text(encoding="utf-8"))
            return [(float(t), v) for t, v in d.get("readings", [])]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self):
        cutoff = time.time() - KEEP
        self.readings = [(t, v) for t, v in self.readings if t >= cutoff]
        tmp = self.state_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"readings": self.readings, "host": self.host}), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            pass

    def _then(self, now, back, key):
        """The reading nearest to `back` seconds ago (at least 3/4 of the way back), or None."""
        best = None
        for t, v in self.readings:
            if key not in v:
                continue
            age = now - t
            if age < back * 0.75:
                continue
            if best is None or abs(age - back) < abs((now - best[0]) - back):
                best = (t, v)
        return best

    # ── read ──
    def read(self):
        s = self.source
        totals = self.cloud._run("select lane, landed, needed from machinery.updates where source = %s and workstation = ''", (s,), True)
        beats = self.cloud._run("select lane, workstation, workers, last_seen, extract(epoch from now() - last_seen)::int, last_word, landed"
                                " from machinery.updates where source = %s and workstation <> '' order by lane, workstation", (s,), True)
        counters = {}
        for name, landed, needed in totals:
            counters["phase" if name == "reproduction" else name] = (int(landed), int(needed))
        if "phase" not in counters:
            raise RuntimeError("machinery.updates holds no phase row for %s - migration 0007 not applied?" % s)
        return counters, beats

    @staticmethod
    def wkey(b):
        """The readings key of a workstation row: lane@workstation."""
        return "%s@%s" % (b[0], b[1])

    # ── compute ──
    def fold(self, beats, name):
        """hosts, width, heartbeat_at, last_event, alive for one lane (name) or every lane (None)."""
        rows = [b for b in beats if name is None or b[0] == name]
        if not rows:
            return {"hosts": None, "width": None, "heartbeat_at": None, "last_event": None, "alive": False, "rejected": False}
        alive = [b for b in rows if b[4] is not None and b[4] < self.fresh]
        freshest = min(rows, key=lambda b: b[4] if b[4] is not None else 10 ** 9)
        last = (freshest[5] or "")
        # a rejection on ANY lane stalls the phase (name None): a fresher "started" on another lane never masks
        # a refusal (audit 2026-09-03).  For one lane the freshest word across its hosts decides.
        per_lane = {}
        for b in rows:
            age = b[4] if b[4] is not None else 10 ** 9
            if b[0] not in per_lane or age < per_lane[b[0]][0]:
                per_lane[b[0]] = (age, b[5] or "")
        rejected = any(w.startswith("REFUSED") or w.startswith("wall") for _, w in per_lane.values())
        return {"hosts": ", ".join("%s:%s" % (b[1], b[2]) for b in sorted(alive, key=lambda b: b[1])) or None,
                "width": sum(int(b[2] or 0) for b in alive) or None,
                "heartbeat_at": freshest[3], "last_event": last or None, "alive": bool(alive),
                "rejected": rejected}

    def compute(self, now, counters, beats):
        rows = {}
        for key, (landed, needed) in counters.items():
            f = self.fold(beats, None if key == "phase" else key)
            r = {"landed": landed, "needed": needed, "hosts": f["hosts"], "width": f["width"],
                 "heartbeat_at": f["heartbeat_at"], "last_event": f["last_event"], "why": None}
            if landed < 0 or needed < 0 or landed > needed:
                r.update({c: None for c in COLUMNS})
                r["why"] = "OUT OF BOUNDS: landed %s against needed %s - metrics not published; run `reconcile`" % (fmt(landed), fmt(needed))
                rows[key] = r
                continue
            r["pct"] = round(landed * 100.0 / needed, 2) if needed else None
            moved = False
            for tag, back in (("60s", 60), ("5m", 300)):
                then = self._then(now, back, key)
                if then is None:
                    r["rate_" + tag] = r["increase_" + tag] = r["pct_" + tag] = r["eta_" + tag] = None
                    continue
                t, v = then
                inc = landed - int(v[key])
                dt = now - t
                rate = inc / dt if dt > 0 else None
                r["increase_" + tag] = inc
                r["rate_" + tag] = round(rate, 2) if rate is not None else None
                r["pct_" + tag] = round(inc * 100.0 / needed, 4) if needed else None
                r["eta_" + tag] = eta_text(needed - landed, rate)
                moved = moved or inc > 0
            if needed > 0 and landed >= needed:
                status = "complete"
            elif f["rejected"]:
                status = "stalled"
            elif moved:
                status = "active"
            else:
                status = "pending"
            r["status"] = status
            if status == "complete":
                r["eta_60s"] = r["eta_5m"] = "complete"
            elif status != "active":
                r["eta_60s"] = r["eta_5m"] = "paused"
            rows[key] = r
        # the workstation rows (0017): each machine's own count, its rate from the same subtraction, its own status; its
        # percentage is its count over the lane's needed, its eta the lane's remaining at this machine's rate
        refused_at = {b[1] for b in beats if (b[5] or "").startswith(("REFUSED", "wall"))}   # a workstation with a lane refused
        for b in beats:
            key = self.wkey(b)
            landed = int(b[6] or 0) if len(b) > 6 else 0       # the machine's own count (0007); a bare heartbeat tuple counts 0
            word = b[5] or ""
            if b[0] == "reproduction" and b[1] in refused_at:
                word = "REFUSED"                                 # the workstation's reproduction row follows its lanes, as the total's does
            lane_landed, lane_needed = counters.get("phase" if b[0] == "reproduction" else b[0], (0, 0))
            r = {"landed": landed, "needed": lane_needed, "hosts": b[1], "width": b[2], "heartbeat_at": b[3], "last_event": b[5] or None,
                 "why": None, "pct": round(landed * 100.0 / lane_needed, 2) if lane_needed else None}
            moved = False
            for tag, back in (("60s", 60), ("5m", 300)):
                then = self._then(now, back, key)
                if then is None:
                    r["rate_" + tag] = r["increase_" + tag] = r["pct_" + tag] = r["eta_" + tag] = None
                    continue
                t, v = then
                inc = landed - int(v[key])
                dt = now - t
                rate = inc / dt if dt > 0 else None
                r["increase_" + tag] = inc
                r["rate_" + tag] = round(rate, 2) if rate is not None else None
                r["pct_" + tag] = round(inc * 100.0 / lane_needed, 4) if lane_needed else None
                r["eta_" + tag] = eta_text(lane_needed - lane_landed, rate)
                moved = moved or inc > 0
            if lane_needed > 0 and lane_landed >= lane_needed:
                status = "complete"                              # the lane is level: nothing left for any workstation
            elif word.startswith("REFUSED") or word.startswith("wall"):
                status = "stalled"
            elif moved:
                status = "active"
            else:
                status = "pending"
            r["status"] = status
            if status == "complete":
                r["eta_60s"] = r["eta_5m"] = "complete"
            elif status != "active":
                r["eta_60s"] = r["eta_5m"] = "paused"
            rows[key] = r
        return rows

    # ── write ──
    def write(self, rows):
        s = self.source
        for key, r in rows.items():
            if "@" in key:                                  # a workstation's own row: its metrics and status
                lane_name, ws = key.split("@", 1)
                self.cloud._run("update machinery.updates set pct=%s, rate_60s=%s, increase_60s=%s, pct_60s=%s, eta_60s=%s,"
                                " rate_5m=%s, increase_5m=%s, pct_5m=%s, eta_5m=%s, status=%s::reproduction.lane_status, as_of=now()"
                                " where source=%s and lane=%s and workstation=%s",
                                tuple(r[c] for c in COLUMNS) + (s, lane_name, ws), False)
            else:                                           # the phase or a lane: its metrics, status and the fold of its workstations
                lane_name = "reproduction" if key == "phase" else key
                self.cloud._run("update machinery.updates set pct=%s, rate_60s=%s, increase_60s=%s, pct_60s=%s, eta_60s=%s,"
                                " rate_5m=%s, increase_5m=%s, pct_5m=%s, eta_5m=%s, status=%s::reproduction.lane_status, as_of=now(),"
                                " workers=%s, last_seen=%s, last_word=%s where source=%s and lane=%s and workstation=''",
                                tuple(r[c] for c in COLUMNS) + (r["width"], r["heartbeat_at"], r["last_event"], s, lane_name), False)

    # ── print ──
    def line(self, key, r):
        name = "reproduction" if key == "phase" else key.replace("@", " @ ")
        if r["why"]:
            return "UPDATE %-8s | %-15s | %s | %s / %s" % (self.source, name, r["why"], fmt(r["landed"]), fmt(r["needed"]))
        def kit(tag):
            rate, inc, pct, eta = r["rate_" + tag], r["increase_" + tag], r["pct_" + tag], r["eta_" + tag]
            if rate is None and inc is None:
                return "%-3s      -" % tag
            return "%-3s %6.2f/s %8s %+8.4f%%  eta %s" % (tag, rate or 0.0, fmt_signed(inc), pct or 0.0, eta or "-")
        pct = ("%.2f%%" % r["pct"]) if r["pct"] is not None else "-"
        out = "UPDATE %-8s | %-15s | %s | %s | %s / %s = %s | %s" % (
            self.source, name, kit("60s"), kit("5m"), fmt(r["landed"]), fmt(r["needed"]), pct,
            (r["status"] or "?").upper())
        if key != "phase" and "@" not in key:
            beat = ""
            if r["heartbeat_at"] is not None:
                beat = " - %s" % (r["hosts"] or "no lane alive")
                if r["last_event"]:
                    beat += " - last: %s" % r["last_event"][:80]
            out += beat
        return out

    # ── one tick ──
    def tick(self, write=True):
        now = time.time()
        counters, beats = self.read()
        rows = self.compute(now, counters, beats)
        if write:
            self.write(rows)
        reading = {k: v[0] for k, v in counters.items()}
        reading.update({self.wkey(b): (int(b[6] or 0) if len(b) > 6 else 0) for b in beats})
        self.readings.append((now, reading))
        self._save()
        for key in ("phase",) + self.lanes + tuple(sorted(k for k in rows if "@" in k)):
            if key in rows:
                self.log(self.line(key, rows[key]))
        return rows

    # ── the loop ──
    def run(self):
        lock = self.here / "update.lock"
        take_lock(lock)

        def _signalled(signum, _frame):
            self.stopping = True
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None), getattr(signal, "SIGBREAK", None)):
            if sig is not None:
                try:
                    signal.signal(sig, _signalled)
                except Exception:
                    pass
        code = 0
        every = getattr(self.args, "every", 60)
        self.log("%s update up on %s - every %d s, reading only (reconcile on demand)" % (self.source, self.host, every))
        try:
            while not self.stopping:
                t = time.time()
                try:
                    self.tick()
                    self.failures = 0
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self.failures += 1
                    self.log("tick failed (%s) - %d in a row; the readings are kept, next tick continues" % (reason(e), self.failures))
                    try:
                        self.cloud.close()
                    except Exception:
                        pass
                if getattr(self.args, "once", False):
                    break
                while not self.stopping and time.time() - t < every:
                    time.sleep(1)
        except KeyboardInterrupt:
            self.log("stopped by hand")
        except Exception as e:
            code = 5
            self.log("CRASH %s: %s" % (type(e).__name__, reason(e)))
            import traceback
            traceback.print_exc()                       # the process leaves with 5 (a raise made it exit 1)
        finally:
            self.cloud.close()
            try:
                lock.unlink()
            except OSError:
                pass
            self.log("%s update end - exit %d" % (self.source, code))
        return code

    def show(self):
        """Read and print once; nothing written, the readings untouched."""
        now = time.time()
        counters, beats = self.read()
        rows = self.compute(now, counters, beats)
        for key in ("phase",) + self.lanes + tuple(sorted(k for k in rows if "@" in k)):
            if key in rows:
                print(self.line(key, rows[key]), flush=True)
        for b in sorted(beats, key=lambda b: (b[0], b[1])):
            print("  workstation %-16s %-14s workers %-4s %6ds ago  landed %s  %s" % (b[0], b[1], b[2], b[4] or 0, fmt(int(b[6] or 0) if len(b) > 6 else 0), (b[5] or "")[:80]), flush=True)
        self.cloud.close()
        return 0

    def reconcile(self):
        """Recount landed and needed from the table's indexes and overwrite the counters - on demand only."""
        s = self.source
        before = self.read()[0]
        t = time.time()
        rows = self.cloud._run("select what, landed, needed from reproduction.reconcile(%s)", (s,), True)
        self.log("reconcile(%s) in %.1f s:" % (s, time.time() - t))
        for what, landed, needed in rows:
            key = what
            b = before.get(key, (None, None))
            drift = "" if b[0] == landed and b[1] == needed else "   (was %s / %s)" % (fmt(b[0]), fmt(b[1]))
            self.log("  %-16s landed %12s  needed %12s%s" % (what, fmt(int(landed)), fmt(int(needed)), drift))
        self.cloud.close()
        return 0
