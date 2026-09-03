"""Prove the cooperation functions on the live project with throwaway rows, then remove them.
  1. insert 6 test documents (ids starting TEST-) into reproduction.acris
  2. host A claims 4, host B claims 4 at once -> the two slices must be disjoint and cover all 6
  3. host A lands 2 (a path and 'absent'), host B lands 1 ('pending') -> cells filled, claims dropped
  4. a wrong word is rejected by the cell rule
  5. heartbeat() from both hosts -> two rows
  6. delete the test rows (claims cascade)
Uses decoded_sql.dsn() for the connection; never prints credentials."""
import os, sys, json, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psycopg2, psycopg2.errors
from decoded_sql import dsn

IDS = ["TEST-%04d" % i for i in range(1, 7)]
PATH = r"D:\CRE Decoding System\Documents\acris\Manhattan\2004\08 Aug\TEST-0001.pdf"


def q(sql, params=None, fetch=True):
    con = psycopg2.connect(dsn(), connect_timeout=30, application_name="test_claims")
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
            out = cur.fetchall() if fetch and cur.description else None
        con.commit()
        return out
    finally:
        con.close()


def claim(host, got):
    got[host] = [r[0] for r in q("select reproduction.claim('acris', 'documentation', %s, 4)", (host,))]


print("1. insert", len(IDS), "test rows")
q("delete from reproduction.acris where doc_id like 'TEST-%'", fetch=False)
q("insert into reproduction.acris (doc_id) select unnest(%s::text[])", (IDS,), fetch=False)

print("2. two hosts claim at once")
got = {}
ta = threading.Thread(target=claim, args=("HOST-A", got)); tb = threading.Thread(target=claim, args=("HOST-B", got))
ta.start(); tb.start(); ta.join(); tb.join()
a, b = set(got["HOST-A"]), set(got["HOST-B"])
print("   A:", sorted(a)); print("   B:", sorted(b))
assert not (a & b), "OVERLAP: %s" % (a & b)
assert a | b == set(IDS), "not all covered: %s" % (set(IDS) - (a | b))
print("   disjoint and complete: OK")
claims = q("select host, count(*) from reproduction.acris_claims where doc_id like 'TEST-%' group by host order by host")
print("   claims table:", claims)

print("3. land: A fills a path and an absent, B fills a pending; counters move by what was new")
before = q("select landed from reproduction.acris_update_lanes where lane = 'documentation'")[0][0]
phase_before = q("select landed from reproduction.acris_update")[0][0]
la = sorted(a)[:2]; lb = sorted(b)[:1]
n1 = q("select reproduction.land('acris', 'documentation', 'HOST-A', %s::jsonb)", (json.dumps([{"doc_id": la[0], "value": PATH}, {"doc_id": la[1], "value": "absent"}]),))[0][0]
n2 = q("select reproduction.land('acris', 'documentation', 'HOST-B', %s::jsonb)", (json.dumps([{"doc_id": lb[0], "value": "pending"}]),))[0][0]
print("   cells written:", n1, "+", n2)
rows = q("select doc_id, document from reproduction.acris where doc_id like 'TEST-%' order by doc_id")
for r in rows:
    print("   ", r[0], "->", r[1])
left = q("select count(*) from reproduction.acris_claims where doc_id like 'TEST-%'")[0][0]
assert left == 3, "expected 3 claims left (6 - 3 landed), got %d" % left
print("   claims left:", left, "OK")
after = q("select landed from reproduction.acris_update_lanes where lane = 'documentation'")[0][0]
assert after - before == 3, "lane landed should rise by 3 (path, absent, pending all count), rose by %d" % (after - before)
print("   documentation landed +3: OK")
# registry for one landed doc -> the row completes -> the phase counter rises by 1
q("select reproduction.land('acris', 'registration', 'HOST-A', %s::jsonb)", (json.dumps([{"doc_id": la[0], "value": {"doc type": "DEED", "test": True}}]),), fetch=False)
phase_after = q("select landed from reproduction.acris_update")[0][0]
assert phase_after - phase_before == 1, "phase landed should rise by 1, rose by %d" % (phase_after - phase_before)
print("   phase landed +1 when the row completed: OK")
# re-landing the same pending as a path adds nothing to the lane counter
q("select reproduction.land('acris', 'documentation', 'HOST-B', %s::jsonb)", (json.dumps([{"doc_id": lb[0], "value": PATH}]),), fetch=False)
again = q("select landed from reproduction.acris_update_lanes where lane = 'documentation'")[0][0]
assert again == after, "pending -> path must not add to landed"
print("   pending -> path adds nothing: OK")
print("   reconcile:", q("select * from reproduction.reconcile('acris')"))

print("4. the cell rule rejects a wrong word")
try:
    q("update reproduction.acris set document = 'unservable' where doc_id = %s", (IDS[0],), fetch=False)
    print("   NOT rejected - FAIL"); sys.exit(1)
except psycopg2.errors.CheckViolation as e:
    print("   rejected:", str(e).splitlines()[0][:90])

print("5. heartbeats from both hosts")
q("select reproduction.heartbeat('acris', 'documentation', 'HOST-A', 40, 'test')", fetch=False)
q("select reproduction.heartbeat('acris', 'documentation', 'HOST-B', 40, null)", fetch=False)
print("   ", q("select lane, host, width, last_event from reproduction.acris_heartbeats order by host"))

print("6. remove the test rows and reset the counters by measuring")
q("delete from reproduction.acris where doc_id like 'TEST-%'", fetch=False)
q("delete from reproduction.acris_heartbeats where host like 'HOST-%'", fetch=False)
print("   reconcile after cleanup:", q("select * from reproduction.reconcile('acris')"))
print("   rows left:", q("select count(*) from reproduction.acris where doc_id like 'TEST-%'")[0][0],
      "| claims left:", q("select count(*) from reproduction.acris_claims")[0][0])
print("ALL OK")
