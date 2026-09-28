"""Phase 4 machinery: marked decisions become Recycle Bin deletions.

This is the only module allowed to change anything on disk. Everything it does
is reversible (send to the Recycle Bin, restore from it) or already-deleted
data (emptying the Bin), and every action lands in a JSONL manifest under
data/manifests/ so a batch can be put back.

    python reclaim.py --self-test        round-trip scratch files through the bin
    python reclaim.py --propose          print the batch the current marks imply
    python reclaim.py --run              execute that batch (manifest first)
    python reclaim.py --run --refresh    and rescan the affected parents after
    python reclaim.py --restore FILE     put back what a manifest recycled
    python reclaim.py --empty-bin        empty the Recycle Bin itself (permanent)

The never-touch list is enforced in code, not by the reviewer: a batch that
contains a protected path refuses before touching anything.
"""

import argparse
import ctypes
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from ctypes import wintypes

from scan import win, unwin, normpath, connect, volume_info, DB_DEFAULT

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MANIFEST_DIR = os.path.join(DATA_DIR, "manifests")

# ------------------------------------------------------------------ never touch
#
# Enforcement, not documentation. A path matching any of these is refused; a
# batch containing one does not run at all. Compared case-insensitively on a
# normalized path, so trailing slashes and casing cannot slip past.

NEVER_PREFIXES = (
    r"c:\windows", r"c:\program files", r"c:\program files (x86)",
    r"c:\programdata", r"c:\$recycle.bin", r"c:\system volume information",
    r"c:\config.msi", r"c:\recovery", r"c:\$sysreset", r"c:\aviddownloads",
    # The Switch SD card's system folders.
    r"e:\atmosphere", r"e:\switch", r"e:\nintendo", r"e:\emummc",
    r"e:\bootloader", r"e:\games",
)
NEVER_FILES = {r"c:\hiberfil.sys", r"c:\pagefile.sys", r"c:\swapfile.sys"}
TOOL_ROOT = normpath(HERE)


def running_processes():
    """Exe paths of every running process, for the running-app AppData rule."""
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    arr = (wintypes.DWORD * 8192)()
    need = wintypes.DWORD(0)
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(need)):
        return []
    k32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, wintypes.LPDWORD]
    out = []
    buf = ctypes.create_unicode_buffer(1024)
    for pid in arr[: need.value // 4]:
        if not pid:
            continue
        h = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            n = wintypes.DWORD(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                out.append(buf.value)
        finally:
            k32.CloseHandle(h)
    return out


def _appdata_target(n):
    """For a normalized path under *\\AppData\\*, return (root, tokens).

    root is the path through the app directory; tokens are normalized name
    fragments a process name could plausibly equal. For
    `...\\appdata\\local\\programs\\devin\\...` the app dir is `devin`, not
    `programs`.
    """
    m = re.search(r"\\appdata\\(local|roaming|locallow)\\([^\\]+)(?:\\([^\\]+))?", n)
    if not m:
        return None
    seg0, seg1 = m.group(2), m.group(3)
    tokens = {re.sub(r"[^a-z0-9]", "", s) for s in (seg0, seg1) if s}
    tokens.discard("programs")
    return (m.group(0), tokens)


def guard_reason(path, running=None):
    """None if the path may be recycled, else a one-line refusal reason."""
    p = path.strip()
    if len(p) < 4 or p[1] != ":":
        return "not an absolute drive path"
    n = normpath(p)
    if len(n) <= 3:
        return "a drive root is never a target"
    for pre in NEVER_PREFIXES:
        if n == pre or n.startswith(pre + "\\"):
            return "protected system area"
    if n in NEVER_FILES:
        return "protected system file"
    if n == TOOL_ROOT or n.startswith(TOOL_ROOT + "\\"):
        return "inside this tool's own directory"
    if not os.path.lexists(win(p)):
        return "not on disk"
    appdata = _appdata_target(n)
    if appdata:
        root, tokens = appdata
        if running is None:
            running = running_processes()
        for exe in running:
            el = exe.lower()
            if el.startswith(root + "\\"):
                return "AppData of a running app (%s)" % os.path.basename(el)
            stem = re.sub(r"[^a-z0-9]", "",
                          os.path.splitext(os.path.basename(el))[0])
            for t in tokens:
                if t and (t == stem
                          or (len(t) >= 4 and len(stem) >= 4
                              and (t in stem or stem in t))):
                    return "AppData of a running app (%s)" % os.path.basename(el)
    return None


# ------------------------------------------------------------ the bin itself

FO_DELETE = 0x3
FOF_ALLOWUNDO = 0x40
FOF_SILENT = 0x4
FOF_NOCONFIRMATION = 0x10
FOF_NOERRORUI = 0x400
FOF_NOCONFIRMMKDIR = 0x200


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.USHORT),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


_sh32 = ctypes.WinDLL("shell32", use_last_error=True)
_sh32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
_sh32.SHFileOperationW.restype = ctypes.c_int
_com_ready = False


def send_to_bin(path):
    """Move one file or directory to the Recycle Bin. Raises OSError."""
    global _com_ready
    if not _com_ready:
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        except OSError:
            pass  # RPC_E_CHANGED_MODE is fine
        _com_ready = True
    p = os.path.abspath(unwin(path))
    buf = ctypes.create_unicode_buffer(p + "\0", len(p) + 2)
    op = SHFILEOPSTRUCTW(
        None, FO_DELETE, ctypes.cast(buf, wintypes.LPCWSTR), None,
        FOF_ALLOWUNDO | FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI
        | FOF_NOCONFIRMMKDIR,
        False, None, None)
    rc = _sh32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError(rc or -1, "recycle failed for %s" % p)
    if os.path.lexists(win(p)):
        raise OSError(-1, "recycle reported success but %s is still there" % p)


def find_in_bin(path, since=0.0, wait=3.0):
    """The ($I, $R) pair a recycled path left in the bin, newest match first.

    $I files hold the original path UTF-16LE; the $R sibling holds the data.
    Matching on file content rather than name because the name is random. The
    pair lands some time *after* SHFileOperationW returns, so callers retry for
    a few seconds - a single lookup right after a delete misses often enough
    to matter.
    """
    deadline = time.monotonic() + wait
    while True:
        pair = _find_in_bin_once(path, since)
        if pair or time.monotonic() >= deadline:
            return pair
        time.sleep(0.15)


def _find_in_bin_once(path, since):
    drive = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    binroot = drive + "$Recycle.Bin"
    want = normpath(path)
    best = None
    try:
        sids = os.scandir(win(binroot))
    except OSError:
        return None
    with sids:
        for sid in sids:
            if not sid.is_dir(follow_symlinks=False):
                continue
            try:
                entries = os.scandir(win(sid.path))
            except OSError:
                continue
            with entries:
                for e in entries:
                    if not e.name.upper().startswith("$I"):
                        continue
                    try:
                        st = e.stat()
                        if st.st_mtime < since or (best and st.st_mtime < best[0]):
                            continue
                        with open(win(e.path), "rb") as fh:
                            text = fh.read().decode("utf-16-le", "ignore")
                    except OSError:
                        continue
                    if want in text.lower():
                        rname = "$R" + e.name[2:]
                        best = (st.st_mtime, os.path.join(sid.path, e.name),
                                os.path.join(sid.path, rname))
    return (best[1], best[2]) if best and os.path.exists(win(best[2])) else None


def restore_pair(path, ipath, rpath, attrs=None):
    """Put a binned item back: move $R to the original path, drop $I.

    Manual because the shell's restore verb is localized; the $R file is the
    data and the $I file is only bookkeeping, so this is locale-proof.
    """
    dest = unwin(path)
    if os.path.lexists(win(dest)):
        raise OSError("restore target already exists: %s" % dest)
    parent = os.path.dirname(dest)
    if parent and not os.path.isdir(win(parent)):
        os.makedirs(win(parent))
    os.rename(win(rpath), win(dest))
    if attrs is not None:
        ctypes.windll.kernel32.SetFileAttributesW(win(dest), int(attrs))
    os.remove(win(ipath))


def empty_bin(drive="C:\\"):
    """Empty the Recycle Bin. Permanent - the Bin cannot go into the Bin."""
    hr = _sh32.SHEmptyRecycleBinW(None, wintypes.LPCWSTR(drive),
                                  0x1 | 0x2 | 0x4)  # no confirm/progress/sound
    if hr not in (0, 0x80070002):  # S_OK, or already empty
        raise OSError(hr, "SHEmptyRecycleBinW failed")


def empty_bin_logged(drive="C:\\"):
    """Empty the bin and record it. reversible: false is not decoration - a
    manifest entry is all the honesty this operation allows."""
    free_before = volume_info(drive)[1]
    empty_bin(drive)
    freed = volume_info(drive)[1] - free_before
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    mpath = os.path.join(
        MANIFEST_DIR, "batch-" + time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"action": "empty_bin", "ts": time.time(),
                             "freed": freed, "reversible": False}) + "\n")
    return {"freed": freed, "manifest": mpath}


# ------------------------------------------------------------------- batches

def _path_size(db, sid, path):
    """What the snapshot knows about a marked path: dir row, file row, or none."""
    r = db.execute(
        "SELECT 'dir' AS src, total_bytes_disk AS bd, total_bytes_logical AS bl,"
        " total_bytes_cloud AS bc, total_files AS nf, newest_mtime AS mt, 0 AS cl"
        " FROM dirs WHERE snapshot_id=? AND path=?", (sid, path)).fetchone()
    if r is None:
        r = db.execute(
            "SELECT 'dir' AS src, total_bytes_disk AS bd, total_bytes_logical AS bl,"
            " total_bytes_cloud AS bc, total_files AS nf, newest_mtime AS mt, 0 AS cl"
            " FROM dirs WHERE snapshot_id=? AND lower(path)=lower(?)",
            (sid, path)).fetchone()
    if r is None:
        r = db.execute(
            "SELECT 'file' AS src, f.bytes_disk AS bd, f.bytes_logical AS bl,"
            " CASE WHEN f.cloud_only=1 THEN f.bytes_logical ELSE 0 END AS bc,"
            " 1 AS nf, f.mtime AS mt, f.cloud_only AS cl"
            " FROM files f JOIN dirs d ON d.id=f.dir_id"
            " WHERE f.snapshot_id=? AND lower(d.path || '\\' || f.name)=lower(?)",
            (sid, path)).fetchone()
    if r is None:
        return dict(src="missing", bd=0, bl=0, bc=0, nf=0, mt=None, cl=0)
    return dict(zip(("src", "bd", "bl", "bc", "nf", "mt", "cl"),
                    (r[0], r[1], r[2], r[3], r[4], r[5], r[6])))


def propose(db, sid):
    """The batch the current 'delete' marks imply, with per-path verdicts."""
    marks = db.execute(
        "SELECT path, decided_at FROM decisions WHERE choice='delete'"
        " ORDER BY decided_at").fetchall()
    running = None
    entries = []
    for path, at in marks:
        info = _path_size(db, sid, path)
        if info["src"] != "missing" and _appdata_target(normpath(path)):
            if running is None:
                running = running_processes()
        entries.append(dict(
            path=path, decided_at=at, guard=guard_reason(path, running),
            src=info["src"], bytes_disk=info["bd"], bytes_logical=info["bl"],
            bytes_cloud=info["bc"], n_files=info["nf"], mtime=info["mt"],
            cloud_only=bool(info["cl"])))
    actionable = [e for e in entries if e["guard"] is None]
    return {
        "entries": entries,
        "actionable": len(actionable),
        "total_disk": sum(e["bytes_disk"] for e in actionable),
        "blocked": [e for e in entries if e["guard"]],
        "can_run": bool(actionable) and not any(e["guard"] for e in entries),
    }


def covering_parents(paths):
    """Minimal set of parent dirs covering every path - one refresh serves
    every deletion beneath it."""
    orig = {}
    for p in paths:
        orig.setdefault(normpath(os.path.dirname(p)), os.path.dirname(p))
    out = []
    for n in sorted(orig, key=len):
        if not any(n.startswith(a + "\\") for a in out):
            out.append(n)
    return [orig[n] for n in out]


def run_batch(db, sid, data_dir=DATA_DIR):
    """Send every 'delete' mark to the Recycle Bin. Manifest first, always.

    Aborts before touching anything if any marked path is refused by the
    guard - one bad row must not ride along inside an otherwise fine batch.
    """
    plan = propose(db, sid)
    if not plan["actionable"]:
        return {"ok": False, "error": "nothing marked for deletion",
                "entries": plan["entries"]}
    if plan["blocked"]:
        return {"ok": False, "error": "batch contains protected paths",
                "entries": plan["entries"], "blocked": plan["blocked"]}

    bid = "batch-" + time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    mpath = os.path.join(MANIFEST_DIR, bid + ".jsonl")
    free_before = volume_info(os.path.splitdrive(plan["entries"][0]["path"])[0]
                              + "\\")[1]
    results = []
    # If the manifest cannot be opened and written, the batch does not run.
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"batch": bid, "action": "begin", "ts": time.time(),
                             "n": len(plan["entries"])},
                            ensure_ascii=False) + "\n")
        fh.flush()
        started = time.time()
        for e in plan["entries"]:
            rec = {"batch": bid, "ts": time.time(), "action": "recycle",
                   "path": e["path"], "bytes_disk": e["bytes_disk"],
                   "decision": "delete", "decided_at": e["decided_at"]}
            try:
                st = os.stat(win(e["path"]))
                rec["attrs"] = getattr(st, "st_file_attributes", None)
                send_to_bin(e["path"])
                pair = find_in_bin(e["path"], since=started - 60)
                if pair:
                    rec["bin_i"], rec["bin_r"] = pair
                rec["ok"] = True
            except OSError as exc:
                rec["ok"] = False
                rec["error"] = str(exc)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            results.append(rec)
        freed = volume_info("C:\\")[1] - free_before
        fh.write(json.dumps({"batch": bid, "action": "done", "ts": time.time(),
                             "freed": freed}, ensure_ascii=False) + "\n")

    done = [r["path"] for r in results if r["ok"]]
    return {
        "ok": True, "batch": bid, "manifest": mpath, "results": results,
        "freed": freed,
        "parents": covering_parents(done),
        "refresh": [sys.executable, os.path.join(HERE, "scan.py"), "--refresh"],
    }


def restore_manifest(mpath):
    """Put back every recycled entry a manifest recorded."""
    out = []
    with open(mpath, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("action") != "recycle" or not rec.get("ok"):
                continue
            ipath, rpath = rec.get("bin_i"), rec.get("bin_r")
            try:
                if not ipath or not os.path.exists(win(ipath)):
                    raise OSError("no $I entry left in the bin (bin emptied?)")
                restore_pair(rec["path"], ipath, rpath, rec.get("attrs"))
                out.append({"path": rec["path"], "restored": True})
            except OSError as exc:
                out.append({"path": rec["path"], "restored": False,
                            "error": str(exc)})
    return out


def list_manifests():
    out = []
    try:
        names = sorted(os.listdir(MANIFEST_DIR), reverse=True)
    except OSError:
        return out
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(MANIFEST_DIR, name)
        n = ok = 0
        freed = None
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    rec = json.loads(line)
                    if rec.get("action") == "recycle":
                        n += 1
                        ok += bool(rec.get("ok"))
                    elif rec.get("action") == "done":
                        freed = rec.get("freed")
        except (OSError, json.JSONDecodeError):
            pass
        out.append({"batch": name[:-6], "file": path, "items": n, "ok": ok,
                    "freed": freed})
    return out


def refresh_parents(parents):
    """scan.py --refresh for each covering parent, as subprocesses."""
    for p in parents:
        print("refreshing %s ..." % p, flush=True)
        subprocess.run([sys.executable, os.path.join(HERE, "scan.py"),
                        "--refresh", p], cwd=HERE)


def recycle_bin_size(db, sid):
    r = db.execute(
        "SELECT COALESCE(SUM(total_bytes_disk),0), COALESCE(SUM(total_files),0)"
        " FROM dirs WHERE snapshot_id=? AND path LIKE 'C:\\$Recycle.Bin\\%'"
        " AND depth=2", (sid,)).fetchone()
    return {"bytes": r[0], "files": r[1]}


# ------------------------------------------------------------------ self test


def self_test():
    """Prove the primitive on scratch files: delete, bin, restore. Phase 1."""
    base = os.path.join(os.path.dirname(HERE),
                        "reclaim-selftest-%d" % os.getpid())
    os.makedirs(os.path.join(base, "sub"))
    fa = os.path.join(base, "a.txt")
    fb = os.path.join(base, "sub", "b.txt")
    with open(fa, "w") as f:
        f.write("alpha")
    with open(fb, "w") as f:
        f.write("beta" * 1000)
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print("%s %s%s" % ("ok  " if cond else "FAIL", label,
                           " - " + detail if detail else ""))

    # Guard refuses the never-touch list, allows the scratch file.
    check("guard refuses C:\\Windows", guard_reason(r"C:\Windows") is not None)
    check("guard refuses hiberfil", guard_reason(r"C:\hiberfil.sys") is not None)
    check("guard refuses ProgramData subtree",
          guard_reason(r"C:\ProgramData\x") is not None)
    check("guard refuses the tool itself",
          guard_reason(os.path.join(HERE, "app.py")) is not None)
    check("guard refuses nonexistent", guard_reason(base + " nope") is not None)
    check("guard allows scratch file", guard_reason(fa) is None,
          guard_reason(fa) or "")

    # Single file: to the bin, findable, restorable.
    send_to_bin(fa)
    check("file deleted", not os.path.exists(fa))
    pair = find_in_bin(fa)
    check("file present in the bin", pair is not None)
    if pair:
        restore_pair(fa, pair[0], pair[1], attrs=0x20)
        check("file restored", os.path.exists(fa))
        with open(fa) as f:
            check("content intact", f.read() == "alpha")

    # Whole directory.
    send_to_bin(os.path.join(base, "sub"))
    check("dir deleted", not os.path.exists(fb))
    pair = find_in_bin(os.path.join(base, "sub"))
    check("dir present in the bin", pair is not None)
    if pair:
        restore_pair(os.path.join(base, "sub"), pair[0], pair[1])
        check("dir restored with file", os.path.exists(fb))

    # Manifest round trip through run_batch's real path is covered by the
    # viewer flow; here prove restore_manifest on a hand-run mini batch.
    db = connect(os.path.join(DATA_DIR, "inventory.sqlite3"))
    sid = db.execute("SELECT MAX(id) FROM snapshots WHERE complete=1").fetchone()[0]
    db.execute("INSERT INTO decisions (path, choice, decided_at) VALUES (?,?,?)"
               " ON CONFLICT(path) DO UPDATE SET choice='delete', decided_at=?",
               (fa, "delete", time.time(), time.time()))
    db.commit()
    res = run_batch(db, sid)
    check("batch ran", res.get("ok"), res.get("error", ""))
    check("manifest written", bool(res.get("manifest"))
          and os.path.exists(res["manifest"]))
    check("file in bin after batch", not os.path.exists(fa)
          and find_in_bin(fa) is not None)
    if res.get("manifest"):
        restored = restore_manifest(res["manifest"])
        check("manifest restore", all(r["restored"] for r in restored)
              and os.path.exists(fa), str(restored))
    db.execute("DELETE FROM decisions WHERE path=?", (fa,))
    db.commit()
    db.close()

    try:
        os.remove(fa)
        os.remove(fb)
        os.rmdir(os.path.join(base, "sub"))
        os.rmdir(base)
    except OSError:
        pass
    print("")
    print("self-test %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


# ------------------------------------------------------------------------ cli


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DB_DEFAULT)
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--propose", action="store_true")
    p.add_argument("--run", action="store_true")
    p.add_argument("--refresh", action="store_true",
                   help="with --run, rescan affected parents afterwards")
    p.add_argument("--restore", metavar="MANIFEST")
    p.add_argument("--empty-bin", action="store_true")
    p.add_argument("--yes", action="store_true",
                   help="required with --run and --empty-bin")
    args = p.parse_args()

    if args.self_test:
        return self_test()
    if args.restore:
        for r in restore_manifest(args.restore):
            print("%s %s" % ("restored " if r["restored"] else "FAILED   ",
                             r["path"] + ("  - " + r.get("error", "")
                                          if not r["restored"] else "")))
        return 0

    db = connect(args.db)
    sid = db.execute(
        "SELECT MAX(id) FROM snapshots WHERE complete=1").fetchone()[0]
    if sid is None:
        print("no complete snapshot")
        return 1

    if args.propose:
        plan = propose(db, sid)
        for e in plan["entries"]:
            tag = ("REFUSED: " + e["guard"]) if e["guard"] else "will recycle"
            print("%-60s %12.1f MB  %s" % (e["path"], e["bytes_disk"] / 2**20, tag))
        print("%d actionable, %d refused, %.1f GB would be freed"
              % (plan["actionable"], len(plan["blocked"]),
                 plan["total_disk"] / 2**30))
        return 0

    if args.run:
        if not args.yes:
            print("--run sends real files to the Recycle Bin. Re-run with --yes.")
            return 1
        res = run_batch(db, sid)
        print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
        if res.get("ok") and args.refresh:
            refresh_parents(res["parents"])
        return 0 if res.get("ok") else 1

    if args.empty_bin:
        if not args.yes:
            print("--empty-bin is permanent. Re-run with --yes.")
            return 1
        res = empty_bin_logged()
        print("Recycle Bin emptied, %.1f GB freed (permanent, logged to %s)"
              % (res["freed"] / 2**30, res["manifest"]))
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
