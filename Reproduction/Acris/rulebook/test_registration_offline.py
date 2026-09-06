"""Offline checks for registration - no ACRIS, no cloud writes.
  1. the echo check on a page that is / is not about the document
  2. parse_acris on a synthetic DocumentDetail page built in the real page's shape (labels, nested tables
     with header rows, twin-table layout, a REMARKS textarea)
  3. the key set of that parse against a REAL registry row read from the old database (read-only,
     a range seek on the id, never LIKE)
  4. the sibling loader: Acris Registration.py can host documentation, and the reverse
"""
import json, pathlib, sqlite3, sys, types
PHASE = pathlib.Path(__file__).resolve().parents[2]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
import acris, lane

DID = "2024081500123001"
PAGE = """<html><body>
<table><tr><td>DOCUMENT ID: %s</td><td>CRFN: 2024000123456</td></tr>
<tr><td>DOC. TYPE: DEED</td><td># of PAGES: 7</td><td>DOC. DATE: 8/9/2024</td></tr>
<tr><td>RECORDED / FILED: 8/15/2024 10:12:03 AM</td><td>DOC. AMOUNT: $1,250,000.00</td><td>%% TRANSFERRED: 100</td></tr>
<tr><td>BOROUGH: N/A</td></tr>
<table><tr><td>PARTY 1</td></tr>
<table><tr><th>NAME</th><th>ADDRESS 1</th><th>ADDRESS 2</th><th>CITY</th><th>STATE</th><th>ZIP</th><th>COUNTRY</th></tr></table>
<table><tr><td>JERIST REALTY LLC</td><td>10-40 VERNON BLVD</td><td></td><td>LONG ISLAND CITY</td><td>NY</td><td>11101</td><td>US</td></tr></table>
</table>
<table><tr><td>PARTY 2</td></tr>
<table><tr><th>NAME</th><th>ADDRESS 1</th><th>ADDRESS 2</th><th>CITY</th><th>STATE</th><th>ZIP</th><th>COUNTRY</th></tr>
<tr><td>VERNON HOLDINGS INC</td><td>1 MAIN ST</td><td>SUITE 4</td><td>NEW YORK</td><td>NY</td><td>10001</td><td>US</td></tr></table>
</table>
<table><tr><td>PARCELS</td></tr>
<table><tr><th>BOROUGH</th><th>BLOCK</th><th>LOT</th><th>PARTIAL</th><th>PROPERTY TYPE</th><th>PROPERTY ADDRESS</th><th>UNIT</th><th>EASEMENT</th><th>AIR RIGHTS</th><th>SUBTERRANEAN RIGHTS</th><th>REMARKS</th></tr>
<tr><td>QUEENS</td><td>00045</td><td>0012</td><td>N/A</td><td>COMMERCIAL</td><td>10-40 VERNON BLVD</td><td>N/A</td><td>N</td><td>Y</td><td>N</td><td>N/A</td></tr></table>
</table>
<table><tr><td>REFERENCES</td></tr>
<table><tr><th>CRFN</th><th>DOCUMENT ID</th><th>BOROUGH</th><th>YEAR</th><th>REEL</th><th>PAGE</th><th>FILE NBR</th></tr>
<tr><td>2019000456789</td><td>2019061500987001</td><td>QUEENS</td><td>2019</td><td>N/A</td><td>N/A</td><td>N/A</td></tr></table>
</table>
<table><tr><td>REMARKS</td></tr><tr><td><textarea>SEE  RIDER  ATTACHED &amp; SCHEDULE A</textarea></td></tr></table>
</table></body></html>""" % DID

print("1. echo")
html = acris.clean_html(PAGE)
print("   about our document ->", acris.echoes(html, DID))
print("   about another id   ->", acris.echoes(html, "2024081500123002"))
print("   an empty viewer    ->", acris.echoes("<html>Document Search</html>", DID))

print("2. parse")
rec = acris.parse_acris(html)
print(json.dumps(rec, indent=1)[:1400])
assert rec["type"] == "DEED" and rec["pages"] == "7" and rec["recorded"].startswith("8/15/2024"), rec
assert "borough" not in rec, "N/A must be omitted"
assert rec["parcels"][0]["bbl"] == "4000450012" and rec["parcels"][0].get("air_rights") == "Y" and "easement" not in rec["parcels"][0]   # borough 1 + block 5 + lot 4 digits
assert [p["panel"] for p in rec["parties"]] == ["1", "2"], rec["parties"]
assert rec["references"][0]["doc_id"] == "2019061500987001" and "reel" not in rec["references"][0]
assert rec["remarks"] == "SEE RIDER ATTACHED & SCHEDULE A"
print("   scalar fields, parties by panel, parcels with flags, references, remarks: OK")

print("3. key set against a real registry row (old database, read-only)")
con = sqlite3.connect(r"file:D:\CRE Decoding System\Legal Instruments.db?mode=ro", uri=True, timeout=60)
row = con.execute("select id, recorded_details from navigation where id >= '2024081' and id < '2024082' and recorded_details != '' limit 1").fetchone()
con.close()
real = json.loads(row[1])
print("   real row", row[0], "keys:", sorted(real.keys()))
print("   parse   keys:", sorted(rec.keys()))
unknown = set(rec.keys()) - set(k for k, _ in acris.FIELD_KEYS) - {"parties", "parcels", "references", "remarks"}
print("   keys the parser can emit that the old parser could not:", unknown or "none")
if real.get("parties"):
    print("   real party keys:", sorted(real["parties"][0].keys()), "| parsed:", sorted(rec["parties"][0].keys()))
if real.get("parcels"):
    print("   real parcel keys:", sorted(real["parcels"][0].keys()), "| parsed:", sorted(rec["parcels"][0].keys()))

print("4. the sibling loader")
reg_here = pathlib.Path(str(PHASE / "Acris" / "workflow" / "registration"))
doc_here = pathlib.Path(str(PHASE / "Acris" / "workflow" / "documentation"))
args = types.SimpleNamespace(lane="registration", width=40, also=["documentation:20"], fresh_days=30)
roles = lane.roles_for("Acris", args, reg_here, "D:\\", types.SimpleNamespace(lane="registration", source="acris"))
print("   registration hosting documentation ->", [(type(r).__name__, w) for r, w in roles])
args = types.SimpleNamespace(lane="documentation", width=40, also=["registration:40"], fresh_days=30)
roles = lane.roles_for("Acris", args, doc_here, "D:\\", types.SimpleNamespace(lane="documentation", source="acris"))
print("   documentation hosting registration ->", [(type(r).__name__, w) for r, w in roles])
try:
    lane.roles_for("Acris", types.SimpleNamespace(lane="registration", width=40, also=["documentation:20"]), reg_here, None, object())
    print("   FAIL: documentation hosted without a drive")
except SystemExit as e:
    print("   documentation without --drive refused:", str(e)[:60])
print("REGISTRATION OFFLINE OK")
