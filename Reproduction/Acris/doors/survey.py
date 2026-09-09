# -*- coding: utf-8 -*-
"""THE SURVEY - which exits serve ACRIS, which pass Cloudflare in front of Richmond's courts host.  A person's tool,
outside the repo (login 2026-09-07 15:5x: "the only way to know is to test access on all vpn to acris and to Richmond").

One stop = the app on one location, then:

    python survey.py --label "Albania"        the exit (five draws, one block, the owner from ipinfo - no source touched),
                                              then ONE lane-style request to ACRIS (the viewer page of one known document,
                                              the lane's own session, UA and Referer) and ONE plain request to the courts
                                              host root; the verdicts appended to survey.md / survey.json beside this file.
    python survey.py --label "Albania" --dry  the exit and the owner only, nothing asked of either source.
    --no-acris / --no-richmond                skip one source.   --doc <id>  another document (default 2005081702043001).

The unit is the OWNER (the ASN): every block of a spent provider answered the notice (2026-09-07 05:42), so one stop per
owner is the whole map, and a location whose owner is already on spent_providers.json is reported, not asked.  A refusal
at the first request costs one request and puts the owner on that list with its evidence; a served answer is the door's
standing at request 1, not its allowance - only a held run measures that.  Never run unasked: every stop is on login's word.
"""
import argparse, datetime as dt, json, os, pathlib, sys, time, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path("C:/dev/nyc-cre-decoded")
sys.path.insert(0, str(REPO / "Reproduction" / "rulebook"))
sys.path.insert(0, str(REPO / "Reproduction" / "Acris" / "rulebook"))
sys.path.insert(0, str(REPO / "Reproduction" / "Richmond" / "rulebook"))
import rulebook, acris, richmond          # noqa: E402  (the repo's own modules: the lane's session, UA, urls, detectors)

SPENT = HERE / "spent_providers.json"
LEDGER_MD, LEDGER_JSON = HERE / "survey.md", HERE / "survey.json"
DOC = "2005081702043001"                  # the cut document of 09-07 (4 pages): its viewer page is the lane's first request shape
COURTS = richmond.IAPPS + "/"


PROXY = {}                                # --proxy socks5h://127.0.0.1:1080 : a VPS door - every request of this run goes through it


def draws(n=5, pause=1.0):
    """The public exit, n fresh connections, pause apart (what the lane's exit-pool gate does)."""
    out = []
    for _ in range(n):
        try:
            if PROXY:
                import requests
                out.append(requests.get("https://api.ipify.org", headers={"User-Agent": "curl/8", "Connection": "close"},
                                        proxies=PROXY, timeout=15).text.strip())
            else:
                r = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "curl/8", "Connection": "close"})
                out.append(urllib.request.urlopen(r, timeout=10).read().decode().strip())
        except Exception as e:
            out.append("? (%s)" % type(e).__name__)
        time.sleep(pause)
    return out


def owner(ip):
    """(asn, org, city, country) from ipinfo.io - a lookup, never a source request."""
    try:
        r = urllib.request.Request("https://ipinfo.io/%s/json" % ip, headers={"User-Agent": "curl/8", "Connection": "close"})
        d = json.loads(urllib.request.urlopen(r, timeout=10).read().decode())
        org = d.get("org", "") or ""
        asn = org.split(" ")[0] if org.startswith("AS") else "?"
        return asn, org[len(asn):].strip() if asn != "?" else org, d.get("city", "?"), d.get("country", "?")
    except Exception as e:
        return "?", "? (%s)" % type(e).__name__, "?", "?"


def spent_list():
    try:
        return json.loads(SPENT.read_text(encoding="utf-8"))
    except Exception:
        return {"spent": {}, "served": {}}


def mark_spent(asn, org, evidence):
    d = spent_list()
    if asn in d.get("spent", {}):
        return
    d.setdefault("spent", {})[asn] = {"org": org, "since": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "evidence": evidence}
    SPENT.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def ask_acris(doc):
    """ONE request, the lane's shape: the viewer page with the detail page as Referer on the lane's own session."""
    s = rulebook.make_session(1, acris.UA)
    s.proxies.update(PROXY)
    try:
        r = s.get(acris.viewer_url(doc), headers={"Referer": acris.detail_url(doc)}, timeout=30)
        data, ctype = r.content, r.headers.get("Content-Type", "")
        try:
            acris.check_refused(data, ctype, "survey " + doc)
        except rulebook.Refused as e:
            return "REFUSED", "HTTP %d, %s, final url %s - %s" % (r.status_code, len(data), r.url, str(e)[:120])
        n = acris.total_pages(data)
        if n is not None:
            return "SERVED", "HTTP %d, TotalPages %s, %d bytes" % (r.status_code, n, len(data))
        return "UNKNOWN", "HTTP %d, %s, %d bytes, final url %s" % (r.status_code, ctype[:40], len(data), r.url)
    except Exception as e:
        return "WIRE", "%s: %s" % (type(e).__name__, str(e)[:120])
    finally:
        s.close()


def ask_richmond():
    """ONE plain request to the courts host root: Cloudflare answers by the address before any document is named."""
    s = rulebook.make_session(1, richmond.UA)
    s.proxies.update(PROXY)
    try:
        r = s.get(COURTS, headers=richmond.PULL_HEADERS, timeout=30, allow_redirects=False)
        if richmond.is_challenge(r.status_code, r.headers, r.content):
            return "CHALLENGED", "HTTP %d, cf-mitigated %s" % (r.status_code, r.headers.get("cf-mitigated", ""))
        return "SERVED", "HTTP %d, %d bytes%s" % (r.status_code, len(r.content), (", to " + r.headers["Location"]) if r.headers.get("Location") else "")
    except Exception as e:
        return "WIRE", "%s: %s" % (type(e).__name__, str(e)[:120])
    finally:
        s.close()


def record(row):
    rows = []
    if LEDGER_JSON.exists():
        rows = json.loads(LEDGER_JSON.read_text(encoding="utf-8"))
    rows.append(row)
    LEDGER_JSON.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if not LEDGER_MD.exists():
        LEDGER_MD.write_text("# The survey - which exits serve ACRIS, which pass Cloudflare at the courts host\n\n"
                             "One row per stop (the app on one location): the exit's block and owner, then one request to each source. "
                             "A served ACRIS answer is standing at request 1, not an allowance; a refusal puts the owner on spent_providers.json.\n\n"
                             "| when | label | block | owner | acris | richmond courts host | note |\n|---|---|---|---|---|---|---|\n", encoding="utf-8")
    with LEDGER_MD.open("a", encoding="utf-8") as f:
        f.write("| %s | %s | %s | %s %s (%s %s) | %s | %s | %s |\n" % (row["when"], row["label"], row["block"], row["asn"], row["org"],
                                                                   row["city"], row["country"], row["acris"], row["richmond"], row["note"]))


def main():
    ap = argparse.ArgumentParser(description="the survey: one stop of the app, one request per source")
    ap.add_argument("--label", default="", help="the app's location name as shown (for the record)")
    ap.add_argument("--doc", default=DOC, help="the document whose viewer page is the ACRIS request")
    ap.add_argument("--dry", action="store_true", help="the exit and its owner only; nothing asked of either source")
    ap.add_argument("--no-acris", action="store_true")
    ap.add_argument("--no-richmond", action="store_true")
    ap.add_argument("--force", action="store_true", help="ask ACRIS even when the owner is on spent_providers.json (the renewal test, on login's word)")
    ap.add_argument("--proxy", default="", help="a VPS door: socks5h://127.0.0.1:1080 (an ssh -N -D 1080 tunnel); every request of this run goes through it")
    a = ap.parse_args()
    if a.proxy:
        PROXY.update({"http": a.proxy, "https": a.proxy})

    ips = draws()
    blocks = {".".join(ip.split(".")[:3]) for ip in ips if ip.count(".") == 3}
    print("draws :", ", ".join(ips))
    if len(blocks) != 1:
        print("the pool spans %d blocks - the tunnel is mid-switch or split; wait and run again" % len(blocks))
        return 2
    block = blocks.pop()
    asn, org, city, country = owner(ips[0])
    spent = spent_list().get("spent", {})
    standing = "SPENT since %s (%s)" % (spent[asn]["since"], spent[asn]["evidence"][:80]) if asn in spent else "not on the spent list"
    print("block :", block)
    print("owner :", asn, org, "(%s %s)" % (city, country))
    print("list  :", standing)

    row = {"when": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "label": a.label, "kind": "vps" if a.proxy else "vpn", "block": block,
           "asn": asn, "org": org, "city": city, "country": country, "acris": "", "richmond": "", "note": ""}
    if a.dry:
        print("dry: nothing asked of either source, nothing recorded")
        return 0

    if a.no_acris:
        row["acris"] = "not asked"
    elif asn in spent and not a.force:
        row["acris"] = "not asked: owner on the spent list"
        print("acris : not asked - the owner is on spent_providers.json (--force is the renewal test, on login's word)")
    else:
        verdict, detail = ask_acris(a.doc)
        row["acris"] = "%s - %s" % (verdict, detail)
        print("acris :", verdict, "-", detail)
        if verdict == "REFUSED" and asn != "?":
            mark_spent(asn, org, "%s refused the survey's first request (%s) - %s" % (block, row["when"], detail[:100]))
            print("        -> %s put on spent_providers.json" % asn)
        if verdict == "SERVED" and asn in spent and a.force:
            row["note"] = "RENEWAL: a spent owner served again - a person removes it from the list on login's word"
            print("        -> RENEWAL: served on a spent owner; the list is a person's to edit")

    if a.no_richmond:
        row["richmond"] = "not asked"
    else:
        verdict, detail = ask_richmond()
        row["richmond"] = "%s - %s" % (verdict, detail)
        print("courts:", verdict, "-", detail)

    record(row)
    print("recorded -> survey.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
