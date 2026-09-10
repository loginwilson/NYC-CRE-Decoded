# ACRIS Doors — the rule set

A **door** is a cloud instance we own, used as an exit address. Its worth is the **address**, not the machine:
ACRIS meters access per address block (a /24), so a door is only ever as good as the block it happens to land in.

## THE CYCLE — the whole of it

```
create a door  ->  run the lane on it  ->  it lands documents until ACRIS blocks it  ->  delete it  ->  create another
```

That is the entire law. There is no step between "create" and "run the lane".

**Why there is no gate in between.** Every gate tried on 2026-09-08/09 got the answer wrong in *both* directions:

| gate | what it did |
|---|---|
| 25 pages/s floor | destroyed a door that was landing **8.29 documents a second** |
| 2.0 then 4.0 docs/s floor | **kept refusals** — a refused block answers instantly, so it scores HIGH |
| 2.0 pages-a-document | threw away Hetzner and Vultr doors pulling **real scans at 52 KB a page** |
| the reaper (8-minute fuse) | destroyed **nine live serving doors** at 08:20, because a door being adopted has no ledger row yet |

The lane settles it in about twenty seconds, cannot be fooled, and is the thing we actually want:

```
run end 0.3 min - REFUSED at 2006060800799001 - ACRIS served its Bandwidth Notice (5/5 signals, 25103 bytes)
```

**A door can be blocked without saying so** (2026-09-09). The gate above asks whether the lane landed *any*
documents — binary, zero or not — and a half-dead door passes it easily: ten pdfs beside five hundred `absent`
verdicts reads as alive. That is what ran through the night of 09-09. Nothing failed, nothing was logged as an
error, every counter said the lane was working, and ~70,000 cells were marked absent for documents ACRIS hands over
the moment you ask. The logs that would have named the door had rotated away before the audit found it.

So `lane_landed()` now returns the `absent` count beside the pdf count — both were already on the PROGRESS line the
lane writes every minute, they were simply never read — and a door whose absent share runs far above the corpus is
burned. Across 4,437,404 decisions before the reset, `absent` was **6.0%**. The default fires at **35% over at least
200 decisions**: high enough that a genuine run of imageless documents cannot burn a good door, low enough that the
night's doors would have gone in their first minutes. `--absent-share` and `--absent-min` move it.

This is not a rate gate and does not contradict the law above — a door being served readable pages that say "no
image" for documents that have one **is** blocked, in the one way that costs us the table rather than the clock.
UNTESTED against a live door: it is built from the arithmetic of a night already measured, not from a door watched
burning by it.

So: **a door is deleted when, and only when, it is blocked.** Not when it is slow. Every block has a finite
allowance (~6,000 requests); a fast door and a slow door both end at the same wall, so grading them buys nothing.
Drain the allowance, delete, replace. An underperforming door still beats the empty slot that replaces it.

**AMENDED 2026-09-10 — a sustained slow door is worth replacing after all, and the paragraph above says why it is
not, on an assumption that measurement did not support.** It assumed the wall is a REQUEST count, so that any door
reaches it eventually and only the clock differs. Measured over a full day of ten doors, lifetime is closer to
time-bounded than request-bounded: **median 95 minutes** to the notice, whatever the door's rate. Over that same
95 minutes a New York door landed 1.6 docs/s and a Frankfurt one 0.5 — the fast door yields roughly **double the
documents from the same lifetime**. And "still beats the empty slot" was priced wrong: a replacement costs a
**median of 5 candidates and 2.4 minutes**, which is 2.5% of a door's life, not a meaningful share of it.

So the rule now has a floor as well as a verdict, and the two are different things:
- **BLOCKED → destroy immediately.** Unchanged, and still the only reason to burn a door on the spot.
- **SLOW → replace, on evidence, one at a time.** Under **7 req/s** (login's benchmark) for five consecutive
  readings, past its ten-minute ramp, worst door only.

⚠ **The slow rule needs a fleet-health guard or it eats the fleet.** The whole fleet swings 58-110 req/s minute to
minute and every door moves together — that is ACRIS pacing, not ten doors going bad at once. So the benchmark
applies only while the MEDIAN door clears it; below that we fall back to a relative floor (60% of the median),
which cannot cull everyone. And the cull only fires at full strength, so a swap drops the fleet to nine and no
second swap can start until the hunt has restored ten: the fleet cannot be stripped, whatever the numbers say.

## How ACRIS says no — five ways, four of which look like success

1. **The Bandwidth Notice** — HTTP 200, `text/html`, exactly **25,103 bytes**, or a 307 to `/BandwidthPolicy/ACRIS-BW-POL.html`. The only unambiguous refusal.
2. **Page 1 only** — a refused block is still served page 1 and refused every page after, so it "completes" documents at one page each and scores well on documents-a-second.
3. **The refusal is FAST** — it returns in milliseconds, so a dying door's requests/second goes **UP**. A healthy door is LOW req/s with near-zero failures (the best of the night: 39 req/s, `fail 0`, 239 documents in its first minute).
4. **The end marker** — a 310×320 greyscale TIFF of exactly **13,684 bytes**, ACRIS's end-of-document placeholder, served as a normal page image.
5. **Service Unavailable (C0500100506)** — HTTP 200, exactly **4,961 bytes**, md5 `395dcdb0151838b3c5ec485077cee4ab`,
   reading *"ACRIS ERROR  Service Unavailable. (C0500100506)"*. Found 2026-09-10. It shuts the **detail and viewer
   endpoints while still serving images**, so nothing in the lane's output betrays it: no REFUSED line is written,
   the crew never retires, and req/s stays HIGH because the retries themselves count. A rate floor cannot see it.
   Five of ten doors fell into it inside nine minutes and no detector we had noticed. It is a POSITIVE STATEMENT
   from ACRIS, so it is a verdict — the only way to find it is to **ask the door directly**, one request, and read
   the response signature. And it arrives on MANY DOORS AT ONCE: three of the five sat in adjacent /24s of one
   165.245.x parent and no survivor did, so this refusal is scoped **wider than a /24**.

`DocumentImageView` (the viewer page) is also how ACRIS refuses a cloud block: it 404s while `GetImage` still serves.
RETRACTED 2026-09-09. The answer to that was `--trust-registry-pages` — take the page count from registration, keep
the viewer URL only as a Referer — and measured on one line it looked like a win: **64 documents with the flag, 20
without.** It was landing SHORT PDFS. Registration undercounts (it misses covers and riders), the lane writes exactly
`total` pages or nothing, so the files landed whole and incomplete, and looked complete: 9 of 142 held four pages where
there are seven, three where there are seven, five where there are eleven. 39,360 pdfs were deleted. The flag is gone
from the code and cannot be passed.

**A 404 on the viewer means the door is refused. Destroy the door.** It is not a reason to take the page count from
somewhere else — the viewer is the only authority on how many pages a document has, and a lane that cannot reach it
is a lane that must not write.

## Regions — spread, never walk

A provider is never uniformly refused; a **range** is refused. Every Linode create on 2026-09-09 landed in
`172.104/105` or `172.232-239` and every one was refused, while Linode's single success sat outside that range.
So creates are **shuffled across the whole region list**, and Linode leads with its oldest datacentres
(`us-central`, `us-west`, `us-southeast` — `45.x`, `66.x`, `173.255.x`), not the Akamai-era `172.x` ones.

### Which region is best — PROXIMITY, measured (2026-09-10)

A door's request rate is set by the round trip to ACRIS, so it is a property of the PLACE and it does not change.
Measured across seven regions that produced live doors: **correlation(distance, req/s) = −0.78**. But it is a
**step, not a slope**, and the step is what matters:

| band | regions | req/s |
|---|---|---|
| same metro (< 100 mi) | `nyc1` `nyc2` `nyc3` | **17.7** |
| continental (< 3,000 mi) | `ric1` `tor1` `atl1` `mem1` `mkc1` `sfo2` `sfo3` | 9–10 |
| transatlantic | `lon1` `ams3` `fra1` | 6.1 |
| far | `blr1` `sgp1` `syd1` | 2.9 |

New York is a class of its own at roughly double everything else; from Toronto (342 mi) to San Francisco
(2,566 mi) the rate is flat, so within the continent distance barely matters; an ocean halves it and the Pacific
quarters it. **A region we have never measured inherits its band's average**, so a never-tried New York region is
ranked beside the New York door doing 17.7 req/s instead of being lumped in with Bangalore.

⚠ **The anchor is PER SOURCE.** These distances are to the ACRIS servers in Manhattan. For Richmond's data the
anchor moves to Virginia and the whole ladder re-sorts — `ric1` would lead. Latency generalises to any source;
**access rules do not** (ACRIS 503s an honest user agent where Richmond serves it).

### What to do when the best region is refusing

Acceptance and speed are not the same kind of fact and must not share a rule:

- **ACCEPTANCE is ACRIS's mood.** It turns on a dime. `nyc1` refused **19 times in a row** and then accepted, and the
  door it gave was the fastest in the fleet — then closed again half an hour later. So a region that keeps refusing
  is **RESTED, never written off**: every 10 minutes the least-recently-tried rested region comes back for two
  attempts, and one accept clears it for good. Before this, **35% of a day's hunt attempts (about 76 minutes) went
  to nine regions that had never once let us in**, because a decaying window forgets too fast to tell a region that
  is 0-for-14 from one running at 17%.
- **SPEED IS GEOGRAPHY.** Singapore is ~230 ms away and will be next month too. There is nothing to re-test, so the
  speed floor has **no exploration escape** — a 5% escape there is not exploration, it is a slow door every
  twentieth draw, and it took a slot twice in ten minutes immediately after a Frankfurt door had been burned to
  upgrade it.

And when everything above the floor is refusing, **hold out, then settle**: at a fixed droplet cap the hunt
candidate IS the spare droplet, so an empty slot and an active hunt are the same thing, and holding out forever is
a slot producing nothing. Wait ten minutes for a door that clears the benchmark, then drop the floor a band, then
take whatever serves. What we settle for is under the benchmark by definition, so the ordinary cull replaces it
later — which frees the droplet, restarts the hunt, and re-probes whether the close regions have reopened. **The
churn is the discovery mechanism.**

## The files

| file | what it is |
|---|---|
| `cloud_doors.py` | the manager for Vultr / Linode / Hetzner (`DOORS_PROVIDER=<name>`) |
| `do_doors.py` | the same for DigitalOcean |
| `do_station.py` | the supervisor: keeps N doors, runs a lane on each, burns one the moment it is blocked |
| `night_guard.py` | keeps the four stations and the board up |
| `box_fetch.py` | runs ON the door: one call per document, its pages fetched in parallel on the box |
| `box_lane.py` | the on-box measurement, used by hand |
| `door_tunnel.py` | the keeper — `ssh -N -D` holding the socks tunnel open |
| `night_status.py` | one reading: doors held, what each lane is producing **right now** |
| `spend.py` | what the doors have cost, priced from the provider |

## Two things that are not in git, on purpose

- **Secrets** — `<provider>.env` holds the API tokens. They stay in `C:\dev\cre-office`.
- **State and logs** — ledgers, spent-block lists, station logs. Also `C:\dev\cre-office`.

The code is the repository's; the keys and the running state are the machine's.

## Standing rules

- **Judge a door by DOCUMENTS ON THE DRIVE**, never by requests, pages, HTTP status, content-type, or any lifetime total.
- **Delete means DESTROY at the provider.** Billing stops, tunnel dies, ledger row goes. "Stop using" is not deleting.
- **Hourly billing, never monthly.** Vultr's live figure is the honest one: $1.27 for 30 instances = **$0.0423 each**.
- **Never rapid-hop.** A burned block stays burned for hours; re-entering it spends money to be refused again.
- **Every provider owns a disjoint PORT RANGE and SLOT RANGE, and nothing may drift off them.**
  `cloud_doors.PROVIDERS` assigns the door and probe port bases (DigitalOcean 1080/1100, Vultr 1200/1400,
  Linode 1300/1500) and `do_station._P` assigns the slot base (2, 20, 40, 60). Slots must not overlap because
  every lane's lock, control and log file lives in ONE directory keyed by slot; ports must not overlap because a
  second station's door would bind a port the first is already probing through. ⚠ A tool that hardcodes a base
  instead of reading it from `PROVIDERS` is the failure mode: one did, with probes on 1200 — Vultr's door range —
  and nothing broke while DigitalOcean ran alone, so it would have surfaced only on the first day of mirroring,
  looking like random door corruption rather than a port clash.
- **A lane must not park as a whole because ONE door hit a wall.** The lane's breaker was written when a lane meant
  one door; a lane now runs three or four independent doors, and on 2026-09-10 one bad door parked two lanes and
  left five of seven enrolled doors billing and idle while ACRIS was serving every one of them. Read the door out
  of the wall message, burn THAT door, and bring the lane back — after checking ACRIS still answers through some
  other live door, so a restart never runs into a real outage.
