"""THE RATE MANAGER - login 2026-09-04: "rate manager adds a worker every 5 seconds to reach sustained rate preference and
then adjusts based on rate ... i like ramp until rate is met and then adjust."  The band (login 19:5x): "5 is the lower, 7 is
the higher, and between 6-7 is ideal ... try not going over 7 ... try not going below 5"; the hard line stays 8.

Two knobs, nothing else:
  * WIDTH follows the measured docs/s (the PROGRESS line's own "repro": pdf + pending + imageless landings per second over
    the window).  A GRADUATED hand around the band:
        dps > 8      : over the hard line - retire a FULL step at once
        7 < dps <= 8 : above the band - retire HALF a step
        6 <= dps <= 7: the ideal - HOLD
        5 <= dps < 6 : below the ideal - grow HALF a step, gently, toward the middle of the band
        dps < 5      : below the floor - grow a FULL step, toward the middle of the band
    Every grow births workers --stagger apart (the ramp's shape, never a burst) and never overshoots the width that would
    reach the band's middle; every shrink retires workers that each finish their document and leave.  One decision per
    window, clamped to [width_min, width_max].  The width is the manager's INSTRUMENT, not a rule (login).
  * THE DOOR CURVE (the record, 2026-08-2x: "requests FLAT from 28 to 112 connections: doors/workers buy NOTHING"; seen
    again 2026-09-04 20:2x when 100 -> 110 -> 120 lines took docs/s from 6.8 to 4.0 on the Tirana exit): after a grow the
    manager WAITS `knee_windows` windows at the new width and compares the mean docs/s with the mean at the old width; if
    the grow bought less than `knee_gain`, it steps BACK to the old width and holds there `knee_hold` windows before it
    will try growing again.  No stacked grows while a grow is being judged; retires are always allowed.
  * SESSION RESET on the request count lives in the lane (a request cap) with the batch manager checking from outside.

Pure arithmetic in next_width() so it can be proven offline; the Governor thread only calls it and the two callbacks.
"""
import math
import threading
import time

EPS = 1e-9


def _grow(dps, width, aim, wmin, wmax, step):
    """Grow by up to `step`, toward the width that would put dps at `aim`, never overshooting it."""
    per_worker = dps / width if width and dps > 0 else 0.0
    want = int(math.ceil(aim / per_worker)) if per_worker > 0 else width + step
    return max(wmin, min(wmax, width + step, max(width + 1, want)))


def next_width(dps, width, floor, ideal_lo, ideal_hi, hard, wmin, wmax, step):
    """The one decision.  dps = landings per second over the last window.  Returns the new width (== width means hold).
    floor=5, ideal 6..7, hard=8 (login's band)."""
    aim = (ideal_lo + ideal_hi) / 2.0                       # grow toward the middle of the ideal band (6.5)
    half = max(1, math.ceil(step / 2))
    if width < wmin:
        return min(wmax, wmin)
    if dps > hard + EPS:                                    # over the hard line: a full step down, at once
        return max(wmin, width - step)
    if dps > ideal_hi + EPS:                                # above the band (7..8): half a step down
        return max(wmin, width - half)
    if dps < floor - EPS:                                   # below the floor (<5): a full step up
        return _grow(dps, width, aim, wmin, wmax, step)
    if dps < ideal_lo - EPS:                                # below the ideal (5..6): half a step up, gently
        return _grow(dps, width, aim, wmin, wmax, half)
    return width                                            # inside the ideal band (6..7): hold


class Governor(threading.Thread):
    """Every `every` seconds: read the landings counter, compute dps over the window, decide, act.
    spawn(n) births n workers (the caller staggers them); retire(n) asks n workers to finish and leave.
    landings() returns the running total (pdf + pending + imageless); alive() returns the live worker count."""

    def __init__(self, landings, alive, spawn, retire, stop, log, *, floor=5.0, ideal_lo=6.0, ideal_hi=7.0, hard=8.0,
                 lo=20, hi=120, step=10, every=120, settle=240, knee_windows=2, knee_hold=5, knee_gain=0.15,
                 requests=None, rps_ceiling=0.0, ramp=False, stagger=5.0, ramp_window=60.0):
        super().__init__(daemon=True, name="rate-manager")
        self.landings, self.alive, self.spawn, self.retire = landings, alive, spawn, retire
        self.stop, self.log = stop, log
        self.floor, self.ideal_lo, self.ideal_hi, self.hard = floor, ideal_lo, ideal_hi, hard
        self.lo, self.hi, self.step, self.every, self.settle = lo, hi, step, every, settle
        self.knee_windows, self.knee_hold, self.knee_gain = knee_windows, knee_hold, knee_gain
        # RAMP UNTIL THE RATE IS MET (login 2026-09-04: "rate manager adds a worker every 5 seconds to reach sustained rate
        # preference and then adjusts based on rate ... i like ramp until rate is met and then adjust ... instead of hard setting
        # it"): with ramp=True the lane enters with ONE worker and the manager births one more every `stagger` seconds while
        # the docs/s over the last `ramp_window` seconds sits under ideal_lo and the request rate under 90% of the ceiling;
        # the ramp ends when the rate is met (or width_max), and the windows begin after `settle`.  No starting width to guess.
        self.ramp, self.stagger, self.ramp_window = ramp, stagger, ramp_window
        # THE REQUEST CEILING (the record's meter): docs/s is login's band, but the notices came at 58-81 REQUESTS/s held for
        # hours (the golden day ran ~57), and a stretch of small documents can hold 6 docs/s at a low request rate while a
        # stretch of long ones can push 6 docs/s past 80 requests/s.  requests() returns the lane's running request count;
        # a window above rps_ceiling retires half a step and forbids a grow, whatever the docs/s.  0 = off.
        self.requests, self.rps_ceiling = requests, rps_ceiling
        self.decisions = []          # (dps, width, new) per window
        self.hist = []               # (width, dps) per window, newest last
        self.pending = None          # a grow being judged: {"from": w0, "to": w1, "before": mean dps at w0}
        self.hold_left = 0           # windows left to refuse grows after a knee
        self.knee_hold_now = knee_hold   # the next knee's hold: doubles per repeat (cap 8x), back to the base when a grow buys
        self.per_line_hist = []      # requests/s per line, last three windows: the cap reads the exit's recent speed, not a stall

    def _mean_at(self, width, n):
        xs = [d for w, d in reversed(self.hist) if abs(w - width) <= 2][:n]
        return (sum(xs) / len(xs)) if xs else None

    def _ramp(self):
        """One worker every `stagger` seconds until the docs/s over the last `ramp_window` seconds reaches ideal_lo (or
        width_max, or the request rate nears the ceiling).  The lane enters with one worker already born."""
        t0 = time.time()
        samples = [(t0, self.landings(), self.requests() if self.requests else 0, max(1, self.alive()))]
        births = 0
        while not self.stop.wait(self.stagger):
            now = time.time()
            width = self.alive()
            samples.append((now, self.landings(), self.requests() if self.requests else 0, max(1, width)))
            while len(samples) > 2 and now - samples[0][0] > self.ramp_window:
                samples.pop(0)
            (t_a, l_a, r_a, _), (t_b, l_b, r_b, _) = samples[0], samples[-1]
            span = max(0.01, t_b - t_a)
            # the window's rates describe its AVERAGE width; project them to the width standing now, or the ramp overshoots by
            # half a window of births (live 2026-09-04: done at 66 on 54 requests/s, the first windows then read 58-60 and retired)
            w_avg = sum(s[3] for s in samples) / len(samples)
            scale = max(1, width) / max(1.0, w_avg)
            dps, rps = (l_b - l_a) / span * scale, (r_b - r_a) / span * scale
            warm = now - t0 >= self.ramp_window                  # the rate means something only once a full window has passed
            if width >= self.hi:
                why = "width_max %d reached" % self.hi
            elif warm and dps >= self.ideal_lo - EPS:
                why = "the rate is met"
            elif self.rps_ceiling and warm and rps >= 0.9 * self.rps_ceiling:
                why = "the request rate is within 10%% of the ceiling %.0f/s" % self.rps_ceiling
            else:
                self.spawn(1)
                births += 1
                if births % 10 == 0:
                    self.log("RAMP: %d workers - %.2f docs/s, %.1f requests/s over the last %.0fs - adding one every %.0fs until %.1f docs/s"
                             % (self.alive(), dps, rps, min(self.ramp_window, now - t0), self.stagger, self.ideal_lo))
                continue
            self.log("RAMP DONE at %d workers after %.0fs: %s (%.2f docs/s, %.1f requests/s over the last %.0fs, read at this width) - the rate manager's"
                     " first window in %ds" % (width, now - t0, why, dps, rps, min(self.ramp_window, now - t0), self.settle + self.every))
            return

    def run(self):
        if self.ramp:
            self._ramp()
        # the first window starts only after the ramp has settled (a half-born width reads as a slow one)
        if self.stop.wait(self.settle):
            return
        last, t_last = self.landings(), time.time()
        last_req = self.requests() if self.requests else 0
        while not self.stop.wait(self.every):
            try:
                now, n = time.time(), self.landings()
                dps = (n - last) / max(0.01, now - t_last)
                rps = 0.0
                if self.requests:
                    r = self.requests()
                    rps = (r - last_req) / max(0.01, now - t_last)
                    last_req = r
                last, t_last = n, now
                width = self.alive()
                self.hist.append((width, dps))
                if len(self.hist) > 60:
                    cut = len(self.hist) - 60
                    del self.hist[:cut]
                    if self.pending is not None:
                        self.pending["since"] = max(0, self.pending.get("since", 0) - cut)
                band = "floor %.1f, ideal %.1f-%.1f, ceiling %.1f" % (self.floor, self.ideal_lo, self.ideal_hi, self.hard)
                new = next_width(dps, width, self.floor, self.ideal_lo, self.ideal_hi, self.hard, self.lo, self.hi, self.step)
                # A SLOWING EXIT IS NOT A LACK OF LINES (00:0x): a grow is decided on the mean of the last two windows, a retire on
                # this one (fast on the safety side, slow on the grow side); a slow window pulls the mean down but not to a full step
                dps_smooth = (dps + self.hist[-2][1]) / 2.0 if len(self.hist) >= 2 else dps
                if new > width:
                    new = max(width, next_width(dps_smooth, width, self.floor, self.ideal_lo, self.ideal_hi, self.hard, self.lo, self.hi, self.step))
                per_line = (rps / width) if (width > 0 and rps > EPS) else 0.0
                self.per_line_hist.append(per_line); del self.per_line_hist[:-3]
                per_line_ref = max(self.per_line_hist)          # the exit's recent speed: a stalled window never raises the cap

                # THE REQUEST CEILING comes first, as a PROJECTION (22:4x): this window's requests per line say how many lines
                # put the request rate at 95% of the ceiling - the cap.  Over the ceiling: retire straight to the cap.  A grow the
                # docs band asks for never passes the cap; a move under 3 lines is a hold.  (Before this the manager stepped 5-10
                # lines up on the docs band and 5 back on the ceiling every few windows - two rules fighting, never a hold.)
                cap = None
                if self.rps_ceiling and per_line_ref > EPS:
                    cap = max(self.lo, min(self.hi, int(0.95 * self.rps_ceiling / per_line_ref)))
                if cap is not None and rps > self.rps_ceiling + EPS:
                    new = max(self.lo, min(cap, width - 1))
                    self.pending = None
                    self.decisions.append((round(dps, 2), width, new))
                    if new < width:
                        self.log("RATE MANAGER: %.1f requests/s over the request ceiling %.0f (%.2f docs/s with %d workers) -> RETIRE %d to %d, each"
                                 " after its document - %.2f requests/s per line puts 95%% of the ceiling at %d lines; the record's meter: 58-81"
                                 " requests/s held for hours drew the notices" % (rps, self.rps_ceiling, dps, width, width - new, new, rps / width, cap))
                        self.retire(width - new)
                    else:
                        self.log("RATE MANAGER: %.1f requests/s over the request ceiling %.0f with %d workers - at width_min %d, holding"
                                 % (rps, self.rps_ceiling, width, self.lo))
                    continue
                if cap is not None and new > width:
                    if cap - width < max(3, width // 20):     # a move under 3 lines (5% past 60 lines) is a hold, not a dither
                        self.decisions.append((round(dps, 2), width, width))
                        self.log("RATE MANAGER: %.2f docs/s (two-window mean %.2f) with %d workers asks for more lines, but %.1f requests/s (%.2f per"
                                 " line at the exit's recent speed) puts 95%% of the ceiling %.0f at %d lines - holding"
                                 % (dps, dps_smooth, width, rps, per_line_ref, self.rps_ceiling, cap))
                        continue
                    new = min(new, cap)              # the docs band's grow, no further than the cap

                # THE DOOR CURVE: judge the last grow before allowing another
                if self.pending is not None and abs(width - self.pending["to"]) <= 2:
                    fresh = self.hist[self.pending.get("since", 0):]                 # only the windows since the grow, never an earlier visit
                    seen = [d for w, d in reversed(fresh) if abs(w - self.pending["to"]) <= 2][:self.knee_windows]
                    if len(seen) >= self.knee_windows:
                        after, before, w0 = sum(seen) / len(seen), self.pending["before"], self.pending["from"]
                        self.pending = None
                        if after < before + self.knee_gain:
                            self.hold_left = self.knee_hold_now
                            self.decisions.append((round(dps, 2), width, w0))
                            self.log("RATE MANAGER: growing %d -> %d bought nothing (%.2f -> %.2f docs/s over %d windows): the door curve"
                                     " - back to %d and holding there %d windows" % (w0, width, before, after, self.knee_windows, w0, self.hold_left))
                            self.knee_hold_now = min(self.knee_hold_now * 2, 8 * self.knee_hold)    # each repeat holds twice as long
                            self.retire(width - w0)
                            continue
                        self.knee_hold_now = self.knee_hold      # the grow bought documents: the next knee starts from the base hold
                    elif new > width:
                        self.decisions.append((round(dps, 2), width, width))
                        self.log("RATE MANAGER: %.2f docs/s with %d workers - judging the last grow (%d -> %d), no further grow yet"
                                 % (dps, width, self.pending["from"], self.pending["to"]))
                        continue
                elif self.pending is not None:
                    self.pending = None                     # the width moved away from the judged grow (a cut, a retire): drop the judgment

                if new > width and self.hold_left > 0:
                    self.hold_left -= 1
                    self.decisions.append((round(dps, 2), width, width))
                    self.log("RATE MANAGER: %.2f docs/s with %d workers - below the band, but more lines bought nothing here (the door curve)"
                             " - holding at %d, %d windows before trying again" % (dps, width, width, self.hold_left))
                    continue
                if new > width and width >= self.hi:
                    self.decisions.append((round(dps, 2), width, width))
                    self.log("RATE MANAGER: %.2f docs/s with %d workers - below the band but at width_max %d - holding" % (dps, width, self.hi))
                    continue

                self.decisions.append((round(dps, 2), width, new))
                if new > width:
                    before = self._mean_at(width, self.knee_windows)
                    self.pending = {"from": width, "to": new, "before": before if before is not None else dps, "since": len(self.hist)}
                    self.log("RATE MANAGER: %.2f docs/s (two-window mean %.2f) with %d workers (%s) -> GROW to %d, births staggered" % (dps, dps_smooth, width, band, new))
                    self.spawn(new - width)
                elif new < width:
                    self.pending = None
                    self.log("RATE MANAGER: %.2f docs/s with %d workers (%s) -> RETIRE %d, each after its document" % (dps, width, band, width - new))
                    self.retire(width - new)
                else:
                    self.log("RATE MANAGER: %.2f docs/s with %d workers - in the band, holding" % (dps, width))
            except Exception as e:                          # one bad window must never stop the manager deciding
                self.log("RATE MANAGER: error in this window (%s: %.120s) - still deciding next window" % (type(e).__name__, e))


def session_over(t0, max_min, now=None):
    """True once the session has run --session-max-min minutes (0 = never)."""
    if not max_min:
        return False
    return ((now or time.time()) - t0) >= max_min * 60
