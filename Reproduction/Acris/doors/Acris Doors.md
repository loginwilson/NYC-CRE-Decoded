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

## How ACRIS says no — four ways, three of which look like success

1. **The Bandwidth Notice** — HTTP 200, `text/html`, exactly **25,103 bytes**, or a 307 to `/BandwidthPolicy/ACRIS-BW-POL.html`. The only unambiguous refusal.
2. **Page 1 only** — a refused block is still served page 1 and refused every page after, so it "completes" documents at one page each and scores well on documents-a-second.
3. **The refusal is FAST** — it returns in milliseconds, so a dying door's requests/second goes **UP**. A healthy door is LOW req/s with near-zero failures (the best of the night: 39 req/s, `fail 0`, 239 documents in its first minute).
4. **The end marker** — a 310×320 greyscale TIFF of exactly **13,684 bytes**, ACRIS's end-of-document placeholder, served as a normal page image.

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
