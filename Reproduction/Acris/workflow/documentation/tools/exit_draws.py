"""Five fresh-connection draws of the public exit over ~12 s, through the lane's own library (requests) and UA.
Never touches ACRIS."""
import time, requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
seen = []
for i in range(5):
    try:
        r = requests.get("https://api.ipify.org", headers={"User-Agent": UA, "Connection": "close"}, timeout=15)
        ip = r.text.strip()
    except Exception as e:
        ip = "fail:" + type(e).__name__
    seen.append(ip)
    print(time.strftime("%H:%M:%S"), ip, flush=True)
    time.sleep(3)
blocks = sorted({".".join(x.split(".")[:3]) for x in seen if x[0].isdigit()})
print("distinct exits:", len(set(seen)), "| blocks:", blocks, "| STABLE" if len(blocks) == 1 else "| MOVING")
