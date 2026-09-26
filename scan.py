"""Read-only filesystem inventory.

Walks a tree recording, for every file, both its logical size and the bytes it
actually occupies on disk. The two differ for OneDrive placeholders, sparse
files and NTFS-compressed files, and the difference is the whole point: a
cloud-only file reports gigabytes to stat while occupying nothing.

Nothing here opens a file's data. stat and GetCompressedFileSize read metadata
only, so a placeholder is never hydrated.
"""

import argparse
import ctypes
import os
import sqlite3
import sys
import time
from ctypes import wintypes

DB_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "inventory.sqlite3")

FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_SPARSE_FILE = 0x00000200
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_COMPRESSED = 0x00000800
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_PINNED = 0x00080000
FILE_ATTRIBUTE_UNPINNED = 0x00100000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

# Needs GetCompressedFileSize to know the real footprint; a plain file's is just
# its logical size rounded up to a cluster.
NEEDS_REAL_SIZE = (
    FILE_ATTRIBUTE_SPARSE_FILE
    | FILE_ATTRIBUTE_COMPRESSED
    | FILE_ATTRIBUTE_REPARSE_POINT
    | FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)

IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
IO_REPARSE_TAG_SYMLINK = 0xA000000C

# Cloud tags are 0x9000_X01A for X in 0..F. These are OneDrive and must be
# descended into; a junction or symlink must not be, or the walk can loop.
def is_cloud_tag(tag):
    return (tag & 0xFFFF0FFF) == 0x9000001A


# Locked or meaningless to walk. Compared case-insensitively against the full
# path. These are still reported as skipped rather than silently dropped.
SKIP_PATHS = {
    r"c:\system volume information",
    r"c:\windows\csc",
    r"c:\windows\system32\logfiles\wmi\rtbackup",
    r"c:\$sysreset",
    r"c:\config.msi",
}

# Classification for the viewer. Lowercase extensions, no dot.
EXT_GROUPS = {
    "video": "mp4 mkv avi mov wmv flv webm m4v mpg mpeg ts m2ts vob rm 3gp f4v mxf r3d braw",
    "audio": "mp3 wav flac aac ogg wma m4a aiff aif alac opus mid midi sf2 npy",
    "image": "jpg jpeg png gif bmp tiff tif webp heic raw cr2 nef arw dng psd ai svg ico",
    "document": "pdf doc docx xls xlsx ppt pptx odt ods odp txt rtf md csv epub mobi pages numbers key",
    "archive": "zip rar 7z tar gz bz2 xz iso img cab wim gho tgz zst",
    "installer": "msi msix appx exe deb rpm dmg pkg",
    "code": "py js ts jsx tsx java c cpp h hpp cs go rs rb php swift kt sh ps1 bat sql html css scss json yaml yml xml toml ipynb",
    "database": "sqlite sqlite3 db mdb accdb sql dump bak",
    "disk_image": "vhd vhdx vmdk vdi qcow2 ova ovf",
    "font": "ttf otf woff woff2 fon",
}
EXT_TO_GROUP = {e: g for g, exts in EXT_GROUPS.items() for e in exts.split()}

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    root TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    elevated INTEGER NOT NULL,
    cluster_bytes INTEGER NOT NULL,
    volume_total_bytes INTEGER,
    volume_free_bytes INTEGER,
    n_dirs INTEGER DEFAULT 0,
    n_files INTEGER DEFAULT 0,
    n_errors INTEGER DEFAULT 0,
    bytes_logical INTEGER DEFAULT 0,
    bytes_disk INTEGER DEFAULT 0,
    complete INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dirs (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL,
    parent_id INTEGER,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    depth INTEGER NOT NULL,
    attrs INTEGER DEFAULT 0,
    reparse_tag INTEGER DEFAULT 0,
    -- files directly in this dir
    own_files INTEGER DEFAULT 0,
    own_bytes_logical INTEGER DEFAULT 0,
    own_bytes_disk INTEGER DEFAULT 0,
    -- whole subtree, filled in by rollup()
    total_dirs INTEGER DEFAULT 0,
    total_files INTEGER DEFAULT 0,
    total_bytes_logical INTEGER DEFAULT 0,
    total_bytes_disk INTEGER DEFAULT 0,
    total_bytes_cloud INTEGER DEFAULT 0,
    newest_mtime REAL,
    newest_atime REAL
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL,
    dir_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    ext TEXT,
    grp TEXT,
    bytes_logical INTEGER NOT NULL,
    bytes_disk INTEGER NOT NULL,
    mtime REAL,
    atime REAL,
    ctime REAL,
    attrs INTEGER DEFAULT 0,
    cloud_only INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT
);
"""

INDEXES = """
-- parent_id alone, not (snapshot_id, parent_id). The rollup joins children to
-- parents without naming a snapshot, and an index leading with snapshot_id
-- cannot serve that lookup: SQLite falls back to scanning the whole table once
-- per parent, which turns the rollup quadratic. This index is the difference
-- between seconds and never finishing.
CREATE INDEX IF NOT EXISTS ix_dirs_parent ON dirs(parent_id);
CREATE INDEX IF NOT EXISTS ix_dirs_snap_parent ON dirs(snapshot_id, parent_id);
CREATE INDEX IF NOT EXISTS ix_dirs_snap_depth ON dirs(snapshot_id, depth);
CREATE INDEX IF NOT EXISTS ix_dirs_path ON dirs(snapshot_id, path);
CREATE INDEX IF NOT EXISTS ix_dirs_size ON dirs(snapshot_id, total_bytes_disk DESC);
CREATE INDEX IF NOT EXISTS ix_files_dir ON files(dir_id);
CREATE INDEX IF NOT EXISTS ix_files_size ON files(snapshot_id, bytes_disk DESC);
CREATE INDEX IF NOT EXISTS ix_files_grp ON files(snapshot_id, grp);
CREATE INDEX IF NOT EXISTS ix_files_atime ON files(snapshot_id, atime);
CREATE INDEX IF NOT EXISTS ix_files_logical ON files(snapshot_id, bytes_logical);
"""


# ---------------------------------------------------------------- win32 helpers

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.GetCompressedFileSizeW.argtypes = [wintypes.LPCWSTR, wintypes.LPDWORD]
_k32.GetCompressedFileSizeW.restype = wintypes.DWORD
INVALID_FILE_SIZE = 0xFFFFFFFF


def compressed_size(win_path):
    """Bytes actually allocated on disk, or None if the call fails."""
    high = wintypes.DWORD(0)
    low = _k32.GetCompressedFileSizeW(win_path, ctypes.byref(high))
    if low == INVALID_FILE_SIZE and ctypes.get_last_error() != 0:
        return None
    return (high.value << 32) | low


def volume_info(drive):
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    _k32.GetDiskFreeSpaceExW(
        wintypes.LPCWSTR(drive), None, ctypes.byref(total), ctypes.byref(free)
    )
    sectors = wintypes.DWORD(0)
    bytes_per_sector = wintypes.DWORD(0)
    free_clusters = wintypes.DWORD(0)
    total_clusters = wintypes.DWORD(0)
    _k32.GetDiskFreeSpaceW(
        wintypes.LPCWSTR(drive),
        ctypes.byref(sectors),
        ctypes.byref(bytes_per_sector),
        ctypes.byref(free_clusters),
        ctypes.byref(total_clusters),
    )
    cluster = (sectors.value * bytes_per_sector.value) or 4096
    return total.value, free.value, cluster


def is_elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def win(path):
    """Long-path form, for passing to the OS."""
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def unwin(path):
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


# ------------------------------------------------------------------- the walker


class Scanner:
    def __init__(self, db, root, cluster, quiet=False):
        self.db = db
        self.root = root
        self.cluster = cluster
        # The in-place progress line only makes sense on a terminal; when output
        # is piped it just trails garbage after the report.
        self.quiet = quiet or not sys.stderr.isatty()
        self.n_dirs = 0
        self.n_files = 0
        self.n_errors = 0
        self.bytes_logical = 0
        self.bytes_disk = 0
        self.file_rows = []
        self.error_rows = []
        self.snapshot_id = None
        self._last_report = 0.0

    def log_error(self, path, kind, message):
        self.n_errors += 1
        self.error_rows.append((self.snapshot_id, unwin(path), kind, str(message)[:500]))

    def progress(self, path):
        if self.quiet:
            return
        now = time.monotonic()
        if now - self._last_report < 2.0:
            return
        self._last_report = now
        sys.stderr.write(
            "\r%7d dirs  %9d files  %7.1f GB on disk  %-58.58s"
            % (self.n_dirs, self.n_files, self.bytes_disk / 2**30, unwin(path)[:58])
        )
        sys.stderr.flush()

    def flush(self, force=False):
        if force or len(self.file_rows) >= 20000:
            self.db.executemany(
                "INSERT INTO files (snapshot_id, dir_id, name, ext, grp, bytes_logical,"
                " bytes_disk, mtime, atime, ctime, attrs, cloud_only)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                self.file_rows,
            )
            self.file_rows.clear()
        if force or len(self.error_rows) >= 500:
            self.db.executemany(
                "INSERT INTO errors (snapshot_id, path, kind, message) VALUES (?,?,?,?)",
                self.error_rows,
            )
            self.error_rows.clear()
        if force:
            self.db.commit()

    def disk_size(self, entry, st, attrs):
        """Actual on-disk footprint. Cheap path for ordinary files."""
        if attrs & NEEDS_REAL_SIZE:
            real = compressed_size(win(entry.path))
            if real is not None:
                return real
        if st.st_size == 0:
            return 0
        return -(-st.st_size // self.cluster) * self.cluster

    def insert_dir(self, parent_id, path, depth, attrs, tag):
        name = os.path.basename(path.rstrip("\\")) or path
        cur = self.db.execute(
            "INSERT INTO dirs (snapshot_id, parent_id, path, name, depth, attrs, reparse_tag)"
            " VALUES (?,?,?,?,?,?,?)",
            (self.snapshot_id, parent_id, unwin(path), name, depth, attrs, tag),
        )
        self.n_dirs += 1
        return cur.lastrowid

    def run(self, snapshot_id, graft_parent=None, graft_depth=0):
        """Walk self.root into the snapshot.

        `graft_*` is for refreshes: instead of hanging the new tree off nothing,
        the refreshed subtree's root is attached beneath an existing directory
        copied from the previous snapshot.
        """
        self.snapshot_id = snapshot_id
        root_id = self.insert_dir(graft_parent, self.root, graft_depth,
                                  FILE_ATTRIBUTE_DIRECTORY, 0)
        # Explicit stack: some of these trees are deep enough to blow recursion.
        stack = [(self.root, root_id, graft_depth)]
        while stack:
            path, dir_id, depth = stack.pop()
            self.walk_one(path, dir_id, depth, stack)
        self.flush(force=True)
        return root_id

    def walk_one(self, path, dir_id, depth, stack):
        self.progress(path)
        own_files = own_logical = own_disk = 0
        newest_mtime = newest_atime = None
        subdirs = []
        try:
            it = os.scandir(win(path))
        except OSError as exc:
            self.log_error(path, "scandir", exc)
            return
        with it:
            while True:
                try:
                    entry = next(it)
                except StopIteration:
                    break
                except OSError as exc:
                    self.log_error(path, "iterate", exc)
                    break
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    self.log_error(entry.path, "stat", exc)
                    continue
                attrs = getattr(st, "st_file_attributes", 0)
                tag = getattr(st, "st_reparse_tag", 0)
                if attrs & FILE_ATTRIBUTE_DIRECTORY:
                    subdirs.append((entry.path, attrs, tag))
                    continue
                size = st.st_size
                disk = self.disk_size(entry, st, attrs)
                cloud = 1 if (attrs & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
                                       | FILE_ATTRIBUTE_RECALL_ON_OPEN)) and disk < size else 0
                ext = os.path.splitext(entry.name)[1].lower().lstrip(".")[:24]
                own_files += 1
                own_logical += size
                own_disk += disk
                if newest_mtime is None or st.st_mtime > newest_mtime:
                    newest_mtime = st.st_mtime
                if newest_atime is None or st.st_atime > newest_atime:
                    newest_atime = st.st_atime
                self.file_rows.append(
                    (self.snapshot_id, dir_id, entry.name, ext, EXT_TO_GROUP.get(ext),
                     size, disk, st.st_mtime, st.st_atime, st.st_ctime, attrs, cloud)
                )
                self.n_files += 1

        self.bytes_logical += own_logical
        self.bytes_disk += own_disk
        self.db.execute(
            "UPDATE dirs SET own_files=?, own_bytes_logical=?, own_bytes_disk=?,"
            " newest_mtime=?, newest_atime=? WHERE id=?",
            (own_files, own_logical, own_disk, newest_mtime, newest_atime, dir_id),
        )

        for child_path, attrs, tag in subdirs:
            clean = unwin(child_path)
            if clean.lower() in SKIP_PATHS:
                self.log_error(child_path, "skipped", "on the skip list")
                continue
            # A reparse point is only safe to descend into if it is a cloud
            # placeholder. Junctions and symlinks are recorded and not followed,
            # otherwise the walk can loop or double-count.
            if attrs & FILE_ATTRIBUTE_REPARSE_POINT and not is_cloud_tag(tag):
                self.insert_dir(dir_id, child_path, depth + 1, attrs, tag)
                continue
            child_id = self.insert_dir(dir_id, child_path, depth + 1, attrs, tag)
            stack.append((child_path, child_id, depth + 1))

        self.flush()


# ----------------------------------------------------------------------- rollup


def rollup(db, snapshot_id, verbose=True):
    """Propagate subtree totals upward, one level at a time, deepest first.

    Each pass aggregates a whole depth level in a single GROUP BY and joins the
    result to the parents. Doing it with per-row correlated subqueries instead
    is quadratic and does not finish on a full drive.
    """
    db.execute(
        "UPDATE dirs SET total_files=own_files, total_bytes_logical=own_bytes_logical,"
        " total_bytes_disk=own_bytes_disk, total_dirs=0 WHERE snapshot_id=?",
        (snapshot_id,),
    )
    db.execute(
        """
        UPDATE dirs SET total_bytes_cloud = COALESCE(agg.b, 0)
        FROM (SELECT dir_id, SUM(bytes_logical) AS b FROM files
              WHERE snapshot_id=? AND cloud_only=1 GROUP BY dir_id) AS agg
        WHERE dirs.id = agg.dir_id
        """,
        (snapshot_id,),
    )
    db.commit()
    max_depth = db.execute(
        "SELECT MAX(depth) FROM dirs WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()[0] or 0
    for depth in range(max_depth, 0, -1):
        if verbose:
            sys.stderr.write("\r  rollup depth %d  " % depth)
            sys.stderr.flush()
        db.execute(
            """
            UPDATE dirs SET
              total_files          = dirs.total_files          + agg.files,
              total_dirs           = dirs.total_dirs           + agg.dirs,
              total_bytes_logical  = dirs.total_bytes_logical  + agg.logical,
              total_bytes_disk     = dirs.total_bytes_disk     + agg.disk,
              total_bytes_cloud    = dirs.total_bytes_cloud    + agg.cloud,
              newest_mtime = MAX(COALESCE(dirs.newest_mtime, 0), agg.mtime),
              newest_atime = MAX(COALESCE(dirs.newest_atime, 0), agg.atime)
            FROM (
              SELECT parent_id,
                     SUM(total_files) AS files,
                     COUNT(*) + SUM(total_dirs) AS dirs,
                     SUM(total_bytes_logical) AS logical,
                     SUM(total_bytes_disk) AS disk,
                     SUM(total_bytes_cloud) AS cloud,
                     COALESCE(MAX(newest_mtime), 0) AS mtime,
                     COALESCE(MAX(newest_atime), 0) AS atime
              FROM dirs WHERE snapshot_id=? AND depth=? AND parent_id IS NOT NULL
              GROUP BY parent_id
            ) AS agg
            WHERE dirs.id = agg.parent_id
            """,
            (snapshot_id, depth),
        )
        db.commit()
    if verbose:
        sys.stderr.write("\r" + " " * 30 + "\r")
        sys.stderr.flush()


# ------------------------------------------------------------------------- cli


def gb(n):
    return (n or 0) / 2**30


def connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=OFF")
    db.executescript(SCHEMA)
    # Refresh provenance. Older databases lack these columns; add rather than
    # migrate, so every snapshot that already exists keeps working.
    cols = {r[1] for r in db.execute("PRAGMA table_info(snapshots)")}
    for col in ("refresh_of INTEGER", "refresh_path TEXT"):
        name = col.split()[0]
        if name not in cols:
            db.execute("ALTER TABLE snapshots ADD COLUMN " + col)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            choice TEXT NOT NULL,
            decided_at REAL NOT NULL,
            note TEXT
        );
        """
    )
    return db


def cmd_scan(args):
    root = os.path.abspath(args.root).rstrip("\\") + "\\" if len(args.root) <= 3 else os.path.abspath(args.root)
    drive = os.path.splitdrive(root)[0] + "\\"
    total, free, cluster = volume_info(drive)
    elevated = is_elevated()

    db = connect(args.db)
    started = time.time()
    cur = db.execute(
        "INSERT INTO snapshots (root, started_at, elevated, cluster_bytes,"
        " volume_total_bytes, volume_free_bytes) VALUES (?,?,?,?,?,?)",
        (root, started, int(elevated), cluster, total, free),
    )
    snapshot_id = cur.lastrowid
    db.commit()

    print("snapshot %d  root %s" % (snapshot_id, root))
    print("volume: %.1f GB total, %.1f GB free, %d-byte clusters" % (gb(total), gb(free), cluster))
    print("elevated: %s%s" % (elevated, "" if elevated else "  (ProgramData and other profiles will be partly hidden)"))
    print("")

    sc = Scanner(db, root, cluster, quiet=args.quiet)
    try:
        sc.run(snapshot_id)
    except KeyboardInterrupt:
        sc.flush(force=True)
        print("\ninterrupted; snapshot %d left incomplete" % snapshot_id)
        return 1

    sys.stderr.write("\r" + " " * 110 + "\r")
    sys.stderr.flush()
    print("walked %d dirs, %d files in %.0f s" % (sc.n_dirs, sc.n_files, time.time() - started))
    finalize(db, snapshot_id)
    print("")
    return cmd_verify(args, db, snapshot_id)


def finalize(db, snapshot_id):
    """Index, roll up, and write the snapshot's totals from what is in the table.

    Totals are recomputed from the rows rather than taken from the scanner's
    counters, so this is safe to re-run on a walk that was interrupted after the
    rows were committed.
    """
    print("creating indexes...", flush=True)
    db.executescript(INDEXES)
    db.commit()
    print("rolling up directory totals...", flush=True)
    t0 = time.time()
    rollup(db, snapshot_id)
    print("  rollup took %.0f s" % (time.time() - t0), flush=True)

    n_dirs, = db.execute("SELECT COUNT(*) FROM dirs WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    n_files, logical, disk = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(bytes_logical),0), COALESCE(SUM(bytes_disk),0)"
        " FROM files WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    n_errors, = db.execute("SELECT COUNT(*) FROM errors WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    db.execute(
        "UPDATE snapshots SET finished_at=?, n_dirs=?, n_files=?, n_errors=?,"
        " bytes_logical=?, bytes_disk=?, complete=1 WHERE id=?",
        (time.time(), n_dirs, n_files, n_errors, logical, disk, snapshot_id),
    )
    db.commit()


def cmd_finish(args):
    """Index and roll up a snapshot whose walk already committed its rows."""
    db = connect(args.db)
    sid = args.finish
    row = db.execute("SELECT root, complete FROM snapshots WHERE id=?", (sid,)).fetchone()
    if row is None:
        print("no snapshot %d" % sid)
        return 1
    print("finishing snapshot %d (%s)" % (sid, row[0]))
    finalize(db, sid)
    print("")
    return cmd_verify(args, db, sid)


def normpath(p):
    return os.path.normpath(p).rstrip("\\").lower()


def cmd_refresh(args):
    """Rescan one subtree into a NEW snapshot.

    Copies everything outside the refreshed path from the previous snapshot,
    re-walks the path itself, then rolls up. The old snapshot is left intact, so
    a refresh is diffable and a delete is verifiable: if the folder no longer
    exists on disk, it should simply not appear in the new snapshot.
    """
    db = connect(args.db)
    base_row = db.execute(
        "SELECT MAX(id), root FROM snapshots WHERE complete=1").fetchone()
    base, base_root = base_row
    if base is None:
        print("no complete snapshot to refresh; run a full scan first")
        return 1
    target = normpath(args.refresh)
    if not target.startswith(normpath(base_root)):
        print("%s is not under this scan's root (%s)" % (args.refresh, base_root))
        return 1

    # Locate the refresh point in the old snapshot. If the target itself was
    # never scanned (e.g. it is newly created) or no longer exists (deleted),
    # climb to the nearest ancestor that the old snapshot knows about.
    by_path = {normpath(r[1]): r for r in db.execute(
        "SELECT id, path, depth, parent_id FROM dirs WHERE snapshot_id=?", (base,))}
    want = target
    want_deleted = not os.path.isdir(win(target))
    probe = want
    while probe is not None:
        row = by_path.get(probe)
        if row:
            break
        parent = os.path.dirname(probe)
        probe = normpath(parent) if normpath(parent) != probe else None
    if row is None:
        print("no part of %s is in snapshot %d" % (args.refresh, base))
        return 1
    target_id, target_path, target_depth, target_parent = row
    if want_deleted and normpath(target_path) == want:
        # The target is still recorded in the old snapshot but gone from disk:
        # refresh its parent so the removal shows up.
        parent = by_path.get(normpath(os.path.dirname(target_path)))
        if parent is None:
            print("cannot refresh a deleted root")
            return 1
        target_id, target_path, target_depth, target_parent = parent
        print("%s is gone from disk; refreshing its parent %s"
              % (args.refresh, target_path))
    elif normpath(target_path) != want:
        why = "it was deleted" if want_deleted else "it was never scanned"
        print("%s not in snapshot because %s; refreshing nearest ancestor %s"
              % (args.refresh, why, target_path))

    subtree = {r[0] for r in db.execute(
        """WITH RECURSIVE s(i) AS (
             SELECT id FROM dirs WHERE id=?
             UNION ALL SELECT d.id FROM dirs d JOIN s ON d.parent_id=s.i)
           SELECT i FROM s""", (target_id,))}

    total, free, cluster = volume_info(os.path.splitdrive(base_root)[0] + "\\")
    new_sid = db.execute(
        "INSERT INTO snapshots (root, started_at, elevated, cluster_bytes,"
        " volume_total_bytes, volume_free_bytes, refresh_of, refresh_path)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (base_root, time.time(), int(is_elevated()), cluster, total, free,
         base, target_path)).lastrowid

    print("snapshot %d: refresh of %s, based on snapshot %d" % (new_sid, target_path, base))
    print("copying rows outside the subtree...", flush=True)
    t0 = time.time()

    # Copy dirs outside the subtree with fresh ids, remapping parent_id through
    # idmap. Rows are processed parents-first (ordered by depth), and the next
    # rowid is predictable because this connection is the only writer - so the
    # map old->new is built BEFORE inserting and parent links survive the copy.
    # Building the map afterwards, as a first version did, left every copied row
    # orphaned: parent_id=None, which is exactly the kind of wrongness the
    # rollup invariant check exists to catch.
    rows = db.execute(
        "SELECT id, parent_id, path, name, depth, attrs, reparse_tag, own_files,"
        " own_bytes_logical, own_bytes_disk, newest_mtime, newest_atime"
        " FROM dirs WHERE snapshot_id=? ORDER BY depth", (base,)).fetchall()
    first_new = (db.execute("SELECT MAX(id) FROM dirs").fetchone()[0] or 0) + 1
    idmap = {}
    batch = []
    i = 0
    for r in rows:
        if r[0] in subtree:
            continue
        idmap[r[0]] = first_new + i
        i += 1
        batch.append((new_sid, idmap.get(r[1])) + r[2:])
    db.executemany(
        "INSERT INTO dirs (snapshot_id, parent_id, path, name, depth, attrs,"
        " reparse_tag, own_files, own_bytes_logical, own_bytes_disk,"
        " newest_mtime, newest_atime) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", batch)
    copied = db.execute("SELECT COUNT(*) FROM dirs WHERE snapshot_id=?",
                        (new_sid,)).fetchone()[0]
    if copied != i:
        print("copy produced %d rows for %d expected - aborting" % (copied, i))
        return 1
    # Defensive: the assigned ids must actually be the contiguous range we
    # mapped to. If rowid allocation ever changes, fail loudly rather than ship
    # a corrupt tree.
    rmin, rmax = db.execute(
        "SELECT MIN(id), MAX(id) FROM dirs WHERE snapshot_id=?",
        (new_sid,)).fetchone()
    if rmin != first_new or rmax != first_new + i - 1:
        print("assigned ids are not the contiguous range assumed - aborting")
        return 1

    db.execute("CREATE TEMP TABLE idmap(old_id INTEGER PRIMARY KEY, new_id INTEGER)")
    db.executemany("INSERT INTO idmap VALUES (?,?)", idmap.items())
    db.execute(
        """INSERT INTO files (snapshot_id, dir_id, name, ext, grp, bytes_logical,
             bytes_disk, mtime, atime, ctime, attrs, cloud_only)
           SELECT ?, m.new_id, f.name, f.ext, f.grp, f.bytes_logical, f.bytes_disk,
                  f.mtime, f.atime, f.ctime, f.attrs, f.cloud_only
           FROM files f JOIN idmap m ON m.old_id = f.dir_id
           WHERE f.snapshot_id=?""", (new_sid, base))

    # Error rows belong to their snapshot by path, not by id; copy the ones that
    # lie outside the refreshed subtree.
    prefix = normpath(target_path) + "\\"
    db.executemany(
        "INSERT INTO errors (snapshot_id, path, kind, message) VALUES (?,?,?,?)",
        [(new_sid, p, k, m) for p, k, m in db.execute(
            "SELECT path, kind, message FROM errors WHERE snapshot_id=?", (base,))
         if normpath(p) != normpath(target_path)
         and not normpath(p).startswith(prefix)])
    db.commit()
    print("  copied in %.0f s" % (time.time() - t0), flush=True)

    if os.path.isdir(win(target_path)):
        sc = Scanner(db, target_path, cluster, quiet=args.quiet)
        sc.run(new_sid, graft_parent=idmap.get(target_parent), graft_depth=target_depth)
    else:
        # The whole refresh target is gone; nothing to re-walk. That is the
        # expected path when verifying a deletion.
        if normpath(target_path) == want:
            print("%s is gone; nothing to re-walk" % target_path)

    finalize(db, new_sid)
    print("")
    rc = cmd_verify(args, db, new_sid)

    # If the user asked to refresh a path they had deleted, confirm it is gone.
    if want_deleted or normpath(target_path) != want:
        still = db.execute(
            "SELECT COUNT(*) FROM dirs WHERE snapshot_id=? AND lower(path)=?",
            (new_sid, want)).fetchone()[0]
        fstill = db.execute(
            "SELECT COUNT(*) FROM files f JOIN dirs d ON d.id=f.dir_id"
            " WHERE f.snapshot_id=? AND lower(d.path || '\\' || f.name)=?",
            (new_sid, want)).fetchone()[0]
        if still or fstill:
            print("")
            print("WARNING: %s still appears in the new snapshot (%d dirs, %d files)"
                  % (args.refresh, still, fstill))
        else:
            print("")
            print("confirmed: %s is no longer on disk" % args.refresh)
    return rc


def cmd_verify(args, db=None, snapshot_id=None):
    db = db or connect(args.db)
    if snapshot_id is None:
        row = db.execute("SELECT MAX(id) FROM snapshots WHERE complete=1").fetchone()
        snapshot_id = row[0]
        if snapshot_id is None:
            print("no complete snapshot")
            return 1
    s = db.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
    cols = [c[0] for c in db.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).description]
    s = dict(zip(cols, s))

    used = s["volume_total_bytes"] - s["volume_free_bytes"]
    whole_volume = len(s["root"]) <= 3
    # Cloud-only bytes have to be summed from the flagged rows. Subtracting
    # on-disk from logical does not work: cluster rounding makes on-disk larger
    # than logical for any directory full of small files.
    cloud_bytes, cloud_files = db.execute(
        "SELECT COALESCE(SUM(bytes_logical), 0), COUNT(*) FROM files"
        " WHERE snapshot_id=? AND cloud_only=1", (snapshot_id,)).fetchone()

    print("=== snapshot %d: %s ===" % (snapshot_id, s["root"]))
    print("%-34s %8.1f GB" % ("occupies on disk", gb(s["bytes_disk"])))
    print("%-34s %8.1f GB" % ("logical size of all files", gb(s["bytes_logical"])))
    print("%-34s %8.1f GB  (%d files)" % ("of which cloud-only, not on disk",
                                          gb(cloud_bytes), cloud_files))
    if whole_volume:
        print("%-34s %8.1f GB" % ("Windows reports used", gb(used)))
        print("%-34s %8.1f %%" % ("accounted for", 100.0 * s["bytes_disk"] / used if used else 0))
        gap = used - s["bytes_disk"]
        print("%-34s %8.1f GB  %s" % ("unaccounted", gb(gap),
              "check the errors below" if gap > 5 * 2**30 else "ok"))
    print("")
    print("%d dirs, %d files, %d errors, elevated=%s"
          % (s["n_dirs"], s["n_files"], s["n_errors"], bool(s["elevated"])))
    rows = db.execute(
        "SELECT kind, COUNT(*) FROM errors WHERE snapshot_id=? GROUP BY kind ORDER BY 2 DESC",
        (snapshot_id,),
    ).fetchall()
    for kind, n in rows:
        print("   %-12s %d" % (kind, n))
    if s["n_errors"]:
        # Where the denials cluster matters more than their count: 600 of them
        # inside one cache folder is noise, 600 spread across a profile is a
        # hole in the measurement.
        print("   unreadable paths, grouped by top three levels:")
        seen = {}
        for (path,) in db.execute(
            "SELECT path FROM errors WHERE snapshot_id=? AND kind IN ('scandir','iterate')",
            (snapshot_id,)):
            key = "\\".join(path.split("\\")[:4])
            seen[key] = seen.get(key, 0) + 1
        for key, n in sorted(seen.items(), key=lambda kv: -kv[1])[:12]:
            print("      %5d  %s" % (n, key))
    # The rollup is the one piece of arithmetic everything downstream trusts.
    # The root's subtree total must equal the sum over every file row, and the
    # directory count must match. If either drifts, the tree sums are wrong and
    # no report built on them means anything.
    root = db.execute(
        "SELECT total_bytes_disk, total_bytes_logical, total_files, total_dirs FROM dirs"
        " WHERE snapshot_id=? AND depth=0", (snapshot_id,)).fetchone()
    if root:
        checks = [
            ("bytes on disk", root[0], s["bytes_disk"]),
            ("bytes logical", root[1], s["bytes_logical"]),
            ("file count", root[2], s["n_files"]),
            ("dir count", root[3] + 1, s["n_dirs"]),
        ]
        bad = [c for c in checks if c[1] != c[2]]
        print("rollup invariant: %s" % ("OK" if not bad else "FAILED"))
        for label, got, want in bad:
            print("   %-14s rollup says %d, files table says %d (%+d)"
                  % (label, got, want, got - want))
    # Every non-root row must point at a parent inside the same snapshot. A
    # refresh that mangles parent links passes every size check and still means
    # the whole tree is silently detached.
    orphans = db.execute(
        "SELECT COUNT(*) FROM dirs c WHERE c.snapshot_id=? AND c.parent_id IS NOT NULL"
        " AND c.parent_id NOT IN (SELECT id FROM dirs WHERE snapshot_id=?)",
        (snapshot_id, snapshot_id)).fetchone()[0]
    print("parent links intact: %s" % ("OK" if orphans == 0 else "FAILED - %d orphans" % orphans))
    print("")
    print("largest top-level directories (on disk):")
    for path, disk, logical, files in db.execute(
        "SELECT path, total_bytes_disk, total_bytes_logical, total_files FROM dirs"
        " WHERE snapshot_id=? AND depth=1 ORDER BY total_bytes_disk DESC LIMIT 15",
        (snapshot_id,),
    ):
        print("   %8.1f GB  (logical %8.1f GB, %8d files)  %s"
              % (gb(disk), gb(logical), files, path))
    return 0


def cmd_list(args):
    db = connect(args.db)
    print("%3s  %-28s %-20s %10s %10s %8s %s"
          % ("id", "root", "when", "on disk", "files", "errors", "state"))
    for r in db.execute("SELECT id, root, started_at, bytes_disk, n_files, n_errors, complete"
                        " FROM snapshots ORDER BY id"):
        print("%3d  %-28s %-20s %9.1fG %10d %8d %s"
              % (r[0], r[1][:28], time.strftime("%Y-%m-%d %H:%M", time.localtime(r[2])),
                 gb(r[3]), r[4], r[5], "complete" if r[6] else "INCOMPLETE"))
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DB_DEFAULT)
    p.add_argument("--root", default="C:\\")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--verify", action="store_true", help="report on the latest snapshot and exit")
    p.add_argument("--list-snapshots", action="store_true")
    p.add_argument("--finish", type=int, metavar="ID",
                   help="index and roll up an already-walked snapshot")
    p.add_argument("--refresh", metavar="PATH",
                   help="rescan one subtree into a new snapshot; use to verify "
                        "a deletion or pick up local changes without re-walking C:\\")
    args = p.parse_args()
    if args.list_snapshots:
        return cmd_list(args)
    if args.finish:
        return cmd_finish(args)
    if args.refresh:
        return cmd_refresh(args)
    if args.verify:
        return cmd_verify(args)
    return cmd_scan(args)


if __name__ == "__main__":
    sys.exit(main())
