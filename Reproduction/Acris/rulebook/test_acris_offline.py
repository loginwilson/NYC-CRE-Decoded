"""Offline checks - no ACRIS, no cloud: the drive lookup, the path rule, the ACRIS rules."""
import pathlib
import glob, json, sys, time
PHASE = pathlib.Path(__file__).resolve().parents[2]          # this file's Reproduction folder
sys.path.insert(0, str(PHASE / "rulebook"))
sys.path.insert(0, str(PHASE / "Acris" / "rulebook"))
import storage, acris, lane

print("1. drives this machine sees:")
for root, name in sorted(storage.volumes().items()):
    print("   %-6s %r" % (root, name))
try:
    print("   find_drive('One Touch') ->", storage.find_drive("One Touch"))
except SystemExit as e:
    print("   find_drive('One Touch'):", e)
print("   find_drive('D') ->", storage.find_drive("D"))

print("2. the path rule")
reg = {"recorded": "8/21/2004 7:56:37 PM", "parcels": [{"bbl": "100450012"}]}
c = acris.canonical_path("2004082100762006", reg)
print("   canonical:", c)
print("   local on D:", storage.local("D:\\", c))
print("   local on Mac:", storage.local("/Volumes/NYCCRED2", c))
assert c == r"D:\NYC CRE Decoded\Reproduction\Acris\By Document\2004\08 Aug\21\2004082100762006.pdf", c
assert acris.canonical_path("FT_4700012345678", {"type": "DEED"}) == r"D:\NYC CRE Decoded\Reproduction\Acris\By Document\FT_4\7000\FT_4700012345678.pdf"
assert acris.canonical_path("2017010200012001", {"type": "DEED"}) == r"D:\NYC CRE Decoded\Reproduction\Acris\By Document\2017\01 Jan\02\2017010200012001.pdf"
assert acris.canonical_path("2003010600934005", {"recorded": "5/13/2003 3:49:24 PM"}) == r"D:\NYC CRE Decoded\Reproduction\Acris\By Document\2003\05 May\13\2003010600934005.pdf"   # a real old row, its file sits in exactly this day folder
print("   borough from the BOROUGH line:", acris.borough_of("X", {"borough": "QUEENS / NEW YORK"}))
print("   borough from a microfilm id:", acris.borough_of("FT_3210001234567", {}))
print("   no borough anywhere:", acris.borough_of("BK_1", {}))
print("   undated microfilm:", acris.canonical_path("FT_4700012345678", {"type": "DEED"}))
print("   digital id, no registry date:", acris.canonical_path("2017010200012001", {"type": "DEED"}))
import datetime
rc = storage.canonical("richmond", "RC_988537", datetime.date(2019, 3, 28))
print("   richmond form:", rc)
assert rc == r"D:\NYC CRE Decoded\Reproduction\Richmond\By Document\2019\03 Mar\28\RC_988537.pdf", rc
assert storage.canonical("richmond", "RC_1", "3/18/1975") == r"D:\NYC CRE Decoded\Reproduction\Richmond\By Document\1975\03 Mar\18\RC_1.pdf"   # a real old row
assert storage.canonical("richmond", "RC_1900390", None) == r"D:\NYC CRE Decoded\Reproduction\Richmond\By Document\RC_1\9003\RC_1900390.pdf"   # no date: the id split

print("3. freshness")
today = time.strftime("%m/%d/%Y")
print("   recorded today, 30-day window ->", acris.fresh({"recorded": today + " 9:00:00 AM"}, 30))
print("   recorded 2004 ->", acris.fresh(reg, 30))
print("   no date ->", acris.fresh({}, 30))

print("4. the page count")
print("   viewer with TotalPages 3 ->", acris.total_pages(b'...%7B%22TotalPages%22%3A3%2C...'))
print("   viewer with TotalPages 0 ->", acris.total_pages(b'x TotalPages%22%3A0 y'))
print("   page without the token ->", acris.total_pages(b"<html>some other page</html>"))

print("5. the refusal detector")
tiff = b"II*\x00" + b"\x00" * 100
acris.check_refused(tiff, "image/tiff", "t")
print("   a TIFF passes")
acris.check_refused(b"<html><body>DOCUMENT ID: 2004082100762006 ... TotalPages</body></html>", "text/html", "t")
print("   a document page passes")
try:
    acris.check_refused(b"<html><body>a plain error page, 0 signals</body></html>", "text/html", "t")
    print("   an ordinary error page passes (not a refusal)")
except lane.Refused as e:
    print("   FAIL: ordinary page called a refusal:", e)
notice = b"<html><body><p>ACRIS</p><p>Bandwidth</p><p> Notice</p><p>Further access to <b>ACRIS</b> is denied. automated scripts/robots</p></body></html>"
try:
    acris.check_refused(notice, "text/html", "t")
    print("   FAIL: the notice passed")
except lane.Refused as e:
    print("   the notice is caught:", str(e)[:80])
saved = sorted(glob.glob(r"D:\CRE Decoding System\01 Navigations\Legal Instruments Navigation\_working\refusals\*.html"))
if saved:
    body = open(saved[-1], "rb").read()
    try:
        acris.check_refused(body, "text/html", "saved")
        print("   FAIL: a REAL preserved notice (%s) passed" % saved[-1])
    except lane.Refused as e:
        print("   a REAL preserved notice from %s is caught (%d bytes)" % (saved[-1].split("\\")[-1], len(body)))
else:
    print("   (no preserved notice page on D: to test against)")
print("   placeholder md5 check on random bytes ->", acris.is_placeholder(b"abc"))
print("6. URLs minted from the id")
print("  ", acris.detail_url("2004082100762006"))
print("  ", acris.viewer_url("2004082100762006"))
print("  ", acris.image_url("2004082100762006", 2))
print("OFFLINE OK")
