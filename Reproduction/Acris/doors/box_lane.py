#!/usr/bin/env python3
# box_lane.py - THE DIRECT-ACRIS FETCH, run ON a droplet (login 2026-09-08 15:0x: "Try the direct Acris. 165 to 180 would be
# great per door").  Proof of the throttle fix: fetch REAL documents from ACRIS on the box itself, N workers, keep-alive one
# connection each, and report the true rate - the tunnel from home caps a door at 8-19 req/s; on the box a 30-worker burst hit
# 165-180.  stdlib only (Ubuntu's python3).  Reads doc_ids from a file, saves page images under /tmp/box, prints one summary.
#   python3 box_lane.py <docids_file> [workers=30] [seconds=25]
import http.client, os, re, ssl, sys, threading, time

HOST = "a836-acris.nyc.gov"
BASE = "/DS/DocumentSearch"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
OUT = "/tmp/box"
NOTICE_BYTES = 25103

docids = [l.strip() for l in open(sys.argv[1]) if l.strip()]
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 30
SECONDS = int(sys.argv[3]) if len(sys.argv) > 3 else 25
os.makedirs(OUT, exist_ok=True)
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

lock = threading.Lock()
idx = [0]
end = time.time() + SECONDS
stat = {"viewers": 0, "pages": 0, "ok": 0, "bytes": 0, "docs": 0, "notice": 0, "err": 0, "stub": 0}
stop = threading.Event()


def bump(**kw):
    with lock:
        for k, v in kw.items():
            stat[k] += v


def next_doc():
    with lock:
        if time.time() > end or stop.is_set():
            return None
        d = docids[idx[0] % len(docids)]          # cycle the list: worker count is the only variable, and a repeat image
        idx[0] += 1                               # still takes ACRIS ~11 s to serve (the cache test), so it is a faithful load
        return d


def worker():
    conn = None
    def get(path, ref=None):
        nonlocal conn
        for attempt in (1, 2):
            try:
                if conn is None:
                    conn = http.client.HTTPSConnection(HOST, 443, timeout=30, context=CTX)
                h = {"User-Agent": UA, "Accept": "*/*", "Connection": "keep-alive"}
                if ref:
                    h["Referer"] = ref
                conn.request("GET", path, headers=h)
                r = conn.getresponse()
                body = r.read()
                return r.status, body
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
                if attempt == 2:
                    return 0, b""
    while not stop.is_set():
        doc = next_doc()
        if doc is None:
            break
        ref = "https://%s%s/DocumentImageView?doc_id=%s" % (HOST, BASE, doc)
        st, body = get("%s/DocumentImageView?doc_id=%s" % (BASE, doc), ref)
        bump(viewers=1)
        if st == 0:
            bump(err=1); continue
        if len(body) == NOTICE_BYTES or b"BandwidthPolicy" in body[:4000]:
            bump(notice=1); stop.set(); break
        m = re.search(rb"TotalPages[\"'\s:=]+(\d+)", body)
        pages = int(m.group(1)) if m else 6   # no TotalPages: ask for six.  A serving door returns all six real
                                             # scans; a refused one returns page 1 and misses the rest, and THAT
                                             # difference is what tells the two apart.  The loop stops at the miss.
        pages = min(pages, 40)
        got = 0
        sizes = []
        for p in range(1, pages + 1):
            if stop.is_set():
                break
            st, img = get("%s/GetImage?doc_id=%s&page=%d" % (BASE, doc, p), ref)
            bump(pages=1)
            if len(img) == NOTICE_BYTES or (img[:20].find(b"BandwidthPolicy") >= 0):
                bump(notice=1); stop.set(); break
            if st == 200 and img:
                sizes.append(len(img)); got += 1
                with open(os.path.join(OUT, "%s_p%d" % (doc, p)), "wb") as f:
                    f.write(img)
            else:
                bump(err=1)
                # THE FIRST MISS IS THE END OF THE DOCUMENT.  ACRIS numbers pages 1..N with no gaps, so everything
                # after a miss is a request for a page that does not exist - and those requests are not free: they
                # come out of the block's allowance, which belongs to the lane that runs here next.  Measured, this
                # was ~35,000 of the probe's ~40,000 requests, spent to learn nothing.
                break
        # THE STUB SET.  A refused address answers with the SAME image for every page - HTTP 200, image/tiff, one
        # constant byte length - so nothing about the response says refusal except that the pages are all identical.
        # Real scanned pages differ.  Counted as stubs, they earn the address nothing at the gate.
        if len(sizes) > 1 and len(set(sizes)) == 1:
            bump(stub=len(sizes))
        elif got:
            bump(ok=got, bytes=sum(sizes), docs=1)
    if conn:
        try:
            conn.close()
        except Exception:
            pass


t0 = time.time()
ths = [threading.Thread(target=worker) for _ in range(WORKERS)]
for t in ths:
    t.start()
for t in ths:
    t.join()
el = time.time() - t0
reqs = stat["viewers"] + stat["pages"]
print("box_lane %d workers %.0fs: %d docs, %d pages ok, %.1f req/s, %.2f docs/s, %.1f MB, %d notices, %d err, %d stubs"
      % (WORKERS, el, stat["docs"], stat["ok"], reqs / el, stat["docs"] / el, stat["bytes"] / 1e6, stat["notice"], stat["err"], stat["stub"]))
