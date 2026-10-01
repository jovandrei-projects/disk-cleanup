"""Localhost viewer for a scan snapshot.

Reads the SQLite inventory written by scan.py and serves it as JSON to a small
browser front end. Read-only apart from the reveal endpoint, which asks Explorer
to highlight a path.

    python app.py            http://127.0.0.1:8770

Binds to loopback only. The snapshot is a complete map of the filesystem and has
no business being reachable from the network.
"""

import argparse
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import analyze
import reclaim

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
DB_DEFAULT = os.path.join(HERE, "data", "inventory.sqlite3")
PORT = 8770

YEAR = 365.25 * 86400
# Upper bound of each bucket, in seconds since last access.
AGE_BUCKETS = [
    ("this week", 7 * 86400),
    ("this month", 30 * 86400),
    ("1-6 months", 182 * 86400),
    ("6-12 months", YEAR),
    ("1-2 years", 2 * YEAR),
    ("2-5 years", 5 * YEAR),
    ("5+ years", float("inf")),
]

# Folders whose contents are regenerable, or are caches. Matched on the folder
# name anywhere in the tree. Used only to annotate, never to act.
REGENERABLE = [
    "node_modules", "__pycache__", ".venv", "venv", ".gradle", ".m2", ".nuget",
    "Cache", "cache", "CacheStorage", "Code Cache", "GPUCache", "ShaderCache",
    "Temp", "tmp", "build", "dist", "target", "obj", "bin", ".next", ".parcel-cache",
    "CrashDumps", "WER", "ReportArchive", "ReportQueue", "packages",
]


class Store:
    def __init__(self, path):
        if not os.path.exists(path):
            sys.exit("no scan database at %s - run scan.py first" % path)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE complete=1 ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            sys.exit("no complete snapshot in %s - finish a scan first" % path)
        self.snap = dict(row)
        self.sid = self.snap["id"]
        # The user's keep/delete marks live in the same database and survive
        # rescans because they are keyed on path, not on a snapshot's row id.
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS decisions ("
            " id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,"
            " choice TEXT NOT NULL, decided_at REAL NOT NULL, note TEXT)")
        # Apps removed through Add/Remove Programs live outside the snapshot,
        # so they get their own log: marked when the user decides, done when
        # the uninstaller has run. Keyed on the app's name, like decisions is
        # keyed on path, so it survives rescans.
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS uninstalls ("
            " id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,"
            " publisher TEXT, install_dir TEXT, bytes INTEGER,"
            " marked_at REAL NOT NULL, done_at REAL)")
        self.conn.commit()
        analyze.ensure_schema(self.conn)
        # A snapshot never changes once complete, so whole-table aggregates are
        # computed once and kept. Without this the Age tab re-scans 956k rows on
        # every click.
        self._cache = {}

    def cached(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def warm(self):
        for key, fn in (("snapshot", self._snapshot), ("types", self._types),
                        ("ages", self._ages), ("treedups", self._treedups),
                        ("software", self._software),
                        ("candidates", lambda: self._candidates())):
            t = time.time()
            self.cached(key, fn)
            print("  %-10s %.1fs" % (key, time.time() - t), flush=True)

    def q(self, sql, args=()):
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.conn.execute(sql, args).fetchone()
        return dict(r) if r else None

    # ------------------------------------------------------------------ views

    def snapshot(self):
        return self.cached("snapshot", self._snapshot)

    def _snapshot(self):
        s = dict(self.snap)
        cloud = self.one(
            "SELECT COALESCE(SUM(bytes_logical),0) AS bytes, COUNT(*) AS n FROM files"
            " WHERE snapshot_id=? AND cloud_only=1", (self.sid,))
        s["cloud_bytes"] = cloud["bytes"]
        s["cloud_files"] = cloud["n"]
        s["used_bytes"] = s["volume_total_bytes"] - s["volume_free_bytes"]
        s["db_path"] = self.path
        s["root_id"] = self.one(
            "SELECT id FROM dirs WHERE snapshot_id=? AND depth=0", (self.sid,))["id"]
        return s

    def breadcrumb(self, dir_id):
        trail = []
        cur = dir_id
        while cur is not None:
            row = self.one("SELECT id, name, path, parent_id FROM dirs WHERE id=?", (cur,))
            if row is None:
                break
            trail.append({"id": row["id"], "name": row["name"], "path": row["path"]})
            cur = row["parent_id"]
        return list(reversed(trail))

    def listing(self, dir_id, sort):
        """Child directories with subtree totals, plus the files directly here."""
        me = self.one("SELECT * FROM dirs WHERE id=?", (dir_id,))
        if me is None:
            return None
        order = {
            "size": "total_bytes_disk DESC",
            "logical": "total_bytes_logical DESC",
            "files": "total_files DESC",
            "name": "name COLLATE NOCASE",
            # Modification time, not access time: see Store._atime_health.
            "oldest": "COALESCE(newest_mtime, 0) ASC",
        }.get(sort, "total_bytes_disk DESC")
        subdirs = self.q(
            "SELECT id, name, path, total_bytes_disk, total_bytes_logical, total_bytes_cloud,"
            " total_files, total_dirs, newest_atime, newest_mtime, attrs, reparse_tag"
            " FROM dirs WHERE parent_id=? ORDER BY " + order, (dir_id,))
        forder = {
            "size": "bytes_disk DESC",
            "logical": "bytes_logical DESC",
            "files": "bytes_disk DESC",
            "name": "name COLLATE NOCASE",
            "oldest": "COALESCE(mtime, 0) ASC",
        }.get(sort, "bytes_disk DESC")
        files = self.q(
            "SELECT name, ext, grp, bytes_disk, bytes_logical, atime, mtime, cloud_only"
            " FROM files WHERE dir_id=? ORDER BY " + forder + " LIMIT 3000", (dir_id,))
        for d in subdirs:
            d["regenerable"] = d["name"] in REGENERABLE
        return {
            "dir": {k: me[k] for k in me.keys()},
            "breadcrumb": self.breadcrumb(dir_id),
            "subdirs": subdirs,
            "files": files,
            "files_truncated": len(files) >= 3000,
        }

    def types(self):
        return self.cached("types", self._types)

    def _types(self):
        groups = self.q(
            "SELECT COALESCE(grp,'other') AS grp, SUM(bytes_disk) AS bytes_disk,"
            " SUM(bytes_logical) AS bytes_logical, COUNT(*) AS n,"
            " SUM(cloud_only) AS cloud_files"
            " FROM files WHERE snapshot_id=? GROUP BY 1 ORDER BY 2 DESC", (self.sid,))
        exts = self.q(
            "SELECT CASE WHEN ext='' OR ext IS NULL THEN '(none)' ELSE ext END AS ext,"
            " COALESCE(grp,'other') AS grp, SUM(bytes_disk) AS bytes_disk,"
            " SUM(bytes_logical) AS bytes_logical, COUNT(*) AS n"
            " FROM files WHERE snapshot_id=? GROUP BY ext ORDER BY 3 DESC LIMIT 60",
            (self.sid,))
        return {"groups": groups, "exts": exts}

    def ages(self):
        return self.cached("ages", self._ages)

    def _bucketed(self, column, now):
        """One pass over the table, assigning each row to a bucket with CASE.

        One query per bucket means one full scan per bucket, which for seven
        buckets over a million rows is tens of seconds. This is a single scan.
        """
        cases = []
        for i, (_, upper) in enumerate(AGE_BUCKETS):
            if upper == float("inf"):
                break
            cases.append("WHEN %s > %f THEN %d" % (column, now - upper, i))
        case = "CASE " + " ".join(cases) + " ELSE %d END" % (len(AGE_BUCKETS) - 1)
        rows = {r["b"]: r for r in self.q(
            "SELECT " + case + " AS b, COUNT(*) AS n,"
            " COALESCE(SUM(bytes_disk),0) AS bytes_disk,"
            " COALESCE(SUM(bytes_logical),0) AS bytes_logical"
            " FROM files WHERE snapshot_id=? GROUP BY b", (self.sid,))}
        empty = {"n": 0, "bytes_disk": 0, "bytes_logical": 0}
        return [rows.get(i, dict(empty)) for i in range(len(AGE_BUCKETS))]

    def _ages(self):
        """Buckets on last access and on last modification, plus evidence about
        whether the access times can be believed at all.

        On this machine they cannot. Access-time recording is switched on, but it
        records reads by *any* process, and antivirus, search indexing and backup
        all sweep the whole disk. The result is that most files look recently
        read whatever the user actually did, so modification time is the honest
        staleness signal. See atime_health for the numbers behind that claim.
        """
        now = time.time()
        return {
            "now": now,
            "buckets": [
                {"label": label, "atime": a, "mtime": m}
                for (label, _), a, m in zip(
                    AGE_BUCKETS, self._bucketed("atime", now),
                    self._bucketed("mtime", now))],
            "atime_health": self._atime_health(now),
        }

    def _atime_health(self, now):
        """Quantify how badly access times are polluted by background sweeps.

        Two signatures. First, files read recently but not modified in years:
        nobody opens a two-year-dormant file and leaves it unchanged, in bulk.
        Second, access timestamps piling up on a handful of calendar days, which
        is a scan working through the disk rather than a person using it.
        """
        swept = self.one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(bytes_disk),0) AS bytes_disk FROM files"
            " WHERE snapshot_id=? AND atime > ? AND mtime < ?",
            (self.sid, now - 0.5 * YEAR, now - 2 * YEAR))
        days = self.q(
            "SELECT CAST(atime/86400 AS INT) * 86400 AS day, COUNT(*) AS n FROM files"
            " WHERE snapshot_id=? GROUP BY day ORDER BY n DESC LIMIT 5", (self.sid,))
        top = days[0]["n"] if days else 0
        return {
            "swept_files": swept["n"],
            "swept_bytes": swept["bytes_disk"],
            "top_days": days,
            "busiest_day_share": (top / self.snap["n_files"]) if self.snap["n_files"] else 0,
            "trustworthy": top < 0.05 * max(1, self.snap["n_files"]),
        }

    def biggest(self, limit=300, grp=None, min_mb=0, years=0, local_only=True,
                basis="mtime"):
        """Biggest files, optionally filtered to those untouched for `years`.

        `basis` defaults to mtime rather than atime deliberately: access times on
        this machine are dominated by background sweeps, so filtering on them
        hides genuinely dormant files. See Store._atime_health.
        """
        if basis not in ("mtime", "atime"):
            basis = "mtime"
        where = ["f.snapshot_id=?"]
        args = [self.sid]
        if local_only:
            where.append("f.cloud_only=0")
        if grp and grp != "all":
            if grp == "other":
                where.append("f.grp IS NULL")
            else:
                where.append("f.grp=?")
                args.append(grp)
        if min_mb:
            where.append("f.bytes_disk >= ?")
            args.append(int(min_mb) * 1024 * 1024)
        if years:
            where.append("f.%s < ?" % basis)
            args.append(time.time() - float(years) * YEAR)
        args.append(int(limit))
        return self.q(
            "SELECT f.name, f.ext, f.grp, f.bytes_disk, f.bytes_logical, f.atime, f.mtime,"
            " f.cloud_only, d.path AS dir_path, d.id AS dir_id"
            " FROM files f JOIN dirs d ON d.id=f.dir_id"
            " WHERE " + " AND ".join(where) +
            " ORDER BY f.bytes_disk DESC LIMIT ?", args)

    def folders_by(self, grp, limit=60):
        """Which folders hold the bytes of one file group. Answers 'where is my
        video', which the per-file list makes you reconstruct by eye."""
        cond = "f.grp IS NULL" if grp == "other" else "f.grp=?"
        args = [self.sid] if grp == "other" else [self.sid, grp]
        args.append(int(limit))
        return self.q(
            "SELECT d.id AS dir_id, d.path, SUM(f.bytes_disk) AS bytes_disk,"
            " COUNT(*) AS n, MAX(f.atime) AS atime, MAX(f.mtime) AS mtime"
            " FROM files f JOIN dirs d ON d.id=f.dir_id"
            " WHERE f.snapshot_id=? AND f.cloud_only=0 AND " + cond +
            " GROUP BY d.id ORDER BY 3 DESC LIMIT ?", args)

    def search(self, term, limit=400):
        like = "%" + term + "%"
        dirs = self.q(
            "SELECT id, name, path, total_bytes_disk, total_files, newest_atime, newest_mtime"
            " FROM dirs WHERE snapshot_id=? AND name LIKE ?"
            " ORDER BY total_bytes_disk DESC LIMIT ?", (self.sid, like, limit))
        files = self.q(
            "SELECT f.name, f.grp, f.bytes_disk, f.atime, f.mtime, f.cloud_only,"
            " d.path AS dir_path,"
            " d.id AS dir_id FROM files f JOIN dirs d ON d.id=f.dir_id"
            " WHERE f.snapshot_id=? AND f.name LIKE ?"
            " ORDER BY f.bytes_disk DESC LIMIT ?", (self.sid, like, limit))
        return {"dirs": dirs, "files": files}

    def _candidates(self):
        data = analyze.candidates(self.conn, self.sid)
        marks = {r["path"]: r["choice"] for r in self.q(
            "SELECT path, choice FROM decisions")}
        # The guard verdict rides along so the viewer can refuse a checkbox it
        # could never honour - a 'delete' mark on a protected path aborts a
        # whole batch, so it must not be tickable at all.
        running = reclaim.running_processes()
        for c in data["items"]:
            c["decision"] = marks.get(c["path"])
            c["guard"] = reclaim.guard_reason(c["path"], running)
        dups = analyze.dup_sets(self.conn, self.sid)
        for s in dups["sets"]:
            for m in s["members"]:
                m["decision"] = marks.get(m["path"])
        data["dup_sets"] = dups
        return data

    def _treedups(self):
        return analyze.tree_dups(self.conn, self.sid)

    def _software(self):
        return analyze.software(self.conn, self.sid)

    def decide(self, path, choice):
        self.decide_many([(path, choice)])

    def decide_many(self, pairs):
        """Commit many (path, choice) decisions in one transaction - the
        Recommended view's staged selection applies a whole slice at once."""
        now = time.time()
        self.conn.executemany(
            "INSERT INTO decisions (path, choice, decided_at) VALUES (?,?,?)"
            " ON CONFLICT(path) DO UPDATE SET choice=excluded.choice,"
            " decided_at=excluded.decided_at",
            [(p, c, now) for p, c in pairs])
        self.conn.commit()
        self._cache.pop("candidates", None)
        self._cache.pop("reclaim", None)

    def history(self):
        """What Phase 4 leaves behind: uninstall marks, batch manifests, and
        the free-space timeline across snapshots. Not cached - it changes
        every time something is marked, recycled or uninstalled."""
        apps = self.q("SELECT * FROM uninstalls ORDER BY bytes DESC")
        for a in apps:
            a["exists"] = bool(a["install_dir"]) and os.path.exists(
                a["install_dir"])
        timeline = self.q(
            "SELECT id, started_at, finished_at, volume_free_bytes, bytes_disk,"
            " n_files, refresh_path FROM snapshots WHERE complete=1 ORDER BY id")
        return {"apps": apps, "timeline": timeline,
                "manifests": reclaim.list_manifests()}

    def mark_uninstall(self, name, install_dir, size_bytes, publisher):
        self.conn.execute(
            "INSERT INTO uninstalls (name, publisher, install_dir, bytes,"
            " marked_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET publisher=excluded.publisher,"
            " install_dir=excluded.install_dir, bytes=excluded.bytes,"
            " marked_at=excluded.marked_at, done_at=NULL",
            (name, publisher, install_dir, size_bytes, time.time()))
        self.conn.commit()

    def proposed_batch(self):
        """What the current 'delete' marks would do if run: per-path verdicts,
        the Recycle Bin's own footprint, and past batches."""
        plan = reclaim.propose(self.conn, self.sid)
        plan["bin"] = reclaim.recycle_bin_size(self.conn, self.sid)
        plan["manifests"] = reclaim.list_manifests()
        return plan

    def reload(self):
        """Pick up a snapshot created after this process started (a refresh),
        and drop every cached aggregate so views compute against it."""
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE complete=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return
        self.snap = dict(row)
        self.sid = self.snap["id"]
        self._cache = {}
        self.warm()

    def empty_dirs(self, limit=500):
        # "Topmost" empty branches: the folder itself holds nothing anywhere
        # beneath it, but its parent does. Filtering on parent keeps a folder
        # full of empty folders as one entry per branch root instead of one per
        # leaf, and reparse_tag=0 keeps junctions out - their zero count is a
        # scanning artifact, not emptiness.
        return self.q(
            "SELECT c.id, c.name, c.path, c.depth FROM dirs c"
            " JOIN dirs p ON p.id=c.parent_id"
            " WHERE c.snapshot_id=? AND c.total_files=0 AND c.reparse_tag=0"
            " AND c.depth>0 AND p.total_files>0"
            " ORDER BY c.path LIMIT ?", (self.sid, limit))


# ----------------------------------------------------------------------- server


class Server(HTTPServer):
    # The page's first load and the Recommended tab fire bursts of parallel
    # requests at a single-threaded server; the default backlog of 5 refuses
    # the excess outright (ECONNREFUSED) instead of letting them wait.
    request_queue_size = 64


class Handler(BaseHTTPRequestHandler):
    store = None
    server_version = "disk-cleanup"

    def log_message(self, fmt, *a):
        pass  # the access log adds nothing here

    def send_json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, rel):
        path = os.path.normpath(os.path.join(WEB, rel.lstrip("/")))
        if not path.startswith(WEB) or not os.path.isfile(path):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        s = self.store
        try:
            if u.path == "/" or u.path == "/index.html":
                return self.send_file("index.html")
            if u.path == "/favicon.ico":
                # No icon, but a 404 here looks like a real error in the console.
                self.send_response(204)
                self.end_headers()
                return
            if not u.path.startswith("/api/"):
                return self.send_file(u.path)

            if u.path == "/api/snapshot":
                return self.send_json(s.snapshot())
            if u.path == "/api/dir":
                dir_id = int(qs.get("id") or s.snapshot()["root_id"])
                out = s.listing(dir_id, qs.get("sort", "size"))
                return self.send_json(out or {"error": "no such directory"},
                                      200 if out else 404)
            if u.path == "/api/types":
                return self.send_json(s.types())
            if u.path == "/api/ages":
                return self.send_json(s.ages())
            if u.path == "/api/biggest":
                return self.send_json({"files": s.biggest(
                    limit=int(qs.get("limit", 300)), grp=qs.get("grp"),
                    min_mb=float(qs.get("min_mb", 0)), years=float(qs.get("years", 0)),
                    local_only=qs.get("cloud") != "1",
                    basis=qs.get("basis", "mtime"))})
            if u.path == "/api/folders_by":
                return self.send_json({"folders": s.folders_by(
                    qs.get("grp", "video"), int(qs.get("limit", 60)))})
            if u.path == "/api/search":
                term = (qs.get("q") or "").strip()
                if len(term) < 2:
                    return self.send_json({"dirs": [], "files": []})
                return self.send_json(s.search(term))
            if u.path == "/api/empty":
                return self.send_json({"dirs": s.empty_dirs()})
            if u.path == "/api/candidates":
                return self.send_json(s.cached("candidates", s._candidates))
            if u.path == "/api/treedups":
                return self.send_json(s.cached("treedups", s._treedups))
            if u.path == "/api/software":
                return self.send_json({"apps": s.cached("software", s._software)})
            if u.path == "/api/decisions":
                return self.send_json({"decisions": s.q(
                    "SELECT path, choice, decided_at FROM decisions")})
            if u.path == "/api/history":
                return self.send_json(s.history())
            if u.path == "/api/reclaim":
                # Always fresh: a deletion proposal is a few rows and must
                # never lag behind the marks it acts on.
                return self.send_json(s.proposed_batch())
            if u.path == "/api/refresh_status":
                return self.send_json(REFRESH)
            if u.path == "/api/reclaim_status":
                return self.send_json(BATCH)
            if u.path == "/api/emptybin_status":
                return self.send_json(EMPTYBIN)
            if u.path == "/api/reveal":
                return self.send_json(reveal(qs.get("path", "")))
            self.send_error(404)
        except Exception as exc:  # a broken query should not kill the server
            self.send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            s = self.store
            if u.path == "/api/decide":
                CHOICES = ("keep", "delete", "archive", "unsure")
                decisions = body.get("decisions")
                if decisions is not None:
                    # Staged selection from the Recommended focus view:
                    # [[path, choice], ...] committed as one unit.
                    ok = (isinstance(decisions, list)
                          and 0 < len(decisions) <= 20000
                          and all(isinstance(x, (list, tuple)) and len(x) == 2
                                  and isinstance(x[0], str) and x[0].strip()
                                  and x[1] in CHOICES for x in decisions))
                    if not ok:
                        return self.send_json({"error": "bad decision list"}, 400)
                    s.decide_many([(x[0].strip(), x[1]) for x in decisions])
                    return self.send_json({"ok": True, "n": len(decisions)})
                path = (body.get("path") or "").strip()
                choice = (body.get("choice") or "").strip()
                if not path or choice not in CHOICES:
                    return self.send_json({"error": "bad decision"}, 400)
                s.decide(path, choice)
                return self.send_json({"ok": True})
            if u.path == "/api/reclaim":
                return self.send_json(start_batch(s))
            if u.path == "/api/restore":
                batch = body.get("batch") or ""
                if not re.fullmatch(r"batch-[\d-]+", batch):
                    return self.send_json({"error": "bad batch id"}, 400)
                mpath = os.path.join(reclaim.MANIFEST_DIR, batch + ".jsonl")
                if not os.path.isfile(mpath):
                    return self.send_json({"error": "no such manifest"}, 404)
                s._cache.pop("reclaim", None)
                return self.send_json({"results": reclaim.restore_manifest(mpath)})
            if u.path == "/api/emptybin":
                return self.send_json(start_emptybin(s))
            if u.path == "/api/refresh":
                paths = body.get("paths") or []
                if not isinstance(paths, list) or not all(
                        isinstance(p, str) for p in paths) or len(paths) > 20:
                    return self.send_json({"error": "bad path list"}, 400)
                return self.send_json(start_refresh(paths))
            if u.path == "/api/reload":
                s.reload()
                return self.send_json({"ok": True, "snapshot": s.sid})
            if u.path == "/api/uninstall":
                act = body.get("action")
                name = (body.get("name") or "").strip()
                if not name or act not in ("mark", "done", "unmark"):
                    return self.send_json({"error": "bad uninstall action"}, 400)
                if act == "mark":
                    s.mark_uninstall(name, body.get("install_dir") or "",
                                     int(body.get("bytes") or 0),
                                     body.get("publisher") or "")
                else:
                    s.conn.execute(
                        "UPDATE uninstalls SET done_at=? WHERE name=?"
                        if act == "done" else
                        "DELETE FROM uninstalls WHERE name=?",
                        (time.time(), name) if act == "done" else (name,))
                    s.conn.commit()
                return self.send_json({"ok": True})
            self.send_error(404)
        except Exception as exc:
            self.send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)


# Refreshing a subtree takes about a minute each, so it runs off-thread and
# the UI polls /api/refresh_status. A refresh appends a new snapshot; the views
# keep serving the old one until /api/reload re-reads the table.
REFRESH = {"running": False, "queue": [], "done": [], "started_at": None}


def start_refresh(paths):
    if REFRESH["running"]:
        return {"ok": False, "error": "a refresh is already running"}
    REFRESH.update(running=True, queue=list(paths), done=[],
                   started_at=time.time())
    threading.Thread(target=_refresh_worker, daemon=True).start()
    return {"ok": True, "queued": len(paths)}


def _refresh_worker():
    log_path = os.path.join(HERE, "data", "refresh.log")
    try:
        while REFRESH["queue"]:
            p = REFRESH["queue"][0]
            with open(log_path, "ab") as log:
                log.write(("\n=== %s  %s ===\n" % (
                    p, time.strftime("%Y-%m-%d %H:%M:%S"))).encode("utf-8"))
                log.flush()
                subprocess.run(
                    [sys.executable, os.path.join(HERE, "scan.py"),
                     "--refresh", p],
                    cwd=HERE, stdout=log, stderr=subprocess.STDOUT)
            REFRESH["done"].append(REFRESH["queue"].pop(0))
    finally:
        REFRESH["running"] = False


# The same goes for reclaim: a batch of SHFileOperation calls or a
# SHEmptyRecycleBinW over a full bin is minutes of synchronous disk work.
# On the request thread it stalls the single-threaded server until the
# listen backlog overflows and the page sees ECONNREFUSED - indistinguishable
# from a crash. Both run on daemon threads; the page polls the status dicts.
# The batch worker opens its own connection: check_same_thread=False permits
# sharing but concurrent calls on one connection are not safe, and WAL lets
# a writer and the reader coexist anyway.
BATCH = {"running": False, "result": None, "error": None}
EMPTYBIN = {"running": False, "result": None, "error": None}


def start_batch(store):
    if BATCH["running"]:
        return {"ok": False, "error": "a batch is already running"}
    BATCH.update(running=True, result=None, error=None)

    def work():
        db = sqlite3.connect(store.path)
        try:
            BATCH["result"] = reclaim.run_batch(db, store.sid)
            store._cache.pop("reclaim", None)
        except Exception as exc:
            BATCH["error"] = "%s: %s" % (type(exc).__name__, exc)
        finally:
            db.close()
            BATCH["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "started": True}


def start_emptybin(store):
    if EMPTYBIN["running"]:
        return {"ok": False, "error": "the bin is already being emptied"}
    EMPTYBIN.update(running=True, result=None, error=None)

    def work():
        try:
            EMPTYBIN["result"] = reclaim.empty_bin_logged()
            store._cache.pop("reclaim", None)
        except Exception as exc:
            EMPTYBIN["error"] = "%s: %s" % (type(exc).__name__, exc)
        finally:
            EMPTYBIN["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "started": True}


def reveal(path):
    """Ask Explorer to highlight a path. No shell, so the path cannot inject."""
    if not path or not os.path.exists(path):
        return {"ok": False, "error": "path does not exist"}
    try:
        if os.path.isdir(path):
            subprocess.Popen(["explorer.exe", os.path.normpath(path)], shell=False)
        else:
            subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)],
                             shell=False)
        return {"ok": True}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DB_DEFAULT)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()

    Handler.store = Store(args.db)
    # Pay the whole-table aggregates once, at startup, rather than making the
    # first click on each tab wait for them.
    print("precomputing summaries...", flush=True)
    Handler.store.warm()
    snap = Handler.store.snapshot()
    url = "http://127.0.0.1:%d" % args.port
    print("snapshot %d of %s, taken %s"
          % (snap["id"], snap["root"],
             time.strftime("%Y-%m-%d %H:%M", time.localtime(snap["started_at"]))))
    print("%d files, %.1f GB on disk" % (snap["n_files"], snap["bytes_disk"] / 2**30))
    print("serving %s   (ctrl-c to stop)" % url)
    if not args.no_browser:
        webbrowser.open(url)
    Server(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
