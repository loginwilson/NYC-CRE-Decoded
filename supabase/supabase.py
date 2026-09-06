"""THE DATABASE - one Supabase project for the whole process, reached from here.

One project; one schema per phase (`reproduction` today, `construction` and `production` when those phases open); one
table prefix per source; one cell per lane.  The database never computes the process: the workers on the workstations
fill it and the boards read it.  Each phase defines its own schema as numbered SQL files in that phase's rulebook
(`<Phase>/rulebook/schema/<version>_<name>.sql` - one file per dictated decision, applied once, never edited after);
this program applies them and keeps the record of which are applied in the project's own ledger
(`supabase_migrations.schema_migrations`, the table the Supabase CLI writes too, so either tool agrees).

    python supabase.py check               the server, the schemas and their tables, every SQL file on disk against the ledger
    python supabase.py push --dry          list the files not yet applied, in version order; run nothing
    python supabase.py push                apply them, one transaction per file (the file, then its ledger row); stop at the first failure.
                                           A file whose first line says `-- statement by statement` runs each statement on its own
                                           (autocommit) - for index builds, which must not be one transaction on a small instance,
                                           and for CREATE INDEX CONCURRENTLY; such a file must be re-runnable (if not exists / or replace)
    python supabase.py sql -c "select 1"   one statement, or several separated by ;
    python supabase.py sql -f file.sql     a script, as one transaction
    python supabase.py sql ... --dry       print only

Credentials: the env file - `C:/dev/nyc-cre-decoded.env` at home, `~/nyc-cre-decoded.env` on a Mac, or the path in
NYC_CRE_DECODED_ENV - holding SUPABASE_DB_URL (Connect > Session pooler > URI) and SUPABASE_DB_PASSWORD.  Nothing here
prints a credential.  Every `sql` run is appended to `supabase.log` beside this file (kept out of git by `*.log`) so the
schema has a written history of every hand statement that touched it; `push` needs no log - the ledger is its record.
"""
import argparse, datetime, os, pathlib, re, sys, urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent                                   # rulebook -> the repo: the phases are its capitalized folders
LOG = HERE / "supabase.log"
LEDGER = "supabase_migrations.schema_migrations"
FILE = re.compile(r"^(\d{14})_(.+)\.sql$")


# ── the connection ────────────────────────────────────────────────────────────────────────────────────────────────────

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
        raise SystemExit("SUPABASE_DB_URL missing in %s (Connect > Session pooler > URI)" % env_path())
    return v


def dsn():
    """The session-pooler URI with the password taken from SUPABASE_DB_PASSWORD (so nobody edits inside a long
    string), percent-encoded so symbols still parse, TLS required."""
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


def connect(app="supabase.py"):
    import psycopg2
    con = psycopg2.connect(dsn(), connect_timeout=30, application_name=app,
                           keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
    con.autocommit = False
    with con.cursor() as cur:
        cur.execute("set statement_timeout = 0")    # the project's default is two minutes on the postgres role; a migration over the populated table needs more
    con.commit()
    return con


# ── the schema files and the ledger ───────────────────────────────────────────────────────────────────────────────────

def phases():
    """The phases that define a schema: the root's folders holding rulebook/schema/, alphabetical."""
    return sorted(p for p in ROOT.iterdir() if p.is_dir() and (p / "rulebook" / "schema").is_dir())


def sql_files():
    """Every phase's SQL files as (version, name, phase, path), in version order across the phases."""
    out = []
    for ph in phases():
        for f in sorted((ph / "rulebook" / "schema").iterdir()):
            if not f.is_file() or f.suffix != ".sql":
                continue
            m = FILE.match(f.name)
            if not m:
                raise SystemExit("%s: a schema file is named <14-digit version>_<name>.sql" % f)
            out.append((m.group(1), m.group(2), ph.name, f))
    out.sort()
    versions = [v for v, _, _, _ in out]
    dup = sorted({v for v in versions if versions.count(v) > 1})
    if dup:
        raise SystemExit("two schema files share a version: %s" % ", ".join(dup))
    return out


def ledger(cur):
    """{version: name} of what the project has applied, or None when the ledger does not exist yet."""
    cur.execute("select to_regclass(%s) is not null", (LEDGER,))
    if not cur.fetchone()[0]:
        return None
    cur.execute("select version, name from %s order by version" % LEDGER)
    return {v: n for v, n in cur.fetchall()}


def show(cur, limit=200):
    if cur.description is None:
        print("  ok - %s" % cur.statusmessage)
        return
    cols = [d[0] for d in cur.description]
    rows = cur.fetchmany(limit)
    widths = [max(len(c), *(len(str(r[i])) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
    print("  " + " | ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  " + "-+-".join("-" * w for w in widths))
    for r in rows:
        print("  " + " | ".join(str(x).ljust(w) for x, w in zip(r, widths)))
    more = cur.fetchmany(1)
    print("  (%d row%s%s)" % (len(rows), "" if len(rows) == 1 else "s", ", more not shown" if more else ""))


SCHEMAS = """
select n.nspname as schema,
       count(c.oid) filter (where c.relkind in ('r','p')) as tables,
       count(c.oid) filter (where c.relkind = 'v') as views,
       count(c.oid) filter (where c.relkind = 'm') as matviews
from pg_namespace n
left join pg_class c on c.relnamespace = n.oid
where n.nspname not like 'pg#_%' escape '#' and n.nspname not in ('information_schema')
group by n.nspname order by n.nspname;
"""
TABLES = """
select table_schema as schema, table_name as name, table_type as type
from information_schema.tables
where table_schema not in ('pg_catalog','information_schema','extensions','graphql','graphql_public',
                           'net','pgsodium','pgsodium_masks','realtime','storage','supabase_functions',
                           'supabase_migrations','vault','auth','cron','pgbouncer','_realtime','public')
order by 1, 2;
"""


# ── the commands ──────────────────────────────────────────────────────────────────────────────────────────────────────

def check():
    files = sql_files()
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute("select version()")
            print("server: " + cur.fetchone()[0].split(",")[0])
            print("schemas:")
            cur.execute(SCHEMAS)
            show(cur)
            print("the phases' relations:")
            cur.execute(TABLES)
            show(cur)
            done = ledger(cur)
        print("the ledger (%s): %s" % (LEDGER, "%d applied" % len(done) if done is not None else "not created yet - the first push creates it"))
        for v, n, ph, f in files:
            state = "applied" if done and v in done else "PENDING"
            print("  %-8s %s  %s/rulebook/schema/%s" % (state, v, ph, f.name))
        if not files:
            print("  no schema files on disk (no <Phase>/rulebook/schema/ folder)")
        extra = sorted(set(done or {}) - {v for v, _, _, _ in files})
        if extra:
            print("  applied in the project but without a file on disk: %s" % ", ".join(extra))
    finally:
        con.close()
    return 0


def push(dry, rest=0):
    files = sql_files()
    con = connect()
    try:
        with con.cursor() as cur:
            done = ledger(cur)
            if done is None and not dry:
                cur.execute("create schema if not exists supabase_migrations")
                cur.execute("create table if not exists %s (version text primary key, statements text[], name text)" % LEDGER)
                con.commit()
                done = {}
            done = done or {}
        todo = [x for x in files if x[0] not in done]
        if not todo:
            print("nothing to apply - %d file(s) on disk, every one in the ledger" % len(files))
            return 0
        for v, n, ph, f in todo:
            text = f.read_text(encoding="utf-8")
            print("%s %s  %s/rulebook/schema/%s  (%d lines)" % ("would apply" if dry else "applying", v, ph, f.name, text.count("\n")))
            if dry:
                continue
            if STATEMENT_BY_STATEMENT in text.splitlines()[0]:
                if not push_statements(con, v, n, text, rest):
                    return 1
                continue
            try:
                with con.cursor() as cur:
                    cur.execute(text)                                       # the whole file, one transaction; no parameters, so % is literal
                    cur.execute("insert into %s (version, statements, name) values (%%s, %%s, %%s)" % LEDGER, (v, [text], n))
                con.commit()
                print("  applied and recorded")
            except Exception as e:
                con.rollback()
                print("  ROLLED BACK - %s: %s" % (type(e).__name__, str(e).strip().splitlines()[0]))
                print("  nothing after it was attempted")
                return 1
        return 0
    finally:
        con.close()


STATEMENT_BY_STATEMENT = "-- statement by statement"


def statements(text):
    """The file's statements, split on the semicolons that are outside quotes, dollar-quoted bodies and comments."""
    out, buf, i, n = [], [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("--", i):                              # a comment to the end of the line
            j = text.find("\n", i)
            j = n if j < 0 else j
            buf.append(text[i:j]); i = j; continue
        if c == "'":                                              # a string, '' inside it
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2; continue
                    break
                j += 1
            buf.append(text[i:j + 1]); i = j + 1; continue
        if c == "$":                                              # $$ or $tag$ ... the same tag closes it
            j = text.find("$", i + 1)
            tag = text[i:j + 1] if j > 0 and all(ch.isalnum() or ch == "_" for ch in text[i + 1:j]) else None
            if tag:
                k = text.find(tag, i + len(tag))
                k = n if k < 0 else k + len(tag)
                buf.append(text[i:k]); i = k; continue
        if c == ";":
            stmt = "".join(buf).strip()
            if stmt and not all(line.strip().startswith("--") or not line.strip() for line in stmt.splitlines()):
                out.append(stmt)
            buf = []; i += 1; continue
        buf.append(c); i += 1
    stmt = "".join(buf).strip()
    if stmt and not all(line.strip().startswith("--") or not line.strip() for line in stmt.splitlines()):
        out.append(stmt)
    return out


def label(stmt):
    """The statement's first real line, for the log."""
    for line in stmt.splitlines():
        t = line.strip()
        if t and not t.startswith("--"):
            return " ".join(t.split())[:100]
    return stmt[:100]


def push_statements(con, v, n, text, rest=0):
    """One statement at a time, each its own transaction, timed; stop at the first failure (what ran stays - the file is
    re-runnable); the ledger row after the last.  Returns True when the file is recorded."""
    import time
    stmts = statements(text)
    print("  statement by statement: %d statements" % len(stmts))
    con.rollback()                                            # end the ledger's read transaction: autocommit cannot be set inside one
    con.autocommit = True
    try:
        with con.cursor() as cur:
            cur.execute("set statement_timeout = 0")
            for k, stmt in enumerate(stmts, 1):
                t0 = time.time()
                try:
                    cur.execute(stmt)
                except Exception as e:
                    print("  %2d/%d FAILED after %.0f s - %s: %s" % (k, len(stmts), time.time() - t0, type(e).__name__, str(e).strip().splitlines()[0]))
                    print("  the statements before it stand; fix and run push again - it skips what exists")
                    return False
                took = time.time() - t0
                print("  %2d/%d %6.0f s  %s" % (k, len(stmts), took, label(stmt)), flush=True)
                if rest and took >= 10 and k < len(stmts):
                    print("  resting %d s (the disk's budget)" % rest, flush=True)
                    time.sleep(rest)
            cur.execute("insert into %s (version, statements, name) values (%%s, %%s, %%s)" % LEDGER, (v, [text], n))
        print("  applied and recorded")
        return True
    finally:
        con.autocommit = False


def run_sql(sql, dry):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("-- %s%s\n%s\n\n" % (stamp, " (dry)" if dry else "", sql.strip()))
    if dry:
        print(sql.strip())
        return 0
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(sql)
            show(cur)
        con.commit()
        print("  committed")
        return 0
    except Exception as e:
        con.rollback()
        print("  ROLLED BACK - %s: %s" % (type(e).__name__, str(e).strip()))
        return 1
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="the process's one database: check it, push the phases' schema files, run a statement")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="server, schemas, tables; every schema file on disk against the ledger")
    p = sub.add_parser("push", help="apply the schema files not yet applied, in version order")
    p.add_argument("--dry", action="store_true", help="list what would be applied; run nothing")
    p.add_argument("--rest", type=int, default=0, help="statement by statement: seconds to rest after each statement that ran 10 s or longer (a small instance's disk budget)")
    s = sub.add_parser("sql", help="one statement (-c) or a script (-f), logged beside this file")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("-c", "--command")
    g.add_argument("-f", "--file")
    s.add_argument("--dry", action="store_true", help="print only")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return check()
    if a.cmd == "push":
        return push(a.dry, a.rest)
    sql = a.command if a.command else open(a.file, encoding="utf-8").read()
    return run_sql(sql, a.dry)


if __name__ == "__main__":
    sys.exit(main())
