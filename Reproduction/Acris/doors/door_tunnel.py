# -*- coding: utf-8 -*-
"""door_tunnel.py - keep one door open: an `ssh -N -D <port>` SOCKS tunnel to a rented address, restarted whenever it drops
(a wifi blip, the VPN app reconnecting, the droplet rebooting).  A tool outside the repo (C:/dev/cre-office), one per door.

    python door_tunnel.py --port 1080 --host root@159.223.139.255 [--key C:/Users/smile/.ssh/door_ed25519]

The lane reaches the door as socks5h://127.0.0.1:<port> (--door).  The private key never leaves this machine.  ssh's own
keep-alive (ServerAliveInterval 30, CountMax 3) ends a dead session inside ~90 s; this loop then waits 10 s and dials again,
logging every start and end with a timestamp to door<port>.tunnel.log beside this file.  Stop it by killing this process
(the ssh child is killed with it)."""
import argparse, atexit, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--host", required=True, help="user@address of the rented machine")
ap.add_argument("--key", default=os.path.expanduser("~/.ssh/door_ed25519"))
ap.add_argument("--ssh", default=r"C:\dev\cre-office\ssh\ssh.exe",       # a copy of System32\OpenSSH: the VPN's split-tunnel
                help="the ssh client; the copy outside System32 is the one the split-tunnel bypass rule names (09-08)")
a = ap.parse_args()
log_path = os.path.join(HERE, "door%d.tunnel.log" % a.port)
child = None


def log(msg):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))


def cleanup():
    if child is not None and child.poll() is None:
        child.kill()
        log("keeper stopping: ssh pid %d killed" % child.pid)


atexit.register(cleanup)
cmd = [a.ssh, "-i", a.key, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-o", "GlobalKnownHostsFile=NUL", "-o", "ExitOnForwardFailure=yes",
       "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=20",
       "-N", "-D", "127.0.0.1:%d" % a.port, a.host]
log("keeper up: pid %d, door 127.0.0.1:%d -> %s" % (os.getpid(), a.port, a.host))
n = 0
fast = 0                       # ssh sessions in a row that died inside 15 s (a destroyed droplet, a dead line)
NOWIN = 0x08000000             # CREATE_NO_WINDOW - 09-08 13:06: this keeper runs detached (no console), so every ssh it
                               # started without this flag opened a NEW console window on login's screen; two burnt
                               # droplets' keepers redialing every 10 s = "multiple pop-ups every second"
while True:
    n += 1
    t0 = time.time()
    with open(os.path.join(HERE, "door%d.ssh.err" % a.port), "a", encoding="utf-8") as err:
        child = subprocess.Popen(cmd, stdout=err, stderr=err, stdin=subprocess.DEVNULL, creationflags=NOWIN)
        log("ssh #%d started, pid %d" % (n, child.pid))
        rc = child.wait()
    up = time.time() - t0
    fast = fast + 1 if up < 15 else 0
    wait = min(300, 10 * (2 ** min(fast, 5)))          # 10, 20, 40, 80, 160, 300 s: a dead door is redialed ever more slowly
    log("ssh #%d ended after %.0f s, exit %s - redial in %d s%s" % (n, up, rc, wait, " (%d fast deaths in a row)" % fast if fast else ""))
    time.sleep(wait)
