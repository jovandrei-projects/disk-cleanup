"""Candidate generation for the Recommended view.

Reads one snapshot and produces a ranked list of things worth removing or
reviewing. Two tiers, because the failure mode of a cleanup tool is telling
someone to delete something they needed:

  A = safe by construction. Empty folders, macOS litter, temp and cache trees
      that regenerate, the Recycle Bin, stale VM images nobody has booted.
  B = needs a decision. Big, real, possibly wanted - the point is to put the
      number in front of it, not to pretend a tool can decide for you.

Every candidate carries a one-line reason and enough identity (dir_id or path)
to jump to it in the viewer. Nothing here deletes anything.
"""

import hashlib
import os
import sys
import time
import winreg

YEAR = 365.25 * 86400

# Folder names whose contents are regenerable on next run/build. Only matched
# as whole directory names, and only applied under paths that are clearly user
# or cache space.
REGENERABLE_NAMES = {
    "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".parcel-cache", ".next", "dist", "build",
    "out", "target", "obj", ".cache",
}
APPDATA_CACHE_NAMES = {
    "cache", "cachestorage", "code cache", "gpucache", "shadercache",
    "serviceworker", "dawngraphitecache", "dawnwebgpuCache".lower(),
}
JUNK_FILES = {"desktop.ini", ".ds_store", "thumbs.db"}


def _rows(db, sql, args):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def _dir_candidates(db, sid, where, args, kind, tier, reason):
    return [dict(kind=kind, tier=tier, path=r["path"], dir_id=r["id"],
                 bytes_disk=r["total_bytes_disk"], n_files=r["total_files"],
                 mtime=r["newest_mtime"], reason=reason)
            for r in _rows(db, "SELECT id, path, total_bytes_disk, total_files,"
                           " newest_mtime FROM dirs WHERE snapshot_id=? AND " + where,
                           (sid,) + args)]


def _file_candidates(db, sid, where, args, kind, tier, reason,
                     reason_from=None):
    rows = _rows(db,
                 "SELECT f.id, f.name, f.bytes_disk, f.bytes_logical, f.mtime,"
                 " f.cloud_only, d.path AS dir_path, d.id AS dir_id"
                 " FROM files f JOIN dirs d ON d.id=f.dir_id"
                 " WHERE f.snapshot_id=? AND " + where,
                 (sid,) + args)
    out = []
    for r in rows:
        path = r["dir_path"] + "\\" + r["name"]
        why = reason_from(r) if reason_from else reason
        out.append(dict(kind=kind, tier=tier, path=path, dir_id=r["dir_id"],
                        bytes_disk=r["bytes_disk"], n_files=1,
                        mtime=r["mtime"], reason=why))
    return out


def candidates(db, sid):
    now = time.time()
    two_years_ago = now - 2 * YEAR
    one_year_ago = now - YEAR
    out = []

    # ---- Tier A: safe to remove -------------------------------------------

    # Empty folders. Report the topmost branch only: a folder containing
    # nothing but empty subfolders is one decision, and its children must not
    # each become a row. Grouped by parent, because on this machine one folder
    # (WinSxS\Temp) holds ~70k empty subdirectories and any per-leaf list is
    # unreadable. Junctions and placeholders are excluded - their zero count is
    # a scanning artifact, not emptiness.
    empties = _rows(db, """
        SELECT c.id, c.path, c.parent_id FROM dirs c
        JOIN dirs p ON p.id = c.parent_id
        WHERE c.snapshot_id=? AND c.total_files=0 AND c.reparse_tag=0
          AND c.depth>0 AND p.total_files>0""", (sid,))
    by_parent = {}
    for r in empties:
        by_parent.setdefault(r["parent_id"], []).append(r)
    parent_paths = {}
    if by_parent:
        marks = ",".join("?" * len(by_parent))
        for r in _rows(db, "SELECT id, path, total_files FROM dirs WHERE id IN (%s)"
                       % marks, tuple(by_parent)):
            parent_paths[r["id"]] = r["path"]
    # Every row names the folder that would actually be recycled - never the
    # parent that merely groups them. A mark means "send this path to the
    # Bin", so a row pointing at a non-empty parent would take the parent's
    # real contents with it.
    shown_parents = 0
    for pid, kids in sorted(by_parent.items(), key=lambda kv: -len(kv[1])):
        shown_parents += 1
        if shown_parents > 400:
            break
        ppath = parent_paths.get(pid, "?")
        same = "Empty folder - nothing beneath it" if len(kids) <= 2 else (
            "Empty folder - one of %d under %s" % (len(kids), ppath))
        for k in kids:
            out.append(dict(kind="empty_dir", tier="A", path=k["path"],
                            dir_id=k["id"], bytes_disk=0, n_files=0,
                            mtime=None, reason=same))

    # macOS resource-fork litter (._*) and .DS_Store. The paths are the turd
    # files themselves for the same reason: a row's path is the unit that a
    # 'delete' mark would recycle, so it must never be the folder around them.
    # The underscore in '._%' is escaped - unescaped it is LIKE's single-char
    # wildcard and matches every dotfile (.condarc, .babelrc, .gitattributes).
    mac = db.execute(
        "SELECT d.path || '\\' || f.name AS p, f.bytes_disk"
        " FROM files f JOIN dirs d ON d.id=f.dir_id"
        " WHERE f.snapshot_id=? AND (f.name LIKE '.\\_%' ESCAPE '\\'"
        " OR f.name='.DS_Store')", (sid,)).fetchall()
    out += [dict(kind="macos_junk", tier="A", path=r[0], dir_id=None,
                 bytes_disk=r[1], n_files=1, mtime=None,
                 reason="macOS metadata file (._*, .DS_Store)")
            for r in mac]

    # The Recycle Bin itself. Deleting here frees space instantly.
    rb = db.execute(
        "SELECT id, path, total_bytes_disk, total_files, newest_mtime FROM dirs"
        " WHERE snapshot_id=? AND path LIKE 'C:\\$Recycle.Bin%'"
        " ORDER BY total_bytes_disk DESC LIMIT 1", (sid,)).fetchone()
    if rb and rb[2] > 0:
        out.append(dict(kind="recycle_bin", tier="A", path=rb[1], dir_id=rb[0],
                        bytes_disk=rb[2], n_files=rb[3], mtime=rb[4],
                        reason="Recycle Bin - already deleted once"))

    # Regenerable build/caches by folder name, only where the name is
    # unambiguous - a folder called "build" inside System32 stays out.
    names = ",".join("'%s'" % n for n in REGENERABLE_NAMES)
    out += _dir_candidates(
        db, sid,
        "lower(name) IN (%s) AND total_bytes_disk > 5*1024*1024"
        " AND (path LIKE 'C:\\Users\\%%' OR path LIKE 'C:\\Projects\\%%')"
        % names, (),
        "regenerable", "A",
        "Build output or package cache - regenerates when the project runs")

    # AppData cache folders of any depth.
    cn = ",".join("'%s'" % n for n in APPDATA_CACHE_NAMES)
    out += _dir_candidates(
        db, sid,
        "lower(name) IN (%s) AND total_bytes_disk > 10*1024*1024"
        " AND path LIKE '%%\\AppData\\%%'" % cn, (),
        "appdata_cache", "A", "Application cache - regenerated on next use")

    # Windows Update's download staging area: consumed already.
    out += _dir_candidates(
        db, sid,
        "path='C:\\Windows\\SoftwareDistribution\\Download' AND total_files>0",
        (), "winupdate", "A",
        "Windows Update download staging - safe to clear via Disk Cleanup")

    # Crash/error reports.
    out += _dir_candidates(
        db, sid,
        "path LIKE 'C:\\ProgramData\\Microsoft\\Windows\\WER\\%%'"
        " AND total_files>0", (),
        "wer", "A", "Windows error-report archives")

    # ---- Tier B: your call ------------------------------------------------

    # Stale emulator / VM images - big, dormant, recreatable but annoying if you
    # still use the VM.
    out += _dir_candidates(
        db, sid,
        "total_bytes_disk > 500*1024*1024 AND ("
        " name LIKE '%.avd'"
        " OR path LIKE '%\\Android\\Sdk\\system-images%'"
        " OR path LIKE '%\\Play Games\\%%avd%')",
        (), "vm_image", "B",
        "Emulator/VM image - stale ones are recreatable from the SDK manager")

    # Large files not modified in 2+ years. Modification, not access: see the
    # atime health note in the app.
    out += _file_candidates(
        db, sid,
        "f.cloud_only=0 AND f.bytes_disk > 500*1024*1024 AND f.mtime < ?",
        (two_years_ago,), "stale_large", "B",
        "Unchanged 2+ years and large - verify before removing")

    # Installers and disc images still sitting around (not the Windows
    # Installer cache - those are needed for uninstalls). grp='installer'
    # covers every .exe, so restrict .exe hits to setup-ish names or
    # download-ish locations - otherwise the query "finds" Code.exe and
    # Typora.exe, which are the installed apps, not leftover installers.
    # $Recycle.Bin contents are also excluded - the bin is its own candidate.
    out += _file_candidates(
        db, sid,
        "f.grp='installer' AND f.cloud_only=0 AND f.bytes_disk > 100*1024*1024"
        " AND d.path NOT LIKE 'C:\\Windows\\Installer%'"
        " AND d.path NOT LIKE 'C:\\$Recycle.Bin%'"
        " AND (lower(f.ext) != 'exe'"
        "      OR lower(f.name) LIKE '%setup%' OR lower(f.name) LIKE '%install%'"
        "      OR lower(f.name) LIKE '%driver%' OR lower(f.name) LIKE '%unins%'"
        "      OR d.path LIKE '%\\Downloads%' OR d.path LIKE '%\\Temp\\%'"
        "      OR d.path LIKE '%\\Desktop%'"
        "      OR d.path LIKE '%Downloaded Installations%'"
        "      OR d.path LIKE '%\\Downloader%')",
        (), "installer", "B",
        "Installer already run - the installed app does not need it")

    # Local archives. Someone downloaded an ISO and kept it.
    out += _file_candidates(
        db, sid,
        "f.grp='archive' AND f.cloud_only=0 AND f.bytes_disk > 500*1024*1024",
        (), "archive", "B",
        "Large archive on disk - extract once, keep the result, drop the rest?")

    # Cloud-only archives: deleting frees OneDrive quota, not disk. Say so.
    out += _file_candidates(
        db, sid,
        "f.grp='archive' AND f.cloud_only=1 AND f.bytes_logical > 1024*1024*1024",
        (), "cloud_archive", "B",
        "Cloud-only archive - removing frees OneDrive quota, NOT local disk")

    # Downloads untouched for a year.
    out += _file_candidates(
        db, sid,
        "d.path LIKE 'C:\\Users\\%%\\Downloads%%' AND f.cloud_only=0"
        " AND f.bytes_disk > 100*1024*1024 AND f.mtime < ?",
        (one_year_ago,), "old_download", "B",
        "Sat in Downloads over a year")

    # Large local video untouched for 2+ years.
    out += _file_candidates(
        db, sid,
        "f.grp='video' AND f.cloud_only=0 AND f.bytes_disk > 1024*1024*1024"
        " AND f.mtime < ?",
        (two_years_ago,), "stale_video", "B",
        "Video untouched 2+ years - watched already or never will be?")

    # ---- bookkeeping ------------------------------------------------------

    # A recommendations view that needs a scrollbar to find the bottom has
    # failed. Cap each kind at its biggest 400.
    capped = []
    counts = {}
    for c in sorted(out, key=lambda c: -c["bytes_disk"]):
        k = counts.get(c["kind"], 0)
        if k < 400:
            capped.append(c)
            counts[c["kind"]] = k + 1
    out = capped

    for c in out:
        c["decision"] = None
    out.sort(key=lambda c: (0 if c["tier"] == "A" else 1, -c["bytes_disk"]))
    tiers = {}
    for c in out:
        t = tiers.setdefault(c["tier"], {"bytes": 0, "n": 0})
        t["bytes"] += c["bytes_disk"]
        t["n"] += 1
    return {"items": out, "tiers": tiers}


# --------------------------------------------------------------- hashing
#
# The three passes below open real files. Everything in them is read-only,
# and OneDrive placeholders (cloud_only=1) are excluded at the SQL level
# before any path is ever opened - opening one would hydrate it and consume
# the free space this tool exists to recover.

DUP_FLOOR = 1 * 1024 * 1024  # below this a duplicate is not worth a review row
PART_CHUNK = 65536

ANALYSIS_SCHEMA = """
-- sha256 of a file's content, keyed by path so a refresh can reuse it when
-- size and mtime say the file is unchanged. file_ids are per-snapshot and
-- would not survive one.
CREATE TABLE IF NOT EXISTS hashes (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT NOT NULL
);
-- One row per proven-identical set: n members, each bytes_logical large,
-- occupying bytes_disk summed over all copies.
CREATE TABLE IF NOT EXISTS dup_sets (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    bytes_logical INTEGER NOT NULL,
    bytes_disk INTEGER NOT NULL,
    n INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS dup_members (
    set_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    file_id INTEGER NOT NULL,
    nlink INTEGER DEFAULT 1,
    ino INTEGER
);
-- Verdict of content-proving a duplicate-folder group, keyed by the group's
-- name+size signature so a refresh reuses it. 1 = byte-identical,
-- 0 = contents differ, -1 = unreadable.
CREATE TABLE IF NOT EXISTS tree_proofs (
    snapshot_id INTEGER NOT NULL,
    sig TEXT NOT NULL,
    verdict INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, sig)
);
"""


def ensure_schema(db):
    db.executescript(ANALYSIS_SCHEMA)
    # Older databases predate the column; add rather than migrate.
    cols = {r[1] for r in db.execute("PRAGMA table_info(dup_members)")}
    if "nlink" not in cols:
        db.execute("ALTER TABLE dup_members ADD COLUMN nlink INTEGER DEFAULT 1")
    if "ino" not in cols:
        db.execute("ALTER TABLE dup_members ADD COLUMN ino INTEGER")
    db.commit()


def _win(p):
    return p if p.startswith("\\\\?\\") else "\\\\?\\" + p


def _head_tail(path):
    """Cheap discriminator: first and last 64 KB. Files under the floor are
    never here, so the two reads never overlap enough to matter."""
    h = hashlib.blake2b(digest_size=16)
    with open(_win(path), "rb") as fh:
        h.update(fh.read(PART_CHUNK))
        fh.seek(-PART_CHUNK, os.SEEK_END)
        h.update(fh.read(PART_CHUNK))
    return h.digest()


def _sha256(path):
    h = hashlib.sha256()
    with open(_win(path), "rb") as fh:
        for blk in iter(lambda: fh.read(4 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _stat_link(path):
    """(nlink, ino) for hard-link detection: two members of a set may be the
    same file under two names, in which case deleting one frees nothing."""
    try:
        st = os.stat(_win(path))
        return st.st_nlink, st.st_ino
    except OSError:
        return 1, None


def _load_hash_cache(db):
    return {r[0]: (r[1], r[2], r[3])
            for r in db.execute("SELECT path, size, mtime, sha256 FROM hashes")}


def _sha_cached(db, cache, path, size, mtime):
    """Full hash, reusing the persisted value when size+mtime say the file is
    unchanged since it was last hashed."""
    ent = cache.get(path)
    if (ent and ent[0] == size and mtime is not None
            and abs(ent[1] - mtime) < 2.0):
        return ent[2], False
    sha = _sha256(path)
    cache[path] = (size, mtime, sha)
    db.execute("INSERT OR REPLACE INTO hashes (path, size, mtime, sha256)"
               " VALUES (?,?,?,?)", (path, size, mtime, sha))
    return sha, True


def dup_sets(db, sid):
    """Persisted sets for a snapshot, shaped for the viewer. Empty list when
    --dupes has never run; `computed_for` reports which snapshot they belong
    to so a refresh does not silently show yesterday's duplicates."""
    try:
        sid_done = db.execute(
            "SELECT MAX(snapshot_id) FROM dup_sets").fetchone()[0]
    except Exception:
        sid_done = None
    sets = []
    for s in db.execute(
            "SELECT id, sha256, bytes_logical, bytes_disk, n FROM dup_sets"
            " WHERE snapshot_id=? ORDER BY bytes_disk DESC", (sid,)):
        members = [dict(path=m[0], dir_id=m[1], bytes_disk=m[2], mtime=m[3],
                        name=m[4], shared=m[5] > 1, ino=m[6],
                        protected=_is_protected(m[0]))
                   for m in db.execute(
                       "SELECT dm.path, d.id, f.bytes_disk, f.mtime, f.name,"
                       " dm.nlink, dm.ino"
                       " FROM dup_members dm"
                       " JOIN files f ON f.id=dm.file_id"
                       " JOIN dirs d ON d.id=f.dir_id"
                       " WHERE dm.set_id=? ORDER BY dm.path", (s[0],))]
        sets.append(dict(id=s[0], sha256=s[1][:12], bytes_logical=s[2],
                         bytes_disk=s[3], n=s[4], members=members))
    return {"sets": sets, "computed_for": sid_done}


def compute_dup_sets(db, sid, floor=DUP_FLOOR, log=sys.stderr):
    """Size groups -> head+tail partial hash -> full sha256 -> persisted sets.

    The expensive stage is the last and only touches files whose partial hash
    collides, so most of the candidate mass is never fully read.
    """
    ensure_schema(db)
    # The DELETEs are deliberately NOT up front: they would open a write
    # transaction that then stays open through the whole hashing phase,
    # blocking every other writer (the viewer's marks included) for minutes.
    # Hash first, then swap the sets in one short transaction at the end.

    rows = db.execute(
        "SELECT f.id, f.bytes_logical, f.bytes_disk, f.mtime,"
        " d.path || '\\' || f.name"
        " FROM files f JOIN dirs d ON d.id=f.dir_id"
        " WHERE f.snapshot_id=? AND f.cloud_only=0 AND f.bytes_logical>=?"
        " AND f.bytes_logical IN (SELECT bytes_logical FROM files"
        "   WHERE snapshot_id=? AND cloud_only=0 AND bytes_logical>=?"
        "   GROUP BY bytes_logical HAVING COUNT(*)>1)",
        (sid, floor, sid, floor)).fetchall()
    groups = {}
    for fid, size, disk, mt, path in rows:
        groups.setdefault(size, []).append(
            dict(file_id=fid, path=path, size=size, disk=disk, mtime=mt))
    log.write("%d files in %d same-size groups\n"
              % (len(rows), len(groups)))

    # Partial hash culls groups whose members only share a size.
    by_part = {}
    skipped = 0
    for i, (size, members) in enumerate(groups.items()):
        for m in members:
            try:
                key = (size, _head_tail(m["path"]))
            except OSError:
                skipped += 1
                continue
            by_part.setdefault(key, []).append(m)
        if log and i % 200 == 199:
            log.write("\r  partial hash: %d/%d groups" % (i + 1, len(groups)))
            log.flush()
    survivors = [ms for ms in by_part.values() if len(ms) > 1]
    n_surv = sum(len(ms) for ms in survivors)
    log.write("\r  partial hash culled to %d files in %d groups\n"
              % (n_surv, len(survivors)))

    cache = _load_hash_cache(db)
    hashed = 0
    found = []
    for i, members in enumerate(survivors):
        by_sha = {}
        for m in members:
            try:
                sha, fresh = _sha_cached(db, cache, m["path"],
                                         m["size"], m["mtime"])
            except OSError:
                skipped += 1
                continue
            hashed += fresh
            m["sha"] = sha
            by_sha.setdefault(sha, []).append(m)
        found += [ms for ms in by_sha.values() if len(ms) > 1]
        if i % 50 == 49:
            # Flush the hash-cache inserts as they accumulate; holding them
            # in one transaction keeps the write lock for the whole phase.
            db.commit()
            if log:
                log.write("\r  full hash: %d/%d groups"
                          % (i + 1, len(survivors)))
                log.flush()
    db.commit()

    # Swap in the new sets atomically - the previous list stays readable
    # until the replacement is ready.
    db.execute("DELETE FROM dup_members WHERE set_id IN"
               " (SELECT id FROM dup_sets WHERE snapshot_id=?)", (sid,))
    db.execute("DELETE FROM dup_sets WHERE snapshot_id=?", (sid,))
    for members in found:
        cur = db.execute(
            "INSERT INTO dup_sets (snapshot_id, sha256, bytes_logical,"
            " bytes_disk, n) VALUES (?,?,?,?,?)",
            (sid, members[0]["sha"], members[0]["size"],
             sum(m["disk"] for m in members), len(members)))
        # st_nlink/st_ino: a member may share its bytes with another name,
        # possibly inside the same set, so deleting it frees nothing.
        db.executemany(
            "INSERT INTO dup_members (set_id, path, file_id, nlink, ino)"
            " VALUES (?,?,?,?,?)",
            [(cur.lastrowid, m["path"], m["file_id"]) + _stat_link(m["path"])
             for m in members])
    db.commit()

    reclaim = sum(ms[0]["size"] * (len(ms) - 1) for ms in found)
    log.write("\r  %d proven sets, %d copies, %.1f GB reclaimable keeping one"
              " each (%d unreadable files skipped)\n"
              % (len(found), sum(len(m) for m in found), reclaim / 2**30,
                 skipped))
    return {"sets": len(found), "copies": sum(len(m) for m in found),
            "reclaimable": reclaim, "skipped": skipped}


# --------------------------------------------------------- duplicate trees

# Reported, never edited - a dup group that lives entirely under these is
# measurement, not a candidate. A mixed group keeps its protected members so
# the one in user space can still be judged.
PROTECTED_PREFIXES = (
    "c:\\windows\\", "c:\\program files\\", "c:\\program files (x86)\\",
    "c:\\programdata\\", "c:\\$recycle.bin\\",
)


def _is_protected(path):
    p = path.lower().rstrip("\\") + "\\"
    return p.startswith(PROTECTED_PREFIXES)


def tree_dups(db, sid, min_files=3, min_bytes=1 << 20,
              prove_max_bytes=256 << 20, prove_max_files=8000,
              hash_prove=False):
    """Whole folders that are copies of each other.

    Signature per directory = hash of every descendant file's (name, size)
    plus every child's (name, signature), computed deepest-first so each dir
    is hashed once. Equal signatures mean identical names and sizes at every
    level; small groups are then hash-proven content-identical. Only the
    topmost copy pair is reported - if `a` and `b` already match, `a\\x` and
    `b\\x` are not a separate finding.
    """
    meta = {}   # id -> (parent_id, name, path, total_files, total_bytes_disk)
    order = []
    for i, pid, name, depth, path, tf, td in db.execute(
            "SELECT id, parent_id, name, depth, path, total_files,"
            " total_bytes_disk FROM dirs WHERE snapshot_id=?"
            " ORDER BY depth DESC, id", (sid,)):
        meta[i] = (pid, name, path, tf, td)
        order.append(i)

    # Each dir's file material, one hasher per dir. ORDER BY dir_id, name
    # makes the input to every hasher deterministic.
    part = {}
    for dir_id, name, sz in db.execute(
            "SELECT dir_id, name, bytes_logical FROM files WHERE snapshot_id=?"
            " ORDER BY dir_id, name", (sid,)):
        h = part.get(dir_id)
        if h is None:
            h = part[dir_id] = hashlib.blake2b(digest_size=16)
        h.update(b"f\0")
        h.update(name.encode("utf-8", "surrogateescape"))
        h.update(b"\0" + str(sz).encode())

    sig = {}
    kids = {}
    for i in order:
        h = part.pop(i, None) or hashlib.blake2b(digest_size=16)
        for name, cid in sorted(kids.get(i, ())):
            h.update(b"d\0" + name.encode("utf-8", "surrogateescape")
                     + b"\0" + sig[cid])
        sig[i] = h.digest()
        pid = meta[i][0]
        if pid is not None:
            kids.setdefault(pid, []).append((meta[i][1], i))
    del part

    groups = {}
    for i, s in sig.items():
        pid, name, path, tf, td = meta[i]
        if tf >= min_files and td >= min_bytes and pid is not None:
            groups.setdefault(s, []).append(i)
    groups = [ids for ids in groups.values() if len(ids) > 1]

    # Collapse nested matches: members whose parents also match each other
    # belong to a group one level up, which reports them.
    top = []
    for ids in groups:
        psigs = {}
        for i in ids:
            ps = sig.get(meta[i][0])
            if ps is not None:
                psigs.setdefault(ps, []).append(i)
        for i in ids:
            ps = sig.get(meta[i][0])
            if ps is None or len(psigs.get(ps, ())) < 2:
                top.append(i)
    by_sig = {}
    for i in top:
        by_sig.setdefault(sig[i], []).append(i)
    del sig
    groups = sorted(by_sig.items(),
                    key=lambda kv: -meta[kv[1][0]][4] * (len(kv[1]) - 1))

    # Content proof is expensive (one open per file, and AV scans each open),
    # so it happens only when asked - the --dupes CLI run proves and persists
    # verdicts; the viewer then reads them without hashing.
    verdicts = {r[0]: r[1] for r in db.execute(
        "SELECT sig, verdict FROM tree_proofs WHERE snapshot_id=?", (sid,))}
    cache = _load_hash_cache(db)
    out = []
    n_proven = n_differ = 0
    for gsig, ids in groups:
        paths = [meta[i][2] for i in ids]
        size, nf = meta[ids[0]][4], meta[ids[0]][3]
        if all(_is_protected(p) for p in paths):
            continue
        members = [dict(dir_id=i, path=meta[i][2], bytes_disk=meta[i][4],
                        n_files=meta[i][3],
                        protected=_is_protected(meta[i][2])) for i in ids]
        rec = dict(n=len(ids), bytes_disk=size, n_files=nf,
                   reclaimable=size * (len(ids) - 1), members=members,
                   proven=None, note=None)
        key = gsig.hex()
        flat = [d for i in ids for d in _subtree_ids(kids, i)]
        if size > prove_max_bytes or nf > prove_max_files:
            rec["note"] = ("names and sizes identical throughout; too large "
                           "to hash-prove")
        elif _tree_has_cloud(db, flat):
            rec["note"] = "contains cloud-only files - contents not hashed"
        elif key in verdicts:
            verdict = verdicts[key]
            rec["proven"] = verdict == 1 if verdict >= 0 else None
            rec["note"] = {1: "hash-proven byte-identical",
                           0: "same names and sizes; contents differ",
                           -1: "contents unreadable - not verified"}[verdict]
        elif hash_prove:
            proven = _prove_trees(db, meta, kids, cache, ids)
            verdict = 1 if proven else (-1 if proven is None else 0)
            db.execute("INSERT OR REPLACE INTO tree_proofs"
                       " (snapshot_id, sig, verdict) VALUES (?,?,?)",
                       (sid, key, verdict))
            rec["proven"] = proven
            rec["note"] = ("hash-proven byte-identical" if proven
                           else "contents unreadable - not verified"
                           if proven is None
                           else "same names and sizes; contents differ")
        else:
            rec["note"] = ("names and sizes identical throughout; not "
                           "hash-proven yet - run analyze.py --dupes")
        if rec["proven"] is True:
            n_proven += 1
        elif rec["proven"] is False:
            n_differ += 1
        out.append(rec)
    db.commit()
    del kids

    return {"groups": out[:400],
            "stats": {"signature_groups": len(groups), "reported": len(out),
                      "proven": n_proven, "differ": n_differ}}


def _subtree_ids(kids, root_id):
    out = [root_id]
    stack = [root_id]
    while stack:
        for _name, cid in kids.get(stack.pop(), ()):
            out.append(cid)
            stack.append(cid)
    return out


def _chunked(db, sql_head, dir_ids, tail=""):
    """Run `sql_head IN (?,?,...) tail` in batches - a big subtree can exceed
    SQLite's variable limit."""
    rows = []
    for j in range(0, len(dir_ids), 4000):
        chunk = dir_ids[j:j + 4000]
        marks = ",".join("?" * len(chunk))
        rows += db.execute(sql_head % marks + tail, chunk).fetchall()
    return rows


def _tree_has_cloud(db, dir_ids):
    return any(r[0] for r in _chunked(
        db, "SELECT COUNT(*) FROM files WHERE cloud_only=1 AND dir_id IN (%s)",
        dir_ids))


def _prove_trees(db, meta, kids, cache, ids):
    """Hash every file under each member. Returns True if all members are
    byte-identical, False if contents differ, None on read failure."""
    sigs = []
    for i in ids:
        root = meta[i][2].rstrip("\\")
        dir_ids = _subtree_ids(kids, i)
        rows = _chunked(
            db,
            "SELECT f.name, f.bytes_logical, f.mtime, f.cloud_only,"
            " d.path || '\\' || f.name"
            " FROM files f JOIN dirs d ON d.id=f.dir_id"
            " WHERE f.dir_id IN (%s)", dir_ids)
        h = hashlib.blake2b(digest_size=16)
        file_sigs = []
        try:
            for name, size, mt, cloud, full in rows:
                if cloud:
                    return None
                sha, _ = _sha_cached(db, cache, full, size, mt)
                file_sigs.append((full[len(root) + 1:], sha))
        except OSError:
            return None
        for rel, sha in sorted(file_sigs):
            h.update(rel.encode("utf-8", "surrogateescape")
                     + b"\0" + sha.encode())
        sigs.append(h.digest())
        # Flush the hash-cache writes per member: the write lock otherwise
        # stays held through the whole group's hashing.
        db.commit()
    return len(set(sigs)) == 1


# ------------------------------------------------------ installed software

UNINSTALL_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM64"),
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
     "HKLM32"),
    (winreg.HKEY_CURRENT_USER,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "HKCU"),
)


def _reg_values(key):
    vals = {}
    i = 0
    while True:
        try:
            name, val, _ = winreg.EnumValue(key, i)
            vals[name] = val
            i += 1
        except OSError:
            return vals


def _loc_from_uninstall(uninstall):
    """Fallback install dir: the folder the uninstaller lives in."""
    if not uninstall or not isinstance(uninstall, str):
        return None
    s = uninstall.strip().strip('"')
    if len(s) < 4 or s[1:3] != ":\\":
        return None
    # 'C:\path\uninstall.exe /args' -> 'C:\path'
    exe_end = s.lower().find(".exe")
    if exe_end < 0:
        return None
    return os.path.dirname(s[:exe_end + 4].strip('"'))


def software(db, sid):
    """Installed applications from the uninstall registry keys, joined to the
    scanned dirs so the size shown is measured on disk, not the (often
    missing or wrong) registered estimate."""
    apps = []
    for hive, sub, source in UNINSTALL_KEYS:
        try:
            key = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(key)[0]):
            try:
                sk = winreg.OpenKey(key, winreg.EnumKey(key, i))
            except OSError:
                continue
            with sk:
                v = _reg_values(sk)
            name = v.get("DisplayName")
            if not name or not isinstance(name, str):
                continue
            if v.get("SystemComponent") == 1 or v.get("ParentKeyName"):
                continue  # updates and components, not uninstallable apps
            loc = v.get("InstallLocation")
            guess = False
            if not loc or not isinstance(loc, str) or not loc.strip():
                loc = _loc_from_uninstall(v.get("UninstallString"))
                guess = bool(loc)
            if loc:
                loc = os.path.normpath(loc.strip().strip('"'))
            if loc and (len(loc) <= 3
                        or loc.lower() in ("c:\\windows", "c:\\users",
                                           "c:\\program files",
                                           "c:\\program files (x86)")):
                loc = None  # a registered location of "C:\Windows" is not a folder to size
            est = v.get("EstimatedSize")
            apps.append(dict(
                name=name.strip(), publisher=v.get("Publisher") or "",
                version=str(v.get("DisplayVersion") or ""),
                install_date=str(v.get("InstallDate") or ""),
                loc=loc, loc_guess=guess, source=source,
                est_bytes=int(est) * 1024 if isinstance(est, int) else None))
    # Join install locations to scanned dirs. Exact path first (indexed);
    # the residue takes one scan with an IN list on lower(path).
    want = {a["loc"] for a in apps if a["loc"]}
    by_path = {}
    for p in want:
        r = db.execute(
            "SELECT id, path, total_bytes_disk, total_files, newest_mtime"
            " FROM dirs WHERE snapshot_id=? AND path=?", (sid, p)).fetchone()
        if r:
            by_path[r[1].lower()] = r
    missing = {p.lower() for p in want} - set(by_path)
    if missing:
        marks = ",".join("?" * len(missing))
        for r in db.execute(
                "SELECT id, path, total_bytes_disk, total_files, newest_mtime"
                " FROM dirs WHERE snapshot_id=? AND lower(path) IN (%s)"
                % marks, (sid,) + tuple(missing)):
            by_path[r[1].lower()] = r
    for a in apps:
        r = by_path.get((a["loc"] or "").lower())
        a.update(dir_id=r[0] if r else None,
                 real_bytes=r[2] if r else None,
                 real_files=r[3] if r else None,
                 dir_mtime=r[4] if r else None)
    apps.sort(key=lambda a: -(a["real_bytes"] or a["est_bytes"] or 0))
    return apps


# ----------------------------------------------------------------------- cli


def main():
    import argparse
    import sqlite3
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data",
        "inventory.sqlite3"))
    p.add_argument("--snapshot", type=int, default=None,
                   help="snapshot id (default: latest complete)")
    p.add_argument("--dupes", action="store_true",
                   help="hash same-size files and persist proven duplicate sets")
    p.add_argument("--trees", action="store_true",
                   help="compute duplicate-folder signatures and print groups")
    p.add_argument("--software", action="store_true",
                   help="print the installed-software inventory")
    args = p.parse_args()

    db = sqlite3.connect(args.db)
    ensure_schema(db)
    sid = args.snapshot
    if sid is None:
        sid = db.execute(
            "SELECT MAX(id) FROM snapshots WHERE complete=1").fetchone()[0]
        if sid is None:
            sys.exit("no complete snapshot")
    if args.dupes:
        compute_dup_sets(db, sid)
        res = tree_dups(db, sid, hash_prove=True)
        print("tree groups: %d signature, %d reported,"
              " %d proven identical, %d differing" % (
                  res["stats"]["signature_groups"], res["stats"]["reported"],
                  res["stats"]["proven"], res["stats"]["differ"]))
    if args.trees:
        t = time.time()
        res = tree_dups(db, sid)
        print("computed in %.1f s" % (time.time() - t))
        for g in res["groups"][:60]:
            print("%8.1f MB x%d  %s" % (
                g["bytes_disk"] / 2**20, g["n"],
                " | ".join(m["path"] for m in g["members"]))[:220])
            print("           %s" % g["note"])
        print(res["stats"])
    if args.software:
        for a in software(db, sid):
            sz = a["real_bytes"] if a["real_bytes"] is not None else a["est_bytes"]
            print("%9s  %-60.60s  %s" % (
                ("%8.1f MB" % (sz / 2**20)) if sz else "        -",
                a["name"], a["loc"] or ""))
    if not (args.dupes or args.trees or args.software):
        p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
