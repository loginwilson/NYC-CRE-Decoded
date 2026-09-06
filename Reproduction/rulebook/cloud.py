"""THE CLOUD TABLE, FROM A LANE'S POINT OF VIEW - claim, land, heartbeat, and a local outbox.

One connection per crew, used by the lane's main thread - and, one statement at a time under its lock, by the
census's comparing workers.  Every call is one round trip to a function defined in the migrations
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
import threading
import time
import urllib.parse

import psycopg2


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


NUL_ESCAPE = "\\u0000"        # the JSON escape for NUL: PostgreSQL jsonb refuses it ("unsupported Unicode escape sequence")


class Cloud:
    """claim / registries / land / heartbeat for one source, one lane, one workstation."""

    def __init__(self, source, lane, host, app="lane"):
        self.source, self.lane, self.host, self.app = source, lane, host, app
        self.con = None
        self._lock = threading.RLock()        # one statement at a time: a reconnect never races another thread's statement

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
        with self._lock:
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

    def claim(self, n=500, ttl="20 minutes"):
        """The doc_ids now held by this host: pendings whose cooldown has run out first, then empties, both in
        id order (migration 0004: the wait between two checks of a pending is its claim, written by land())."""
        rows = self._run("select reproduction.claim(%s, %s, %s, %s, %s::interval)",
                         (self.source, self.lane, self.host, n, ttl), True)
        return [r[0] for r in rows]

    def registries(self, ids):
        """{doc_id: registry} for the claimed ids (registry is a dict, or 'pending'/'absent', or None)."""
        if not ids:
            return {}
        rows = self._run("select doc_id, registry from reproduction.%s where doc_id = any(%%s)" % self.source,
                         (list(ids),), True)
        return {r[0]: r[1] for r in rows}

    def land(self, rows, pending_age="1 hour"):
        """rows = [{"doc_id": ..., "value": ...}] -> cells written.  The cell rule in the table rejects
        any value that is not a fill, 'pending' or 'absent' (the whole batch, so nothing half-lands).  A landed
        pending keeps its claim as a cooldown for pending_age; claim() offers it again after that (migration 0004)."""
        if not rows:
            return 0
        payload = json.dumps(rows).replace(NUL_ESCAPE, "")   # jsonb cannot hold NUL; a source page's stray NUL is dropped, nothing else
        out = self._run("select reproduction.land(%s, %s, %s, %s::jsonb, %s::interval)",
                        (self.source, self.lane, self.host, payload, pending_age), True)
        return out[0][0]

    def heartbeat(self, width, last_event=None):
        self._run("select reproduction.heartbeat(%s, %s, %s, %s, %s)",
                  (self.source, self.lane, self.host, width, last_event), False)

    def insert_ids(self, ids):
        """synchronization: new document ids into the workflow table - one row per document, nothing
        else filled - and the counters moved in the SAME transaction by exactly the rows that were new:
        needed (the phase and every lane) and synchronization's landed.  Returns the rows inserted."""
        if not ids:
            return 0
        for attempt in (1, 2):
            try:
                if self.con is None or self.con.closed:
                    self.connect()
                self.con.autocommit = False
                try:
                    with self.con.cursor() as cur:
                        cur.execute("insert into reproduction.%s (doc_id) select unnest(%%s::text[]) on conflict (doc_id) do nothing"
                                    % self.source, (list(ids),))
                        n = cur.rowcount
                        if n:
                            cur.execute("update reproduction.%s_update set needed = needed + %%s" % self.source, (n,))
                            cur.execute("update reproduction.%s_update_lanes set needed = needed + %%s" % self.source, (n,))
                            cur.execute("update reproduction.%s_update_lanes set landed = landed + %%s where lane = 'synchronization'"
                                        % self.source, (n,))
                    self.con.commit()
                    return n
                except Exception:
                    self.con.rollback()
                    raise
                finally:
                    if self.con is not None and not self.con.closed:
                        self.con.autocommit = True
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                self.close()
                if attempt == 2:
                    raise
                time.sleep(2)

    # ── reads for the audit: enumeration never writes a cell and has no table ────────────
    def _range(self, lo, hi, after=None):
        parts, params = [], []
        if after is not None:
            parts.append("doc_id > %s")
            params.append(after)
        elif lo is not None:
            parts.append("doc_id >= %s")
            params.append(lo)
        if hi is not None:
            parts.append("doc_id < %s")
            params.append(hi)
        return (" where " + " and ".join(parts)) if parts else "", tuple(params)

    def count(self, lo=None, hi=None):
        """Rows in [lo, hi) of the workflow table (every row when lo is None): a range on the key."""
        where, params = self._range(lo, hi)
        return self._run("select count(*) from reproduction.%s%s" % (self.source, where), params, True)[0][0]

    def ids(self, lo, hi=None, page=50_000):
        """Every doc_id in [lo, hi), keyset-paged on the primary key - a range, never a scan."""
        out, after = set(), None
        while True:
            where, params = self._range(lo, hi, after)
            rows = self._run("select doc_id from reproduction.%s%s order by doc_id limit %%s" % (self.source, where),
                             params + (page,), True)
            out.update(r[0] for r in rows)
            if len(rows) < page:
                return out
            after = rows[-1][0]

    def prefixes(self, lo, hi, n):
        """{prefix: rows} for the n-character id prefixes the table holds in [lo, hi)."""
        where, params = self._range(lo, hi)
        rows = self._run("select left(doc_id, %%s) p, count(*) from reproduction.%s%s group by 1 order by 1"
                         % (self.source, where), (n,) + params, True)
        return {r[0]: r[1] for r in rows}

    def todo(self, ids):
        """The subset of ids whose registry needs work: empty, or pending and not held - no live claim for the
        registration lane, neither another workstation's nor the cooldown land() left after the last check
        (migration 0004).  For a lane whose source grants details only behind its listing (richmond), so the lane
        walks the listing and asks the table which of the ids it passes are its work."""
        if not ids:
            return set()
        rows = self._run("select w.doc_id from reproduction.%s w where w.doc_id = any(%%s) and (w.registry is null or"
                         " (w.registry = '\"pending\"'::jsonb and not exists (select 1 from reproduction.%s_claims c"
                         " where c.doc_id = w.doc_id and c.lane = 'registration' and c.until > now())))" % (self.source, self.source),
                         (list(ids),), True)
        return {r[0] for r in rows}

    def held(self, ids):
        """The subset of ids the table holds."""
        if not ids:
            return set()
        rows = self._run("select doc_id from reproduction.%s where doc_id = any(%%s)" % self.source, (list(ids),), True)
        return {r[0] for r in rows}

    def max_id(self, lo, hi=None):
        where, params = self._range(lo, hi)
        return self._run("select max(doc_id) from reproduction.%s%s" % (self.source, where), params, True)[0][0]

    def alive(self, within="3 minutes"):
        """[(lane, host, width, age_seconds, last_event)] for every lane heard from within the interval."""
        return self._run("select lane, host, width, extract(epoch from now() - heartbeat_at)::int, last_event"
                         " from reproduction.%s_heartbeats where heartbeat_at > now() - %%s::interval order by lane, host"
                         % self.source, (within,), True)


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
        if not self.path.exists():
            return 0
        with self.path.open("rb") as f:
            return sum(1 for line in f if line.strip())

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
