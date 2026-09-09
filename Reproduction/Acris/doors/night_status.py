# night_status.py - THE FLEET, PROVIDER BY PROVIDER, in the terms login asks for: the doors under each, and what each
# one is actually doing right now - documents a second and requests a second, off the lane's own last PROGRESS line.
#
# Only a lane that wrote in the last four minutes counts.  A dead lane's last line sits in its log for ever, and
# summing those is how a fleet reads 1.98 docs/s while one lane is running - the same mistake in the reporting that the
# door gates made in the judging.
import json, pathlib, re, time

HERE = pathlib.Path(r"C:\dev\cre-office")
DOC = pathlib.Path(r"C:\dev\nyc-cre-decoded\Reproduction\Acris\workflow\documentation")
FRESH = 240

# name -> (ledger, station log, manager log, first slot).  A station owns a slot RANGE of 20.
PROV = [("DigitalOcean", "cloud_doors.json",         "do_station.log",         "do_doors.log",           2),
        ("Vultr",        "cloud_doors.vultr.json",   "do_station.vultr.log",   "cloud_doors.vultr.log",  20),
        ("Linode",       "cloud_doors.linode.json",  "do_station.linode.log",  "cloud_doors.linode.log", 40),
        ("Hetzner",      "cloud_doors.hetzner.json", "do_station.hetzner.log", "cloud_doors.hetzner.log",60)]


def now_s():
    t = time.localtime()
    return t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec


def lane(slot):
    """(docs/s, req/s, pdfs, fails) off the slot's last PROGRESS line, if it is fresh."""
    p = DOC / ("documentation.%d.log" % slot)
    if not p.exists():
        return None
    try:
        rows = p.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
    except OSError:
        return None
    for l in reversed(rows):
        if "PROGRESS" not in l:
            continue
        try:
            age = now_s() - (int(l[0:2]) * 3600 + int(l[3:5]) * 60 + int(l[6:8]))
        except ValueError:
            return None
        if age < 0:
            age += 86400
        if age > FRESH:
            return None
        d = re.search(r"([\d.]+) docs/s", l)
        rq = re.search(r"reqs ([\d,]+) \(([\d.]+)/s\)", l)
        pdf = re.search(r"- ([\d,]+) pdfs", l)
        fail = re.search(r"fail ([\d,]+)", l)
        return (float(d.group(1)) if d else 0.0, float(rq.group(2)) if rq else 0.0,
                pdf.group(1) if pdf else "-", fail.group(1) if fail else "-", age)
    return None


print(time.strftime("%H:%M:%S"), "- the fleet, provider by provider")
tot_d = tot_r = 0.0
tot_doors = 0
for name, ledger, slog, mlog, base in PROV:
    try:
        rows = json.loads((HERE / ledger).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    print()
    print("%s" % name.upper())
    if not rows:
        last = ""
        try:
            ls = (HERE / slog).read_text(encoding="utf-8", errors="replace").splitlines()
            last = ls[-1][20:130] if ls else ""
        except OSError:
            pass
        print("   no doors                                          %s" % last)
        continue
    for r in rows:
        slot = base + (r["port"] - (r["port"] // 100) * 100) if False else None
        tot_doors += 1
    # a door's slot is recorded by the station; fall back to matching on port order
    for i, r in enumerate(sorted(rows, key=lambda x: x["port"])):
        slot = base + i
        st = lane(slot)
        if st:
            d, rq, pdfs, fails, age = st
            tot_d += d
            tot_r += rq
            print("   %-16s %-15s  %5.2f docs/s   %6.1f req/s   %8s pdfs   %8s fails" %
                  (r.get("name", "-")[:16], r["ip"], d, rq, pdfs, fails))
        else:
            print("   %-16s %-15s  no lane reporting" % (r.get("name", "-")[:16], r["ip"]))
print()
print("FLEET  %d doors   %.0f requests a second" % (tot_doors, tot_r))
# THE LANE'S OWN docs/s COUNTS DOCUMENTS DISPOSED OF, NOT DOCUMENTS LANDED.  A lane retiring viewer-404 documents as
# 'pending' scores them in that number, which is how the fleet read "664 documents a second" at 09:22 while the pdf
# column said 0.  The board's landed total is the only figure that means files on the drive, so it is the headline.
try:
    import psycopg2, sys as _s
    _s.path.insert(0, 'C:\\dev\\nyc-cre-decoded\\Reproduction\\rulebook')
    import rulebook
    con = psycopg2.connect(rulebook.dsn()); con.autocommit = True
    cur = con.cursor()
    # MAX, not SUM: the board carries one row per workstation PLUS a total row with a blank workstation, so summing
    # them double-counts (8,771,810 against a true 4,284,337).
    cur.execute("select max(landed) from machinery.updates where source='acris' and lane='documentation'")
    landed = int(cur.fetchone()[0] or 0)
    mark = HERE / 'night_status.mark'
    prev = None
    if mark.exists():
        try:
            a_, b_ = mark.read_text(encoding='utf-8').split(',')
            prev = (float(a_), int(b_))
        except ValueError:
            prev = None
    now = time.time()
    mark.write_text('%f,%d' % (now, landed), encoding='utf-8')
    line = 'BOARD  %s documents landed' % format(landed, ',')
    if prev and now > prev[0] + 30:
        line += '   -> %+d in %.1f min = %.2f documents a second' % (
            landed - prev[1], (now - prev[0]) / 60.0, (landed - prev[1]) / (now - prev[0]))
    print(line)
except Exception as e:
    print('BOARD  unreadable (%s: %s)' % (type(e).__name__, str(e)[:60]))
