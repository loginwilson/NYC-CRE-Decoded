# ACRIS documentation lane — RUNBOOK (2026-09-03)

The lane is one process: `acris_reproduction.py --floor document --sync-workers 0 --rd-workers 0 --pdf-workers 40 --every 3600 --hi 2014`, run from the decoder directory. Everything around it is in `reproduction/acris/doc_lane.py`, which is the procedure as code. Authority for the rules and their history: `ACRIS REPRODUCTION.md` §17 and THE BLOCK LEDGER (on the D: drive; copy under `docs/acris/`).

## One command

```
python doc_lane.py status                 what is running, last minute, sockets, park, board row
python doc_lane.py checks                 pre-launch checks only
python doc_lane.py launch [label]         checks -> clear the lane's own park -> rotate log -> 1x40 via WMI -> helpers -> minute 1
python doc_lane.py stop --reason "..."    a person's stop: park entry first, supervisor second, lane last
```

Expected minute 1 of a clean launch: ~4,000 requests, 250–400 PDFs, fail ≤ 2, 4–7 docs/s, 40 ESTABLISHED sockets to 157.188.15.133 and no TIME_WAIT churn.

## The shape

One entry = one pooled session. One connection per worker at birth, staggered over ~20 s. Keep-alive after; zero further handshakes. Never a fresh-handshake burst test ("40x5 blocks"). The lane has no IP of its own: ExpressVPN hands each new connection a different exit from a pool, so "the current IP" is one draw. Launch only when five draws sit in one /24 block; a pool spanning blocks means the VPN app is mid-switch.

## Two failure kinds

**Block** = HTTP 200 + the Bandwidth Notice page. Nothing else is a block. A redial right after a notice is refused within six requests; the notice lifts on its own clock (33 minutes to 5 hours seen). Do not redial into it.

**Hang-up** = the far side closes all 40 keep-alive lines within one minute (ESTABLISHED → CLOSE_WAIT in one tick), the same process's redials fail with SSLError for ~6 minutes, the lane's dead-transport breaker stops it. A fresh process is served at once. The supervisor redials: wifi down waits, lane down with wire up relaunches up to three times per incident, then parks with the reason. Hang-ups began with the ExpressVPN 14 / Lightway upgrade on 2026-09-03; their timing is not the run's age (a prediction to that effect was refuted at 14:07).

## Standing rules

- Never kill the lane on a fail count. Its own detectors decide (notice page → self-park; dead transport → stop).
- Never edit running code. Edit at a stop, keep a `.bak`, `py_compile`.
- Launch via WMI so the process survives a Claude session restart.
- A multi-GB WAL on the navigation DB is drained before a launch (a lane launched onto it freezes at its first commit).
- A person's park entry in `_paused_runtime.json` is never touched by code. Only the lane's own `REFUSED at …` / `supervisor …` entries are cleared by `launch`.
- The board (`board_truth.py --loop --every 60`, `routine_update.py --loop`) always runs beside a lane; `launch` ensures it.

## Helpers

- `night_supervisor.py` — the redial policy above; log `night_supervisor.log` in the decoder dir.
- `block_watch.py` — per-minute record: lane counters, sockets to ACRIS by state and pid, processes born, exit draw and scheduled-task runs every 10 minutes, a SNAPSHOT at every stop; log `block_watch.log` in the decoder dir.
- `tools/exit_draws.py` — five fresh draws, STABLE/MOVING by block.
- `tools/tls_contrast.py` — neutral hosts vs ONE ACRIS request with full error text (the most a diagnostic may spend on ACRIS).
- `tools/block_ledger.py [--write]` — regenerates the block ledger from every lane log on disk.
- `tools/board_row.py` — the board's acris documentation row and anchor.
- `tools/night_filter.py` — the Monitor filter (hourly heartbeat + genuine stops only).
- `tools/conc_test.py` — pooled-shape concurrency test; never a fresh-handshake loop.
