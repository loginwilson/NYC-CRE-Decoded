#!/usr/bin/env python3
# box_fetch.py - THE ON-BOX FETCH (2026-09-08; login: "Try the workers on the droplets", "we need a manager for workers to
# maximize the worker to its max request/s on droplet given the ACRIS ceiling").  Runs ON a droplet (a door), bound to its
# loopback only, reached from home through the door's own ssh tunnel (socks5h to 127.0.0.1:<port> connects on the box).
# One call per document: GET /doc/<doc_id>[?total=N] fetches the viewer page and every page image from ACRIS HERE, in
# parallel, and returns them RAW - no verdicts on the box: the lane at home judges the notice, the count, the end marker,
# TIFF and short exactly as before, and lands a cell only once the pdf is on the drive.  Why: a page image takes ACRIS
# ~11 s to serve whoever asks, so a door's rate is requests in flight / latency, and the home machine ran out of RAM
# (856 MB free under ~900 workers) long before any door ran out of allowance.  The RATE MANAGER below ramps the requests
# in flight toward THIS address's own knee (500 in flight = 23 req/s, no errors, on 170.64.213; 1000 = flat + 4,974 errors)
# and steps back when errors or a falling rate say the knee is behind it.
#   python3 box_fetch.py --port 9000 [--start 100 --step 100 --floor 100 --cap 800 --window 60 --log /tmp/box_fetch.log]
#   GET /stats -> the manager's state as JSON.   stdlib only (Ubuntu's python3).
# Wire format of /doc: one JSON line {"doc_id","total","reqs","items":[{"u": url, "s": status, "ct", "n": bytes, "e": err}]}
# then the bodies, concatenated in item order.  s = 0 with e = the transport error; a redirect (the 307 to the policy page)
# is followed once so the lane sees what `requests` would have seen.
import argparse, gzip, hashlib, http.client, json, queue, re, ssl, sys, threading, time, urllib.parse, zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = hashlib.sha1(open(__file__, "rb").read()).hexdigest()[:8]       # do_doors.py `box` restarts the box only when this differs

HOST = "a836-acris.nyc.gov"
BASE = "https://a836-acris.nyc.gov/DS/DocumentSearch"           # acris.py's BASE: the urls must be byte-identical to the lane's
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      " (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")   # acris.py's ONE user-agent, never rotated
_TOTAL = re.compile(r"TotalPages%22%3A(-?\d+)")                 # acris.total_pages's token
NOTICE_BYTES = 25103
PER_DOC = 1                                                     # page images in flight per document (a 1,000-page document must not own the door)
# 2026-09-09: WAS 40, AND 40 WAS THE BUG.  Asked for the same 30 documents, the tunnel fetch returned
# 30 of 30 and 416 pages with no errors while the box returned 6, called 9 of them imageless and cut
# 15 short.  Not the address (same droplet), not the referer (identical), and not a missing session -
# cold, warmed and shared sessions all read the same page counts, 12 of 12.  What differs is the
# burst: the box fires up to PER_DOC images at once, and ACRIS meters BURSTS, not volume.  Under it
# the viewer page comes back reading TotalPages 0, which is the false zero the 09-09 audit named as
# the mechanism behind 267,289 wrong `absent` cells.  Eight in flight still parallelises a document
# an order of magnitude better than the one-at-a-time wire walk, without the burst.

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=9000)
# THE GATE IS THE WHOLE ANSWER TO ERRORS (2026-09-09).  Every error measured today - the box's 31
# short documents, the tunnel's 78 errors at width 24, the lane's 70% failure at width 40 - is the
# same wall, and it is REQUESTS IN FLIGHT AGAINST ONE ADDRESS.  Lined up:
#
#     6 in flight   (tunnel, width 6, one page at a time)   100 of 100 documents, ZERO errors
#    24 in flight   (tunnel, width 24)                      78 errors of 120
#    40 in flight   (lane, width 40)                        ~70% of requests failed
#    48 in flight   (box, width 6 x PER_DOC 8)              31 short of 100
#
# ACRIS does not care HOW you reach the number - six documents of one page or one document of eight.
# It tolerates roughly 6-13 concurrent requests per address and refuses past that.
#
# These defaults said start at 400 and never step below 150.  The gate's manager DOES step down on
# errors, but its floor sat more than ten times above the wall, so it could measure the errors and
# never escape them.  That is why the box was 62 of 100 where the tunnel was 100 of 100.
# Start at the wall, let the manager explore upward only while errors stay under 2%, and give it a
# floor it can actually reach.
ap.add_argument("--start", type=int, default=24)       # the measured knee: 6 in flight ran 100/100 clean
ap.add_argument("--step", type=int, default=4)        # 100 overshot the entire tolerance in one step
ap.add_argument("--floor", type=int, default=12)
ap.add_argument("--cap", type=int, default=48)        # past ~13 the errors start; leave room to prove it per door
ap.add_argument("--window", type=int, default=60)
ap.add_argument("--log", default="/tmp/box_fetch.log")
A = ap.parse_args()

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
threading.stack_size(512 * 1024)
T0 = time.time()
LOGLOCK = threading.Lock()
LINES = []                                                      # the last manager lines, for /stats


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    with LOGLOCK:
        LINES.append(line)
        del LINES[:-12]
        try:
            with open(A.log, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass


class Gate:
    """The requests in flight toward ACRIS, capped at `limit` - the manager's one knob."""
    def __init__(self, limit):
        self.limit, self.inflight, self.waiting, self.max_waiting = limit, 0, 0, 0
        self.cv = threading.Condition()

    def __enter__(self):
        with self.cv:
            if self.inflight >= self.limit:                   # only a request that actually has to wait is demand
                self.waiting += 1
                self.max_waiting = max(self.max_waiting, self.waiting)
                while self.inflight >= self.limit:
                    self.cv.wait(1)
                self.waiting -= 1
            self.inflight += 1

    def __exit__(self, *a):
        with self.cv:
            self.inflight -= 1
            self.cv.notify()

    def set(self, n):
        with self.cv:
            self.limit = n
            self.cv.notify_all()


IDLE_MAX = 90.0                                                 # a keep-alive idle longer than this is presumed closed by the far side
# 2026-09-09: WAS 15 s, AND THAT IS WHAT MADE THE BOX ERROR.  door-3's own manager line, on the run
# that lost 52 of 100 documents:
#
#     MANAGER 6.5 req/s, 39.7% errors, 100 docs, in flight 0 of 40, waiting max 6, 48 CONNECTIONS
#
# Read it twice: `in flight 0 of 40` with `waiting max 6` means the GATE WAS NEVER THE CONSTRAINT -
# concurrency was not what ACRIS objected to.  What it saw was 48 fresh TLS handshakes against one
# address inside a couple of seconds, which is the ban condition this project has written down since
# 08-2x: one pooled session, keep-alive, never a burst of new connections.  A 15-second idle window
# guaranteed the burst - between one document and the next the pool emptied, every worker called
# fresh(), and 50 ms spacing let fifty handshakes through in two and a half seconds.
#
# The tunnel fetch never did this: one requests.Session reusing a handful of connections, which is
# exactly why it scored 100 of 100 at width 24 where the box scored 8.  Hold connections long enough
# to be REUSED, and space a genuinely new one widely enough that a burst cannot form.
CONNECT_GAP = 0.25                                              # seconds between NEW connections (was 0.05)


class Pool:
    """Keep-alive connections to ACRIS, reused most-recent first; one idle past IDLE_MAX is dropped, not tried (the 16:1x
    proof: a fifth of the requests died twice on stale keep-alives between bursts).  A NEW connection no faster than one
    per 50 ms (a handshake burst on one address is the ban condition; 100 more lines spread over five seconds)."""
    def __init__(self):
        self.q, self.lock, self.last, self.made = queue.LifoQueue(), threading.Lock(), 0.0, 0

    def fresh(self):
        with self.lock:
            gap = CONNECT_GAP - (time.time() - self.last)
            if gap > 0:
                time.sleep(gap)
            self.last = time.time()
            self.made += 1
        return http.client.HTTPSConnection(HOST, 443, timeout=90, context=CTX)

    def take(self):
        while True:
            try:
                c, used = self.q.get_nowait()
            except queue.Empty:
                return self.fresh()
            if time.time() - used <= IDLE_MAX:
                return c
            try:
                c.close()
            except Exception:
                pass

    def give(self, c):
        self.q.put((c, time.time()))

    def warm(self, n):
        """Open n connections BEFORE any traffic, one per CONNECT_GAP, and park them in the pool.

        2026-09-09, the last piece.  Widening CONNECT_GAP did not stop the handshake burst, it only
        spread it over the whole run - a brand-new door, box only, width 12, still reported:

            3.6 req/s, 41.6% errors, 50 docs, in flight 0 of 20, waiting max 9, 24 CONNECTIONS

        24 connections inside a 6.8-second run, with the gate never saturated (`in flight 0 of 20`).
        The pool starts EMPTY, so the first wave of workers all miss and every one of them calls
        fresh(); the run IS the burst, whatever the spacing.  ACRIS refuses during it and the
        documents come back short.

        Warming inverts that: the handshakes happen once, slowly, against an idle address, and by the
        time the lane asks for anything the workers find live keep-alive connections and make none.
        This is the same shape as the lane's own rule - ONE entry, then keep-alive - which is why the
        tunnel fetch, reusing a handful of session connections, never provoked this at all.
        """
        def go():
            for _ in range(n):
                try:
                    self.give(self.fresh())      # fresh() already spaces itself by CONNECT_GAP
                except Exception as e:
                    log("warm: %s" % e)
                    return
            log("warm: %d keep-alive connections ready" % n)
        threading.Thread(target=go, daemon=True).start()


GATE = Gate(A.start)
POOL = Pool()
STAT = {"reqs": 0, "err": 0, "retries": 0, "notice": 0, "docs": 0, "bytes": 0}
SLOCK = threading.Lock()
LAST_ERRS = []                                                  # the last transport errors, for /stats


def bump(**kw):
    with SLOCK:
        for k, v in kw.items():
            STAT[k] += v


def _body(r):
    body = r.read()
    enc = (r.getheader("Content-Encoding") or "").lower()
    try:
        if enc == "gzip":
            body = gzip.decompress(body)
        elif enc == "deflate":
            body = zlib.decompress(body)
    except Exception:
        pass
    return body


def _one(conn, path, referer):
    conn.request("GET", path, headers={"User-Agent": UA, "Accept": "*/*", "Referer": referer, "Connection": "keep-alive"})
    r = conn.getresponse()
    return r.status, (r.getheader("Content-Type") or ""), _body(r), (r.getheader("Location") or "")


def fetch(url, referer):
    """One ACRIS request through the gate: (status, content-type, body, error).  status 0 = no answer (a transport error,
    after one retry on a fresh connection).  A redirect is followed once, so the 307 to the policy page comes back as the
    page itself, as `requests` gives it to the lane."""
    path = url[len("https://" + HOST):]
    with GATE:
        bump(reqs=1)
        err = ""
        for attempt in (1, 2, 3):
            conn = POOL.take() if attempt == 1 else POOL.fresh()   # a retry never reuses: a new line each time
            if attempt > 1:
                bump(retries=1)
            try:
                st, ct, body, loc = _one(conn, path, referer)
                if st in (301, 302, 303, 307, 308) and loc:
                    u = urllib.parse.urljoin(url, loc)
                    p = urllib.parse.urlparse(u)
                    if p.netloc == HOST:
                        st, ct, body, _ = _one(conn, p.path + ("?" + p.query if p.query else ""), referer)
                    else:
                        c2 = http.client.HTTPSConnection(p.netloc, 443, timeout=90, context=CTX)
                        try:
                            st, ct, body, _ = _one(c2, p.path + ("?" + p.query if p.query else ""), referer)
                        finally:
                            c2.close()
                POOL.give(conn)
                if st >= 400:
                    bump(err=1)
                if len(body) == NOTICE_BYTES or (body[:2] not in (b"II", b"MM") and b"Bandwidth Notice" in body[:8000]):
                    bump(notice=1)
                bump(bytes=len(body))
                return st, ct, body, ""
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, str(e)[:100])
                with SLOCK:
                    LAST_ERRS.append("%s try %d %s: %s" % (time.strftime("%H:%M:%S"), attempt, path[:60], err))
                    del LAST_ERRS[:-8]
                try:
                    conn.close()
                except Exception:
                    pass
        bump(err=1)
        return 0, "", b"", err


def document(doc_id, total):
    """The viewer page (unless the count is given) and pages 1..total, PER_DOC at a time, in order."""
    items, reqs = [], 0
    detail = BASE + "/DocumentDetail?doc_id=" + doc_id
    viewer = BASE + "/DocumentImageView?doc_id=" + doc_id
    if not total:
        st, ct, body, err = fetch(viewer, detail)
        reqs += 1
        items.append((viewer, st, ct, body, err))
        if st == 200 and not err:
            m = _TOTAL.search(body.decode("utf-8", "ignore"))
            total = int(m.group(1)) if m else None
        else:
            # A NON-ANSWER IS NOT A ZERO (2026-09-09).  `total` arrives as 0 when the caller did not
            # supply a count, so without this branch a FAILED viewer fetch - a timeout, a reset, a
            # 503, a refusal - left it sitting at 0 and the box reported "this document has no
            # images".  The lane reads that as ACRIS having spoken, and an imageless verdict is what
            # it writes.  That is the mechanism behind the 267,289 wrong `absent` cells the 09-09
            # audit found and reset: measured here, the box called 14 of 30 documents imageless while
            # the same droplet's tunnel fetched all 30 in full, 660 pages, no errors.
            # None means UNKNOWN and travels as JSON null, which the lane must treat as a retry.
            total = None
    if total and total > 0:
        results = [None] * total
        pages = list(range(1, total + 1))
        for start in range(0, total, PER_DOC):
            chunk = pages[start:start + PER_DOC]
            ths = []
            for p in chunk:
                def one(p=p):
                    results[p - 1] = fetch("%s/GetImage?doc_id=%s&page=%d" % (BASE, doc_id, p), viewer)
                t = threading.Thread(target=one, daemon=True)
                t.start()
                ths.append(t)
            for t in ths:
                t.join()
            reqs += len(chunk)
            if any(r[3] or r[0] != 200 or len(r[2]) == NOTICE_BYTES for r in results[start:start + len(chunk)]):
                for p in chunk:                                 # this chunk is returned whole; nothing past a failing chunk is asked
                    st, ct, body, err = results[p - 1]
                    items.append(("%s/GetImage?doc_id=%s&page=%d" % (BASE, doc_id, p), st, ct, body, err))
                break
            for p in chunk:
                st, ct, body, err = results[p - 1]
                items.append(("%s/GetImage?doc_id=%s&page=%d" % (BASE, doc_id, p), st, ct, body, err))
    bump(docs=1)
    head = {"doc_id": doc_id, "total": total, "reqs": reqs,
            "items": [{"u": u, "s": st, "ct": ct, "n": len(body), "e": err} for (u, st, ct, body, err) in items]}
    return json.dumps(head).encode("utf-8") + b"\n" + b"".join(body for (_, _, _, body, _) in items)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/octet-stream"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        if p.path == "/stats":
            with SLOCK:
                s = dict(STAT)
            s.update(version=VERSION, limit=GATE.limit, inflight=GATE.inflight, waiting=GATE.waiting, connections=POOL.made,
                     uptime_s=int(time.time() - T0), manager=LINES[-6:], last_errors=list(LAST_ERRS))
            return self._send(200, json.dumps(s).encode("utf-8"), "application/json")
        if p.path.startswith("/doc/"):
            doc_id = p.path[5:].strip("/")
            q = urllib.parse.parse_qs(p.query)
            total = None
            try:
                total = int(q.get("total", ["0"])[0]) or None
            except ValueError:
                total = None
            if not re.fullmatch(r"[A-Za-z0-9_]{6,40}", doc_id):
                return self._send(400, b"bad doc id", "text/plain")
            try:
                return self._send(200, document(doc_id, total))
            except Exception as e:
                log("document %s failed on the box: %s: %s" % (doc_id, type(e).__name__, str(e)[:120]))
                return self._send(500, ("%s: %s" % (type(e).__name__, str(e)[:120])).encode("utf-8"), "text/plain")
        return self._send(404, b"not here", "text/plain")


def manager():
    """Every window: the rate and the error share.  Grow by --step while the rate keeps rising with the crews still
    waiting on the gate and errors under 2%; step back on errors >= 5% or a rate that fell a fifth below the best seen;
    never grow past a notice - the lane retires the door on it and the box dies with the droplet."""
    prev, best, hold = dict(STAT), 0.0, 0
    while True:
        time.sleep(A.window)
        with SLOCK:
            cur = dict(STAT)
        with GATE.cv:
            demand, GATE.max_waiting = GATE.max_waiting, GATE.waiting
        reqs = cur["reqs"] - prev["reqs"]
        errs = cur["err"] - prev["err"]
        notices = cur["notice"] - prev["notice"]
        rate = reqs / float(A.window)
        share = errs / float(max(1, reqs))
        word = "hold"
        if notices:
            word = "NOTICE seen %d - holding" % notices
        elif hold > 0:
            hold -= 1
            word = "holding %d more" % hold
        elif share >= 0.05 or (best > 0 and rate < best * 0.8 and demand > 0 and reqs > 0):
            n = max(A.floor, GATE.limit - A.step)
            word = "errors %.0f%% / rate fell: %d -> %d" % (share * 100, GATE.limit, n) if n != GATE.limit else "at the floor"
            GATE.set(n)
            best, hold = rate, 2
        elif demand > 0 and share < 0.02 and rate > best * 1.05 and GATE.limit < A.cap:
            n = min(A.cap, GATE.limit + A.step)
            word = "rising: %d -> %d" % (GATE.limit, n)
            GATE.set(n)
            best = rate
        elif demand == 0:
            word = "no one waiting (home is the limit)"
        else:
            best = max(best, rate)
        log("MANAGER %.1f req/s, %.1f%% errors, %d docs, in flight %d of %d, waiting max %d, %d connections - %s"
            % (rate, share * 100, cur["docs"] - prev["docs"], GATE.inflight, GATE.limit, demand, POOL.made, word))
        prev = cur


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", A.port), H)
    srv.daemon_threads = True
    threading.Thread(target=manager, daemon=True).start()
    POOL.warm(A.start)                      # the handshakes happen NOW, on an idle address, not under load
    log("box_fetch %s up on 127.0.0.1:%d - start %d, step %d, floor %d, cap %d, window %d s, warming %d connections"
        % (VERSION, A.port, A.start, A.step, A.floor, A.cap, A.window, A.start))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
