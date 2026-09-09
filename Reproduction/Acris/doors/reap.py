#!/usr/bin/env python3
# reap.py - DESTROY EVERY INSTANCE THAT IS NOT A DOOR (login 2026-09-08: "when you have to delete one, you do, and when
# you have to create one, you do").
#
# 22:01, the first hour of the reopening: 30 instances alive across the four accounts and 5 doors in the ledgers.  The
# other 25 were created, then lost - a fill that threw between creating and probing, a supervisor killed mid-round, a
# probe that never returned.  They are not doors: no keeper, no tunnel, no lane, no ledger row.  They cost money and,
# far worse, they fill the account's instance limit, so the station cannot create the doors it actually needs.
# DigitalOcean was at 8 of 10 alive with 3 real doors: two creations away from being unable to work at all.
#
# The rule is simple and safe: an instance is spared while it is young enough to still be inside a probe, and spared
# forever if the ledger holds its id.  Anything else that carries our tag is destroyed.  Nothing else on the account is
# ever touched - only instances tagged `credoor`, which is a tag only these tools apply.
#
#   python reap.py                 what would be destroyed (nothing is)
#   python reap.py --destroy       destroy them
#   python reap.py --destroy --every 300 --age 12     keep doing it, forever
import argparse, json, pathlib, sys, time, urllib.error, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
TAG = "credoor"
LOG = HERE / "reap.log"

# provider: (env file, key, api base, list path, node, delete path, ledger)
P = {
    "digitalocean": ("C:/dev/nyc-cre-decoded.env", "DIGITALOCEAN_TOKEN", "https://api.digitalocean.com/v2/",
                     "droplets?per_page=200&tag_name=" + TAG, "droplets", "droplets/%s", "cloud_doors.json"),
    "vultr":        (str(HERE / "vultr.env"), "VULTR_TOKEN", "https://api.vultr.com/v2/",
                     "instances?per_page=200", "instances", "instances/%s", "cloud_doors.vultr.json"),
    "linode":       (str(HERE / "linode.env"), "LINODE_TOKEN", "https://api.linode.com/v4/",
                     "linode/instances?page_size=200", "data", "linode/instances/%s", "cloud_doors.linode.json"),
    "hetzner":      (str(HERE / "hetzner.env"), "HETZNER_TOKEN", "https://api.hetzner.cloud/v1/",
                     "servers?per_page=50", "servers", "servers/%s", "cloud_doors.hetzner.json"),
}


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


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


def age_minutes(d, provider):
    """Minutes since the provider says it was created; 0 (i.e. spare it) when the field is missing or unreadable."""
    raw = d.get("created") or d.get("date_created") or d.get("created_at") or ""
    if not raw:
        return 0.0
    raw = raw.replace("Z", "+00:00")
    try:
        import datetime
        t = datetime.datetime.fromisoformat(raw)
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 60.0
    except (ValueError, ImportError):
        return 0.0


def tagged(d, provider):
    if provider == "digitalocean":
        return True                                   # the list itself was filtered by tag
    if provider == "hetzner":
        return TAG in (d.get("labels") or {})
    return TAG in (d.get("tags") or [])


def ledger_ids(name):
    p = HERE / name
    if not p.exists():
        return set()
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(r.get("id")) for r in rows if isinstance(r, dict)}


def sweep(destroy, age):
    total_seen = total_killed = 0
    for provider, (tpath, tkey, base, listpath, node, delpath, ledger) in P.items():
        tok = token(tpath, tkey)
        if not tok:
            continue
        try:
            rows = api(base, listpath, tok).get(node, [])
        except Exception as e:
            log("%s: could not list (%s) - skipped this pass" % (provider, str(e)[:70]))
            continue
        keep = ledger_ids(ledger)
        orphans = []
        for d in rows:
            if not tagged(d, provider):
                continue
            total_seen += 1
            i = str(d.get("id"))
            if i in keep:
                continue
            mins = age_minutes(d, provider)
            if mins < age:
                continue                              # still young enough to be inside its own probe
            orphans.append((i, d.get("label") or d.get("name") or i, mins))
        for i, name, mins in orphans:
            if not destroy:
                log("%s WOULD REAP %s %s (%.0f min old, no ledger row)" % (provider, i, name, mins))
                continue
            try:
                api(base, delpath % i, tok, method="DELETE")
                total_killed += 1
                log("%s reaped %s %s (%.0f min old, no ledger row, no keeper, no lane)" % (provider, i, name, mins))
            except Exception as e:
                log("%s could not reap %s: %s" % (provider, i, str(e)[:70]))
    return total_seen, total_killed


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--destroy", action="store_true", help="actually destroy them (without this, only says what it would do)")
ap.add_argument("--age", type=float, default=12.0, help="minutes an instance may live without a ledger row before it is reaped")
ap.add_argument("--every", type=int, default=0, help="keep sweeping every N seconds")
a = ap.parse_args()

while True:
    seen, killed = sweep(a.destroy, a.age)
    log("pass: %d tagged instance(s) alive, %d reaped" % (seen, killed))
    if not a.every:
        break
    time.sleep(a.every)
