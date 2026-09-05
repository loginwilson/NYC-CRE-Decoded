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
                                             drive, reconcile() for both sources, the board rows

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


def map_registry(rd):
    if rd == "":
        return None, None
    s = rd.strip()
    if s.startswith("{") and s.endswith("}"):
        return s, None
    if s in ('"pending"', '"absent"'):
        return s, None
    return None, rd[:40]


def load_found():
    return json.loads(FOUND.read_text(encoding="utf-8")) if FOUND.exists() else {}


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
    pg = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="population")
    pg.autocommit = False
    with pg.cursor() as cur:
        cur.execute("select coalesce(max(doc_id), '') from reproduction.acris")
        a_max = cur.fetchone()[0]
        cur.execute("select coalesce(max(doc_id), '') from reproduction.richmond")
        r_max = cur.fetchone()[0]
        cur.execute("select (select count(*) from reproduction.acris), (select count(*) from reproduction.richmond)")
        have = cur.fetchone()
    pg.commit()
    after = max(a_max, r_max)
    log("cloud holds acris %s / richmond %s rows; continuing after id %r" % ("{:,}".format(have[0]), "{:,}".format(have[1]), after))
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
                log("slice after %r refused (%s) - loading it row by row" % (after, str(e).strip().splitlines()[0][:120]))
                for s in ("acris", "richmond"):
                    for r in rows[s]:
                        try:
                            with pg.cursor() as cur:
                                copy_rows(cur, s, [r])
                            pg.commit()
                        except psycopg2.Error as e2:
                            pg.rollback()
                            reason = str(e2).strip().splitlines()[0][:160]
                            rejects.write(json.dumps({"doc_id": r[1], "reason": reason, "registry": (r[2] or "")[:80], "document": r[3]}) + "\n")
                            rejects.flush()
                            low = reason.lower()
                            blank = (s, r[1], None if ("registry" in low or "json" in low) else r[2], None if "document" in low else r[3])
                            with pg.cursor() as cur:
                                copy_rows(cur, s, [blank])
                            pg.commit()
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

def verify(a):
    import psycopg2
    sv = json.loads(SURVEY.read_text(encoding="utf-8")) if SURVEY.exists() else None
    found = load_found()
    pg = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="population")
    ok = True
    with pg.cursor() as cur:
        for s in ("acris", "richmond"):
            cur.execute("""select count(*),
                                  count(*) filter (where document is null),
                                  count(*) filter (where document = 'pending'),
                                  count(*) filter (where document = 'absent'),
                                  count(*) filter (where document like %s),
                                  count(*) filter (where registry is null),
                                  count(*) filter (where jsonb_typeof(registry) = 'object'),
                                  count(*) filter (where jsonb_typeof(registry) = 'string')
                           from reproduction.%s""" % ("%s", s), (storage.CANON_ROOT + "%",))
            got = cur.fetchone()
            log("%-8s cloud: rows %s | document empty %s pending %s absent %s path %s | registry empty %s object %s word %s" % ((s,) + tuple("{:,}".format(x) for x in got)))
            if sv:
                p = sv["per_source"][s]
                placed = sum(1 for d in found if source_of(d) == s)
                exp = (p["rows"], p["document"]["empty"] - placed, p["document"]["pending"], p["document"]["absent"] + p["document"]["imageless"],
                       p["document"]["path"] + placed, p["registry"]["empty"], p["registry"]["object"], p["registry"]["word"])
                log("%-8s old:   rows %s | document empty %s pending %s absent %s path %s | registry empty %s object %s word %s" % ((s,) + tuple("{:,}".format(x) for x in exp)))
                if exp != tuple(got):
                    ok = False
                    log("%-8s DIFFERENT - read population.rejects.jsonl and the two lines above" % s)
            cur.execute("select doc_id, document from reproduction.%s tablesample system (0.02) where document like %%s limit %%s" % s, (storage.CANON_ROOT + "%", a.sample))
            sample = cur.fetchall()
            exists = sum(1 for _, p in sample if os.path.exists(p))
            log("%-8s paths: %d of %d sampled cells open a file on the drive" % (s, exists, len(sample)))
            for did, p in sample[:2]:
                log("  e.g. %s -> %s (%s)" % (did, p, "exists" if os.path.exists(p) else "MISSING"))
            cur.execute("select * from reproduction.reconcile(%s)", (s,))
            log("%-8s reconcile: %s" % (s, cur.fetchall()))
            pg.commit()
            cur.execute("select lane, landed, needed from reproduction.%s_update_lanes order by lane" % s)
            for lane, landed, needed in cur.fetchall():
                log("  board %-16s landed %s / needed %s (%.2f%%)" % (lane, "{:,}".format(landed), "{:,}".format(needed), 100.0 * landed / needed if needed else 0))
    pg.close()
    log("VERIFY: %s" % ("MATCH on both sources" if ok else "DIFFERENCES - see above"))
    return 0 if ok else 1


def apply_found(a):
    """The documents organize placed from the old stores: their full paths into the cells that had none (NULL, pending, absent -
    a file on disk outranks a verdict word), never over an existing path.  One COPY into a temporary table, one UPDATE per
    source, then reconcile."""
    import psycopg2
    found = load_found()
    if not found:
        raise SystemExit("no population.found.json - run organize first")
    pg = psycopg2.connect(cloud.dsn(), connect_timeout=30, application_name="population")
    pg.autocommit = False
    with pg.cursor() as cur:
        cur.execute("create temporary table found (doc_id text collate \"C\" primary key, document text) on commit drop")
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for did, path in found.items():
            w.writerow([did, path])
        buf.seek(0)
        cur.copy_expert("copy found (doc_id, document) from stdin with (format csv)", buf)
        for s in ("acris", "richmond"):
            cur.execute("""update reproduction.%s w set document = f.document from found f
                           where f.doc_id = w.doc_id and f.doc_id %s and (w.document is null or w.document in ('pending', 'absent'))""" % (
                        s, "like 'RC\\_%%'" if s == "richmond" else "not like 'RC\\_%%'"))
            log("%-8s cells filled from the found map: %s" % (s, "{:,}".format(cur.rowcount)))
            cur.execute("select count(*) from found f join reproduction.%s w on w.doc_id = f.doc_id where w.document like 'D:%%' and w.document <> f.document" % s)
            log("%-8s cells that already held a different path (left alone): %s" % (s, "{:,}".format(cur.fetchone()[0])))
        pg.commit()
        for s in ("acris", "richmond"):
            cur.execute("select * from reproduction.reconcile(%s)", (s,))
            log("%-8s reconcile: %s" % (s, cur.fetchall()))
        pg.commit()
    pg.close()
    return 0


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
    a = ap.parse_args(argv)
    return {"survey": survey, "organize": organize, "load": load, "verify": verify, "apply-found": apply_found}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
