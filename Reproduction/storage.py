"""WHERE A DOCUMENT LIVES - the One Touch layout, the same on every workstation.

The database records the CANONICAL address of a document, always in One Touch form:

    D:\\CRE Decoding System\\Documents\\<source>\\<borough>\\<year>\\<month>\\<id>.pdf     (richmond: no borough)

Each workstation writes the file under ITS OWN drive - found by its label (--drive NYCCRED1,
--drive NYCCRED2) on Windows or Mac alike - with the identical layout beneath, so a later
transfer of that drive's files into the One Touch makes every recorded path literally true
with no change to the database.  The label names the drive; the letter D: in the cell is the
One Touch's address, not a claim about which machine fetched the file.
"""
import os
import pathlib
import string
import sys

CANON_ROOT = "D:\\"
LAYOUT = ("CRE Decoding System", "Documents")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
BOROUGHS = {1: "Manhattan", 2: "Bronx", 3: "Brooklyn", 4: "Queens", 5: "Staten Island"}


def month_folder(m):
    """'08 Aug' - Explorer's alphabetical order is calendar order."""
    return "%02d %s" % (m, MONTHS[m - 1])


def canonical(source, borough, year, month, doc_id):
    """The One Touch address recorded in the cell.  borough=None for a source without one."""
    parts = list(LAYOUT) + [source] + ([borough] if borough else []) + [str(year), month, doc_id + ".pdf"]
    return CANON_ROOT + "\\".join(parts)


def local(root, canonical_path):
    """The same document under THIS workstation's drive root."""
    rel = canonical_path[len(CANON_ROOT):].split("\\")
    return pathlib.Path(root, *rel)


# ── finding the drive by its label ──────────────────────────────────────────────────────────

def _windows_volumes():
    import ctypes
    k = ctypes.windll.kernel32
    k.SetErrorMode(1)                 # SEM_FAILCRITICALERRORS: a drive with no media fails quietly, no dialog
    out = {}
    mask = k.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = letter + ":\\"
        name = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        if k.GetVolumeInformationW(root, name, 261, None, None, None, fs, 261):
            out[root] = name.value
    return out


def volumes():
    """{mount root: label} for every drive this machine can see."""
    if sys.platform == "win32":
        return _windows_volumes()
    if sys.platform == "darwin":
        base = pathlib.Path("/Volumes")
        return {str(p): p.name for p in base.iterdir() if p.is_dir()} if base.is_dir() else {}
    out = {}
    for base in ("/media/%s" % os.environ.get("USER", ""), "/run/media/%s" % os.environ.get("USER", ""), "/mnt"):
        b = pathlib.Path(base)
        if b.is_dir():
            out.update({str(p): p.name for p in b.iterdir() if p.is_dir()})
    return out


def find_drive(label):
    """The mount root of the drive carrying this label (case-insensitive).  On Windows a bare
    letter ('D' or 'D:') is accepted too.  Stops with the labels it can see when nothing matches."""
    vols = volumes()
    if sys.platform == "win32" and len(label.rstrip(":\\")) == 1:
        root = label.rstrip(":\\").upper() + ":\\"
        if root in vols:
            return root
    for root, name in vols.items():
        if name.lower() == label.lower():
            return root
    seen = ", ".join("%s = %r" % (r, n) for r, n in sorted(vols.items())) or "none"
    raise SystemExit("no drive labelled %r is mounted.  Drives seen: %s" % (label, seen))


def documents_root(drive_root):
    """<drive>\\CRE Decoding System\\Documents - created if missing."""
    p = pathlib.Path(drive_root, *LAYOUT)
    p.mkdir(parents=True, exist_ok=True)
    return p
