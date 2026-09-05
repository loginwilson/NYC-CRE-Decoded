"""RICHMOND DOCUMENTATION - one program.

Batches ONE group of N workers through a SINGLE entry (one pooled session, one connection per worker
at birth, keep-alive after, no further handshakes), and for each claimed document MINTS the image on
the clerk and PULLS the pdf from the NY State courts viewer in one breath, saves it to the drive named
by --drive, and records its full One Touch path in the `document` cell - or the verdict word: pending
(no image yet, recorded inside the scan lag) or absent (checked: none).

    python "Richmond Documentation.py" --drive NYCCRED1          home
    python3 "Richmond Documentation.py" --drive NYCCRED2         workstation 2

This file's own authority is Richmond Documentation.md beside it; the cycle's is ../reproduction/Richmond Reproduction.md.

The rules are kept from the lane that ran before this one (rc_lane.py, rc_pdf_pull.py, rc_source.py):

  two hosts     the clerk mints (302 + a token url), the courts host serves the pdf; each host keeps
                its own connection pool so a worker never re-handshakes by switching hosts
  three outcomes an ABSOLUTE token url = present -> pulled; a relative Location, a 200 or a 404 = no
                image -> pending inside --fresh-days else absent; 403/429/5xx = ours -> asked again
  two sources   `absent` needs the registry to agree: if the detail page said the image is PRESENT and
                the mint says no image, the odd one out is us - the document is asked again, never
                decided (rc_lane._no_image, 2026-08-26)
  one breath    the token expires in ~10 minutes: mint and pull by the same worker, back to back
  a pdf is %PDF a body that does not start with %PDF is never written or recorded
  whole file    written to a .part and renamed; the store never holds a truncated pdf
  restricted    a 401/403 from the courts host is AMBIGUOUS: sealed records 403 at any rate (a fact
                about ONE document), a refusal is about us.  Hold every worker --cooldown seconds,
                then ONE probe of a DIFFERENT document decides: probe pdf -> the document is
                RESTRICTED (evidence in documentation.restricted.jsonl, recorded `absent`, never
                asked again); probe also refused -> the lane is refused -> park, exit 2, no retry,
                no rotation (rc_lane.refusal_verdict; RC_1873622 silenced a 190,594-doc run, 2026-08-24)
  no registry   a row without a registry cannot be placed (the recorded date) or judged fresh: it
                waits for registration, not one request spent
  already here  a file already under this drive is recorded without a request
  failures      a fetch error never stops the lane: the document stays empty for a later pass and the
                reason is written to documentation.fails.jsonl
  hang-up, wall, width, one door, drive, pending recheck, no overlap   shared with every lane (lane.py).
                The hang-up is DORMANT at this county (no session close was ever measured here: the
                drumroll rule); it fires only when the wire itself dies - hang up, drop the cut batch
                (the claims expire and come back), wait 60 s, re-enter once, births 0.4 s apart
  maturation    a `pending` comes back from the claim after --pending-age and is minted again; past
                the 7-day lag it lands `absent` - the old 4 AM rc_pdf_state --apply pass lives inside
                this lane and cannot be separated from it (RICHMOND REPRODUCTION.md, the 4 AM tasks)

Exit codes: 0 stopped · 2 refused · 3 redials exhausted · 4 wall · 5 crash · 6 drive gone.
"""
import argparse
import json
import os
import pathlib
import sys
import threading
import time

import requests
import requests.adapters

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[2]                       # documentation -> workflow -> Richmond -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))                # the phase's rulebook: lane, fleet, board, cloud, storage, rate manager
sys.path.insert(0, str(PHASE / "Richmond" / "rulebook"))

import lane                                                     # noqa: E402
import richmond                                                 # noqa: E402
import storage                                                  # noqa: E402


class Documentation:
    """What one worker does with one document."""
    source, lane_name = "richmond", "documentation"
    ua = richmond.UA
    noun = "pdfs"
    needs_registry = True

    def __init__(self, here, drive_root, fresh_days, cooldown):
        self.here = pathlib.Path(here)
        self.root = drive_root
        self.fresh_days = fresh_days
        self.cooldown = cooldown
        self.restricted_path = self.here / "documentation.restricted.jsonl"
        self.restricted = self._load_restricted()
        self.hold = threading.Event()         # a verdict in progress holds every worker
        self.arbiter = threading.Lock()       # one verdict at a time
        self.prep_lock = threading.Lock()
        self.prepared = None                  # id(session) whose pools and cookies are ready

    @property
    def lane(self):
        return self.lane_name

    def _load_restricted(self):
        out = set()
        try:
            for line in self.restricted_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.add(json.loads(line)["id"])
        except (OSError, ValueError, KeyError):
            pass
        return out

    def check(self, ctx):
        """Once a minute: the drive must still be there."""
        if not os.path.isdir(self.root):
            ctx.park("PARKED: the drive %s is gone at %s - plug it back in, then start with --unpark"
                     % (self.root, time.strftime("%Y-%m-%d %H:%M")), code=6)

    # ── the wire ─────────────────────────────────────────────────────────────────────────
    def prepare(self, crew):
        """Once per session: a pool of its own for the courts host (the shared adapter caches ONE host
        pool, so two hosts through it would swap pools and re-handshake on every switch), and the
        clerk's cookies from one GET of its front door."""
        s = crew.session
        with self.prep_lock:
            if self.prepared == id(s):
                return
            s.mount(richmond.IAPPS, requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=lane.MAX_WIDTH + 4,
                                                                  max_retries=0, pool_block=True))
            try:
                crew.get(richmond.BASE + "/", richmond.BASE + "/", timeout=60)
            except lane.HTTPStatus:
                pass                                      # the front door's status is not the point; the cookies are
            self.prepared = id(s)

    def _get(self, crew, url, headers, timeout, allow_redirects, stream=False):
        """A request on the crew's session with the crew's accounting; the caller closes the response."""
        with crew.lock:
            crew.stats["reqs"] += 1
        try:
            return crew.session.get(url, headers=headers, timeout=timeout, allow_redirects=allow_redirects, stream=stream)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError) as e:
            raise lane.Transport("%s: %s" % (type(e).__name__, lane.reason(e)))

    def mint(self, crew, doc_id):
        """-> ('present', token url) | ('noimage', None); 403/429/5xx raise HTTPStatus (the wall counts 429/503)."""
        iid = doc_id[3:]
        r = self._get(crew, richmond.mint_url(iid), {"Referer": richmond.mint_referer(iid)}, 60, allow_redirects=False)
        try:
            status, loc = r.status_code, r.headers.get("Location", "")
            body = r.content if status == 200 else b""
        finally:
            r.close()
        if status == 200:
            richmond.check_refused(body.decode("utf-8", "replace"), "mint %s" % doc_id)
        outcome, token = richmond.classify_mint(status, loc)
        if outcome == "error":
            raise lane.HTTPStatus(status, richmond.mint_url(iid))
        return outcome, token

    def pull(self, crew, doc_id, token_url):
        """The pdf bytes from the courts host, or the verdict on a 401/403."""
        r = self._get(crew, token_url, richmond.PULL_HEADERS, (10, 90), allow_redirects=True, stream=True)
        try:
            if r.status_code in (401, 403):
                return self.verdict(crew, doc_id, r.status_code)
            if r.status_code == 429:
                raise lane.HTTPStatus(429, token_url)
            if r.status_code != 200:
                raise lane.Retry("HTTP %d from the courts host" % r.status_code)
            data = r.content
        finally:
            r.close()
        if not richmond.is_pdf(data):
            raise lane.Retry("not a pdf (%d bytes, %r)" % (len(data), data[:8]))
        return data

    # ── the verdict on a 4xx from the courts host ────────────────────────────────────────
    def verdict(self, crew, doc_id, code):
        """Sealed records 403 at any rate; a refusal is about us.  Hold everyone, cool down, then ONE probe
        of a DIFFERENT document decides.  Returns 'restricted' (the document's verdict) or raises Refused."""
        if not self.arbiter.acquire(blocking=False):
            raise lane.Retry("HTTP %d while a verdict is in progress - asked again later" % code)
        try:
            self.hold.set()
            lane._log(crew.ctx, "documentation: HTTP %d on %s from the courts host - HOLDING every worker %ds; one probe of a DIFFERENT"
                      " document decides: the document restricted, or the lane refused" % (code, doc_id, self.cooldown))
            self._sleep(crew, self.cooldown)
            probe = self._probe(crew, doc_id)
            if probe is None:
                raise lane.Retry("no probe document available - the hold is released unproven; asked again later")
            probe_id, ok = probe
            if ok:
                self.restricted.add(doc_id)
                try:
                    with self.restricted_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"id": doc_id, "code": code, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                            "probe": probe_id, "verdict": "doc restricted"}) + "\n")
                except OSError:
                    pass
                lane._log(crew.ctx, "documentation: VERDICT - %s is RESTRICTED (probe %s returned a pdf): recorded absent, never asked again;"
                          " the lane resumes" % (doc_id, probe_id))
                return "restricted"
            raise richmond.Refused("the courts host refused %s (%d) AND the probe %s - the lane is refused; STOP, no retry, no rotation"
                                   % (doc_id, code, probe_id))
        finally:
            self.hold.clear()
            self.arbiter.release()

    def _sleep(self, crew, seconds):
        end = time.time() + seconds
        while time.time() < end and not crew.stop.is_set():
            time.sleep(min(5, end - time.time()))

    def _probe(self, crew, doc_id):
        """Borrow a different claimed document from the crew's queue, mint and pull it, put it back.
        -> (probe id, served) or None when no probe could be minted."""
        borrowed = []
        try:
            for _ in range(5):
                try:
                    item = crew.q.get_nowait()
                except Exception:
                    break
                borrowed.append(item)
                pid, registry = item[0], item[1]
                if pid == doc_id or pid in self.restricted or not isinstance(registry, dict):
                    continue
                try:
                    outcome, token = self.mint(crew, pid)
                except (lane.HTTPStatus, lane.Transport):
                    continue
                if outcome != "present":
                    continue
                r = self._get(crew, token, richmond.PULL_HEADERS, (10, 90), allow_redirects=True, stream=True)
                try:
                    ok = r.status_code == 200 and richmond.is_pdf(r.content)
                    refused = r.status_code in (401, 403)
                finally:
                    r.close()
                return pid, (ok and not refused)
            return None
        finally:
            for item in borrowed:
                crew.q.put(item)

    # ── one document ─────────────────────────────────────────────────────────────────────
    def fetch(self, crew, doc_id, registry):
        if not isinstance(registry, dict):
            raise lane.Retry("no registry yet (%s)" % (registry if registry else "empty"))
        if doc_id in self.restricted:
            return "absent"                                   # the verdict stands; never asked again
        canon = richmond.canonical_path(doc_id, registry)
        path = storage.local(self.root, canon)
        if path.is_file() and path.stat().st_size > 0:
            return canon                                      # already on this drive: no request spent
        while self.hold.is_set() and not crew.stop.is_set():
            time.sleep(5)                                     # a verdict is being decided
        self.prepare(crew)

        # 1. the mint: three outcomes
        outcome, token = self.mint(crew, doc_id)
        if outcome == "noimage":
            if richmond.fresh(registry, self.fresh_days):
                return "pending"
            if registry.get("image_state") == "present":
                raise lane.Retry("the mint says no image but the registry says present - two sources disagree, asked again")
            return "absent"

        # 2. the pull, in the same breath
        data = self.pull(crew, doc_id, token)
        if data == "restricted":
            return "absent"

        # 3. the file, written whole or not at all
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.parent / (path.name + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError as e:
            if not os.path.isdir(self.root):
                self.check(crew.ctx)
            raise lane.Retry("could not write the file (%s: %s)" % (type(e).__name__, str(e)[:100]))
        return canon


def role(drive_root, args):
    """This lane's role, for a sibling lane hosting it with --also documentation:N."""
    if not drive_root:
        raise SystemExit("documentation needs --drive <label>: the drive its files are written to")
    a = lane.role_args(args, ("fresh_days", "cooldown"), fresh_days=richmond.IMAGE_LAG_DAYS, cooldown=600)
    return Documentation(HERE, drive_root, a.fresh_days, a.cooldown)


def main():
    ap = argparse.ArgumentParser(description="richmond documentation: mint on the clerk, pull from the courts, one entry, N workers")
    ap.add_argument("--drive", required=True, help="label of the drive to write to (NYCCRED1 at home, NYCCRED2 on workstation 2)")
    ap.add_argument("--fresh-days", type=int, default=richmond.IMAGE_LAG_DAYS,
                    help="a document recorded within this many days with no image is pending, not absent (the measured scan lag)")
    ap.add_argument("--cooldown", type=int, default=600, help="seconds every worker holds while a 401/403 from the courts host is arbitrated")
    lane.add_common_args(ap)
    ap.set_defaults(width=8, stagger=0.4)   # rc_bench 2026-08-25: 8 pullers 28.23 docs/s, 16 -> 18.76 (self-contending past the pipe); 0.4 s between first handshakes
    args = ap.parse_args()
    args.lane = "documentation"

    drive_root = storage.find_drive(args.drive)
    storage.documents_root(drive_root)
    roles = lane.roles_for("Richmond", args, HERE, drive_root, Documentation(HERE, drive_root, args.fresh_days, args.cooldown))
    print("drive %r -> %s ; documents under %s ; cell records %s..." % (args.drive, drive_root, storage.documents_root(drive_root), storage.CANON_ROOT), flush=True)
    sys.exit(lane.run(roles, args, HERE))


if __name__ == "__main__":
    main()
