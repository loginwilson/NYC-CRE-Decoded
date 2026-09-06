"""Prove the cooperation functions on the live project with throwaway rows, then remove them - on the POPULATED table.
claim() hands out the due pendings first, in id order, then empties; acris holds no real pending (checked below; the
test refuses otherwise), so a claim sized to the test's own pendings takes exactly them and nothing real.  Empties are
never claimed here (the millions of real empties come first in id order); land() needs no claim, so the counters are
proven on empty test rows landed directly.
  1. insert 8 test documents (ids starting TEST-), each with a registry object (migration 0002: documentation claims
     only rows whose registry is a JSON object): six with document = 'pending', two with the cell empty
  2. host A claims 3, host B claims 3 at once -> the two slices must be disjoint and together be the six pendings
  3. host A lands 2 (a path and 'absent') -> their claims are released; host B lands its highest id as 'pending' -> that
     claim stays as a COOLDOWN until now() + pending_age in B's name (migration 0004); 4 claims left; a pending landed
     again as a path adds nothing to the counters and releases the claim
  4. the cooldown: B lands another pending; while the cooldown lives no claim offers it; its `until` set into the past
     -> the next claim() releases it and hands that row out, skipping the rows still held by A and B
  5. the two empty rows landed directly -> lane landed +2, phase landed +2 (their registry was already there)
  6. a wrong word is rejected by the cell rule; a registry landed over a registry adds nothing
  7. heartbeat() from both hosts -> two rows
  8. delete the test rows (claims cascade), the test heartbeats and claims; reconcile (the counters measured again)
Uses the project's supabase/supabase.py dsn() for the connection; never prints credentials."""
import os, sys, json, threading, pathlib, importlib.util
import psycopg2, psycopg2.errors
ROOT = pathlib.Path(__file__).resolve().parents[2]                       # rulebook -> Reproduction -> the repo
_spec = importlib.util.spec_from_file_location("supabase_program", ROOT / "supabase" / "supabase.py")
_program = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_program)
dsn = _program.dsn

PENDING = ["TEST-%04d" % i for i in range(1, 7)]
EMPTY = ["TEST-0007", "TEST-0008"]
PATH = r"D:\NYC CRE Decoded\Reproduction\Acris\By Document\2004\08 Aug\21\TEST-0001.pdf"
REGISTRY = json.dumps({"doc type": "DEED", "test": True})


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(dsn(), connect_timeout=30, application_name="test_schema")
    try:
        with con.cursor() as cur:
            cur.execute("set statement_timeout = 0")     # reconcile() over the populated table outlasts the project's two-minute default
            cur.execute(sql, params)
            out = cur.fetchall() if fetch and cur.description else None
        con.commit()
        return out
    finally:
        con.close()


def land(host, rows, lane="documentation", pending_age="1 hour"):
    return q("select reproduction.land('acris', %s, %s, %s::jsonb, %s::interval)", (lane, host, json.dumps(rows), pending_age))[0][0]


def claim(host, got, n=3):
    got[host] = [r[0] for r in q("select reproduction.claim('acris', 'documentation', %s, %s)", (host, n))]


def test_claims():
    return q("select doc_id, host, until > now() from reproduction.acris_claims where doc_id like 'TEST-%' order by doc_id")


real_pending = q("select count(*) from reproduction.acris where document = 'pending' and doc_id not like 'TEST-%'")[0][0]
if real_pending:
    raise SystemExit("reproduction.acris holds %s real pending documents - this test's claims would take them first; run it when none is pending" % "{:,}".format(real_pending))

print("1. insert", len(PENDING), "pending test rows and", len(EMPTY), "empty ones, each with a registry object")
q("delete from reproduction.acris where doc_id like 'TEST-%'", fetch=False)
q("insert into reproduction.acris (doc_id, registry, document) select unnest(%s::text[]), %s::jsonb, 'pending'", (PENDING, REGISTRY), fetch=False)
q("insert into reproduction.acris (doc_id, registry) select unnest(%s::text[]), %s::jsonb", (EMPTY, REGISTRY), fetch=False)

print("2. two hosts claim at once")
got = {}
ta = threading.Thread(target=claim, args=("HOST-A", got)); tb = threading.Thread(target=claim, args=("HOST-B", got))
ta.start(); tb.start(); ta.join(); tb.join()
a, b = set(got["HOST-A"]), set(got["HOST-B"])
print("   A:", sorted(a)); print("   B:", sorted(b))
assert not (a & b), "OVERLAP: %s" % (a & b)
assert a | b == set(PENDING), "not exactly the six pendings: %s" % sorted(a | b)
print("   disjoint and complete, nothing real taken: OK")
print("   claims table:", q("select host, count(*) from reproduction.acris_claims where doc_id like 'TEST-%' group by host order by host"))

print("3. land: A fills a path and an absent (released); B lands a pending (kept as a cooldown)")
before = q("select landed from reproduction.acris_update_lanes where lane = 'documentation'")[0][0]
phase_before = q("select landed from reproduction.acris_update")[0][0]
la = sorted(a)[:2]; b_hi = sorted(b)[-1]
n1 = land("HOST-A", [{"doc_id": la[0], "value": PATH}, {"doc_id": la[1], "value": "absent"}])
n2 = land("HOST-B", [{"doc_id": b_hi, "value": "pending"}])
print("   cells written:", n1, "+", n2)
for r in q("select doc_id, document from reproduction.acris where doc_id like 'TEST-%' order by doc_id"):
    print("   ", r[0], "->", r[1])
claims = test_claims()
assert len(claims) == 4, "expected 4 claims left (6 - 2 released; the pending kept), got %d: %s" % (len(claims), claims)
cool = q("select host, until > now() + interval '50 minutes', until < now() + interval '70 minutes' from reproduction.acris_claims where doc_id = %s", (b_hi,))
assert cool == [("HOST-B", True, True)], "the pending's claim should be B's cooldown of about an hour, got %s" % cool
print("   claims left: 4, the pending's held as B's cooldown until about now() + 1 hour: OK")
after = q("select landed from reproduction.acris_update_lanes where lane = 'documentation'")[0][0]
phase_after = q("select landed from reproduction.acris_update")[0][0]
assert after == before and phase_after == phase_before, "landing over pendings must not move the counters (rose %d / %d)" % (after - before, phase_after - phase_before)
print("   a pending -> path / absent / pending adds nothing to the counters: OK")
land("HOST-B", [{"doc_id": b_hi, "value": PATH}])
assert len(test_claims()) == 3, "a pending landed as a path must release its cooldown claim"
print("   the cooling pending landed as a path releases its claim: OK")

print("4. the cooldown ends the way a claim expires")
b_left = sorted(b - {b_hi})
cooler = b_left[-1]
land("HOST-B", [{"doc_id": cooler, "value": "pending"}])
held = test_claims()
assert [c[0] for c in held] == sorted(set(PENDING) - set(la) - {b_hi}), "three rows should be held now: %s" % held
q("update reproduction.acris_claims set until = now() - interval '1 second' where doc_id = %s", (cooler,), fetch=False)
c = {}
claim("HOST-C", c, 1)
assert c["HOST-C"] == [cooler], "C should get exactly the pending whose cooldown ran out (skipping %s, still held), got %s" % (
    [x for x in sorted(set(PENDING) - set(la) - {b_hi}) if x != cooler], c["HOST-C"])
print("   C's claim of 1 handed out", cooler, "- the expired cooldown - and skipped the rows A and B still hold: OK")

print("5. the two empty rows landed directly: counters move by what was new")
land("HOST-A", [{"doc_id": EMPTY[0], "value": PATH}, {"doc_id": EMPTY[1], "value": "absent"}])
after = q("select landed from reproduction.acris_update_lanes where lane = 'documentation'")[0][0]
phase_after = q("select landed from reproduction.acris_update")[0][0]
assert after - before == 2, "lane landed should rise by 2, rose by %d" % (after - before)
assert phase_after - phase_before == 2, "phase landed should rise by 2 (each row had its registry), rose by %d" % (phase_after - phase_before)
print("   documentation landed +2, phase landed +2: OK")

print("6. the cell rule rejects a wrong word; a registry over a registry adds nothing")
try:
    q("update reproduction.acris set document = 'unservable' where doc_id = %s", (PENDING[0],), fetch=False)
    print("   NOT rejected - FAIL"); sys.exit(1)
except psycopg2.errors.CheckViolation as e:
    print("   rejected:", str(e).splitlines()[0][:90])
reg_before = q("select landed from reproduction.acris_update_lanes where lane = 'registration'")[0][0]
land("HOST-A", [{"doc_id": la[0], "value": {"doc type": "DEED", "again": True}}], lane="registration")
reg_after = q("select landed from reproduction.acris_update_lanes where lane = 'registration'")[0][0]
assert reg_after == reg_before, "a registry over a registry must not add to landed"
print("   registry over registry adds nothing: OK")

print("7. heartbeats from both hosts")
q("select reproduction.heartbeat('acris', 'documentation', 'HOST-A', 40, 'test')", fetch=False)
q("select reproduction.heartbeat('acris', 'documentation', 'HOST-B', 40, null)", fetch=False)
print("   ", q("select lane, host, width, last_event from reproduction.acris_heartbeats where host like 'HOST-%' order by host"))

print("8. remove the test rows, heartbeats and claims; the counters measured again")
q("delete from reproduction.acris where doc_id like 'TEST-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host like 'HOST-%'", fetch=False)
q("delete from reproduction.acris_claims where host like 'HOST-%'", fetch=False)
print("   reconcile after cleanup:", q("select * from reproduction.reconcile('acris')"))
print("   rows left:", q("select count(*) from reproduction.acris where doc_id like 'TEST-%'")[0][0],
      "| test claims left:", q("select count(*) from reproduction.acris_claims where host like 'HOST-%'")[0][0])
print("ALL OK")
