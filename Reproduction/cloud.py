"""THE CLOUD TABLE, FROM A LANE'S POINT OF VIEW - claim, land, heartbeat, and a local outbox.

One connection per lane process, used by the lane's main thread only: workers never touch the
database.  Every call is one round trip to a function defined in the migrations
(reproduction.claim / land / heartbeat), so the cooperation rules live in the database and every
workstation gets them by construction.

Credentials: C:/dev/nyc-cre-decoded.env at home, ~/nyc-cre-decoded.env on a Mac, or the path in
NYC_CRE_DECODED_ENV.  Nothing here prints a credential.
"""
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse

import psycopg2
import psycopg2.extras


def env_path():
    p = os.environ.get("NYC_CRE_DECODED_ENV")
    if p:
        return p
    return "C:/dev/nyc-cre-decoded.env" if sys.platform == "win32" else os.path.expanduser("~/nyc-cre-decoded.env")


def env():
    v = {}
    try:
        for line in open(env_path(), encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, val = line.split("=", 1)
                v[k.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        raise SystemExit("no env file at %s - it needs SUPABASE_DB_URL and SUPABASE_DB_PASSWORD" % env_path())
    if not v.get("SUPABASE_DB_URL"):
        raise SystemExit("SUPABASE_DB_URL missing in %s" % env_path())
    return v


def dsn():
    """The session-pooler URI with the password from SUPABASE_DB_PASSWORD, percent-encoded."""
    v = env()
    m = re.match(r"^(postgres(?:ql)?://)([^:@/]+)(?::(.*))?@([^@]+)$", v["SUPABASE_DB_URL"], re.S)
    if not m:
        raise SystemExit("SUPABASE_DB_URL does not look like postgresql://user:password@host:port/db")
    scheme, user, pw, rest = m.groups()
    pw = v.get("SUPABASE_DB_PASSWORD") or pw or ""
    if not pw or "YOUR-PASSWORD" in pw:
        raise SystemExit("database password missing - add SUPABASE_DB_PASSWORD=<password> to %s" % env_path())
    url = "%s%s:%s@%s" % (scheme, user, urllib.parse.quote(pw, safe=""), rest)
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


class Cloud:
    """claim / registries / land / heartbeat for one source, one lane, one workstation."""

    def __init__(self, source, lane, host, app="lane"):
        self.source, self.lane, self.host, self.app = source, lane, host, app
        self.con = None

    def connect(self):
        self.close()
        self.con = psycopg2.connect(dsn(), connect_timeout=30, application_name=self.app,
                                    keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)
        self.con.autocommit = True
        return self.con

    def close(self):
        if self.con is not None:
            try:
                self.con.close()
            except Exception:
                pass
            self.con = None

    def _run(self, sql, params, fetch):
        """One statement, with one reconnect on a dropped connection.  Raises on a second failure so
        the caller can keep the work local (outbox) and try again later."""
        for attempt in (1, 2):
            try:
                if self.con is None or self.con.closed:
                    self.connect()
                with self.con.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchall() if fetch else None
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                self.close()
                if attempt == 2:
                    raise
                time.sleep(2)

    def claim(self, n=500, ttl="20 minutes", pending_age="1 day"):
        rows = self._run("select reproduction.claim(%s, %s, %s, %s, %s::interval, %s::interval)",
                         (self.source, self.lane, self.host, n, ttl, pending_age), True)
        return [r[0] for r in rows]

    def registries(self, ids):
        """{doc_id: registry} for the claimed ids (registry is a dict, or 'pending'/'absent', or None)."""
        if not ids:
            return {}
        rows = self._run("select doc_id, registry from reproduction.%s where doc_id = any(%%s)" % self.source,
                         (list(ids),), True)
        return {r[0]: r[1] for r in rows}

    def land(self, rows):
        """rows = [{"doc_id": ..., "value": ...}] -> cells written.  The cell rule in the table rejects
        any value that is not a fill, 'pending' or 'absent' (the whole batch, so nothing half-lands)."""
        if not rows:
            return 0
        out = self._run("select reproduction.land(%s, %s, %s, %s::jsonb)",
                        (self.source, self.lane, self.host, json.dumps(rows)), True)
        return out[0][0]

    def heartbeat(self, width, last_event=None):
        self._run("select reproduction.heartbeat(%s, %s, %s, %s, %s)",
                  (self.source, self.lane, self.host, width, last_event), False)


class Outbox:
    """Landings that could not reach the cloud yet, one JSON object per line.  Append first, land
    second, drop what landed: a cloud hiccup never loses a fetched document's path."""

    def __init__(self, path):
        self.path = pathlib.Path(path)

    def append(self, rows):
        with self.path.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")

    def load(self):
        if not self.path.exists():
            return []
        rows, seen = [], set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r["doc_id"] in seen:          # a later line for the same id wins
                rows = [x for x in rows if x["doc_id"] != r["doc_id"]]
            seen.add(r["doc_id"])
            rows.append(r)
        return rows

    def count(self):
        return len(self.load())

    def drain(self, land, chunk=500):
        """Land everything held, in chunks; keep whatever the cloud did not take.  Returns (landed, left)."""
        rows = self.load()
        landed = 0
        left = []
        i = 0
        while i < len(rows):
            part = rows[i:i + chunk]
            try:
                land(part)
                landed += len(part)
            except Exception:
                left.extend(rows[i:])
                break
            i += chunk
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in left:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        os.replace(tmp, self.path)
        return landed, len(left)
