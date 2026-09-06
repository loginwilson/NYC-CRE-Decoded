r"""POPULATION - the one-time move of the phase's old home into its new ones: the One Touch tree and the cloud tables.

The old home of the record is `Legal Instruments.db` on the One Touch: one table, `navigation`, 24.1 million rows for
BOTH sources (acris ids: digital / BK_ / FT_; richmond ids: RC_) - id, the recorded details as JSON text, the pdf cell
(a path relative to the old acquisition store, or a word), plus two URL columns and a parcel key the new tables do not
carry (every URL is minted from the id; the parcels are inside the registry).  The old files sit under the old store's
`By Document` tree, both sources mixed, and a few thousand older documents sit in `By Parcel` and `By Party`, never
moved.  This program does the move once, in four commands, each of which can be re-run:

    python Population.py survey              read the old table once, in id order: rows per source, the words in each cell, the path
                                             shapes; writes population.survey.json and nothing else
    python Population.py organize [--dry]    the One Touch: the whole By Document tree renamed under Acris (one rename, instant);
                                             richmond's files (RC_) moved file by file into Richmond\By Document\ keeping their day
                                             folders; the By Parcel / By Party documents placed into By Document by the table (a
                                             duplicate of a file already there is left where it is and counted; a document the
                                             table has no file for is moved in and remembered for load); every move logged to
                                             population.moves.jsonl; NOTHING IS DELETED
    python Population.py load [--limit N]    stream the rows into reproduction.acris and reproduction.richmond by COPY, --slice
                                             rows per transaction, routed by the id, resuming after the last id landed
    python Population.py verify              counts on both sides by cell state, a sample of the recorded paths opened on the
                                             drive, a sample of registries compared value for value with the old table,
                                             reconcile() for both sources, the board rows; --only samples = the two samples
    python Population.py sweep               every file in both trees by directory listing: an empty file, or a small file that is
                                             not a whole PDF, is a stub - listed in population.sweep.jsonl with the other copies the
                                             moves log knows for that id; reads only
    python Population.py resolve [--dry]     the duplicates the file move met at a destination, and the stubs sweep listed, decided
                                             by the files: identical copies and other renderings staged under D:\Ignore, a stub
                                             replaced by its whole copy; the cell untouched; NOTHING IS DELETED

THE CELL MAPPING (old -> new), the same for both sources
    id                      -> doc_id                 (text; byte order on both sides - SQLite BINARY = Postgres collate "C" - so a resume is exact)
    recorded_details ''     -> registry NULL           (registration's to-do)
    recorded_details {json} -> registry (jsonb)        (the recorded details as the old lane landed them)
    pdf ''                  -> document NULL           (documentation's to-do) - unless organize found the file in By Parcel / By Party
    pdf 'pending'           -> document 'pending'      (the cell word, unchanged)
    pdf 'absent'            -> document 'absent'       (the cell word, unchanged)
    pdf 'imageless'         -> document 'absent'       (the old lane's word for "the source has no image": checked, none)
    pdf 'By Document\...'   -> document D:\NYC CRE Decoded\Reproduction\<Source>\By Document\...   the FULL path, the tree as organize leaves it
    anything else           -> named by the survey; load refuses to start until the word has a mapping here (fail closed)

THE PATH LAW (login 2026-09-05): the PDFs stay on the One Touch - Supabase is the table only - and the cell holds the full
path a person pastes into the File Explorer bar: `D:\NYC CRE Decoded\Reproduction\<Source>\By Document\<year>\<MM Mon>\<day>\<id>.pdf`
(`../../rulebook/storage.py`).  Workstation 2 writes the same path for a file on its own drive until the transfer.

The load is COPY in slices, one transaction per slice, so a failure leaves the tables at a slice boundary and the next run
continues after the last id in either table.  A slice the database refuses (a registry that is not valid JSON, a cell rule)
is retried row by row: the rows that pass load; a row that fails is written to population.rejects.jsonl with the reason and
loaded with the failing cell EMPTY, so the lane that owns the cell fills it again - nothing dropped, nothing invented.  The
disk: Supabase grows a disk only four times in 24 hours (90% -> +50%) and turns the project read-only at 95% once that is
spent, so the disk is set by hand above the tables' size BEFORE the load (~25 GB of rows; 40 GB asked for).
"""
import argparse, csv, datetime, io, json, os, pathlib, re, sqlite3, sys, time

HERE = pathlib.Path(__file__).resolve().parent
PHASE = HERE.parents[1]                                  # population -> workflow -> Reproduction
sys.path.insert(0, str(PHASE / "rulebook"))
import cloud, storage                                   # noqa: E402  the same env file, dsn() and path law every lane uses

OLD_DB = r"D:\CRE Decoding System\Legal Instruments.db"
OLD_STORE = r"D:\CRE Decoding System\02 Acquisitions\Legal Instruments Acquisition"
NEW_ROOT = storage.CANON_ROOT + "\\".join(storage.LAYOUT)                       # D:\NYC CRE Decoded\Reproduction
WORDS = {"": None, "pending": "pending", "absent": "absent", "imageless": "absent"}
SURVEY = HERE / "population.survey.json"
STATE = HERE / "population.state.json"
REJECTS = HERE / "population.rejects.jsonl"
MOVES = HERE / "population.moves.jsonl"
FOUND = HERE / "population.found.json"
ORGANIZE = HERE / "population.organize.json"
# the old stores' file names, three shapes: 2026-03-04_2026030400494002.pdf (By Parcel / By Party),
# 1967-10-25__FT_1560008681256__MISC__40235-151.pdf (Ignore's Acquisition by parcel), 2003010500046001.pdf (Ignore's Documents)
FILE_ID = re.compile(r"^(?:\d{4}-\d{2}-\d{2}_+)?((?:BK|FT|RC)_\d+|\d{13,16})(?:__.*)?\.pdf$", re.I)
IGNORE = r"D:\Ignore\02 Acquisitions\Legal Instruments Acquisition\Legal Instruments Acquisition Outputs"
OLD_STORES = (OLD_STORE + r"\By Parcel", OLD_STORE + r"\By Party", IGNORE + r"\Acquisition by parcel", IGNORE + r"\Documents")


def log(msg):
    print("%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def source_of(doc_id):
    return "richmond" if doc_id.startswith("RC_") else "acris"


def source_root(source):
    return NEW_ROOT + "\\" + storage.SOURCE_FOLDER[source]


def old(db):
    con = sqlite3.connect("file:%s?mode=ro" % pathlib.Path(db).as_posix(), uri=True, timeout=30)
    con.text_factory = str
    return con


def rows_after(con, after, n):
    """The next n old rows in id order after `after` ('' for the start): (id, recorded_details, pdf)."""
    return con.execute("select id, recorded_details, pdf from navigation where id > ? order by id limit ?", (after, n)).fetchall()


def old_store_cell(pdf):
    """A cell pointing into an old store (`By Party\\...`, `By Parcel\\...`): a to-do until the found map fills it."""
    return pdf.lower().startswith(("by party", "by parcel"))


def map_document(doc_id, pdf, found):
    """The new document cell, or (None, <unknown word>)."""
    if pdf in WORDS or old_store_cell(pdf):
        d = WORDS.get(pdf)
        if d is None and found and doc_id in found:
            return found[doc_id], None                  # organize placed this document from an old store (or found it already there)
        return d, None
    if pdf.startswith("By Document\\") and pdf.lower().endswith(".pdf"):
        return source_root(source_of(doc_id)) + "\\" + pdf, None
    return None, pdf


NUL_ESCAPE = "\\u0000"        # the six characters \u0000 inside JSON text: a NUL the old lane kept; jsonb cannot hold it


def map_registry(rd):
    """The registry cell, or (None, <unknown shape>).  A JSON text carrying the NUL escape is returned without it (the one
    character PostgreSQL's jsonb cannot represent) - the caller notes the row as modified."""
    if rd == "":
        return None, None
    s = rd.strip()
    if s.startswith("{") and s.endswith("}"):
        return s.replace(NUL_ESCAPE, ""), None
    if s in ('"pending"', '"absent"'):
        return s, None
    return None, rd[:40]


def load_found(with_log=False):
    """The documents organize placed: the found map, and - with_log - every `placed` / `restored` move in the log (the file
    name carries the id), so an interrupted old-store step loses nothing."""
    found = json.loads(FOUND.read_text(encoding="utf-8")) if FOUND.exists() else {}
    if with_log and MOVES.exists():
        for line in io.open(MOVES, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("kind") in ("placed", "restored") and not r.get("dry"):
                m = FILE_ID.match(os.path.basename(r["dst"]))
                if m:
                    found.setdefault(m.group(1), r["dst"])
    return found


# ── survey ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def survey(a):
    con = old(a.db)
    t0 = time.time()
    per = {s: {"rows": 0, "document": {"empty": 0, "pending": 0, "absent": 0, "imageless": 0, "path": 0, "old_store_path": 0},
               "registry": {"empty": 0, "object": 0, "word": 0}} for s in ("acris", "richmond")}
    doc_other, reg_other, shapes = {}, {}, {}
    after, n = "", 0
    while True:
        batch = rows_after(con, after, 200000)
        if not batch:
            break
        for did, rd, pdf in batch:
            n += 1
            p = per[source_of(did)]
            p["rows"] += 1
            if pdf in WORDS:
                p["document"]["empty" if pdf == "" else pdf] += 1
            elif old_store_cell(pdf):
                p["document"]["empty"] += 1               # a to-do until the found map fills it
                p["document"]["old_store_path"] += 1
            elif pdf.startswith("By Document\\") and pdf.lower().endswith(".pdf"):
                p["document"]["path"] += 1
                top = pdf.split("\\")[1] if "\\" in pdf else "?"
                shape = "year" if top.isdigit() else top[:4]
                shapes[shape] = shapes.get(shape, 0) + 1
            else:
                doc_other[pdf[:40]] = doc_other.get(pdf[:40], 0) + 1
            r, unknown = map_registry(rd)
            if unknown is not None:
                reg_other[unknown] = reg_other.get(unknown, 0) + 1
            elif r is None:
                p["registry"]["empty"] += 1
            elif r.startswith("{"):
                p["registry"]["object"] += 1
            else:
                p["registry"]["word"] += 1
        after = batch[-1][0]
        if n % 2000000 < 200000:
            log("surveyed %s rows (%.0f/s) ... last id %s" % ("{:,}".format(n), n / (time.time() - t0), after))
    con.close()
    out = {"rows": n, "per_source": per, "document_other": doc_other, "registry_other": reg_other, "path_top_folders": shapes,
           "last_id": after, "db": a.db, "at": datetime.datetime.now().isoformat(timespec="seconds"), "seconds": round(time.time() - t0)}
    SURVEY.write_text(json.dumps(out, indent=1), encoding="utf-8")
    log("SURVEY: %s rows in %d s" % ("{:,}".format(n), out["seconds"]))
    for s in ("acris", "richmond"):
        log("  %-8s rows %s | document %s | registry %s" % (s, "{:,}".format(per[s]["rows"]), json.dumps(per[s]["document"]), json.dumps(per[s]["registry"])))
    log("  document words without a mapping: %s" % (json.dumps(doc_other) if doc_other else "none"))
    log("  registry shapes without a mapping: %s" % (json.dumps(reg_other) if reg_other else "none"))
    log("  path top folders: %s" % json.dumps(shapes))
    return 1 if (doc_other or reg_other) else 0


# ── organize ─────────────────────────────────────────────────────────────────────────────────────────────────────────

_MADE = set()


def _move(src, dst, kind, moves, dry, left=None):
    """One file, one rename on the same volume, logged.  The rename is tried first and the questions are asked only when
    it fails, so the common case costs one metadata operation: FileExistsError = a duplicate already at dst (left where it
    is, counted); FileNotFoundError = the destination folder is not there yet (made, then one retry) or the source is
    missing.  Returns 'moved' | 'duplicate' | 'missing' | 'already'."""
    if dry:
        if os.path.exists(dst):
            return "duplicate"
        if not os.path.exists(src):
            return "missing"
        moves.write(json.dumps({"kind": kind, "src": src, "dst": dst, "dry": True}) + "\n")
        return "moved"
    for attempt in (1, 2):
        try:
            os.rename(src, dst)
            if left is not None:
                left.add(os.path.dirname(src))
            moves.write(json.dumps({"kind": kind, "src": src, "dst": dst}) + "\n")
            return "moved"
        except FileExistsError:
            moves.write(json.dumps({"kind": "duplicate-at-destination", "src": src, "dst": dst}) + "\n")
            return "duplicate"
        except FileNotFoundError:
            parent = os.path.dirname(dst)
            if attempt == 1 and parent not in _MADE:
                os.makedirs(parent, exist_ok=True)
                _MADE.add(parent)
                continue
            if os.path.exists(dst) and not os.path.exists(src):
                return "already"
            moves.write(json.dumps({"kind": "missing", "src": src, "dst": dst}) + "\n")
            return "missing"
    return "missing"


def organize(a):
    counts = {"tree_renamed": False, "richmond_moved": 0, "richmond_already": 0, "richmond_missing": 0, "richmond_duplicate": 0,
              "old_folders_moved": 0, "old_folders_duplicate": 0, "old_folders_restored": 0, "old_folders_unknown_id": 0,
              "old_folders_not_in_table": 0, "empty_dirs_removed": 0}
    found = load_found()
    con = old(a.db)
    only = a.only
    left = set()
    acris_root, rich_root = source_root("acris"), source_root("richmond")
    old_tree = os.path.join(OLD_STORE, "By Document")
    new_tree = acris_root + "\\By Document"
    with open(MOVES, "a", encoding="utf-8") as moves:
        # 1. the tree, one rename
        if not a.dry:
            os.makedirs(acris_root, exist_ok=True)
            os.makedirs(rich_root, exist_ok=True)
        if only in ("tree", "all") and os.path.isdir(old_tree) and not os.path.isdir(new_tree):
            log("renaming the By Document tree: %s -> %s" % (old_tree, new_tree))
            if not a.dry:
                os.rename(old_tree, new_tree)
            moves.write(json.dumps({"kind": "tree", "src": old_tree, "dst": new_tree, "dry": a.dry}) + "\n")
            counts["tree_renamed"] = True
        elif os.path.isdir(new_tree):
            log("the By Document tree already sits under %s" % acris_root)
        elif only in ("tree", "all"):
            raise SystemExit("no By Document tree at %s or %s - stop" % (old_tree, new_tree))
        if a.dry:
            log("DRY: the richmond and old-folder moves are counted against the OLD tree location")
            base = old_tree
        else:
            base = new_tree

        # 2. richmond's files out of the acris tree, keeping their day folders
        t0, seen = time.time(), 0
        after = "RC_"
        while only in ("richmond", "all"):
            rows = con.execute("select id, pdf from navigation where id > ? and id < 'RC`' and pdf like 'By Document%' order by id limit 20000", (after,)).fetchall()
            if not rows:
                break
            for did, pdf in rows:
                seen += 1
                rel = pdf[len("By Document\\"):]
                src = base + "\\" + rel
                dst = rich_root + "\\By Document\\" + rel
                r = _move(src, dst, "richmond", moves, a.dry, left)
                counts["richmond_" + r] += 1
            after = rows[-1][0]
            if seen % 200000 < 20000:
                log("richmond: %s rows seen, %s moved, %s missing (%.0f/s)" % ("{:,}".format(seen), "{:,}".format(counts["richmond_moved"]), "{:,}".format(counts["richmond_missing"]), seen / (time.time() - t0)))
        if only in ("richmond", "all"):
            log("richmond files: %s moved, %s already there, %s duplicates, %s missing on disk" % tuple("{:,}".format(counts[k]) for k in ("richmond_moved", "richmond_already", "richmond_duplicate", "richmond_missing")))

        # 3. the older documents in By Parcel / By Party, placed by the table
        t0, seen = time.time(), 0
        for top in (OLD_STORES if only in ("old", "all") else ()):
            if not os.path.isdir(top):
                log("old store not found, skipped: %s" % top)
                continue
            log("old store: %s" % top)
            for dirpath, dirs, files in os.walk(top):
                for f in files:
                    if a.limit and seen >= a.limit:
                        break
                    if not f.lower().endswith(".pdf"):
                        continue
                    seen += 1
                    if seen % 20000 == 0:
                        log("old stores: %s files seen - placed %s, restored %s, duplicates %s, not in table %s (%.0f/s)" % (
                            "{:,}".format(seen), "{:,}".format(counts["old_folders_moved"]), "{:,}".format(counts["old_folders_restored"]),
                            "{:,}".format(counts["old_folders_duplicate"]), "{:,}".format(counts["old_folders_not_in_table"]), seen / (time.time() - t0)))
                    m = FILE_ID.match(f)
                    if not m:
                        counts["old_folders_unknown_id"] += 1
                        moves.write(json.dumps({"kind": "unknown-filename", "src": os.path.join(dirpath, f)}) + "\n")
                        continue
                    did = m.group(1)
                    if did in found:
                        counts["old_folders_duplicate"] += 1          # a second copy of a document already placed this run
                        moves.write(json.dumps({"kind": "duplicate", "src": os.path.join(dirpath, f), "of": found[did], "doc_id": did}) + "\n")
                        continue
                    row = con.execute("select recorded_details, pdf from navigation where id = ?", (did,)).fetchone()
                    src = os.path.join(dirpath, f)
                    if row is None:
                        counts["old_folders_not_in_table"] += 1
                        moves.write(json.dumps({"kind": "not-in-table", "src": src, "doc_id": did}) + "\n")
                        continue
                    rd, pdf = row
                    if pdf.startswith("By Document\\"):
                        rel = pdf[len("By Document\\"):]
                        at = source_root(source_of(did)) + "\\By Document\\" + rel
                        if os.path.exists(at) or (a.dry and os.path.exists(old_tree + "\\" + rel)):
                            counts["old_folders_duplicate"] += 1
                            moves.write(json.dumps({"kind": "duplicate", "src": src, "of": at, "doc_id": did}) + "\n")
                        else:
                            r = _move(src, at, "restored", moves, a.dry)
                            counts["old_folders_restored" if r == "moved" else "old_folders_duplicate"] += 1
                        continue
                    # the table has no file for this document: place it by the recorded date, remember it for load
                    try:
                        reg = json.loads(rd) if rd.strip().startswith("{") else {}
                    except ValueError:
                        reg = {}
                    dst = storage.canonical(source_of(did), did, reg.get("recorded"))
                    r = _move(src, dst, "placed", moves, a.dry)
                    if r == "moved":
                        counts["old_folders_moved"] += 1
                        found[did] = dst
                    elif r == "duplicate":
                        counts["old_folders_duplicate"] += 1
                        found.setdefault(did, dst)                    # a file is already at the recorded place: the cell gets that path
                    else:
                        counts["old_folders_unknown_id"] += 1
                        moves.write(json.dumps({"kind": "vanished", "src": src, "doc_id": did}) + "\n")
        if only in ("old", "all"):
            log("old folders: %s placed (remembered for load), %s restored to their recorded place, %s duplicates left in place, %s not in the table, %s unreadable names" % tuple(
                "{:,}".format(counts[k]) for k in ("old_folders_moved", "old_folders_restored", "old_folders_duplicate", "old_folders_not_in_table", "old_folders_unknown_id")))

        # 4. folders the moves emptied: rmdir refuses a folder with anything in it, so only truly empty ones go
        if not a.dry:
            for d in sorted(left, key=len, reverse=True):
                for _ in range(3):                       # the day folder, then its month, then its year if each emptied
                    try:
                        os.rmdir(d); counts["empty_dirs_removed"] += 1
                        d = os.path.dirname(d)
                    except OSError:
                        break
    con.close()
    if not a.dry and only in ("old", "all"):
        FOUND.write_text(json.dumps(found, indent=0), encoding="utf-8")
        log("found map: %s documents the table had no file for now have one - `apply-found` writes their cells" % "{:,}".format(len(found)))
    counts["at"] = datetime.datetime.now().isoformat(timespec="seconds"); counts["dry"] = a.dry; counts["only"] = only
    ORGANIZE.write_text(json.dumps(counts, indent=1), encoding="utf-8")
    log("ORGANIZE %s: %s" % ("(dry)" if a.dry else "done", json.dumps(counts)))
    return 0


# ── load ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def cell_rows(batch, found, rejects):
    """Old rows -> new rows per source; a row whose cell has no mapping goes to the rejects with that cell empty."""
    out = {"acris": [], "richmond": []}
    for did, rd, pdf in batch:
        d, unk_d = map_document(did, pdf, found)
        r, unk_r = map_registry(rd)
        if unk_d is not None or unk_r is not None:
            rejects.write(json.dumps({"doc_id": did, "reason": "no mapping", "document": unk_d, "registry": unk_r}) + "\n")
        if r is not None and NUL_ESCAPE in rd:
            rejects.write(json.dumps({"doc_id": did, "reason": "nul escape stripped from the registry (jsonb cannot hold \\u0000)", "count": rd.count(NUL_ESCAPE)}) + "\n")
        s = source_of(did)
        out[s].append((s, did, r, d))
    return out


def copy_rows(cur, source, rows):
    if not rows:
        return
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in rows:
        w.writerow(["" if v is None else v for v in r])   # an unquoted empty field is NULL in COPY csv; no cell is ever the empty string
    buf.seek(0)
    cur.copy_expert("copy reproduction.%s (source, doc_id, registry, document) from stdin with (format csv)" % source, buf)


def land_one(pg, s, r, rejects):
    """One refused row: written to the rejects with the reason, landed with the failing cell EMPTY (the lane fills it again)."""
    import psycopg2
    try:
        with pg.cursor() as cur:
            copy_rows(cur, s, [r])
        pg.commit()
    except psycopg2.Error as e:
        pg.rollback()
        full = str(e).strip()
        reason = full.splitlines()[0][:160]
        low = full.lower()                       # the COPY context names the column: "column registry" / "column document"
        bad_reg = "registry" in low or "json" in low or "unicode" in low
        bad_doc = "document" in low
        if not (bad_reg or bad_doc):
            bad_reg = bad_doc = True             # cannot tell: both cells empty, the lanes fill them again
        rejects.write(json.dumps({"doc_id": r[1], "reason": reason, "blanked": [c for c, b in (("registry", bad_reg), ("document", bad_doc)) if b],
                                  "registry": (r[2] or "")[:80], "document": r[3]}) + "\n")
        rejects.flush()
        blank = (s, r[1], None if bad_reg else r[2], None if bad_doc else r[3])
        try:
            with pg.cursor() as cur:
                copy_rows(cur, s, [blank])
            pg.commit()
            log("REJECT %s %s: %s - landed with %s empty" % (s, r[1], reason, "+".join(c for c, b in (("registry", bad_reg), ("document", bad_doc)) if b)))
        except psycopg2.Error as e2:
            pg.rollback()
            rejects.write(json.dumps({"doc_id": r[1], "reason": "NOT LANDED: " + str(e2).strip().splitlines()[0][:160]}) + "\n")
            rejects.flush()
            log("NOT LANDED %s %s: %s" % (s, r[1], str(e2).strip().splitlines()[0][:160]))


def land_split(pg, s, rows, rejects):
    """A refused set of rows lands by halving: a bad row is found in log2(n) round trips (a row-by-row retry of a
    50,000-row slice ran at 1.2 rows/s on 2026-09-05), a transient refusal costs two.  In id order, so a resume after
    max(doc_id) stays exact."""
    import psycopg2
    if not rows:
        return
    if len(rows) == 1:
        land_one(pg, s, rows[0], rejects)
        return
    try:
        with pg.cursor() as cur:
            copy_rows(cur, s, rows)
        pg.commit()
    except psycopg2.Error as e:
        pg.rollback()
        half = len(rows) // 2
        log("  %s rows %s..%s refused (%s) - halving" % ("{:,}".format(len(rows)), rows[0][1], rows[-1][1], str(e).strip().splitlines()[0][:120]))
        land_split(pg, s, rows[:half], rejects)
        land_split(pg, s, rows[half:], rejects)


def load(a):
    import psycopg2
    if not SURVEY.exists():
        raise SystemExit("run `survey` first so every word in the old table is known")
    sv = json.loads(SURVEY.read_text(encoding="utf-8"))
    if sv.get("document_other") or sv.get("registry_other"):
        raise SystemExit("the survey found cells without a mapping - add them to WORDS first: %s %s" % (sv.get("document_other"), sv.get("registry_other")))
    found = load_found()
    if not ORGANIZE.exists() or json.loads(ORGANIZE.read_text(encoding="utf-8")).get("dry"):
        log("WARNING: organize has not run for real - the paths written assume the tree under %s" % NEW_ROOT)
    con = old(a.db)
    pg = pg_connect()
    pg.autocommit = False
    with pg.cursor() as cur:
        cur.execute("select coalesce(max(doc_id), '') from reproduction.acris")
        a_max = cur.fetchone()[0]
        cur.execute("select coalesce(max(doc_id), '') from reproduction.richmond")
        r_max = cur.fetchone()[0]
        cur.execute("select (select reltuples::bigint from pg_class where oid = 'reproduction.acris'::regclass),"
                    " (select reltuples::bigint from pg_class where oid = 'reproduction.richmond'::regclass)")
        have = cur.fetchone()                   # the planner's estimate: a full count on the populated table is minutes of IO
    pg.commit()
    after = max(a_max, r_max)
    log("cloud holds about acris %s / richmond %s rows (planner estimate); continuing after id %r" % ("{:,}".format(have[0]), "{:,}".format(have[1]), after))
    t0, n, slices = time.time(), 0, 0
    with open(REJECTS, "a", encoding="utf-8") as rejects:
        while a.limit is None or n < a.limit:
            want = a.slice if a.limit is None else min(a.slice, a.limit - n)
            batch = rows_after(con, after, want)
            if not batch:
                log("the old table is exhausted after id %r" % after)
                break
            rows = cell_rows(batch, found, rejects)
            try:
                with pg.cursor() as cur:
                    for s in ("acris", "richmond"):
                        copy_rows(cur, s, rows[s])
                pg.commit()
            except psycopg2.Error as e:
                pg.rollback()
                log("slice after %r refused (%s) - halving it" % (after, str(e).strip().splitlines()[0][:160]))
                for s in ("acris", "richmond"):
                    land_split(pg, s, rows[s], rejects)
            after = batch[-1][0]
            n += len(batch)
            slices += 1
            STATE.write_text(json.dumps({"after": after, "loaded_this_run": n, "at": datetime.datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
            if slices % 10 == 1 or len(batch) < want:
                el = time.time() - t0
                log("loaded %s rows this run (%.0f/s, %.1f min) ... after %s" % ("{:,}".format(n), n / el if el else 0, el / 60, after))
    con.close()
    pg.close()
    log("LOAD: %s rows this run in %.1f min" % ("{:,}".format(n), (time.time() - t0) / 60))
    return 0


# ── verify ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def found_shift(pg, con, found):
    """What apply-found has written so far, by the cell it overwrote: a found document counts only when its cloud cell IS
    the found path (so verify is exact whatever the timing of the placement still running), and it is classed by its cell
    in the OLD table - empty (or an old-store path), pending, absent / imageless; an old path (a restored or a duplicate
    file) shifts nothing.  {source: {"empty": n, "pending": n, "absent": n}}."""
    import psycopg2
    shift = {s: {"empty": 0, "pending": 0, "absent": 0} for s in ("acris", "richmond")}
    ids = sorted(found)
    t0 = time.time()
    for i in range(0, len(ids), 10000):
        by_source = {}
        for did in ids[i:i + 10000]:
            by_source.setdefault(source_of(did), []).append(did)
        for s, part in by_source.items():
            for attempt in (1, 2, 3):
                try:
                    with pg.cursor() as cur:
                        cur.execute("select doc_id, document from reproduction.%s where doc_id = any(%%s)" % s, (part,))
                        cloud_cells = cur.fetchall()
                    pg.commit()
                    break
                except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                    log("found_shift: the cloud line died (%s) - reconnecting, chunk redone (attempt %d)" % (str(e).strip().splitlines()[0][:80], attempt))
                    if attempt == 3:
                        raise
                    try:
                        pg.close()
                    except Exception:
                        pass
                    pg = pg_connect()
            for did, doc in cloud_cells:
                if doc != found[did]:
                    continue
                row = con.execute("select pdf from navigation where id = ?", (did,)).fetchone()
                if row is None:
                    continue
                pdf = row[0]
                if pdf == "" or old_store_cell(pdf):
                    shift[s]["empty"] += 1
                elif pdf in ("absent", "imageless"):
                    shift[s]["absent"] += 1
                elif pdf == "pending":
                    shift[s]["pending"] += 1
        if (i // 10000) % 5 == 4:
            log("found_shift: %s of %s read (%.0f/s)" % ("{:,}".format(min(i + 10000, len(ids))), "{:,}".format(len(ids)), min(i + 10000, len(ids)) / (time.time() - t0)))
    return shift, pg


def verify(a):
    import psycopg2
    samples_only = a.only == "samples"
    sv = json.loads(SURVEY.read_text(encoding="utf-8")) if SURVEY.exists() else None
    pg = pg_connect()
    con = old(OLD_DB)
    reg_total = {"empty": 0, "object": 0, "word": 0}
    ok = True
    if samples_only:
        shift = None
        log("samples only: the path sample and the registry sample - no counts, no found map, no reconcile")
    else:
        found = load_found(with_log=True)
        log("found documents on record: %s - reading which of them apply-found has written, and what their old cell was" % "{:,}".format(len(found)))
        shift, pg = found_shift(pg, con, found)           # the connection may have been renewed on the way
    with pg.cursor() as cur:
        for s in ("acris", "richmond"):
            cur.execute("select reltuples::bigint from pg_class where relname = %s and relnamespace = 'reproduction'::regnamespace", (s,))
            est = max(cur.fetchone()[0], 1)
            if samples_only:
                got = None
            else:
                cur.execute("""select count(*),
                                      count(*) filter (where document is null),
                                      count(*) filter (where document = 'pending'),
                                      count(*) filter (where document = 'absent'),
                                      count(*) filter (where left(document, %s) = %s),
                                      count(*) filter (where registry is null),
                                      count(*) filter (where jsonb_typeof(registry) = 'object'),
                                      count(*) filter (where jsonb_typeof(registry) = 'string')
                               from reproduction.%s""" % ("%s", "%s", s), (len(storage.CANON_ROOT), storage.CANON_ROOT))
                got = cur.fetchone()
                log("%-8s cloud: rows %s | document empty %s pending %s absent %s path %s | registry empty %s object %s word %s" % ((s,) + tuple("{:,}".format(x) for x in got)))
            if sv and got is not None:
                p = sv["per_source"][s]
                sh = shift[s]
                moved = sh["empty"] + sh["pending"] + sh["absent"]
                exp = (p["rows"], p["document"]["empty"] - sh["empty"], p["document"]["pending"] - sh["pending"],
                       p["document"]["absent"] + p["document"]["imageless"] - sh["absent"], p["document"]["path"] + moved)
                log("%-8s old:   rows %s | document empty %s pending %s absent %s path %s   (apply-found wrote %s cells: %s were empty, %s pending, %s absent)" % (
                    (s,) + tuple("{:,}".format(x) for x in exp) + tuple("{:,}".format(x) for x in (moved, sh["empty"], sh["pending"], sh["absent"]))))
                if exp != tuple(got[:5]):
                    ok = False
                    log("%-8s DIFFERENT - read population.rejects.jsonl and the two lines above" % s)
                for k, v in zip(("empty", "object", "word"), got[5:]):
                    reg_total[k] += v
            cur.execute("select doc_id, document from reproduction.%s tablesample system (0.02) where left(document, %%s) = %%s limit %%s" % s,
                        (len(storage.CANON_ROOT), storage.CANON_ROOT, a.sample))
            sample = cur.fetchall()
            exists = sum(1 for _, p in sample if os.path.exists(p))
            log("%-8s paths: %d of %d sampled cells open a file on the drive" % (s, exists, len(sample)))
            for did, p in sample[:2]:
                log("  e.g. %s -> %s (%s)" % (did, p, "exists" if os.path.exists(p) else "MISSING"))
            # the registry, value for value: a random sample of cells, each read back from the old row by id.  Equal means
            # the same JSON value - jsonb keeps values, not key order or spacing - with the NUL escape set aside (map_registry).
            # An id the old table never had is a row a lane landed after the load (richmond's sync of 2026-09-05): counted, not a defect.
            pct = min(100.0, max(0.001, 200.0 * a.registry_sample / est))
            cur.execute("select doc_id, registry from reproduction.%s tablesample system (%.4f) limit %%s" % (s, pct), (a.registry_sample,))
            same = diff = new = 0
            for did, reg in cur.fetchall():
                r = con.execute("select recorded_details from navigation where id = ?", (did,)).fetchone()
                if r is None:
                    new += 1
                    continue
                mapped, _ = map_registry(r[0])
                old_val = json.loads(mapped) if mapped is not None else None
                if old_val == reg:
                    same += 1
                else:
                    diff += 1
                    if diff <= 5:
                        log("  DIFFERENT registry: %s | old %s | cloud %s" % (did, str(old_val)[:80], str(reg)[:80]))
            log("%-8s registry: %d of %d sampled cells equal the old table's recorded details value for value (%d different; %d landed after the load, not in the old table)" % (
                s, same, same + diff, diff, new))
            if diff:
                ok = False
            if not samples_only:
                cur.execute("select * from reproduction.reconcile(%s)", (s,))
                log("%-8s reconcile: %s" % (s, cur.fetchall()))
                pg.commit()
                cur.execute("select lane, landed, needed from reproduction.%s_update_lanes order by lane" % s)
                for lane, landed, needed in cur.fetchall():
                    log("  board %-16s landed %s / needed %s (%.2f%%)" % (lane, "{:,}".format(landed), "{:,}".format(needed), 100.0 * landed / needed if needed else 0))
    pg.close()
    con.close()
    if sv and not samples_only:
        rt = sv.get("registry_totals") or {}
        log("registry, both sources together: cloud %s | old %s" % (json.dumps(reg_total), json.dumps(rt)))
        if any(reg_total[k] != rt.get(k) for k in reg_total):
            ok = False
            log("registry DIFFERENT")
    log("VERIFY: %s" % ("MATCH on both sources" if ok else "DIFFERENCES - see above"))
    return 0 if ok else 1


def pg_connect():
    """The population's connection: no statement timeout - the project's default (two minutes) cancels a count or an update
    over the populated table (apply-found was cancelled at 21:13 on 2026-09-05); one program name."""
    import psycopg2
    pg = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="population",
                          keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
    with pg.cursor() as cur:
        cur.execute("set statement_timeout = 0")
    pg.commit()
    return pg


def apply_found(a):
    """The documents organize placed from the old stores: their full paths into the cells that had none (NULL, pending, absent -
    a file on disk outranks a verdict word), never over an existing path.  In chunks of 5,000 by the primary key, one
    transaction per chunk (one UPDATE over the whole join was cancelled by the statement timeout); then reconcile."""
    found = load_found(with_log=True)
    if not found:
        raise SystemExit("nothing found: no population.found.json and no placed move in the log - run organize first")
    log("documents to write: %s (the found map and the moves log together)" % "{:,}".format(len(found)))
    pg = pg_connect()
    per = {"acris": [], "richmond": []}
    for did in sorted(found):
        per[source_of(did)].append((did, found[did]))
    with pg.cursor() as cur:
        for s in ("acris", "richmond"):
            filled = other = 0
            pairs = per[s]
            for i in range(0, len(pairs), 5000):
                chunk = pairs[i:i + 5000]
                ids = [d for d, _ in chunk]
                paths = [q for _, q in chunk]
                cur.execute("""select count(*) from reproduction.%s w
                               join unnest(%%s::text[], %%s::text[]) as v(doc_id, document) on v.doc_id = w.doc_id
                               where left(w.document, %%s) = %%s and w.document <> v.document""" % s,
                            (ids, paths, len(storage.CANON_ROOT), storage.CANON_ROOT))
                other += cur.fetchone()[0]
                cur.execute("""update reproduction.%s w set document = v.document
                               from unnest(%%s::text[], %%s::text[]) as v(doc_id, document)
                               where w.doc_id = v.doc_id and (w.document is null or w.document in ('pending', 'absent'))""" % s,
                            (ids, paths))
                filled += cur.rowcount
                pg.commit()
                if (i // 5000) % 10 == 0:
                    log("%-8s %s of %s found documents read - %s cells filled so far" % (
                        s, "{:,}".format(min(i + 5000, len(pairs))), "{:,}".format(len(pairs)), "{:,}".format(filled)))
            log("%-8s cells filled from the found map: %s" % (s, "{:,}".format(filled)))
            log("%-8s cells that already held a different path (left alone): %s" % (s, "{:,}".format(other)))
        for s in ("acris", "richmond"):
            cur.execute("select * from reproduction.reconcile(%s)", (s,))
            log("%-8s reconcile: %s" % (s, cur.fetchall()))
            pg.commit()
    pg.close()
    return 0


# ── sweep / resolve ──────────────────────────────────────────────────────────────────────────────────────────────────
STAGE = r"D:\Ignore\Staged by population"         # copies the tree does not need, by their origin path: a person deletes them with D:\Ignore
SWEEP = HERE / "population.sweep.jsonl"
RESOLVE = HERE / "population.resolve.json"
SMALL = 16 * 1024                                  # a file under this is opened and checked; a stub is 0-7 KB, a scanned page is bigger


def whole(path):
    """A whole PDF: `%PDF-` at the start and `%%EOF` within the last 64 bytes.  What the old lane saved on a refused pull -
    an error page, an empty file - fails one or both."""
    try:
        n = os.path.getsize(path)
        with open(path, "rb") as h:
            head = h.read(5)
            h.seek(max(0, n - 64))
            tail = h.read()
        return head == b"%PDF-" and b"%%EOF" in tail
    except OSError:
        return False


def same_bytes(a, b):
    import hashlib
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    digests = []
    for p in (a, b):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        digests.append(h.digest())
    return digests[0] == digests[1]


def doc_id_of(path):
    m = FILE_ID.match(os.path.basename(path))
    return m.group(1) if m else None


def stage(path, why, moves, dry):
    """A copy the tree does not need goes under STAGE\\<why>\\<its path without the drive letter> - moved, never deleted."""
    dst = os.path.join(STAGE, why, os.path.splitdrive(path)[1].lstrip("\\"))
    if not dry:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(path, dst)
    moves.write(json.dumps({"kind": "staged", "why": why, "src": path, "dst": dst}) + "\n")
    return dst


def sweep(a):
    """Every file in both trees by directory listing (the size comes with the listing; no file at or above SMALL is opened -
    the old lanes wrote `.part` and renamed on completion, so a cut download never wore a .pdf name).  An empty file, or a
    small file that is not a whole PDF, is a stub: written to population.sweep.jsonl with the other copies the moves log
    knows for that id (an old-store duplicate, a duplicate-at-destination source).  Reads only."""
    alternates = {}
    if MOVES.exists():
        for line in io.open(MOVES, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("dry"):
                continue
            k = r.get("kind")
            if k == "duplicate" and r.get("doc_id"):
                alternates.setdefault(r["doc_id"], []).append(r["src"])
            elif k == "duplicate-at-destination":
                did = doc_id_of(r["dst"])
                if did:
                    alternates.setdefault(did, []).append(r["src"])
    counts = {"folders": 0, "files": 0, "empty": 0, "small_opened": 0, "stubs": 0, "stubs_with_alternate": 0, "unreadable_folders": 0}
    t0 = time.time()
    with open(SWEEP, "w", encoding="utf-8") as out:
        for s in ("acris", "richmond"):
            stack = [os.path.join(source_root(s), "By Document")]
            while stack:
                d = stack.pop()
                counts["folders"] += 1
                try:
                    with os.scandir(d) as it:
                        for e in it:
                            if e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                                continue
                            counts["files"] += 1
                            if counts["files"] % 500000 == 0:
                                log("%s: %s files listed, %s stubs so far (%.0f files/s)" % (s, "{:,}".format(counts["files"]), counts["stubs"], counts["files"] / (time.time() - t0)))
                            n = e.stat(follow_symlinks=False).st_size
                            if n >= SMALL:
                                continue
                            if n == 0:
                                counts["empty"] += 1
                                reason = "empty"
                            else:
                                counts["small_opened"] += 1
                                reason = None if whole(e.path) else "not a whole pdf"
                            if not reason:
                                continue
                            counts["stubs"] += 1
                            did = doc_id_of(e.name)
                            alts = [p for p in alternates.get(did, []) if os.path.exists(p) and whole(p)] if did else []
                            if alts:
                                counts["stubs_with_alternate"] += 1
                            out.write(json.dumps({"source": s, "doc_id": did, "path": e.path, "bytes": n, "reason": reason, "alternates": alts}) + "\n")
                except OSError as err:
                    counts["unreadable_folders"] += 1
                    log("unreadable folder: %s (%s)" % (d, err))
    counts["at"] = datetime.datetime.now().isoformat(timespec="seconds")
    counts["seconds"] = round(time.time() - t0)
    log("SWEEP done: %s - the stubs are in %s" % (json.dumps(counts), SWEEP.name))
    return 0


def resolve(a):
    """The file the cell names must be the document.  Two lists are decided by the files, never by the name:
    (1) the duplicates the file move met at a destination (a file already there under the same id), (2) the stubs sweep
    listed with a whole copy elsewhere.  Identical bytes: the second copy is staged.  The destination not a whole PDF and
    the other copy whole: the stub is staged and the whole file moved into its place - the cell was right about the place,
    wrong about the file, and is now right.  Both whole and different (two renderings from two pulls): the cell's file
    stays, the other is staged.  Neither whole: reported, nothing moved - that cell needs its lane.  Nothing is deleted."""
    pairs = {}
    if MOVES.exists():
        for line in io.open(MOVES, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("kind") == "duplicate-at-destination" and not r.get("dry"):
                pairs[r["dst"]] = r["src"]                  # the last note per destination
    stubs = []
    if SWEEP.exists():
        for line in io.open(SWEEP, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("alternates"):
                stubs.append((r["path"], r["alternates"][0]))
            else:
                stubs.append((r["path"], None))
    counts = {"pairs": len(pairs), "swept_stubs": len(stubs), "identical_staged": 0, "stub_replaced": 0, "other_rendering_staged": 0,
              "neither_whole": 0, "stub_without_copy": 0, "already": 0}
    log("duplicates at a destination: %s; stubs from the sweep: %s%s" % ("{:,}".format(len(pairs)), "{:,}".format(len(stubs)), "  (DRY: nothing touched)" if a.dry else ""))
    moves = io.StringIO() if a.dry else open(MOVES, "a", encoding="utf-8")
    try:
        for dst, src in sorted(pairs.items()) + [(p, alt) for p, alt in stubs]:
            if src is None:
                counts["stub_without_copy"] += 1
                log("stub without a whole copy anywhere: %s - its cell needs its lane" % dst)
                continue
            if not os.path.exists(src):
                counts["already"] += 1                       # resolved on an earlier run
                continue
            if not os.path.exists(dst):                      # the destination went missing since the note: the copy takes its place
                if not a.dry:
                    os.rename(src, dst)
                moves.write(json.dumps({"kind": "resolved", "why": "destination missing", "src": src, "dst": dst}) + "\n")
                counts["stub_replaced"] += 1
                continue
            d_ok, s_ok = whole(dst), whole(src)
            if d_ok and same_bytes(src, dst):
                stage(src, "duplicate", moves, a.dry)
                counts["identical_staged"] += 1
            elif s_ok and not d_ok:
                ds, ss = os.path.getsize(dst), os.path.getsize(src)
                stage(dst, "stub", moves, a.dry)
                if not a.dry:
                    os.rename(src, dst)
                moves.write(json.dumps({"kind": "resolved", "why": "stub replaced", "src": src, "dst": dst, "stub_bytes": ds, "bytes": ss}) + "\n")
                counts["stub_replaced"] += 1
                log("stub replaced: %s (%s bytes staged; the document, %s bytes, in its place)" % (dst, "{:,}".format(ds), "{:,}".format(ss)))
            elif s_ok and d_ok:
                stage(src, "other rendering", moves, a.dry)
                counts["other_rendering_staged"] += 1
            else:
                counts["neither_whole"] += 1
                moves.write(json.dumps({"kind": "neither-whole", "src": src, "dst": dst}) + "\n")
                log("NEITHER WHOLE: %s and %s - nothing moved; the cell needs its lane" % (dst, src))
    finally:
        if a.dry:
            log("DRY: %d log lines would be written" % moves.getvalue().count("\n"))
        moves.close()
    counts["at"] = datetime.datetime.now().isoformat(timespec="seconds")
    counts["dry"] = a.dry
    if not a.dry:
        RESOLVE.write_text(json.dumps(counts, indent=1), encoding="utf-8")
    log("RESOLVE %s: %s" % ("(dry)" if a.dry else "done", json.dumps(counts)))
    return 0 if not (counts["neither_whole"] or counts["stub_without_copy"]) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="the one-time move of Legal Instruments.db and the old document tree into their new homes")
    ap.add_argument("--db", default=OLD_DB, help="the old SQLite table (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("survey")
    o = sub.add_parser("organize")
    o.add_argument("--dry", action="store_true", help="count and log what would move; move nothing")
    o.add_argument("--only", choices=("tree", "richmond", "old", "all"), default="all", help="one step, or all (default)")
    o.add_argument("--limit", type=int, default=0, help="old stores: stop after this many files (a sampled dry run); 0 = all")
    sub.add_parser("apply-found", help="write the paths organize found for documents the table had no file for; then reconcile")
    p = sub.add_parser("load")
    p.add_argument("--limit", type=int, default=None, help="rows this run (default: to the end)")
    p.add_argument("--slice", type=int, default=50000, help="rows per COPY transaction (default: %(default)s)")
    v = sub.add_parser("verify")
    v.add_argument("--sample", type=int, default=200, help="recorded paths to open on the drive per source (default: %(default)s)")
    v.add_argument("--registry-sample", type=int, default=2000, help="cells per source compared value for value with the old table's recorded details (default: %(default)s)")
    v.add_argument("--only", choices=("all", "samples"), default="all", help="samples: the path sample and the registry sample only - no counts, no found map, no reconcile")
    sub.add_parser("sweep", help="every file in both trees by listing: empty files and small non-PDFs listed with their other copies; reads only")
    r = sub.add_parser("resolve", help="duplicates the move met at a destination, and the stubs sweep listed: decided by the files, copies staged, nothing deleted")
    r.add_argument("--dry", action="store_true", help="say what would be staged or moved; touch nothing")
    a = ap.parse_args(argv)
    return {"survey": survey, "organize": organize, "load": load, "verify": verify, "apply-found": apply_found,
            "sweep": sweep, "resolve": resolve}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
