"""WHERE A DOCUMENT LIVES - the One Touch layout, the same on every workstation.

The database records the CANONICAL address of a document, always in One Touch form, in the tree that mirrors GitHub
and Supabase (login 2026-09-05: "NYC CRE Decoded -> reproduction -> source -> by document -> by year -> by month ->
by day ... you click on that, and you see all the documents that fall into that day"):

    D:\\NYC CRE Decoded\\Reproduction\\<Source>\\By Document\\<year>\\<MM Mon>\\<day>\\<id>.pdf

The day folder comes from the RECORDED date - the axis that aligns every source (a digital id's embedded date is the
submission date and can lag recording by days; RC ids carry no date) - else a digital id's own date, else the id
split `<id[:4]>\\<id[4:8]>`.  An id shorter than eight characters keeps only its first folder.  That is the old lane's rule since 2026-08-20 (corpus_paths.doc_store_dir), kept exactly
so the tree moved from the old acquisition store keeps every folder it had and a person finds new and old documents
by the same rule.  Months are `04 Apr` so Explorer's alphabetical order is calendar order.  The PDFs never leave the
One Touch: the cloud holds the table, the cell holds the full path a person pastes into the File Explorer bar.

Each workstation writes the file under ITS OWN drive - found by its label (--drive OneTouch at home; workstation 2
names its own) on Windows or Mac alike - with the identical layout beneath, so a later transfer of that drive's files
into the One Touch makes every recorded path literally true with no change to the database.  The label names the
drive; the letter D: in the cell is the One Touch's address, not a claim about which machine fetched the file.
"""
import datetime
import os
import pathlib
import re
import string
import sys

CANON_ROOT = "D:\\"
LAYOUT = ("NYC CRE Decoded", "Reproduction")
SOURCE_FOLDER = {"acris": "Acris", "richmond": "Richmond"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
BOROUGHS = {1: "Manhattan", 2: "Bronx", 3: "Brooklyn", 4: "Queens", 5: "Staten Island"}   # a registry fact (acris.borough_of), not a folder
_MDY = re.compile(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})")


def month_folder(m):
    """'08 Aug' - Explorer's alphabetical order is calendar order."""
    return "%02d %s" % (m, MONTHS[m - 1])


def day_folders(doc_id, recorded=None):
    """The folders under By Document for one document: ('2003', '05 May', '13') from the recorded date - a date, or
    the source's own text 'm/d/yyyy[ h:mm:ss AM]' - else a digital id's own date (yyyymmdd at its front), else the
    id split ('FT_4', '4100') with no day folder.  Exactly the old lane's rule, so the moved tree stays true."""
    if isinstance(recorded, (datetime.date, datetime.datetime)):
        return (str(recorded.year), month_folder(recorded.month), "%02d" % recorded.day)
    if recorded:
        m = _MDY.match(str(recorded))
        if m:
            mm, dd, yy = int(m.group(1)), int(m.group(2)), m.group(3)
            if 1 <= mm <= 12 and 1 <= dd <= 31:
                return (yy, month_folder(mm), "%02d" % dd)
    if len(doc_id) >= 8 and doc_id[:8].isdigit():
        mm, dd = int(doc_id[4:6]), int(doc_id[6:8])
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            return (doc_id[:4], month_folder(mm), "%02d" % dd)
    return tuple(part for part in (doc_id[:4], doc_id[4:8]) if part)     # a short id has no second folder (pathlib dropped the empty part in the old rule too)


def canonical(source, doc_id, recorded=None):
    """The One Touch address recorded in the cell: the tree, the source's folder, By Document, the day folders, the file."""
    folder = SOURCE_FOLDER.get(source.lower(), source.capitalize())
    parts = list(LAYOUT) + [folder, "By Document", *day_folders(doc_id, recorded), doc_id + ".pdf"]
    return CANON_ROOT + "\\".join(parts)


def local(root, canonical_path):
    """The same document under THIS workstation's drive root."""
    rel = canonical_path[len(CANON_ROOT):].split("\\")
    return pathlib.Path(root, *rel)


# ── finding the drive by its label ───────────────────────────────────────────────────────────────────────────────────

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
    """<drive>\\NYC CRE Decoded\\Reproduction - the phase's folder on this drive, created if missing."""
    p = pathlib.Path(drive_root, *LAYOUT)
    p.mkdir(parents=True, exist_ok=True)
    return p
