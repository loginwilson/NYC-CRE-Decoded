# night_status.py - ONE READING OF THE NIGHT, in the only terms that matter: DOCUMENTS ON THE DRIVE.
# Doors held, what each lane is producing right now, what the probes are finding, and what has been spent.
import pathlib, re, subprocess, time, json

HERE = pathlib.Path(r"C:\dev\cre-office")
DOC = pathlib.Path(r"C:\dev\nyc-cre-decoded\Reproduction\Acris\workflow\documentation")
STATIONS = [("DigitalOcean", "do_station.log", "do_doors.log"),
            ("Vultr", "do_station.vultr.log", "cloud_doors.vultr.log"),
            ("Linode", "do_station.linode.log", "cloud_doors.linode.log"),
            ("Hetzner", "do_station.hetzner.log", "cloud_doors.hetzner.log")]


def tail(p, n=4000):
    try:
        return (HERE / p).read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


print(time.strftime("%H:%M:%S"), "- the night, in documents")
print()
total = 0.0
for name, slog, mlog in STATIONS:
    rows = tail(slog)
    last = rows[-1][:110] if rows else "(no log)"
    # every probe verdict this station has reached in the last hour
    kept = sum(1 for l in rows if "fill: KEPT" in l)
    burnt = sum(1 for l in rows if "BURNT" in l)
    speeds = [m.group(1) for l in tail(mlog) for m in [re.search(r"-> ([\d.]+) docs/s\s*$", l)]  if m]
    print("%-13s kept %-3d burnt %-3d   last probes: %s" % (name, kept, burnt, ", ".join(speeds[-5:]) or "-"))
    print("  %s" % last)
print()
print("-- lanes producing right now --")
live = False
for f in sorted(DOC.glob("documentation.*.log")):
    if ".prev." in f.name:
        continue
    try:
        rows = f.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        continue
    prog = [l for l in rows if "PROGRESS" in l]
    if not prog:
        continue
    l = prog[-1]
    # ONLY A LANE THAT WROTE IN THE LAST FOUR MINUTES IS A LANE.  A dead lane's last PROGRESS line sits in its log for
    # ever, and summing those is how a fleet reads 1.98 docs/s while one lane is actually running - the same mistake,
    # in the reporting, that the door gates made in the judging.
    try:
        hh, mm, ss = int(l[0:2]), int(l[3:5]), int(l[6:8])
    except ValueError:
        continue
    age = (time.localtime().tm_hour * 3600 + time.localtime().tm_min * 60 + time.localtime().tm_sec) - (hh * 3600 + mm * 60 + ss)
    if age < 0:
        age += 86400
    if age > 240:
        continue
    d = re.search(r"([\d.]+) docs/s", l)
    pdf = re.search(r"- ([\d,]+) pdfs", l)
    fail = re.search(r"fail ([\d,]+)", l)
    rq = re.search(r"reqs ([\d,]+) \(([\d.]+)/s\)", l)
    if d:
        total += float(d.group(1))
    live = True
    print("  %-26s %6s docs/s   %8s pdfs   %8s fails   %s req/s   (%s)"
          % (f.name, d.group(1) if d else "-", pdf.group(1) if pdf else "-",
             fail.group(1) if fail else "-", rq.group(2) if rq else "-", l[:8]))
if not live:
    print("  (no lane has written a PROGRESS line yet)")
print()
print("FLEET: %.2f documents a second" % total)
