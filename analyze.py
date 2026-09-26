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

import time

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
    shown_parents = 0
    for pid, kids in sorted(by_parent.items(), key=lambda kv: -len(kv[1])):
        shown_parents += 1
        if shown_parents > 400:
            break
        ppath = parent_paths.get(pid, "?")
        if len(kids) > 2:
            out.append(dict(kind="empty_dir", tier="A", path=ppath, dir_id=pid,
                            bytes_disk=0, n_files=len(kids), mtime=None,
                            reason="%d empty subfolders - delete the whole set"
                                   % len(kids)))
        else:
            for k in kids:
                out.append(dict(kind="empty_dir", tier="A", path=k["path"],
                                dir_id=k["id"], bytes_disk=0, n_files=0,
                                mtime=None,
                                reason="Empty folder - nothing beneath it"))

    # macOS resource-fork litter (._*) and .DS_Store, aggregated per folder so
    # a folder of 600 turds is one decision, not 600.
    mac = db.execute(
        "SELECT d.id, d.path, COUNT(*) AS n, SUM(f.bytes_disk) AS b"
        " FROM files f JOIN dirs d ON d.id=f.dir_id"
        " WHERE f.snapshot_id=? AND (f.name LIKE '._%' OR f.name='.DS_Store')"
        " GROUP BY d.id", (sid,)).fetchall()
    out += [dict(kind="macos_junk", tier="A", path=r[1], dir_id=r[0],
                 bytes_disk=r[3], n_files=r[2], mtime=None,
                 reason="%d macOS metadata files (._*, .DS_Store)" % r[2])
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
    # Installer cache - those are needed for uninstalls).
    out += _file_candidates(
        db, sid,
        "f.grp='installer' AND f.cloud_only=0 AND f.bytes_disk > 100*1024*1024"
        " AND d.path NOT LIKE 'C:\\Windows\\Installer%'",
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
