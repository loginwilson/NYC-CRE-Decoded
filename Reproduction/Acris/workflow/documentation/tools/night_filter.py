"""Night monitor filter for the acris document lane log.

Reads the tailed log on stdin. Emits (to stdout, one line = one event):
  - every PROGRESS line whose minute is a multiple of 60 (the hourly heartbeat)
  - any refusal / stop / dead-transport / traceback / fail-burst line at once
Everything else is swallowed. Silence for over an hour therefore means the
heartbeat is missing, which is itself the signal to go and look.
"""
import re
import sys

# Genuine stops only. A fail-count warning is noise the lane rides through by
# design (login 2026-09-03: "you are just lost" - never act on a fail spike).
ALARM = re.compile(r"REFUSED at|Bandwidth Notice|STOPPING ALL|DEAD TRANSPORT|SELF-PARKED|Traceback")
PROG = re.compile(r"PROGRESS (\d+)m ")

for line in sys.stdin:
    line = line.rstrip("\r\n")
    if not line or line.startswith("==>"):
        continue
    m = PROG.search(line)
    if m:
        minute = int(m.group(1))
        if minute % 60 == 0:
            print(line[:220], flush=True)
        continue
    if ALARM.search(line):
        print(line[:220], flush=True)
