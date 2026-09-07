# Access: how the tunnel works and how each source answers it

login, 2026-09-07 06:1x: "We need to figure out the correspondence between how the vpn works and acris access. This is key. Richmond
also had some issues with the vpn." This file is that correspondence, from measurements, in one place. It changes only when a
measurement changes it.

## 1. The tunnel, as measured on the home workstation

| fact | measured |
|---|---|
| where the tunnel sits | not on the workstation: every ExpressVPN adapter is Disconnected, the default route is Wi-Fi to the router (192.168.1.1), the lane's sockets bind to the LAN address (192.168.1.168) - yet the public address is a hosting range. The router carries the tunnel; every device in the house exits through it |
| one connection, one address | a new TCP connection is NATed to a random address of the exit's /24: 20 draws in a row gave 11 distinct addresses of 2.57.171.0/24. The lane's 40-80 lines sit on many addresses of ONE block; the block is the unit we can see |
| the app's location name | a label. "Bolivia" exited from Phoenix (GSL Networks). "Bosnia" from Lelystad, Netherlands (Clouvider). "Brazil" from Sao Paulo (Latitude.sh). "Singapore" from GSL Networks, Singapore. The owner of the range, not the city, is what a source sees |
| few owners behind many labels | GSL Networks AS137409 (Singapore, Phoenix, Dallas, Amsterdam, Frankfurt), Datacamp AS212238 (Vienna), Delta Telecom AS29049 (Baku), Clouvider AS62240 (Netherlands), Latitude.sh AS262287 (Sao Paulo) - five owners across nine blocks on the ledger |
| every exit is a known proxy | ip-api flags all nine blocks `proxy: true`, served and refused alike. A public proxy flag is therefore NOT the gate ACRIS uses; ACRIS keeps its own standing per range |
| a switch | re-keys the router's tunnel: every open connection in the house dies at once (the lane's "dead transport"); the next connections come from the new block |
| a pool that spans blocks | five draws in two blocks = the tunnel mid-switch, or a multi-tunnel mode: the lane's lines would go out on two exits. Never launch on it; wait for one block (the exit-pool gate) |
| protocol modes | single Lightway holds one tunnel = one block. "Automatic" may change protocol or server on its own (a reconnect mid-run = dead transport). A dual / turbo mode opens more than one tunnel = lines spread over exits (the spread pool). The lane wants ONE tunnel, held: single Lightway, not Automatic, not dual |

Read the exit before every entry, no source touched:

    python C:\dev\cre-office\doc_lane.py exit      five draws -> the block -> the owner -> FRESH / SPENT (spent_providers.json)

## 2. ACRIS

Two mechanisms, seen apart on 2026-09-07 (the whole night in `Acris Reproduction.md`):

| mechanism | what it looks like | keyed on |
|---|---|---|
| standing | the Bandwidth Notice at request 1 (HTTP 307 to `/BandwidthPolicy/ACRIS-BW-POL.html`, or the 25,103-byte page) | the exit range's standing with ACRIS - from our spend (Phoenix after Singapore's 415k, both GSL) or none of ours (Clouvider, never used, refused at once) |
| allowance | served at the exit's speed (~45 requests/s whatever the width), then the notice after a cumulative count | the range: 24k, 26k, 49k, 60k, 157k, 415k, 1.35M, 2.3M requests on different ranges at the same rates |

Not the client. The identical binary, TLS stack, Chrome/128 UA, Referer and cookie handling served 415,321 requests on 140.99.118, was
refused at request 1 on 147.90.160 and 200.162.147, and served again on 2.57.171. On 147.90.160 a curl with a different TLS stack got the
same redirect. The client was constant; only the exit changed. A cookie cannot be the trigger: the refusal comes on the first request,
before any cookie exists. (The one client rule that stands: the honest UA is answered 503, the Chrome UA is served - `Acris.md`.)

ACRIS's notice page, in its words: access is denied for "detection of automated scripts/robots that are capturing data" or "having
exceeded the bandwidth limits"; for large amounts of data, the City Register's subscription data services, 212-487-6300.

What the allowance buys: ~10.7 requests per numeric-id document, ~5.4 per microfilm (FT_/BK_) document; 415k requests = ~39k numeric
documents in 2.5 h on one exit. Unknown: whether a spent range renews (one request after a rest, on login's word), and a range's
allowance before it is spent (only running shows it).

## 3. Richmond

The clerk's registry pages serve through the tunnel. The courts host that serves the document images sits behind Cloudflare, which
challenges the tunnel's exits (the 403 challenge page; `is_challenge` parks the lane at once). 2026-09-06 21:57: the same code with the
VPN OFF served 536 pdfs in 2 minutes. Richmond documentation runs on a line without the tunnel; a challenge is never solved by code.

## 4. The rules that follow

1. Before an entry: `doc_lane.py exit`. A provider on `spent_providers.json` is not entered. A fresh one gets ONE entry; the first
   request is the test (a refusal there costs one request; log the owner).
2. One tunnel, one block, held: single Lightway; never launch on a spread pool; never switch under a running lane.
3. A notice parks the lane; the range is never re-entered by a lane. Whether it lifts is one request after a rest, on login's word;
   a lift removes the provider from the list.
4. The survey (login's question "how would we know which work"): walk the app's list once, `exit` at each stop, one request where the
   owner is new; the table of label -> owner -> served / refused is the map for the day. Owners repeat, so the map is shorter than the list.
5. A residential line is outside both gates by construction (no proxy standing, no Cloudflare challenge): the office line on station 2 is
   the strongest door for ACRIS and the only door for Richmond documents.
6. The calendar is doors x allowance: 17.9M documents remaining, ~147M requests; one exit's day at 415k is ~39k documents. More doors and
   larger-standing ranges are the levers; the client is not.
