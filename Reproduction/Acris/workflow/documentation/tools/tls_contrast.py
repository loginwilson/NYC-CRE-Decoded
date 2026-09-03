"""TLS contrast: is the SSLError storm ACRIS-specific or is the tunnel breaking TLS for everyone?
10 fresh-connection GETs to each neutral HTTPS host + 2 single GETs to ACRIS (one rd_url, one pdf_url of an id that just
failed) with the FULL exception text. Same library and UA as the lane. Two ACRIS requests beside a lane doing ~400/min."""
import re, io, time, collections, requests

DEC = r"C:\Users\smile\Downloads\Source Folder (Real Estate Data)\Decoder Prompt\decoder"
src = io.open(DEC + r"\fetch_pages.py", encoding="utf-8").read()
m = re.search(r'^UA\s*=\s*\((.*?)\)\s*$', src, re.M | re.S)
UA = eval("(" + m.group(1) + ")") if m else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
BASE = "https://a836-acris.nyc.gov/DS/DocumentSearch"      # rd_url = BASE/DocumentDetail?doc_id=, pdf_url = BASE/DocumentImageView?doc_id= (nav table)
print("UA:", UA)
print("BASE:", BASE)

H = {"User-Agent": UA}
for host in ("https://www.nyc.gov/", "https://github.com/", "https://www.google.com/"):
    c = collections.Counter(); t = []
    for i in range(10):
        t0 = time.time()
        try:
            with requests.Session() as s:
                r = s.get(host, headers=H, timeout=20, allow_redirects=False)
            c["HTTP %d" % r.status_code] += 1
        except Exception as e:
            c[type(e).__name__] += 1
        t.append(time.time() - t0)
    print("%-26s %s  avg %.2fs max %.2fs" % (host, dict(c), sum(t) / len(t), max(t)))

FAILED_ID = "2004080300407002"
for label, url in (("rd_url ", "%s/DocumentDetail?doc_id=%s" % (BASE.rstrip("/"), FAILED_ID)),
                   ("pdf_url", "%s/DocumentImageView?doc_id=%s" % (BASE.rstrip("/"), FAILED_ID))):
    t0 = time.time()
    try:
        with requests.Session() as s:
            r = s.get(url, headers=H, timeout=30)
        body = r.text
        notice = sum(p in body.lower() for p in ("bandwidth", "denied", "notice", "further access", "acris"))
        print("ACRIS %s -> HTTP %d, %d bytes, %.2fs, doc id in body: %s, notice-ish phrases: %d" % (
            label, r.status_code, len(r.content), time.time() - t0, FAILED_ID in body, notice))
    except Exception as e:
        print("ACRIS %s -> %s after %.2fs: %s" % (label, type(e).__name__, time.time() - t0, str(e)[:300]))
