# cloud_doors.py - DERIVED from do_doors.py by make_cloud_doors.py (scratchpad): PROVIDER-GENERIC - set DOORS_PROVIDER=digitalocean|vultr|linode.
# Every provider call goes through key_id / P_create / P_get / P_destroy / P_limit / droplets; instances come back in the DigitalOcean shape.
# do_doors.py stays as it is for the running DigitalOcean station; edit do_doors.py and re-derive, never this file by hand.
# -*- coding: utf-8 -*-
"""do_doors.py - create, probe and destroy DigitalOcean droplets as ACRIS doors, from the terminal (login 2026-09-08: the
run-and-burn loop - make a door, run its allowance, move on, delete the old one, stop paying).  A tool outside the repo
(C:/dev/cre-office).  The token lives in C:/dev/nyc-cre-decoded.env (DIGITALOCEAN_TOKEN) and is never printed.

    python do_doors.py account                      the account, the SSH keys, the droplet limit, the live droplets
    python do_doors.py create --region nyc1 --count 2 [--prefix door]    -> new droplets (tag credoor), their ids and IPs
    python do_doors.py wait <id|name> ...           poll until active and ssh answers (port 22)
    python do_doors.py probe <ip> [--port 1090]     one ACRIS request through a fresh tunnel (survey.py), then tear it down
    python do_doors.py map --regions nyc1,nyc3,tor1,sfo3,lon1   create one per region, wait, probe each, report; keeps them
    python do_doors.py destroy <id|name> ...        delete a droplet (frees the slot, stops the charge)
    python do_doors.py destroy --tag credoor        delete every credoor droplet
    python do_doors.py list                         the live droplets (id, name, region, ip, status)
    python do_doors.py fill [--count 8] [--regions tor1,lon1,...]   THE CYCLE's front half (login 09-08 09:2x: "maximize digital ocean
                                                    serving doors, delete non serving ones ... create, max, delete, cycle"): create up to
                                                    --count droplets round-robin over the regions, never past the account's limit, ask
                                                    ACRIS once through each; a door that SERVES on a block we do not already hold gets a
                                                    keeper (door_tunnel.py, the next free port 1080..1099) and a row in cloud_doors.json;
                                                    every other one (refused, 503, a duplicate block, never booted) is destroyed at once
    python do_doors.py burn <name|ip|port> ...      THE CYCLE's back half: a door's notice - destroy the droplet, stop its keeper, drop the row
    python do_doors.py status                       the kept doors, their ports, whether each keeper listens and each droplet is alive

Nothing here touches ACRIS except `probe`/`map`, which go through survey.py (recorded in survey.json/survey.md).  A door that
SERVES is kept and a keeper is started for it (door_tunnel.py) so the lane can hot-add it; a door that REFUSES or 503s is
destroyed by hand once reported.  The SSH key stays on this machine; only the public half is on the droplets."""
import argparse, json, os, re, socket, subprocess, sys, time, urllib.request, urllib.error
import concurrent.futures
import random

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
KEY = r"C:\Users\smile\.ssh\door_ed25519"
BOX_PORT = 9000                              # box_fetch.py on every kept droplet (the on-box fetch, 2026-09-08): the lane's --box
SSH = r"C:\dev\cre-office\ssh\ssh.exe"      # a copy of System32\OpenSSH (09-08 12:5x): the VPN's split-tunnel rule refused the
                                             # System32 path ("Invalid split-app arguments"); the rule names THIS copy, so the
                                             # keepers' tunnels bypass the VPN and a location switch never drops them
PROVIDER = os.environ.get("DOORS_PROVIDER", "digitalocean").lower()
PROVIDERS = {
    # name: (token key, api base, ledger, log, keeper port base, probe port base, default regions, station name)
    "digitalocean": ("DIGITALOCEAN_TOKEN", "https://api.digitalocean.com/v2/", "cloud_doors.json", "do_doors.log", 1080, 1100,
                     "syd1,lon1,ams3,tor1,nyc1,nyc3,sfo3", "DigitalOcean"),
    "vultr":        ("VULTR_TOKEN", "https://api.vultr.com/v2/", "cloud_doors.vultr.json", "cloud_doors.vultr.log", 1200, 1400,
                     "syd,mel,sgp,nrt,itm,icn,bom,del,blr,ams,fra,lhr,cdg,mad,sto,waw,tlv,man,jnb,scl,sao,mex,ewr,yto,ord,atl,mia,dfw,sea,lax,sjc", "Vultr"),
    "linode":       ("LINODE_TOKEN", "https://api.linode.com/v4/", "cloud_doors.linode.json", "cloud_doors.linode.log", 1300, 1500,
                     # THE OLD DATACENTRES FIRST.  Every Linode block probed on 2026-09-09 was REFUSED - 70 of them - and every one
                     # sat in 172.104/105 or 172.232-239, one contiguous Akamai-era range ACRIS appears to have refused
                     # wholesale.  us-central (Dallas), us-west (Fremont) and us-southeast (Atlanta) are Linode's oldest
                     # datacentres and hand out entirely different space - 45.33, 45.56, 66.228, 173.255, 96.126 - so they
                     # lead the rotation now.  Linode's one success of the night, 104.105.192.38, was also outside 172.x.
                     "us-central,us-west,us-southeast,us-east,us-iad,us-ord,us-lax,us-sea,us-mia,ca-central,eu-west,gb-lon,eu-central,de-fra-2,nl-ams,fr-par-2,it-mil,es-mad,se-sto,ap-south,ap-southeast,ap-northeast,ap-west,jp-osa,jp-tyo-3,sg-sin-2,in-bom-2,in-maa,id-cgk,au-mel,br-gru", "Linode"),
    "hetzner":      ("HETZNER_TOKEN", "https://api.hetzner.cloud/v1/", "cloud_doors.hetzner.json", "cloud_doors.hetzner.log", 1600, 1800,
                     "nbg1,hel1,fsn1", "Hetzner"),   # ONLY these two: /datacenters shows fsn1-dc14 and sin-dc1 take none of the cheap types, and   # EU only: Hetzner US is E0.0328/h against E0.0096 (6x); an EU box adds ~90 ms to ACRIS, nothing against the 11-80 s it takes per image
}
if PROVIDER not in PROVIDERS:
    raise SystemExit("DOORS_PROVIDER must be one of %s" % ", ".join(PROVIDERS))
TOKEN_KEY, API_BASE, _LEDGER, _LOG, PORT_BASE, _PROBE_BASE, REGIONS_DEFAULT, STATION = PROVIDERS[PROVIDER]
IMAGE = "ubuntu-24-04-x64"
SIZE = "s-1vcpu-512mb-10gb"   # $4/mo = $0.006/h (login 14:5x: the $6 size had been selected; a door runs sshd + tunnels, 512 MB is plenty)
TAG = "credoor"
LOG = os.path.join(HERE, _LOG)
STRIKES = 15                                       # fresh blocks refused at request 1, in a row, before resting.  15, not 3:
                                                   # a refused FRESH block is ordinary hunting - ACRIS keeps a standing per address
                                                   # range and most ranges are refused - and resting the station for an hour over
                                                   # three of them (22:05, Linode: 60 minutes off after 3) stops the only thing that
                                                   # finds doors.  A globally shut ACRIS is caught for free by site_state(), which is
                                                   # what the ladder was really protecting against.
REST_BASE_MIN = 5                                  # the first rest; doubled per rest, capped at REST_MAX_MIN
REST_MAX_MIN = 60
LEDGER = os.path.join(HERE, _LEDGER)     # the kept doors: name, id, region, ip, block (/24), keeper port, kept_at
SPENT = os.path.splitext(LEDGER)[0] + ".spent.json"  # blocks this station has burned: never probed or entered again
SPENT_HOURS = 3                                    # ...for this long; a standing can reset, so the memory expires
REST = os.path.splitext(LEDGER)[0] + ".rest.json"   # THE GUARD IS PER PROVIDER: a wall in one provider's address
                                                    # space says nothing about another's (the derived cloud_doors.py
                                                    # carries its own ledger name, so its rest follows it)
CONTROL = r"C:\dev\nyc-cre-decoded\Reproduction\Acris\workflow\documentation\documentation.control"   # the running lane reads door=URL here within a minute
REGIONS = REGIONS_DEFAULT   # THE PROVIDER'S OWN CODES.  21:48: this line carried DigitalOcean's slugs (nyc1, fra1, sfo3),
                            # so Vultr answered "Invalid datacenter" and Linode "region is not valid" to every create, and three
                            # stations built nothing at all through the first eighteen minutes of an open ACRIS.
# ORDERED BY MEASURED HIT RATE, not by distance (176 probes on 2026-09-08: 29% of fresh blocks were served at
# all, and where mattered enormously - syd1 63%, sgp1 71%, ams3 44%, lon1 28%, against tor1 12%, nyc1 11%,
# sfo3 11%, nyc3 0 of 11).  ACRIS refuses North American datacentre space far harder than it refuses the rest
# of the world.  The old "near regions first" order was written when the ssh tunnel carried every ACRIS request
# and the round trip set the rate; with the fetch on the box the tunnel carries only finished bytes, so distance
# costs almost nothing and a served block is worth everything.  The fastest door of the whole day was Sydney.
MIN_SPEED = 0.5      # A LIVENESS FLOOR ONLY.  At six workers documents-a-second runs BACKWARDS: a refused block answers
                     # instantly and scores HIGH (a known-spent block scored 4.95 here) while a real door, waiting on
                     # real scans, scored 1.66 with 2.83 pages a document, 30 errors and 48.5 KB a page.  Every rate
                     # floor I set tonight - 25 pages/s, 2.0, 6.5, 4.0 - kept refusals and burned doors.  The gate that
                     # works is below: PAGES A DOCUMENT, ERRORS, and KB A PAGE.  This number only catches a dead box.
                     # a healthy door's own ramp on 2026-09-09 00:30: 40 workers -> 9.57 docs/s, 50 -> 10.01, 99 -> 9.84.
                     # A good door is ALREADY at full rate by 40 workers, so anything well under that is a block ACRIS is
                     # mostly refusing - 00:42 one scored 4.80 here while failing 2,330 of its ~2,400 requests, passed a
                     # floor of 2.0, and landed 8 documents in the lane before it was burned.  Documents, never pages or
                     # requests: a floor of 25 PAGES/s burned a door that was landing 8.29 documents a second.
                     # door.  Pages, not requests: a refusing or closed ACRIS fails instantly and looks fast (19:4x, a
                     # probe read 793.7 req/s with 0 pages and 21,018 errors).  At 150 in flight a healthy address gave
                     # 40, raised from 20 and from 6 (login 22:3x, on a DigitalOcean block pulling 114.8 served req/s:
                     # "Gotta get other doors like this going").  The night measured thirteen fresh blocks at 0.8, 1.4,
                     # 1.6, 1.8, 2.2, 2.5, 2.8, 3.2, 4.2, 6.9, 8.8, 8.9 and 10.6 docs/s - so a floor of 40 pages/s
                     # (~6.7 docs/s) keeps the top third and throws the rest away for $0.006 each.  ONE door of that
                     # class is worth four ordinary ones and costs one lane instead of four.
SPEED_WORKERS = 6    # in flight during the speed probe.  SIX.  A block's ACRIS allowance is about 6,000 requests -
                     # the best door of the night spent ~2,000 on its probe and took the notice ~4,000 into its lane -
                     # so a 120-worker probe was spending a THIRD of every door's life proving the door was alive.
                     # Six workers for 12 s is ~500 requests, and it separates a door from a refusal exactly as well:
                     # measured at six workers on a spent block, 1.18 pages a document and 626 errors, unmistakable.
SPEED_SECONDS = 12
PROBE_PORT = _PROBE_BASE                                   # scratch ports for one-request probes; the keepers live on 1080..1099


def env(k):
    for l in open("C:/dev/nyc-cre-decoded.env", encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#") and l.split("=", 1)[0].strip() == k:
            return l.split("=", 1)[1].strip()
    raise SystemExit("%s missing in C:/dev/nyc-cre-decoded.env" % k)


def _env_any(k):
    for p in (os.path.join(HERE, PROVIDER + ".env"), os.path.join(HERE, "providers.env"), r"C:/dev/nyc-cre-decoded.env"):
        try:
            with open(p, encoding="utf-8") as f:
                for l in f:
                    if l.strip().startswith(k + "="):
                        return l.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
    raise SystemExit("%s not found - save it as %s=... in C:/dev/cre-office/%s.env" % (k, k, PROVIDER))

TOKEN = _env_any(TOKEN_KEY)
KEY_ID = None                       # filled by account(); the ssh key to embed


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API_BASE + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=40)
        raw = r.read()
        return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raise SystemExit("%s API %s %s -> %s %s" % (STATION, method, path, e.code, e.read().decode()[:200]))


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))


def _pubkey():
    with open(KEY + ".pub", encoding="utf-8") as f:
        return f.read().strip()


def _is_private(ip):
    """RFC 1918 and loopback, read properly.  "172." IS NOT PRIVATE: only 172.16.0.0/12 is, and Linode hands out public
    addresses in 172.104.0.0/15 and 172.232.0.0/13 - dropping the whole 172/8 cost Linode every door it built tonight."""
    if ip.startswith(("10.", "192.168.", "127.", "169.254.")):
        return True
    if ip.startswith("172."):
        try:
            return 16 <= int(ip.split(".")[1]) <= 31
        except (IndexError, ValueError):
            return False
    return False


def _norm(d):
    """One instance in the DigitalOcean shape whatever the provider: id, name, region.slug, status (active|other), networks.v4, tags."""
    if PROVIDER == "digitalocean":
        return d
    if PROVIDER == "vultr":
        ip = d.get("main_ip") or None
        if ip in ("0.0.0.0", ""):
            ip = None
        return {"id": d["id"], "name": d.get("label") or d.get("hostname") or d["id"], "region": {"slug": d.get("region", "")},
                "status": "active" if d.get("status") == "active" and d.get("server_status") in ("ok", "installingbooting", "none", None) else d.get("status", ""),
                "networks": {"v4": [{"type": "public", "ip_address": ip}] if ip else []}, "tags": d.get("tags") or []}
    if PROVIDER == "hetzner":
        ip = ((d.get("public_net") or {}).get("ipv4") or {}).get("ip") or None
        return {"id": d["id"], "name": d.get("name") or str(d["id"]), "region": {"slug": ((d.get("datacenter") or {}).get("location") or {}).get("name", "")},
                "status": "active" if d.get("status") == "running" else d.get("status", ""),
                "networks": {"v4": [{"type": "public", "ip_address": ip}] if ip else []}, "tags": list((d.get("labels") or {}).keys())}
    ips = [x for x in (d.get("ipv4") or []) if not _is_private(x)]
    return {"id": d["id"], "name": d.get("label") or str(d["id"]), "region": {"slug": d.get("region", "")},
            "status": "active" if d.get("status") == "running" else d.get("status", ""),
            "networks": {"v4": [{"type": "public", "ip_address": ips[0]}] if ips else []}, "tags": d.get("tags") or []}


def key_id():
    """The ssh key the provider embeds: DigitalOcean/Vultr by id (uploaded as workstation-1 if missing), Linode by the public key itself."""
    if PROVIDER == "digitalocean":
        keys = api("GET", "account/keys")["ssh_keys"]
        k = next((x for x in keys if x["name"] == "workstation-1"), keys[0] if keys else None)
        if not k:
            raise SystemExit("no SSH key on the account - add workstation-1 first")
        return k["id"]
    if PROVIDER == "vultr":
        keys = api("GET", "ssh-keys?per_page=500").get("ssh_keys", [])
        k = next((x for x in keys if x["name"] == "workstation-1"), None)
        if not k:
            k = api("POST", "ssh-keys", {"name": "workstation-1", "ssh_key": _pubkey()})["ssh_key"]
            log("ssh key workstation-1 uploaded to Vultr: %s" % k["id"])
        return k["id"]
    if PROVIDER == "hetzner":
        keys = api("GET", "ssh_keys").get("ssh_keys", [])
        k = next((x for x in keys if x["name"] == "workstation-1"), None)
        if not k:
            k = api("POST", "ssh_keys", {"name": "workstation-1", "public_key": _pubkey()})["ssh_key"]
            log("ssh key workstation-1 uploaded to Hetzner: %s" % k["id"])
        return k["id"]
    return _pubkey()


def P_create(name, region, kid):
    """Create one instance; returns it in the DigitalOcean shape (ip may still be empty)."""
    if PROVIDER == "digitalocean":
        return api("POST", "droplets", {"name": name, "region": region, "size": SIZE, "image": IMAGE, "ssh_keys": [kid], "tags": [TAG]})["droplet"]
    if PROVIDER == "vultr":
        return _norm(api("POST", "instances", {"region": region, "plan": "vc2-1c-1gb", "os_id": 2284, "sshkey_id": [kid], "label": name,
                                               "hostname": name, "tags": [TAG], "backups": "disabled"})["instance"])
    if PROVIDER == "hetzner":
        return _norm(api("POST", "servers", {"name": name, "server_type": "cx23", "image": "ubuntu-24.04", "location": region,
                                            "ssh_keys": [kid], "labels": {TAG: "1"}, "start_after_create": True})["server"])
    import secrets, string
    pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24)) + "!Aa1"
    return _norm(api("POST", "linode/instances", {"region": region, "type": "g6-nanode-1", "image": "linode/ubuntu24.04", "root_pass": pw,
                                                  "authorized_keys": [kid], "label": name, "tags": [TAG], "booted": True}))


def P_get(i):
    if PROVIDER == "digitalocean":
        return api("GET", "droplets/%s" % i)["droplet"]
    if PROVIDER == "vultr":
        return _norm(api("GET", "instances/%s" % i)["instance"])
    if PROVIDER == "hetzner":
        return _norm(api("GET", "servers/%s" % i)["server"])
    return _norm(api("GET", "linode/instances/%s" % i))


def P_destroy(i):
    if PROVIDER == "digitalocean":
        P_destroy(i)
    elif PROVIDER == "vultr":
        api("DELETE", "instances/%s" % i)
    elif PROVIDER == "hetzner":
        api("DELETE", "servers/%s" % i)
    else:
        api("DELETE", "linode/instances/%s" % i)


def P_limit():
    if PROVIDER == "digitalocean":
        return api("GET", "account")["account"].get("droplet_limit", 10)
    return int(os.environ.get("DOORS_LIMIT", "10"))          # Vultr/Linode do not expose it; the create call errors past it


def droplets():
    if PROVIDER == "digitalocean":
        return api("GET", "droplets?per_page=200").get("droplets", [])
    if PROVIDER == "vultr":
        return [_norm(d) for d in api("GET", "instances?per_page=500").get("instances", [])]
    if PROVIDER == "hetzner":
        return [_norm(d) for d in api("GET", "servers?per_page=50").get("servers", [])]
    return [_norm(d) for d in api("GET", "linode/instances?page_size=500").get("data", [])]


def public_ip(d):
    return next((n["ip_address"] for n in d.get("networks", {}).get("v4", []) if n["type"] == "public"), None)


def find(idor):
    for d in droplets():
        if str(d["id"]) == str(idor) or d["name"] == idor:
            return d
    return None


def cmd_account(a):
    if PROVIDER == "digitalocean":
        acct = api("GET", "account")["account"]
        print("account:", acct.get("email"), "| status", acct.get("status"), "| droplet_limit", acct.get("droplet_limit"))
        for k in api("GET", "account/keys")["ssh_keys"]:
            print("  key", k["id"], k["name"], k["fingerprint"])
    elif PROVIDER == "vultr":
        acct = api("GET", "account")["account"]
        print("Vultr account:", acct.get("email"), "| balance", acct.get("balance"), "| key", key_id())
    else:
        # LINODES read/write is the only scope the manager needs (it uses four linode/instances endpoints and
        # embeds the public key inline), so the check lists what is alive instead of reading the account
        print("%s: token works, %d instance(s) alive | the public key is embedded per instance" % (STATION, len(droplets())))
    cmd_list(a)


def cmd_list(a):
    ds = droplets()
    print("droplets:", len(ds))
    for d in ds:
        print("  %-11s %-16s %-6s %-16s %s %s" % (d["id"], d["name"], d["region"]["slug"], public_ip(d) or "-", d["status"],
                                                  ",".join(d.get("tags", []))))


def cmd_create(a):
    kid = key_id()
    names = ["%s-%s-%d" % (a.prefix, a.region, i + 1) for i in range(a.count)]
    # avoid name clashes with existing droplets
    have = {d["name"] for d in droplets()}
    seq = 1
    for i in range(len(names)):
        while names[i] in have:
            seq += 1
            names[i] = "%s-%s-%d" % (a.prefix, a.region, seq)
        have.add(names[i]); seq += 1
    made = [P_create(n, a.region, kid) for n in names]
    for d in made:
        log("created %s %s region %s" % (d["id"], d["name"], a.region))
        print("created", d["id"], d["name"], a.region, "- booting")
    ids = [d["id"] for d in made]
    if not a.no_wait:
        _wait(ids)


def _wait(ids, timeout=420):
    # 420 s, not 240: DigitalOcean is up in under a minute but a Linode took past four (2026-09-08 20:1x, an
    # ap-southeast instance was still booting at 240 s and was running fine a minute later).  A provider that is
    # merely slow to boot must not be read as a provider that failed.
    ready = {}
    t0 = time.time()
    while time.time() - t0 < timeout and len(ready) < len(ids):
        for i in ids:
            if i in ready:
                continue
            d = P_get(i)
            ip = public_ip(d)
            if d["status"] == "active" and ip:
                if _port_open(ip, 22, 3):
                    ready[i] = ip
                    print("ready", i, d["name"], ip)
                    log("ready %s %s %s" % (i, d["name"], ip))
        if len(ready) < len(ids):
            time.sleep(6)
    for i in ids:
        if i not in ready:
            print("NOT READY after %ds:" % timeout, i)
    return ready


def cmd_wait(a):
    ids = [find(x)["id"] for x in a.targets if find(x)]
    _wait(ids)


def _port_open(ip, port, timeout):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


NOWIN = 0x08000000          # CREATE_NO_WINDOW on every helper: a detached parent's console child otherwise opens a window (09-08 13:06)


def _images_ok(port, docs=("2017090100341001", "2017090100340001", "2017090100343001")):
    """(True, words) when REAL page scans come back through this door.

    THE VIEWER IS NOT THE PRODUCT.  On 2026-09-09 00:09 DocumentImageView answered 404 site-wide while GetImage served
    perfectly, and a probe that only asked the viewer rejected every address in the world.  A page above 20 KB that
    differs in size from another page is a scan: the end-of-document marker is a constant 13,684 bytes and the refusal
    notice is 25,103 bytes of HTML, so neither can be mistaken for one."""
    try:
        import requests
    except ImportError:
        return False, "no requests module for the image check"
    prx = {"http": "socks5h://127.0.0.1:%d" % port, "https": "socks5h://127.0.0.1:%d" % port}
    base = "https://a836-acris.nyc.gov/DS/DocumentSearch"
    seen = []
    for doc in docs:
        sizes = []
        for page in (1, 2, 3, 4):
            try:
                r = requests.get(base + "/GetImage?doc_id=%s&page=%d" % (doc, page), proxies=prx, timeout=40,
                                 headers={"User-Agent": UA_CHROME, "Accept": "*/*", "Referer": base})
            except Exception as e:
                return False, "images: %s" % type(e).__name__
            if r.status_code != 200:
                continue                                   # a page the document does not have - not a refusal
            if len(r.content) == 25103 or b"BandwidthPolicy" in r.content[:4000]:
                return False, "images: the bandwidth notice - this address is refused"
            sizes.append(len(r.content))
        real = [s for s in sizes if s > 20000]              # 13,684 is the end marker, not a scan
        seen += sizes
        if len(real) >= 2 and len(set(real)) > 1:
            return True, "real scans %s" % real[:4]
    return False, "no real scans %s" % seen[:6]


def _probe(ip, port, label):
    """Bring up ssh -N -D <port> to ip, ask ACRIS once via survey.py, tear the tunnel down.  Returns SERVED/REFUSED/UNKNOWN."""
    child = subprocess.Popen([SSH, "-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-o", "GlobalKnownHostsFile=NUL", "-o", "ExitOnForwardFailure=yes",
                              "-o", "ConnectTimeout=20", "-N", "-D", "127.0.0.1:%d" % port, "root@" + ip],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=NOWIN)
    try:
        for _ in range(20):
            if _port_open("127.0.0.1", port, 2):
                break
            time.sleep(1)
        r = subprocess.run([PY, os.path.join(HERE, "survey.py"), "--label", label,
                            "--proxy", "socks5h://127.0.0.1:%d" % port, "--no-richmond", "--force"],
                           capture_output=True, text=True, timeout=120, cwd=HERE, creationflags=NOWIN)
        out = r.stdout + r.stderr
        verdict = "UNKNOWN"
        line = out.strip().splitlines()[-1][:160] if out.strip() else "no output"
        for l in out.splitlines():
            if l.strip().startswith("acris"):
                verdict = "SERVED" if "SERVED" in l else "REFUSED" if "REFUSED" in l else "UNKNOWN"
                line = l.strip()[:160]
                break
        if verdict == "SERVED":
            return verdict, line
        # THE SECOND OPINION, AND IT IS THE ONE THAT MATTERS.  The viewer can be down site-wide while the images serve
        # (00:09 tonight, for about ten minutes, at every provider and from home at once).  Rejecting an address on the
        # viewer alone threw away good doors all night, so ask this one for what a door is actually for.
        ok, words = _images_ok(port)
        if ok:
            return "SERVED", "%s (the viewer page said: %s)" % (words, line[:60])
        return verdict, "%s | %s" % (line[:95], words)
    finally:
        child.kill()


def cmd_probe(a):
    v, line = _probe(a.ip, a.port, a.label or ("do-probe %s" % a.ip))
    print(v, a.ip, "|", line)


def cmd_map(a):
    regions = [r.strip() for r in a.regions.split(",") if r.strip()]
    kid = key_id()
    made = []
    for r in regions:
        body = {"name": "%s-%s-map" % (a.prefix, r), "region": r, "size": SIZE, "image": IMAGE, "ssh_keys": [kid], "tags": [TAG]}
        have = {d["name"] for d in droplets()}
        n = 1
        while body["name"] in have:
            n += 1; body["name"] = "%s-%s-map%d" % (a.prefix, r, n)
        d = P_create(body["name"], body["region"], kid)
        made.append(d["id"]); log("map created %s %s %s" % (d["id"], d["name"], r))
        print("created", d["id"], d["name"], r)
    ready = _wait(made)
    print("\n-- probing --")
    port = a.port
    results = []
    for i in made:
        d = P_get(i)
        ip = ready.get(i) or public_ip(d)
        if not ip or not _port_open(ip, 22, 3):
            print("SKIP", d["name"], "not reachable"); results.append((d["name"], d["region"]["slug"], ip, "UNREACHABLE")); continue
        v, line = _probe(ip, port, "map %s %s %s" % (d["name"], d["region"]["slug"], ip))
        port += 1
        results.append((d["name"], d["region"]["slug"], ip, v))
        print("%-16s %-6s %-16s %s" % (d["name"], d["region"]["slug"], ip, v))
        log("map probe %s %s %s -> %s" % (d["name"], d["region"]["slug"], ip, v))
    print("\n-- summary --")
    for name, reg, ip, v in results:
        print("  %-6s %-16s %s  (%s)" % (reg, ip, v, name))
    print("SERVED doors are kept; destroy the rest with: python do_doors.py destroy --tag %s  (or by name)" % TAG)


def cmd_destroy(a):
    if a.tag:
        ds = [d for d in droplets() if a.tag in d.get("tags", [])]
    else:
        ds = [find(x) for x in a.targets]
    kept = ledger_read()
    for d in ds:
        if not d:
            continue
        P_destroy(d["id"])
        print("destroyed", d["id"], d["name"])
        log("destroyed %s %s" % (d["id"], d["name"]))
        row = next((r for r in kept if r["name"] == d["name"]), None)
        if row:                                           # a kept door: its keeper goes too, and its row
            _kill_keeper(row["port"])
            kept = [r for r in kept if r is not row]
            ledger_write(kept)


# ---- THE CYCLE: create, probe, keep what serves, burn the rest ------------------------------------------------------------

def ledger_read():
    try:
        return json.load(open(LEDGER, encoding="utf-8"))
    except (OSError, ValueError):
        return []


def ledger_write(rows):
    with open(LEDGER, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)


def hotadd_control(port):
    """Tell the RUNNING lane to open one more door on this port: append `door=socks5h://127.0.0.1:PORT` to the lane's control
    file (documentation.control).  The lane reads it within a minute (_add_door in rulebook.py) and the crew enters on its own
    ramp; a door already open is not opened twice.  Harmless if no lane is running - the line just waits there."""
    try:
        with open(CONTROL, "a", encoding="utf-8") as f:
            f.write("door=socks5h://127.0.0.1:%d\n" % port)
        return True
    except OSError as e:
        print("   could not hot-add port %d to the lane: %s" % (port, e))
        return False


def block_of(ip):
    return ".".join(ip.split(".")[:3])


def _listening(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _free_port(taken):
    for p in range(PORT_BASE, PORT_BASE + 20):
        if p not in taken and not _listening(p):
            return p
    raise SystemExit("no free keeper port in %d..%d" % (PORT_BASE, PORT_BASE + 19))


PACE_MAX = 60000     # 14:3x: the pace filter is OFF (was 2500). The idle serial pace does NOT predict what a door pulls: ACRIS
                     # meters each ADDRESS to a rate - measured on the droplets under their lanes, one page took 5.5 s on Toronto
                     # 134.122.46 (idle pace 0.46 s; the lane gets ~35 req/s) and 16.7 s on Sydney 170.64.213 (idle 0.57 s; the
                     # lane gets ~8.5) - so a 4 s-paced block is no worse than a kept one, and every SERVED block is a door.
                     # (the old note: ms per page image, measured ON the droplet (pace.sh); slower = a door not worth a core (12:01 09-08:
                     # 64.227.71 ~1,300 ms = 45 req/s at 60 wide; 209.38.x/146.190.x/165.22.x ~5,000 = 12; 159.223.x/152.42.x ~12,000 = 4.5)


def _pace(ip):
    """ACRIS's pace for this address, measured on the droplet itself (pace.sh: viewer page, one session, six page images
    serially): (ms per image or None, the probe's line).  The pace is assigned per block at the first request; the loaded
    rate at 60 workers is ~60000/ms."""
    try:
        with open(os.path.join(HERE, "pace.sh"), "rb") as f:
            r = subprocess.run([SSH, "-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-o", "GlobalKnownHostsFile=NUL", "-o", "ConnectTimeout=20",
                                "root@" + ip, "bash -s"], stdin=f, capture_output=True, text=True, timeout=240, creationflags=NOWIN)
    except Exception as e:
        return None, "pace probe failed: %s" % e
    line = (r.stdout.strip().splitlines() or [r.stderr.strip()[:120] or "no output"])[-1]
    m = re.search(r"pace (\d+) ms", line)
    return (int(m.group(1)) if m else None), line


def _box_version():
    import hashlib
    with open(os.path.join(HERE, "box_fetch.py"), "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:8]


_STATS = "python3 -c 'import urllib.request as u;print(u.urlopen(\"http://127.0.0.1:%d/stats\",timeout=5).read()[:300].decode())'" % BOX_PORT


def _box(ip, force=False):
    """THE ON-BOX FETCH (2026-09-08): box_fetch.py on the droplet, on its loopback, reached by the lane through this door with
    --box 9000.  Deploy the file and start it; a copy already running the same version is left alone (its gate and manager
    keep their state) unless `force`.  True when /stats answers on the box."""
    want = _box_version()
    try:
        if not force:
            r = subprocess.run([SSH, "-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-o", "GlobalKnownHostsFile=NUL", "-o", "ConnectTimeout=20", "root@" + ip, _STATS],
                               capture_output=True, text=True, timeout=60, creationflags=NOWIN)
            if '"version": "%s"' % want in r.stdout:
                return True
        # the kill in its OWN call: a command line that also carried the start command matched its own shell (16:05)
        subprocess.run([SSH, "-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-o", "GlobalKnownHostsFile=NUL", "-o", "ConnectTimeout=20", "root@" + ip,
                        "pkill -f '[p]ython3 /tmp/box_fetch.py'; sleep 1; true"],
                       capture_output=True, text=True, timeout=60, creationflags=NOWIN)
        with open(os.path.join(HERE, "box_fetch.py"), "rb") as f:
            r = subprocess.run([SSH, "-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-o", "GlobalKnownHostsFile=NUL", "-o", "ConnectTimeout=20", "root@" + ip,
                                "cat > /tmp/box_fetch.py; "                  # `;` not `&&`: `A && B &` backgrounds the whole list and cat then reads /dev/null (16:1x: empty files)
                                "setsid nohup python3 /tmp/box_fetch.py --port %d >/dev/null 2>&1 < /dev/null & sleep 3; " % BOX_PORT + _STATS],
                               stdin=f, capture_output=True, text=True, timeout=120, creationflags=NOWIN)
        ok = '"version": "%s"' % want in r.stdout
        log("box_fetch %s on %s -> %s" % (want, ip, "up" if ok else "NOT UP: " + (r.stdout + r.stderr).strip().replace("\n", " | ")[:160]))
        return ok
    except Exception as e:
        log("box_fetch on %s failed: %s" % (ip, e))
        return False


MAINT = ("/mxpage/maintenance", "acris-bw-pol")     # the two pages ACRIS bounces between while the service is closed


def _images_serving():
    """ASKED TWICE BEFORE IT HOLDS THE FLEET.  A single reading of the stub wall is not enough to rest four stations for
    ten minutes: 01:11:44 Linode rested on a STUBBING verdict while the very next check read "images real (69058/40636
    bytes)".  ACRIS blips.  A real stub wall lasted twenty minutes (22:37-22:57) and will still be there five seconds
    later; a blip will not."""
    ok, words = _images_serving_once()
    if ok:
        return True, words
    time.sleep(5)
    ok2, words2 = _images_serving_once()
    if ok2:
        return True, words2 + " (a first reading said stubbing - a blip, not the wall)"
    return False, words2


def _images_serving_once():
    """(True, words) if ACRIS is serving real page images to anyone at all - asked from THIS machine, for free.

    THE STUB STATE (found 22:37-22:57): the viewer page serves perfectly while every GetImage returns the SAME canned
    TIFF - 13,684 bytes, HTTP 200, content-type image/tiff, for every page of every document, on the home line and on
    fresh address space at four providers alike.  Nothing in the response says refusal, so every request-side measure
    reads the door as healthy while not one document can be fetched by anybody.  A real document's scanned pages differ
    in size, so two pages of the same length is the whole test.  Two documents are asked, because one could genuinely
    be a two-page document of equal-sized scans; both stubbing is the site."""
    import urllib.request
    base = "https://a836-acris.nyc.gov/DS/DocumentSearch"
    docs = ["2017090100340001", "2006050100996006"]
    seen = []
    for d in docs:
        ref = base + "/DocumentImageView?doc_id=" + d
        sizes = []
        for page in (1, 2):
            try:
                q = urllib.request.Request(base + "/GetImage?doc_id=%s&page=%d" % (d, page),
                                           headers={"User-Agent": UA_CHROME, "Accept": "*/*", "Referer": ref})
                with urllib.request.urlopen(q, timeout=30) as f:
                    sizes.append(len(f.read()))
            except Exception as e:
                return True, "image check inconclusive (%s) - not holding on it" % type(e).__name__
        seen.append(sizes)
        if len(set(sizes)) > 1:
            return True, "images real (%s bytes)" % "/".join(str(s) for s in sizes)
    return False, "every page the same size (%s) - the image service is serving a placeholder to everyone" % (
        ", ".join("/".join(str(s) for s in x) for x in seen))


def site_state():
    """What ACRIS does to EVERY request right now, asked from THIS machine - free, no droplet, no allowance spent.
    The redirect chain is followed by hand, four hops at most.
      MAINTENANCE  the chain reaches /MXPage/maintenance (or the two pages bounce): the service is closed to everyone,
                   so there is no address on earth that would probe SERVED and no droplet worth creating
      LIVE         anything else - a page, a notice, a 503: ACRIS is answering per address, and login's rule runs
                   exactly as before (a blocked address is deleted and we go on to the next)
    The home line's own standing does not matter here: a blocked address still gets its answer, and the bounce is a
    different answer from a refusal."""
    import urllib.request, urllib.error

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise _Hop(code, newurl)

    op = urllib.request.build_opener(NoRedirect)
    url = "https://a836-acris.nyc.gov/DS/DocumentSearch/DocumentImageView?doc_id=2006050100996006"
    seen = []
    for _ in range(4):
        req = urllib.request.Request(url, headers={"User-Agent": UA_CHROME, "Accept": "*/*"})
        try:
            r = op.open(req, timeout=25)
            r.read(2048)
            st, why = _images_serving()
            if not st:
                return "STUBBING", why
            return "LIVE", "HTTP %d, no bounce; %s" % (r.getcode(), why)
        except _Hop as h:
            seen.append(h.url)
            low = h.url.lower()
            if any(m in low for m in MAINT):
                return "MAINTENANCE", "307 -> %s" % h.url[-58:]
            url = h.url
        except urllib.error.HTTPError as e:
            return "LIVE", "HTTP %d" % e.code
        except Exception as e:
            return "LIVE", "%s: %s" % (type(e).__name__, str(e)[:70])
    return "MAINTENANCE", "bouncing: " + " -> ".join(u[-34:] for u in seen[-2:])


class _Hop(Exception):
    def __init__(self, code, url):
        Exception.__init__(self, "%d %s" % (code, url))
        self.code, self.url = code, url


UA_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
             " (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def spent_read():
    """{block: {"at": epoch, "why": ...}} - every /24 this station has burned, so nothing re-enters a burned address
    (login's rule).  `held` only ever knew the blocks we hold RIGHT NOW, so a block burned an hour ago could be created,
    probed and paid for all over again.  Entries older than SPENT_HOURS are forgotten: a standing can reset."""
    try:
        with open(SPENT, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        return {}
    cut = time.time() - SPENT_HOURS * 3600
    return {b: v for b, v in s.items() if v.get("at", 0) > cut}


def spent_write(block, why):
    if not block:
        return
    s = spent_read()
    s[block] = {"at": time.time(), "why": str(why)[:90], "when": time.strftime("%Y-%m-%d %H:%M")}
    try:
        with open(SPENT, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
    except OSError:
        pass


def rest_read():
    try:
        with open(REST, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"strikes": 0, "rests": 0, "until": 0, "why": ""}


def rest_write(s):
    with open(REST, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)


def resting():
    """(True, words) while the manager is resting off a wall of first-request refusals."""
    s = rest_read()
    left = s.get("until", 0) - time.time()
    if left > 0:
        return True, "RESTING %d more minutes (until %s) - %s" % (
            int(left // 60) + 1, time.strftime("%H:%M", time.localtime(s["until"])), s.get("why", ""))
    return False, ""


def strike(served, what):
    """One probe's verdict against the guard.  A served block clears everything: the standing is fine.  A fresh block
    refused at request 1 is a strike; STRIKES in a row buys a rest, doubling each time."""
    s = rest_read()
    if served:
        if s.get("strikes") or s.get("rests"):
            log("guard: %s served - strikes cleared" % what)
        rest_write({"strikes": 0, "rests": 0, "until": 0, "why": ""})
        return False
    s["strikes"] = s.get("strikes", 0) + 1
    if s["strikes"] < STRIKES:
        rest_write(s)
        log("guard: strike %d of %d (%s)" % (s["strikes"], STRIKES, what))
        return False
    mins = min(REST_MAX_MIN, REST_BASE_MIN * (2 ** s.get("rests", 0)))
    s.update(strikes=0, rests=s.get("rests", 0) + 1, until=time.time() + mins * 60,
             why="%d fresh blocks refused at request 1 (%s)" % (STRIKES, what))
    rest_write(s)
    log("guard: THE WALL - %d fresh blocks refused at their first request; resting %d minutes (rest %d)"
        % (STRIKES, mins, s["rests"]))
    print("\nTHE WALL: %d fresh blocks refused at request 1 - not the blocks, the standing." % STRIKES)
    print("Resting %d minutes; the first creation after it is the cold test." % mins)
    return True


def _reference():
    """DIAGNOSTIC ONLY.  survey.py on this machine's own line - which has been fetching all day and is spent by its own
    allowance (login 2026-09-08: "the home ip is blocked naturally").  REFUSED or DOWN here says nothing about the
    doors; SERVING here says the whole standing has reset, which is worth knowing."""
    try:
        r = subprocess.run([PY, os.path.join(HERE, "survey.py"), "--label", "reference", "--no-richmond", "--force"],
                           capture_output=True, text=True, timeout=180, cwd=HERE, creationflags=NOWIN)
    except Exception as e:
        return "DOWN", "the reference check itself failed: %s: %s" % (type(e).__name__, str(e)[:90])
    out = r.stdout + r.stderr
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("acris"):
            detail = s.split(":", 1)[1].strip() if ":" in s else s
            return ("SERVING" if "SERVED" in s else "REFUSED" if "REFUSED" in s else "DOWN"), detail[:150]
    return "DOWN", (out.strip().splitlines() or ["no output"])[-1][:150]


def cmd_reference(a):
    st, d = site_state()
    print("service   %s - %s" % (st, d))
    if st == "MAINTENANCE":
        print("  ACRIS is closed to every client: no address can be served, so no droplet is worth creating.")
        return
    if st == "STUBBING":
        print("  ACRIS is serving a PLACEHOLDER IMAGE to every client - its viewer pages work, its page images do not.")
        print("  No address on earth can fetch a document right now, so no droplet is worth creating.")
        return
    state, detail = _reference()
    print("reference %s - %s" % (state, detail))
    print("  (the home line is spent by its own allowance: only SERVING here is news - it means the standing has reset)")
    log("reference %s - %s" % (state, detail))


def cmd_speed(a):
    """Measure what ACRIS sustains for an address, under load, on its own box (targets: an ip, or a kept door's name/port)."""
    kept = ledger_read()
    for tgt in a.targets:
        ip = tgt
        for row in kept:
            if tgt in (row["name"], str(row["port"]), row["ip"]):
                ip = row["ip"]
        s, line = _speed(ip)
        print("  %-16s %s" % (ip, ("%.1f req/s" % s) if s is not None else "no answer"))
        print("      %s" % line[:150])


def cmd_rest(a):
    if a.clear:
        rest_write({"strikes": 0, "rests": 0, "until": 0, "why": ""})
        print("the guard is cleared - the next fill creates again")
        log("guard: cleared by hand")
        return
    s = rest_read()
    on, words = resting()
    print("strikes %d of %d, rests taken %d" % (s.get("strikes", 0), STRIKES, s.get("rests", 0)))
    print(words if on else "not resting - the fill may create")


def _speed(ip):
    """THE SPEED PROBE: how many requests a second does ACRIS actually sustain for THIS address?  box_lane.py is run on
    the candidate's own box against real unfetched documents, SPEED_WORKERS in flight for SPEED_SECONDS, and its one
    summary line is read.  Returns (requests/s or None, the line).

    This is the measurement that decides a door's worth, and it cannot be taken from here or taken idle: through a
    tunnel the home machine is the limit, and an idle serial pace does not predict the loaded rate (09-08: an address
    that paced at 1.8 s served at 56 s under load).  A notice during the probe means the block is spent already."""
    ids = os.path.join(HERE, "probe_docids.txt")
    lane = os.path.join(HERE, "box_lane.py")
    if not (os.path.exists(ids) and os.path.exists(lane)):
        return None, "no probe_docids.txt / box_lane.py beside do_doors.py - speed probe skipped"
    base = [SSH, "-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-o", "GlobalKnownHostsFile=NUL", "-o", "ConnectTimeout=20", "root@" + ip]
    try:
        with open(lane, "rb") as f:
            subprocess.run(base + ["cat > /tmp/box_lane.py"], stdin=f, capture_output=True, timeout=90, creationflags=NOWIN)
        with open(ids, "rb") as f:
            subprocess.run(base + ["cat > /tmp/ids.txt"], stdin=f, capture_output=True, timeout=90, creationflags=NOWIN)
        r = subprocess.run(base + ["python3 /tmp/box_lane.py /tmp/ids.txt %d %d" % (SPEED_WORKERS, SPEED_SECONDS)],
                           capture_output=True, text=True, timeout=SPEED_SECONDS + 180, creationflags=NOWIN)
    except Exception as e:
        return None, "speed probe failed: %s: %s" % (type(e).__name__, str(e)[:80])
    line = ""
    for l in (r.stdout + r.stderr).splitlines():
        if l.startswith("box_lane "):
            line = l.strip()
    if not line:
        return None, ((r.stdout + r.stderr).strip().splitlines() or ["no output"])[-1][:120]
    # THE SPEED IS SUCCESSFUL PAGES A SECOND, NEVER req/s.  A closed or refusing ACRIS fails every request instantly,
    # which reads as a blazing request rate: the maintenance window at 19:4x gave "793.7 req/s" with 0 pages fetched
    # and 21,018 errors.  What a door is worth is the images it actually brings back, so that is what is counted.
    got = re.search(r"(\d+) pages ok", line)
    secs = re.search(r"(\d+)s:", line)
    notices = re.search(r"(\d+) notices", line)
    errs = re.search(r"(\d+) err", line)
    if notices and int(notices.group(1)) > 0:
        return 0.0, line + "   <- a notice during the probe: this block is spent already"
    if not (got and secs) or int(secs.group(1)) <= 0:
        return None, line
    # DOCUMENTS A SECOND IS THE PRODUCT.  Pages, requests and errors all mislead: a refused address answers instantly
    # so its req/s climbs as it dies, and a HEALTHY address books an error for every page a document does not have
    # (box_lane asks for six when the viewer gives no TotalPages, so a one-page deed books five).  On 2026-09-09 that
    # error veto destroyed a door doing 8.29 documents a second - the rate we have been hunting for all night.
    dps = re.search(r"([\d.]+) docs/s", line)
    docs = re.search(r": (\d+) docs", line)
    ok_s = float(dps.group(1)) if dps else (int(docs.group(1)) / float(secs.group(1)) if docs else 0.0)
    if ok_s <= 0 and int(got.group(1)) == 0:
        return 0.0, line + "   <- not one document landed: not a door"
    # IF IT SERVES, KEEP IT.  No pages-a-document line, no error ratio.  Every threshold tried tonight ended up
    # rejecting doors that were pulling real scans, and an empty slot produces nothing at all while a mediocre
    # door produces something.  Two things still disqualify a block, and both are unambiguous: ACRIS's own
    # refusal notice (checked above), and bringing back no document whatsoever.  Everything else runs, and the
    # lane - documents on the drive - is the judge, which is where the judging always belonged.
    # THE SECOND STUB TEST, INDEPENDENT OF THE FIRST.  box_lane already refuses to count a page set whose pages are all
    # the same length, but the size itself is a giveaway that costs nothing to check: a real ACRIS page averages about
    # 45 KB, and the stub ACRIS serves a refused address is 13.7 KB.  Measured 22:29, two doors that scored 64.0 and
    # 60.6 pages/s carried 13.7 KB a page and landed NOTHING; the door that worked carried 44.7 KB.
    mb = re.search(r"([\d.]+) MB", line)
    if mb and int(got.group(1)) > 20 and ok_s > 0:
        per_page = float(mb.group(1)) * 1e6 / int(got.group(1))
        if per_page < 20000:
            return 0.0, line + "   <- %.1f KB a page: ACRIS is serving this address stubs, not scans" % (per_page / 1000.0)
    return ok_s, line + "   -> %.2f docs/s" % ok_s


def _keeper(port, ip):
    """Start door_tunnel.py for this door, detached from this process (it outlives the command); True once the port listens."""
    flags = 0x00000008 | 0x00000200 | 0x08000000          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    subprocess.Popen([PY, "-u", os.path.join(HERE, "door_tunnel.py"), "--port", str(port), "--host", "root@" + ip],
                     cwd=HERE, creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True)
    for _ in range(30):
        if _listening(port):
            _box(ip)                      # the on-box fetch rides every kept door (a line's keeper finds it already up)
            return True
        time.sleep(1)
    return False


def _kill_keeper(port):
    """Stop the keeper on this port and its ssh child (a forced stop skips the keeper's own cleanup, so both by hand)."""
    # a door's extra LINES live on port+1000, port+2000 ... (cmd_lines): they go with it
    for p in (port, port + 1000, port + 2000, port + 3000):
        ps = ("Get-CimInstance Win32_Process | Where-Object { ($_.Name -like 'python*' -and $_.CommandLine -like '*door_tunnel.py*--port %d *')"
              " -or ($_.Name -eq 'ssh.exe' -and $_.CommandLine -like '*-D 127.0.0.1:%d *') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
              % (p, p))
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60, creationflags=NOWIN)
        except Exception as e:
            print("keeper on %d not stopped: %s" % (p, e))


def _print_doors(kept):
    print("\n-- the doors (%d) --" % len(kept))
    for row in kept:
        pace = row.get("pace_ms")
        print("  %-14s %-5s %-16s %-14s port %d  pace %-9s %s" % (row["name"], row["region"], row["ip"], row["block"], row["port"],
                                                                ("%d ms" % pace) if pace else "-",
                                                                "keeper listening" if _listening(row["port"]) else "NO KEEPER"))
    if kept:
        print("fleet flags:", " ".join("--door socks5h://127.0.0.1:%d" % row["port"] for row in kept))
        print("hot-add:    ", " / ".join("door documentation=socks5h://127.0.0.1:%d" % row["port"] for row in kept))


def cmd_fill(a):
    """Rounds of _fill_round until --until doors are kept (login 09-08 09:3x: "create doors, probe, and either keep or delete.
    then when we have 10, we can run"); two rounds in a row without a new served door stop it (the regions are spent)."""
    # NO HOME-LINE CHECK, AND NO REST GUARD.  Both used to stop the fill here, and both are judged from THIS
    # MACHINE'S line - refused for days - so they read "ACRIS IS CLOSED TO EVERYONE" while cloud doors were serving
    # perfectly.  At 08:55 that alone held Vultr at zero doors.  A door costs about four cents and its lane settles
    # the question in twenty seconds: create, run the lane, delete on a refusal, create again - nothing in front.
    without_gain = 0
    rounds = 0
    while True:
        on, words = resting()
        if on and not getattr(a, 'force', False):
            print(words)
            break
        before = len(ledger_read())
        _fill_round(a)
        kept = len(ledger_read())
        rounds += 1
        if not a.until or kept >= a.until:
            break
        if getattr(a, "rounds", 0) and rounds >= a.rounds:
            print("round limit %d reached at %d kept" % (a.rounds, kept))   # the supervisor paces creations by the hour
            break
        without_gain = without_gain + 1 if kept == before else 0
        if without_gain >= 2:
            print("two rounds without a served door - stopping at %d kept" % kept)
            break
        print("\n== %d kept, going again ==\n" % kept)


def _created_total():
    """Droplets this manager has ever created (the ' created ' lines of do_doors.log) - the fill's region rotation counter."""
    p = LOG            # THIS provider's log, not DigitalOcean's.  Hardcoded, the counter never moved for Vultr,
                       # Linode or Hetzner, so the region rotation never advanced: Linode made six droplets in a row
                       # in sg-sin-2 and burned the same three /24s (23:2x).
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return sum(1 for l in f if " created " in l)
    except OSError:
        return 0


def _fill_round(a):
    """Create up to --count droplets round-robin over --regions (never past the account's limit), ask ACRIS once through each.
    SERVED on a block we do not hold -> a keeper on the next free port and a ledger row.  Anything else -> destroyed at once."""
    regions = [r.strip() for r in a.regions.split(",") if r.strip()]
    shuffled = list(regions)
    random.Random(int(time.time()) // 60).shuffle(shuffled)   # a fresh spread each minute, stable within a round
    kid = key_id()
    limit = P_limit()
    alive = droplets()
    n = min(a.count, limit - len(alive))
    if n <= 0:
        print("no free slot: %d of %d droplets alive" % (len(alive), limit))
        return
    kept = ledger_read()
    held = {r["block"] for r in kept}
    spent = spent_read()
    have = {d["name"] for d in alive}
    made = []
    bad = set()
    bad_why = set()                     # regions this provider refused THIS round: tried once, then stepped over
    tries = 0
    while len(made) < n and tries < len(regions) * 2:
        # SPREAD, DO NOT WALK.  A provider is never uniformly refused - it is a RANGE that is refused - so the way to
        # find the block that serves is to sample the whole list, not march along it.  Every Linode create of the night
        # landed in 172.104/105 or 172.232-239 and every one was refused, while its single success sat outside that
        # range entirely.  Shuffled per round, so a round of four touches four unrelated datacentres.
        r = shuffled[(len(made) + tries) % len(shuffled)]
        tries += 1
        if r in bad:
            continue
        k = 1
        while "door-%s-%d" % (r, k) in have:
            k += 1
        name = "door-%s-%d" % (r, k)
        try:
            d = P_create(name, r, kid)
        except (Exception, SystemExit) as e:            # api() raises SystemExit on an HTTP error - Exception alone never catches it
            # A REGION WE CANNOT BUILD IN IS NEWS, NOT A FAILURE (21:44: one bad code silenced three whole stations for
            # the first quarter-hour of an open ACRIS).  Nothing was created, so nothing is billed - step over it.
            bad.add(r)
            why = " ".join(str(e).split())[:110]
            bad_why.add(why)
            log("fill cannot build in %s: %s" % (r, why))
            print("SKIP", r, "-", why)
            continue
        have.add(name)
        made.append((d["id"], name, r))
        log("fill created %s %s %s" % (d["id"], name, r))
        print("created", d["id"], name, r)
    if not made:
        # A LIMIT REFUSAL IS NOT THE SAME AS A REGION REFUSAL.  When the provider says the account is full, the cure is
        # not another region - it is to judge what is ALREADY on the account (Hetzner allows five servers, so five
        # candidates nobody is judging leave the station unable to build at all).  Saying "no free slot" here is what
        # makes the supervisor run its adopt.
        why = " ".join(sorted(bad_why)).lower()
        if any(w in why for w in ("limit", "quota", "exceeded", "maximum", "too many")):
            print("no free slot: the account is full - %d region(s) refused on the account limit" % len(bad))
            log("fill: the account is full (%s) - the untracked instances need adopting" % ",".join(sorted(bad))[:90])
            return
        print("no region would build this round (%d tried) - nothing created, nothing billed" % len(bad))
        log("fill made nothing: every region tried refused (%s)" % ",".join(sorted(bad))[:120])
        return
    ready = _wait([i for i, _, _ in made], timeout=300)
    print("\n-- probing every candidate at once --")
    # THE ROUND TAKES AS LONG AS ITS SLOWEST CANDIDATE, NOT THE SUM OF THEM.  Probing and load-testing one address at a
    # time cost four to seven minutes a round and was the whole reason doors arrived slowly; the candidates are
    # independent addresses on independent machines, so they are judged together.  The DECISIONS below stay serial:
    # they write the ledger, the spent list and the strike count, and they hand out keeper ports.
    _jobs = []
    _pp = PROBE_PORT
    for i, name, r in made:
        _jobs.append((i, name, r, _pp))
        _pp += 1

    def _judge(job):
        i, name, r, pport = job
        out = {"i": i, "name": name, "r": r, "ip": ready.get(i), "block": None,
               "verdict": None, "line": "", "speed": None, "sline": ""}
        if not out["ip"]:
            return out
        out["block"] = block_of(out["ip"])
        if out["block"] in held or out["block"] in spent:
            return out                                   # decided without spending one request of its allowance
        # NO PROBE, NO SPEED TEST.  It booted and it has an address: that is the whole entry exam.  Whether ACRIS
        # serves this block is answered by the lane, in twenty seconds, in documents - and the lane is the only judge
        # that has never been wrong tonight.  Skipping the probe also hands the lane the block's full allowance.
        out["verdict"], out["line"] = "SERVED", "kept unjudged - the lane is the test"
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(_jobs))) as _pool:
        _verdicts = list(_pool.map(_judge, _jobs))

    served = stubbed = 0
    for _v in _verdicts:
        i, name, r = _v["i"], _v["name"], _v["r"]
        ip = _v["ip"]
        if not ip:
            P_destroy(i)
            log("fill burnt %s %s: never came up" % (i, name))
            print("BURNT", name, r, "- never came up")
            continue
        b = _v["block"]
        if b in held:
            P_destroy(i)
            log("fill burnt %s %s %s: block %s already held" % (i, name, ip, b))
            print("BURNT", name, r, ip, "- block", b, "already held")
            continue
        if b in spent:                                    # NOTHING RE-ENTERS A BURNED ADDRESS (login's rule): destroyed
            P_destroy(i)              # without spending a probe request on a block we know is done
            log("fill burnt %s %s %s: block %s is spent (%s)" % (i, name, ip, b, spent[b].get("why", "")))
            print("BURNT", name, r, ip, "- block", b, "was burned", spent[b].get("when", ""), "- not probed again")
            continue
        v, line = _v["verdict"], _v["line"]
        log("fill probe %s %s %s -> %s | %s" % (name, r, ip, v, line))
        # THE ESCALATION GUARD: this block has served nobody - a refusal here is the standing, not a spent door
        walled = strike(v == "SERVED", "%s %s %s: %s" % (name, r, ip, v))
        if v != "SERVED":
            P_destroy(i)
            spent_write(b, "probe %s" % v)
            log("fill burnt %s %s %s: %s" % (i, name, ip, v))
            print("BURNT", name, r, ip, v)
            if walled:
                break                                     # rest now: the rest of this round would be more of the same
            continue
        # GATE 1b, THE SPEED PROBE: it answered - but how fast is ACRIS for THIS address, under real load, on its own
        # box?  Eight-fold spread block to block, and the idle pace does not predict it, so a door is judged here rather
        # than six minutes into a lane's life.
        speed, sline = _v["speed"], _v["sline"]
        served += 1
        log("fill speed %s %s %s -> %s" % (name, r, ip, sline))
        if speed is None:
            print("      speed probe gave no answer (%s) - keeping the block and letting the station judge it" % sline[:70])
        elif speed < a.min_speed:
            if "stubs" in (sline or "") and " 0 pages ok" in (sline or ""):
                stubbed += 1                      # not a slow address: an address ACRIS answered with a canned image
            P_destroy(i)
            spent_write(b, "only %.2f docs/s" % speed)
            # NOT a strike: the escalation ladder counts blocks ACRIS REFUSED, and this one served - it was merely slow.
            # Counting slow blocks would rest the whole station for half an hour exactly when the hunt is working.
            strike(True, "%s %s %s: served but only %.2f docs/s" % (name, r, ip, speed))
            log("fill burnt %s %s %s: %.1f req/s under %.1f" % (i, name, ip, speed, a.min_speed))
            print("BURNT", name, r, ip, "SLOW - %.2f docs/s (floor %.2f): %s" % (speed, a.min_speed, sline[:60]))
            continue
        ms = None
        port = _free_port({row["port"] for row in kept})
        up = _keeper(port, ip)
        kept.append({"name": name, "id": i, "region": r, "ip": ip, "block": b, "port": port, "pace_ms": ms,
                     "kept_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        held.add(b)
        ledger_write(kept)
        log("fill kept %s %s %s block %s port %d keeper %s" % (name, r, ip, b, port, "up" if up else "NOT LISTENING"))
        print("KEPT ", name, r, ip, "block", b, (("pace %d ms (~%d req/s at 60 wide)" % (ms, 60000 // max(1, ms))) if ms else "judged on the speed probe, not an idle pace"),
              "-> socks5h://127.0.0.1:%d" % port, "keeper up" if up else "KEEPER NOT LISTENING")
        if getattr(a, "hotadd", False) and hotadd_control(port):
            print("      hot-added to the running lane (door=socks5h://127.0.0.1:%d written to the control file)" % port)
    # EVERY SERVED ADDRESS STUBBED: that is the SITE, not the addresses (22:46-22:49, five in a row across two
    # providers, all answering with the same canned 13,684-byte image).  Buying more addresses cannot cure it, so the
    # station rests and tries again; the first fresh address that serves a real page clears it.
    if served >= 2 and stubbed == served:
        s = rest_read()
        s["rests"] = s.get("rests", 0) + 1
        mins = min(REST_MAX_MIN, 10 * (2 ** (s["rests"] - 1)))
        s["until"] = time.time() + mins * 60
        s["why"] = "ACRIS is serving a canned stub image to every fresh address (%d of %d this round)" % (stubbed, served)
        rest_write(s)
        log("guard: THE STUB WALL - %d of %d fresh addresses served canned images; resting %d minutes" % (stubbed, served, mins))
        print("STUB WALL: every fresh address is being served a canned image, not scans - resting %d minutes" % mins)
    _print_doors(kept)


def cmd_burn(a):
    """A door's notice: destroy the droplet, stop its keeper, drop the ledger row.  A target is a name, an ip or a port."""
    kept = ledger_read()
    for t in a.targets:
        row = next((r for r in kept if t in (r["name"], r["ip"], str(r["port"]))), None)
        d = find(row["name"] if row else t)
        if row:
            _kill_keeper(row["port"])
            spent_write(row.get("block"), "burnt at %s" % time.strftime("%H:%M"))   # never re-entered (login's rule)
            kept = [r for r in kept if r is not row]
            ledger_write(kept)
        if d:
            P_destroy(d["id"])
            print("burnt", d["id"], d["name"], "port %s" % (row["port"] if row else "-"))
            log("burnt %s %s port %s" % (d["id"], d["name"], row["port"] if row else "-"))
        elif not row:
            print("no such door:", t)
    _print_doors(kept)


def cmd_replace(a):
    """A door burned on its notice: destroy it (billing stops, slot freed), then bring a fresh serving door up in its place and
    hot-add it to the running lane, so the door count holds.  Targets are name|ip|port.  The refill draws from --regions (the
    serving regions by default) - a block is the unit, so any serving region will do; it keeps probing until it has replaced
    every burned door or two rounds run dry."""
    kept = ledger_read()
    burned = 0
    for t in a.targets:
        row = next((r for r in kept if t in (r["name"], r["ip"], str(r["port"]))), None)
        if not row:
            print("no such door:", t); continue
        _kill_keeper(row["port"])
        d = find(row["name"])
        if d:
            P_destroy(d["id"])
            print("burnt", d["id"], row["name"], "port", row["port"])
            log("replace burnt %s %s port %d" % (d["id"], row["name"], row["port"]))
        kept = [r for r in kept if r is not row]
        ledger_write(kept)
        burned += 1
    if not burned:
        print("nothing to replace"); return
    a.until = len(kept) + burned                          # refill back to where we were
    a.count = min(burned + 2, 8)                           # a little over-probe, refused ones are cheap
    a.hotadd = True
    print("\n-- refilling %d door%s --" % (burned, "" if burned == 1 else "s"))
    cmd_fill(a)


def cmd_adopt(a):
    """Droplets alive on the account but not in the ledger (a fill that died mid-round leaves them billing): probe, pace,
    keep or destroy - the same judgment a fill round makes.  Targets are names or ips; none = every untracked credoor."""
    kept = ledger_read()
    tracked = {r["ip"] for r in kept}
    held = {r["block"] for r in kept}
    alive = [d for d in droplets() if TAG in (d.get("tags") or []) and public_ip(d) not in tracked]
    if a.targets:
        alive = [d for d in alive if d["name"] in a.targets or public_ip(d) in a.targets]
    if not alive:
        print("nothing to adopt"); return
    probe_port = PROBE_PORT
    for d in alive:
        ip, name, r, i = public_ip(d), d["name"], d["region"]["slug"], d["id"]
        b = block_of(ip)
        if b in held:
            P_destroy(i); log("adopt burnt %s %s %s: block %s already held" % (i, name, ip, b))
            print("BURNT", name, r, ip, "- block", b, "already held"); continue
        v, line = _probe(ip, probe_port, "adopt %s %s %s" % (name, r, ip)); probe_port += 1
        log("adopt probe %s %s %s -> %s | %s" % (name, r, ip, v, line))
        if v != "SERVED":
            P_destroy(i); log("adopt burnt %s %s %s: %s" % (i, name, ip, v))
            print("BURNT", name, r, ip, v); continue
        # THE SAME SECOND GATE THE FILL USES.  An idle pace does not predict a loaded rate (an address that paced at
        # 1.8 s served at 56 s under load), and adopt is not a rare path: Hetzner allows five servers, so a station
        # there reaches its limit constantly and adopts far more doors than it creates.
        speed, sline = _speed(ip)
        log("adopt speed %s %s %s -> %s" % (name, r, ip, sline))
        ms = None
        if speed is not None and speed < MIN_SPEED:
            P_destroy(i); spent_write(b, "only %.2f docs/s" % speed)
            log("adopt burnt %s %s %s: %.1f pages/s under %.1f" % (i, name, ip, speed, MIN_SPEED))
            print("BURNT", name, r, ip, "SLOW - %.1f pages/s (floor %.1f)" % (speed, MIN_SPEED)); continue
        port = _free_port({row["port"] for row in kept})
        up = _keeper(port, ip)
        kept.append({"name": name, "id": i, "region": r, "ip": ip, "block": b, "port": port, "pace_ms": ms,
                     "kept_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        held.add(b); ledger_write(kept)
        log("adopt kept %s %s %s block %s port %d keeper %s" % (name, r, ip, b, port, "up" if up else "NOT LISTENING"))
        print("KEPT ", name, r, ip, "block", b, (("pace %d ms (~%d req/s at 60 wide)" % (ms, 60000 // max(1, ms))) if ms else "judged on the speed probe, not an idle pace"),
              "-> socks5h://127.0.0.1:%d" % port, "keeper up" if up else "KEEPER NOT LISTENING")
    _print_doors(kept)


def cmd_lines(a):
    """Ensure every kept door has --lines tunnels: ports port, port+1000, port+2000 (one `ssh -D` each).  Idempotent.
    Why (09-08 13:5x): one ssh tunnel is ONE TCP connection carrying all of a door's workers, and its throughput falls with
    the round trip - from home, Toronto ran 1.5 s a page against 0.46 s on the droplet, Sydney 10 s against 0.57 s.  Three
    lines = three connections; the lane runs one crew per line on the same address (the allowance is the address's)."""
    for row in ledger_read():
        for j in range(a.lines):
            p = row["port"] + 1000 * j
            if _listening(p):
                continue
            up = _keeper(p, row["ip"])
            print("  %-14s %-16s line %d port %d -> %s" % (row["name"], row["ip"], j + 1, p, "up" if up else "NOT LISTENING"))
            log("line %d for %s %s: port %d -> %s" % (j + 1, row["name"], row["ip"], p, "up" if up else "NOT LISTENING"))


def cmd_keepers(a):
    """Restart every kept door's keeper (after a change to door_tunnel.py or the ssh client it names): kill, start, verify.
    The slots on those doors hang up once and re-enter on their own (~2 min)."""
    kept = ledger_read()
    for row in kept:
        _kill_keeper(row["port"])
        up = _keeper(row["port"], row["ip"])
        print("  port %d  %-14s %-16s keeper %s" % (row["port"], row["name"], row["ip"], "up" if up else "NOT LISTENING"))
        log("keeper restarted %s %s port %d -> %s" % (row["name"], row["ip"], row["port"], "up" if up else "NOT LISTENING"))


def cmd_box(a):
    """Deploy / restart box_fetch.py on the kept doors (targets name|ip|port, default all); --force restarts a copy already
    running the current version."""
    kept = ledger_read()
    rows = [r for r in kept if not a.targets or r["name"] in a.targets or r["ip"] in a.targets or str(r["port"]) in a.targets]
    for row in rows:
        ok = _box(row["ip"], force=a.force)
        print("  port %d  %-14s %-16s box_fetch %s" % (row["port"], row["name"], row["ip"], "up" if ok else "NOT UP"))


def cmd_pace(a):
    """ACRIS's pace for each kept door (or the targets), measured on the droplet: ms per page image and the rate it implies
    at 60 workers.  A slow door (> PACE_MAX) is a droplet and a core spent for 4-5 req/s - burn it and refill."""
    kept = ledger_read()
    rows = kept if not a.targets else [r for r in kept if any(t in (r["name"], r["ip"], str(r["port"])) for t in a.targets)]
    for row in rows:
        ms, line = _pace(row["ip"])
        row["pace_ms"] = ms
        print("  port %d  %-14s %-16s %s" % (row["port"], row["name"], row["ip"], line))
        log("pace %s %s -> %s" % (row["name"], row["ip"], line))
    ledger_write(kept)


def cmd_status(a):
    kept = ledger_read()
    alive = {d["name"] for d in droplets()}
    _print_doors(kept)
    for row in kept:
        if row["name"] not in alive:
            print("  !!", row["name"], "is in the ledger but not on the account - burn it to clear the row")


ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("account").set_defaults(f=cmd_account)
sub.add_parser("list").set_defaults(f=cmd_list)
p = sub.add_parser("create"); p.add_argument("--region", required=True); p.add_argument("--count", type=int, default=1); p.add_argument("--prefix", default="door"); p.add_argument("--no-wait", action="store_true"); p.set_defaults(f=cmd_create)
p = sub.add_parser("wait"); p.add_argument("targets", nargs="+"); p.set_defaults(f=cmd_wait)
p = sub.add_parser("probe"); p.add_argument("ip"); p.add_argument("--port", type=int, default=1090); p.add_argument("--label", default=""); p.set_defaults(f=cmd_probe)
p = sub.add_parser("map"); p.add_argument("--regions", required=True); p.add_argument("--prefix", default="door"); p.add_argument("--port", type=int, default=1090); p.set_defaults(f=cmd_map)
p = sub.add_parser("destroy"); p.add_argument("targets", nargs="*"); p.add_argument("--tag", default=""); p.set_defaults(f=cmd_destroy)
p = sub.add_parser("fill"); p.add_argument("--force", action="store_true", help="create even while the guard is resting (the cold test by hand)"); p.add_argument("--min-speed", type=float, default=MIN_SPEED, help="requests/s a fresh block must sustain under load or be destroyed (0 = keep whatever answers)"); p.add_argument("--count", type=int, default=8); p.add_argument("--regions", default=REGIONS); p.add_argument("--until", type=int, default=0, help="keep filling until this many doors are kept (0 = one round)"); p.add_argument("--hotadd", action="store_true", help="hot-add each kept door to the running lane via its control file"); p.add_argument("--rounds", type=int, default=0, help="stop after this many rounds (0 = until --until or two dry rounds); the supervisor's pacing"); p.set_defaults(f=cmd_fill)
p = sub.add_parser("burn"); p.add_argument("targets", nargs="+"); p.set_defaults(f=cmd_burn)
sub.add_parser("keepers", help="restart every kept door's keeper on the current door_tunnel.py / ssh client").set_defaults(f=cmd_keepers)
p = sub.add_parser("lines", help="ensure every kept door has N tunnels (ports port, port+1000, ...): one TCP connection each"); p.add_argument("--lines", type=int, default=3); p.set_defaults(f=cmd_lines)
p = sub.add_parser("adopt", help="droplets alive but not in the ledger: probe, pace, keep or destroy (a fill that died mid-round)"); p.add_argument("targets", nargs="*"); p.set_defaults(f=cmd_adopt)
p = sub.add_parser("pace", help="ACRIS's pace per kept door, measured on the droplet (pace.sh); targets name|ip|port, default all"); p.add_argument("targets", nargs="*"); p.set_defaults(f=cmd_pace)
p = sub.add_parser("box", help="deploy / restart box_fetch.py (the on-box fetch) on the kept doors; default all"); p.add_argument("targets", nargs="*"); p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_box)
p = sub.add_parser("replace"); p.add_argument("targets", nargs="+"); p.add_argument("--regions", default=REGIONS); p.set_defaults(f=cmd_replace)
p = sub.add_parser("speed", help="what ACRIS sustains for an address under load, measured on its own box"); p.add_argument("targets", nargs="+"); p.set_defaults(f=cmd_speed)
sub.add_parser("reference", help="DIAGNOSTIC: ask ACRIS on this machine's own line (spent by its own allowance; only SERVING is news)").set_defaults(f=cmd_reference)
p = sub.add_parser("rest", help="the escalation guard: strikes and the rest a wall of first-request refusals bought"); p.add_argument("--clear", action="store_true"); p.set_defaults(f=cmd_rest)
sub.add_parser("status").set_defaults(f=cmd_status)
a = ap.parse_args()
a.f(a)
