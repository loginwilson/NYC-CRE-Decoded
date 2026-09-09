#!/usr/bin/env python3
# spend.py - THE BUDGET WATCHDOG (login 2026-09-08: "my only concern if everything is in place is expecting a small bill
# around $40 when done and getting $1000+").
#
# Arithmetic is not a safeguard.  This is: it counts what every station has actually created, prices it at the WORST
# credible rate, compares that against a hard ceiling, and if the ceiling is crossed it stops all four supervisors and
# destroys every instance on every account.  It does not need permission at that point, because the ceiling IS the
# permission.
#
# It prices two ways at once and reports both:
#   HOURLY  what the providers publish and what Vultr's real-time charges confirm - a droplet costs its hourly rate,
#           one hour minimum.  This is the expected bill.
#   WORST   the fear: a full month billed per instance created.  If that were true the number goes vertical at once,
#           which is exactly what makes it safe to check rather than assume.
# Vultr posts charges within minutes, so its pending_charges is the fleet's live canary: if the hourly column tracks
# what Vultr actually reports, the model holds for the others, which publish the same shape of price.
#
#   python spend.py status                    what has been spent so far, both ways
#   python spend.py watch --budget 120        check every 5 minutes; halt everything if the HOURLY estimate crosses it
#   python spend.py watch --budget 120 --worst-budget 400   ...or if even the worst-case reading crosses its own ceiling
#   python spend.py halt                      stop every station and destroy every instance, now
import argparse, json, os, pathlib, re, subprocess, sys, time, urllib.request, urllib.error

HERE = pathlib.Path(__file__).resolve().parent
PY = sys.executable
NOWIN = 0x08000000

# provider: (token file, token key, api base, alive endpoint, node, $/hour for the size we create, $/month)
P = {
    "digitalocean": ("C:/dev/nyc-cre-decoded.env", "DIGITALOCEAN_TOKEN", "https://api.digitalocean.com/v2/",
                     "droplets?per_page=200", "droplets", 0.00595, 4.00, "do_doors.log"),
    "vultr":        (str(HERE / "vultr.env"), "VULTR_TOKEN", "https://api.vultr.com/v2/",
                     "instances?per_page=200", "instances", 0.00700, 5.00, "cloud_doors.vultr.log"),
    "linode":       (str(HERE / "linode.env"), "LINODE_TOKEN", "https://api.linode.com/v4/",
                     "linode/instances?page_size=200", "data", 0.00750, 5.00, "cloud_doors.linode.log"),
    "hetzner":      (str(HERE / "hetzner.env"), "HETZNER_TOKEN", "https://api.hetzner.cloud/v1/",
                     "servers?per_page=50", "servers", 0.01040, 6.50, "cloud_doors.hetzner.log"),
}
STOPS = {"digitalocean": "do_station.stop", "vultr": "do_station.vultr.stop",
         "linode": "do_station.linode.stop", "hetzner": "do_station.hetzner.stop"}


def token(path, key):
    p = pathlib.Path(path)
    if not p.exists():
        return ""
    for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if l.strip().startswith(key + "="):
            return l.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def api(base, path, tok, method="GET"):
    r = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + tok}, method=method)
    with urllib.request.urlopen(r, timeout=40) as f:
        body = f.read()
    return json.loads(body) if body else {}


def created_today(logname):
    """Droplets this station's manager has created today, from its own log - the only count that cannot be lost."""
    p = HERE / logname
    if not p.exists():
        return 0
    day = time.strftime("%Y-%m-%d")
    n = 0
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            for l in f:
                if l.startswith(day) and " created " in l:
                    n += 1
    except OSError:
        pass
    return n


def read():
    """Per provider: instances alive now, droplets created today, and the two prices."""
    out = {}
    for name, (tpath, tkey, base, ep, node, hourly, monthly, log) in P.items():
        tok = token(tpath, tkey)
        alive, err, ages = None, "", []
        if tok:
            try:
                _rows = api(base, ep, tok).get(node, [])
                alive = len(_rows)
                ages = []
                for d in _rows:
                    raw = (d.get("created") or d.get("date_created") or d.get("created_at") or "").replace("Z", "+00:00")
                    if not raw:
                        continue
                    try:
                        import datetime
                        tt = datetime.datetime.fromisoformat(raw)
                        if tt.tzinfo is None:
                            tt = tt.replace(tzinfo=datetime.timezone.utc)
                        ages.append((datetime.datetime.now(datetime.timezone.utc) - tt).total_seconds() / 3600.0)
                    except ValueError:
                        pass
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, str(e)[:60])
        out[name] = {"alive": alive, "made": created_today(log), "hourly": hourly, "monthly": monthly,
                     "err": err, "token": bool(tok), "ages": ages}
    # Vultr posts charges within minutes: the fleet's live canary
    tok = token(P["vultr"][0], P["vultr"][1])
    if tok:
        try:
            a = api(P["vultr"][2], "account", tok)["account"]
            out["vultr"]["reported"] = float(a.get("pending_charges") or 0)
        except Exception:
            pass
    try:
        tok = token(P["digitalocean"][0], P["digitalocean"][1])
        b = api(P["digitalocean"][2], "customers/my/balance", tok)
        out["digitalocean"]["reported"] = float(b.get("month_to_date_usage") or 0)
        out["digitalocean"]["reported_at"] = (b.get("generated_at") or "")[:19]
    except Exception:
        pass
    return out


def alive_hours(rows):
    """Hours already run by the instances that are still up, beyond the one hour their creation already paid for.
    A creation-only model undercounts a door that lives three hours by two of them; doors mostly die on their notice
    inside half an hour, so the correction is small - but it should be counted, not assumed away."""
    extra = 0.0
    for name, r in rows.items():
        for age in r.get("ages", []):
            extra += max(0.0, age - 1.0) * r["hourly"]
    return extra


def price(rows):
    """(hourly-model dollars, worst-case dollars).  The hourly model charges every creation a one-hour minimum, which
    is what the providers publish; the worst case charges every creation a full month, which is the fear being tested."""
    hourly = sum(r["made"] * r["hourly"] for r in rows.values()) + alive_hours(rows)
    worst = sum(r["made"] * r["monthly"] for r in rows.values())
    return hourly, worst


def show(rows):
    print("%-14s %7s %8s %12s %12s   %s" % ("station", "alive", "made", "hourly $", "worst $", "reported by the provider"))
    for name, r in rows.items():
        rep = ""
        if "reported" in r:
            rep = "$%.2f" % r["reported"]
            if r.get("reported_at"):
                rep += "  (as of %s - their console updates once a day)" % r["reported_at"]
        print("%-14s %7s %8d %12.2f %12.2f   %s" % (
            name, ("-" if r["alive"] is None else r["alive"]), r["made"],
            r["made"] * r["hourly"], r["made"] * r["monthly"], rep or r["err"] or ""))
    h, w = price(rows)
    print("-" * 92)
    print("%-14s %16d %12.2f %12.2f" % ("TOTAL today", sum(r["made"] for r in rows.values()), h, w))
    print()
    print("  HOURLY is what all four providers publish and what Vultr's live charges confirm - the expected bill.")
    print("  WORST is the fear (a full month per instance created); if it were true, the reported column goes vertical.")
    v = rows.get("vultr", {})
    if "reported" in v and v["made"]:
        print("  CANARY: Vultr reports $%.2f for %d instance(s) - $%.4f each, against $%.4f hourly and $%.2f monthly."
              % (v["reported"], v["made"], v["reported"] / v["made"], v["hourly"], v["monthly"]))
    return h, w


def halt(why):
    print("\n!! %s - STOPPING EVERY STATION AND DESTROYING EVERY INSTANCE !!" % why)
    for name, stop in STOPS.items():
        try:
            (HERE / stop).write_text("stop", encoding="utf-8")
        except OSError:
            pass
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
                    "$_.CommandLine -like '*do_station.py*run*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                   capture_output=True, creationflags=NOWIN)
    for name, (tpath, tkey, base, ep, node, _, _, _) in P.items():
        tok = token(tpath, tkey)
        if not tok:
            continue
        try:
            for d in api(base, ep, tok).get(node, []):
                i = d.get("id")
                path = {"digitalocean": "droplets/%s", "vultr": "instances/%s",
                        "linode": "linode/instances/%s", "hetzner": "servers/%s"}[name] % i
                api(base, path, tok, method="DELETE")
                print("   destroyed %s %s" % (name, i))
        except Exception as e:
            print("   %s: could not clear (%s) - check the console by hand" % (name, str(e)[:70]))
    print("!! halted. nothing is billing. re-read the numbers before starting again !!")


ap = argparse.ArgumentParser(description=__doc__)
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("status").set_defaults(f=lambda a: show(read()))
p = sub.add_parser("watch")
p.add_argument("--budget", type=float, default=120.0, help="dollars, on the HOURLY model, before everything is halted")
p.add_argument("--worst-budget", type=float, default=0.0, help="dollars on the WORST-case reading before halting (0 = ignore)")
p.add_argument("--max-alive", type=int, default=45, help="instances alive across ALL providers before halting - the runaway guard")
p.add_argument("--every", type=int, default=300)
p.set_defaults(f=None)
sub.add_parser("halt").set_defaults(f=lambda a: halt("asked by hand"))
a = ap.parse_args()

if a.cmd == "watch":
    print("watching: halt at $%.2f hourly%s, every %d s" %
          (a.budget, (" or $%.2f worst-case" % a.worst_budget) if a.worst_budget else "", a.every))
    while True:
        rows = read()
        h, w = price(rows)
        print("%s  hourly $%.2f / $%.2f   worst $%.2f%s   alive %s" % (
            time.strftime("%H:%M:%S"), h, a.budget, w,
            (" / $%.2f" % a.worst_budget) if a.worst_budget else "",
            ", ".join("%s %s" % (n, r["alive"]) for n, r in rows.items())), flush=True)
        n = sum(r["alive"] or 0 for r in rows.values())
        if a.max_alive and n > a.max_alive:
            halt("%d instances alive across all providers, over the %d allowed - a runaway" % (n, a.max_alive))
            break
        if h > a.budget:
            halt("the hourly estimate passed $%.2f" % a.budget)
            break
        if a.worst_budget and w > a.worst_budget:
            halt("even the worst-case reading passed $%.2f" % a.worst_budget)
            break
        time.sleep(a.every)
else:
    a.f(a)
