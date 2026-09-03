"""BLOCK LEDGER - every acris lane log on disk: width, duration, requests, rate, pdfs, fails, and how it ended.
Reads only. Prints a table; with --write appends it to the reproduction doc as a dated section."""
import os, re, glob, sys, time

DEC = r"C:\Users\smile\Downloads\Source Folder (Real Estate Data)\Decoder Prompt\decoder"
PROG = re.compile(r"PROGRESS (\d+)m - reqs ([\d,]+) \(([\d.]+)/s\).*?- ([\d,]+) pdfs.*?fail (\d+)")
UP = re.compile(r"acris_reproduction up - (\d+) FLOOR.*?: (.*?) - each", re.S)
FLOORS = re.compile(r"(document|register|sync|rd|edge)\s+(\d+)")


def parse(path):
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    lines = txt.splitlines()
    up = UP.search(txt)
    cfg = ""
    if up:
        cfg = up.group(2).strip()
    else:
        m = re.search(r"(\d+)\s*x\s*(\d+)|--pdf-workers (\d+)|workers?[: ]+(\d+)", txt)
        cfg = m.group(0) if m else "?"
    last = None
    for l in lines:
        m = PROG.search(l)
        if m:
            last = m
    end = "running/unknown"
    ended_id = ""
    for l in lines:
        if "REFUSED at" in l or "Bandwidth Notice" in l:
            end = "NOTICE (refused)"
            mm = re.search(r"REFUSED at (\d+)", l)
            ended_id = mm.group(1) if mm else ""
            break
    else:
        if "DEAD TRANSPORT" in txt:
            end = "dead transport (self-stop)"
        elif "run end" in txt:
            end = "stopped (run end)"
        elif "Traceback" in txt:
            end = "crash"
    reqs_at_end = None
    m = re.search(r"run end ([\d.]+) min - reqs ([\d,]+) \(([\d.]+)/s\).*?pdf ([\d,]+).*?fail (\d+)", txt)
    return {
        "file": os.path.basename(path),
        "mtime": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(path))),
        "cfg": cfg[:28],
        "min": (float(m.group(1)) if m else (int(last.group(1)) if last else 0)),
        "reqs": (int(m.group(2).replace(",", "")) if m else (int(last.group(2).replace(",", "")) if last else 0)),
        "rps": (float(m.group(3)) if m else (float(last.group(3)) if last else 0.0)),
        "pdfs": (int(m.group(4).replace(",", "")) if m else (int(last.group(4).replace(",", "")) if last else 0)),
        "fail": (int(m.group(5)) if m else (int(last.group(5)) if last else 0)),
        "end": end, "id": ended_id,
    }


rows = []
for p in sorted(glob.glob(os.path.join(DEC, "acris_repro_document.log*")) + glob.glob(os.path.join(DEC, "acris_repro_document.log.err*")), key=os.path.getmtime):
    if ".err" in p:
        continue
    r = parse(p)
    if r and (r["reqs"] or r["end"] != "running/unknown"):
        rows.append(r)

# other lane logs that hold a notice (older methods: acris_lane, rd_walk, image_walk...)
others = []
for p in glob.glob(os.path.join(DEC, "*.log*")):
    b = os.path.basename(p)
    if b.startswith("acris_repro_document") or b.startswith("night_supervisor") or b.startswith("block_watch") or b.startswith("follow_doc"):
        continue
    try:
        txt = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    if "Bandwidth Notice" in txt or "REFUSED" in txt or "refusing service" in txt:
        n = txt.count("Bandwidth Notice") + txt.count("REFUSED at")
        others.append((time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p))), b, n, len(txt)))

hdr = "%-52s %-11s %-28s %7s %10s %6s %8s %6s  %s" % ("log", "mtime", "config", "min", "reqs", "req/s", "pdfs", "fail", "end")
print(hdr)
print("-" * len(hdr))
for r in rows:
    print("%-52s %-11s %-28s %7.1f %10s %6.1f %8s %6d  %s %s" % (r["file"][:52], r["mtime"], r["cfg"], r["min"], format(r["reqs"], ","), r["rps"], format(r["pdfs"], ","), r["fail"], r["end"], r["id"]))
print()
print("other lane logs holding a notice/refusal line (older methods):")
for o in sorted(others):
    print("  %s  %-45s notices/refusals: %d  (%s bytes)" % (o[0], o[1], o[2], format(o[3], ",")))

if "--write" in sys.argv:
    DOC = r"D:\CRE Decoding System\Reproduction\Acris Reproduction\ACRIS REPRODUCTION.md"
    s = open(DOC, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in s else "\n"
    key = "## THE BLOCK LEDGER (generated 2026-09-03"
    if key in s:
        print("ledger already in doc")
    else:
        out = ["## THE BLOCK LEDGER (generated 2026-09-03 %s by block_ledger.py from the logs on disk — regenerate, never hand-edit)" % time.strftime("%H:%M"),
               "", "login 08:3x: \"I think you just need to really understand when and why a block occurs. for now I am happy if it is pulling sustainably.\" This table is every acris_repro_document run on disk, from its own log: width, minutes, requests, rate, pdfs, fails, and how it ended. `NOTICE` = ACRIS served the Bandwidth Notice page (the only thing the record calls a block). `dead transport` = the lane's own breaker (our side). Rows with a few requests and NOTICE are entries into an EXISTING block, not new blocks.", "",
               "```", hdr, "-" * len(hdr)]
        for r in rows:
            out.append("%-52s %-11s %-28s %7.1f %10s %6.1f %8s %6d  %s %s" % (r["file"][:52], r["mtime"], r["cfg"], r["min"], format(r["reqs"], ","), r["rps"], format(r["pdfs"], ","), r["fail"], r["end"], r["id"]))
        out += ["```", "", "Older-method logs that hold a notice line (acris_lane / rd_walk era):", ""]
        for o in sorted(others):
            out.append("- %s  `%s`  notices/refusals: %d" % (o[0], o[1], o[2]))
        open(DOC, "w", encoding="utf-8", newline="").write(s.rstrip("\r\n") + nl + nl + nl.join(out) + nl)
        print("ledger written to doc")
