"""CONCURRENCY under the Lightway tunnel: one pooled keep-alive Session (the lane's shape), N threads, R requests each.
Records every outcome class + the FULL first error text. Neutral host first (never ACRIS), then ACRIS at small and lane width.
usage: conc_test.py <neutral|acris> <N> <R>"""
import sys, io, json, time, threading, collections, requests
from requests.adapters import HTTPAdapter

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
mode, N, R = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])

if mode == "acris":
    p = r"D:\CRE Decoding System\01 Navigations\Legal Instruments Navigation\_working\acris_reproduction_fails.jsonl"
    ids = []
    for l in io.open(p, encoding="utf-8").read().splitlines()[-2000:]:
        try:
            i = json.loads(l).get("id")
            if i and i not in ids:
                ids.append(i)
        except Exception:
            pass
    urls = ["https://a836-acris.nyc.gov/DS/DocumentSearch/DocumentDetail?doc_id=%s" % i for i in ids[-(N * R):]]
else:
    urls = ["https://github.com/robots.txt"] * (N * R)

s = requests.Session()
s.headers["User-Agent"] = UA
s.mount("https://", HTTPAdapter(pool_connections=1, pool_maxsize=N + 4, max_retries=0, pool_block=True))
res = collections.Counter(); first_err = {}; lock = threading.Lock(); t_all = time.time()


def worker(k):
    for j in range(R):
        u = urls[(k * R + j) % len(urls)]
        t0 = time.time()
        try:
            r = s.get(u, timeout=30)
            body = r.content
            key = "HTTP %d" % r.status_code
            if mode == "acris" and r.status_code == 200:
                key += " served" if u.split("=")[-1] in r.text else " NO-DOC-ID(notice?)"
            r.close()
        except Exception as e:
            key = type(e).__name__
            with lock:
                first_err.setdefault(key, "%.1fs: %s" % (time.time() - t0, str(e)[:260]))
        with lock:
            res[key] += 1


ths = [threading.Thread(target=worker, args=(k,)) for k in range(N)]
for t in ths:
    t.start(); time.sleep(0.2)              # staggered births like the lane
for t in ths:
    t.join()
el = time.time() - t_all
print("%s N=%d R=%d -> %d requests in %.1fs: %s" % (mode, N, R, N * R, el, dict(res)))
for k, v in first_err.items():
    print("   first %s: %s" % (k, v))
