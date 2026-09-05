"""Run SQL against the NYC CRE Decoded project from here.

    python decoded_sql.py --check                 # server version, schemas, tables
    python decoded_sql.py -c "select 1"           # one statement (or several, ; separated)
    python decoded_sql.py -f file.sql             # a file, as one script
    python decoded_sql.py -c "..." --dry          # print only, run nothing

Reads C:/dev/nyc-cre-decoded.env (or NYC_CRE_DECODED_ENV): SUPABASE_DB_URL is
the session-pooler URI with the password filled in. Nothing here prints a
credential. Every run is appended to _decoded_sql.log beside this file so the
schema has a written history of every statement that shaped it.
"""
import argparse, datetime, os, pathlib, sys

HERE = pathlib.Path(__file__).parent
ENV = os.environ.get("NYC_CRE_DECODED_ENV", "C:/dev/nyc-cre-decoded.env")
LOG = HERE / "_decoded_sql.log"


def env():
    v = {}
    try:
        for line in open(ENV, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, val = line.split("=", 1)
                v[k.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        raise SystemExit("no env file at %s - create it with SUPABASE_DB_URL (and SUPABASE_DB_PASSWORD if the URL carries no password)" % ENV)
    if not v.get("SUPABASE_DB_URL"):
        raise SystemExit("SUPABASE_DB_URL missing in %s (Connect > Session pooler > URI, password filled in)" % ENV)
    return v


def dsn():
    """The pooler URI, with the password taken from SUPABASE_DB_PASSWORD when that
    line exists (so nobody has to edit inside a long string) and percent-encoded,
    so a password with symbols still parses."""
    import re, urllib.parse
    v = env()
    url = v["SUPABASE_DB_URL"]
    m = re.match(r"^(postgres(?:ql)?://)([^:@/]+)(?::(.*))?@([^@]+)$", url, re.S)
    if not m:
        raise SystemExit("SUPABASE_DB_URL does not look like postgresql://user:password@host:port/db")
    scheme, user, pw, rest = m.groups()
    pw = v.get("SUPABASE_DB_PASSWORD") or pw or ""
    if not pw or "YOUR-PASSWORD" in pw:
        raise SystemExit("database password missing - add a line SUPABASE_DB_PASSWORD=<password> to %s" % ENV)
    url = "%s%s:%s@%s" % (scheme, user, urllib.parse.quote(pw, safe=""), rest)
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def connect():
    import psycopg2
    url = dsn()
    con = psycopg2.connect(url, connect_timeout=30, application_name="decoded_sql")
    con.autocommit = False
    return con


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


def run(sql, dry=False):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("-- %s%s\n%s\n\n" % (stamp, " (dry)" if dry else "", sql.strip()))
    if dry:
        print(sql.strip())
        return
    con = connect()
    try:
        with con.cursor() as cur:
            cur.execute(sql)
            show(cur)
        con.commit()
        print("  committed")
    except Exception as e:
        con.rollback()
        print("  ROLLED BACK - %s: %s" % (type(e).__name__, str(e).strip()))
        sys.exit(1)
    finally:
        con.close()


CHECK = """
select version() as version;
"""
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
                           'supabase_migrations','vault','auth','cron','pgbouncer','_realtime')
order by 1, 2;
"""


def check():
    con = connect()
    try:
        with con.cursor() as cur:
            for label, q in (("server", CHECK), ("schemas", SCHEMAS), ("our relations", TABLES)):
                print(label + ":")
                cur.execute(q)
                show(cur)
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("-c", "--command")
    ap.add_argument("-f", "--file")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.check:
        check()
    elif a.command:
        run(a.command, a.dry)
    elif a.file:
        run(open(a.file, encoding="utf-8").read(), a.dry)
    else:
        ap.print_help()
