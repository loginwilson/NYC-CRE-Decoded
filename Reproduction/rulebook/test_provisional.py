"""THE PROVISIONAL REGISTRATION proven on the live table with throwaway rows inside ONE transaction that is rolled back - no row,
claim or counter survives; the 0009 functions are applied inside the same transaction first, so this proves the file before
`push` records it and the applied functions after.
  1. three rows with ids younger than 400 days and below every real provisional id (2025-10-29 ..): A registered WITHOUT a recorded date (provisional),
     B registered WITH one, C not registered
  2. registration's first claim is A (due before every empty); B is not due; C is landed directly (an empty needs no claim)
  3. A lands again still without a recorded date -> its claim stays as a COOLDOWN (until ~ now + pending_age); C lands with a
     date -> released; the registration counter moved by 1 (C was new), not for A
  4. A's cooldown set into the past -> the next claim offers A again; A lands WITH a recorded date -> released, offered no more
  5. rollback
Uses supabase.py dsn(); prints nothing secret."""
import json, pathlib, sys, importlib.util
import psycopg2
ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("supabase_program", ROOT / "supabase" / "supabase.py")
_program = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_program)
SQL = (ROOT / "Reproduction/rulebook/schema/20260906210000_provisional_registration.sql").read_text(encoding="utf-8")
A, B, C = "2025090100000001", "2025090100000002", "2025090100000003"   # younger than 400 days, below every real provisional id (2025-10-29 ..)
NO_DATE = {"type": "FL", "crfn": "2025000000001", "parties": [{"name": "TEST LIEN CO", "panel": "1"}]}
DATED = dict(NO_DATE, recorded="9/6/2026 8:45:00 PM")
fails = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)

con = psycopg2.connect(_program.dsn(), connect_timeout=30, application_name="test_provisional")
con.autocommit = False
cur = con.cursor()
try:
    cur.execute("set statement_timeout = 0")
    for stmt in _program.statements(SQL):
        cur.execute(stmt)
    print("0009's two functions applied inside the transaction")
    cur.execute("select count(*) from reproduction.acris where doc_id in (%s, %s, %s)", (A, B, C))
    assert cur.fetchone()[0] == 0, "the test ids exist"
    cur.execute("insert into reproduction.acris (doc_id, registry) values (%s, %s::jsonb), (%s, %s::jsonb), (%s, null)",
                (A, json.dumps(NO_DATE), B, json.dumps(DATED), C))
    cur.execute("select landed from reproduction.updates where source = 'acris' and lane = 'registration' and workstation = ''")
    before = cur.fetchone()[0]
    cur.execute("select reproduction.claim('acris', 'registration', 'HOST-P', 1)")
    got = [r[0] for r in cur.fetchall()]
    check("registration's first claim is the provisional A (due before every empty)", got == [A], got)
    cur.execute("""select count(*) from reproduction.acris w where w.doc_id = %s and (w.registry = '"pending"'::jsonb
                   or (jsonb_typeof(w.registry) = 'object' and reproduction.us_date(w.registry->>'recorded') is null))""", (B,))
    check("B (registered, dated) is not due", cur.fetchone()[0] == 0)
    # C, an empty, would be offered only after the 8,876 real provisional rows: it is landed directly (land needs no claim)
    cur.execute("select reproduction.land('acris', 'registration', 'HOST-P', %s::jsonb, interval '1 day')",
                (json.dumps([{"doc_id": A, "value": NO_DATE}, {"doc_id": C, "value": DATED}]),))
    cur.execute("select doc_id, until > now() + interval '23 hours', until < now() + interval '25 hours' from machinery.claims where source = 'acris' and lane = 'registration' and doc_id in (%s, %s, %s) order by doc_id", (A, B, C))
    claims = cur.fetchall()
    check("A landed without a date keeps its claim as a one-day cooldown; C landed dated is released", claims == [(A, True, True)], claims)
    cur.execute("select landed from reproduction.updates where source = 'acris' and lane = 'registration' and workstation = ''")
    after = cur.fetchone()[0]
    check("the registration counter moved by 1 (C was new), not for A's re-read", after - before == 1, after - before)
    cur.execute("select reproduction.claim('acris', 'registration', 'HOST-P', 1)")
    check("while A cools, the claim does not offer it", A not in [r[0] for r in cur.fetchall()])
    cur.execute("update machinery.claims set until = now() - interval '1 second' where source = 'acris' and lane = 'registration' and doc_id = %s", (A,))
    cur.execute("select reproduction.claim('acris', 'registration', 'HOST-Q', 1)")
    got = [r[0] for r in cur.fetchall()]
    check("A's cooldown over: the next claim offers A again", got == [A], got)
    cur.execute("select reproduction.land('acris', 'registration', 'HOST-Q', %s::jsonb, interval '1 day')", (json.dumps([{"doc_id": A, "value": DATED}]),))
    cur.execute("select count(*) from machinery.claims where source = 'acris' and lane = 'registration' and doc_id = %s", (A,))
    check("A landed WITH a recorded date: released", cur.fetchone()[0] == 0)
    cur.execute("select reproduction.claim('acris', 'registration', 'HOST-Q', 1)")
    check("A is offered no more", A not in [r[0] for r in cur.fetchall()])
    cur.execute("select count(*) from reproduction.acris where doc_id >= to_char(now() - interval '400 days', 'YYYYMMDD') and doc_id < '3' and jsonb_typeof(registry) = 'object' and reproduction.us_date(registry->>'recorded') is null and doc_id not in (%s, %s, %s)", (A, B, C))
    print("   real provisional registries the rule will offer in gate 3:", "{:,}".format(cur.fetchone()[0]))
finally:
    con.rollback()
    con.close()
    print("rolled back - nothing kept")
print("PROVISIONAL REGISTRATION:", "ALL OK" if not fails else "FAILURES: %s" % fails)
sys.exit(1 if fails else 0)
