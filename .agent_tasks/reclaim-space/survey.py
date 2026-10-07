"""Survey helpers for the marking pass - read-only over data/cand.json."""
import json
import sys
from collections import defaultdict

d = json.load(open(r"data\cand.json"))


def terr(p):
    p = p.lower()
    if (p.startswith("c:\\windows\\") or p.startswith("c:\\program files\\")
            or p.startswith("c:\\program files (x86)\\")
            or p.startswith("c:\\programdata\\")
            or p.startswith("c:\\$recycle.bin\\")):
        return "system"
    if "\\appdata\\" in p:
        return "appdata"
    return "personal"


def sets_by_territory():
    groups = defaultdict(list)
    for s in d["dup_sets"]["sets"]:
        ts = sorted(set(terr(m["path"]) for m in s["members"]))
        phys = len(set(m["ino"] for m in s["members"]))
        rec = max(0, phys - 1) * s["bytes_logical"]
        groups["+".join(ts)].append((s, phys, rec))
    return groups


def treedups():
    d2 = json.load(open(r"data\td.json"))
    rows = []
    for g in d2["groups"]:
        ts = sorted(set(terr(m["path"]) for m in g["members"]))
        rows.append((g["reclaimable"], g["proven"], "+".join(ts),
                     g["n_files"], [m["path"] for m in g["members"]]))
    rows.sort(key=lambda r: -r[0])
    return rows


def dir_info(prefix):
    import sqlite3
    db = sqlite3.connect(r"data\inventory.sqlite3")
    db.row_factory = sqlite3.Row
    sid = 28
    for r in db.execute(
            "SELECT id, path, total_bytes_disk, total_files FROM dirs"
            " WHERE snapshot_id=? AND path LIKE ?"
            " ORDER BY total_bytes_disk DESC LIMIT 15",
            (sid, prefix + "%")):
        print("%8.2f GB %6d  %s"
              % (r["total_bytes_disk"] / 1e9, r["total_files"], r["path"]))
    r = db.execute(
        "SELECT id FROM dirs WHERE snapshot_id=? AND path=?",
        (sid, prefix)).fetchone()
    if r:
        print("--- direct children ---")
        for c in db.execute(
                "SELECT path, total_bytes_disk, total_files FROM dirs"
                " WHERE snapshot_id=? AND parent_id=? ORDER BY 2 DESC",
                (sid, r["id"])):
            print("%8.2f GB %6d  %s"
                  % (c["total_bytes_disk"] / 1e9, c["total_files"],
                     c["path"]))
        for f in db.execute(
                "SELECT name, bytes_disk FROM files"
                " WHERE snapshot_id=? AND dir_id=?", (sid, r["id"])):
            print("   file %s %.2f GB" % (f["name"], f["bytes_disk"] / 1e9))


if __name__ == "__main__":
    groups = sets_by_territory()
    if len(sys.argv) > 1 and sys.argv[1] == "dir":
        dir_info(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "trees":
        minb = float(sys.argv[2]) if len(sys.argv) > 2 else 0
        for rec, prov, t, nf, paths in treedups():
            if rec < minb:
                continue
            print("%8.2f GB  proven=%s  %d files  %s"
                  % (rec / 1e9, prov, nf, t))
            for p in paths[:8]:
                print("     ", p)
            if len(paths) > 8:
                print("      ...", len(paths) - 8, "more")
    elif len(sys.argv) > 1 and sys.argv[1] == "summary":
        for k, v in sorted(groups.items(),
                           key=lambda kv: -sum(x[2] for x in kv[1])):
            print("%-25s %5d sets  %8.2f GB reclaimable"
                  % (k, len(v), sum(x[2] for x in v) / 1e9))
    elif len(sys.argv) > 1 and sys.argv[1] == "paths":
        # Compact: every personal-territory set, member paths only.
        which = sys.argv[2] if len(sys.argv) > 2 else "personal"
        v = sorted(groups.get(which, []), key=lambda x: -x[2])
        for i, (s, phys, rec) in enumerate(v):
            print("#%-3d set %s rec=%.1fMB n=%d"
                  % (i, s["id"], rec / 1e6, s["n"]))
            for m in s["members"]:
                print("      %s" % m["path"])
    elif len(sys.argv) > 1 and sys.argv[1] == "temptrees":
        d2 = json.load(open(r"data\td.json"))
        for g in d2["groups"]:
            paths = [m["path"] for m in g["members"]]
            if all("\\temp\\" in p.lower() for p in paths):
                print("%.2f GB proven=%s" % (g["reclaimable"] / 1e9,
                                             g["proven"]))
                for p in paths:
                    print("    ", p)
    elif len(sys.argv) > 1 and sys.argv[1] == "buckets":
        # Which areas the personal sets' members sit in - catches categories
        # a size-ranked look would miss.
        from collections import Counter
        v = groups.get("personal", [])
        buckets = Counter()
        odd = []
        for s, phys, rec in v:
            for m in s["members"]:
                p = m["path"].lower()
                if "video-tools\\.venv" in p:
                    buckets["video-tools .venv"] += 1
                elif "singing-practice-tools" in p:
                    buckets["singing-tools"] += 1
                elif "nirvana-concert" in p:
                    buckets["nirvana"] += 1
                elif "python311\\lib" in p:
                    buckets["Python311 site-packages"] += 1
                elif "clases canto" in p:
                    buckets["OneDrive Clases canto"] += 1
                elif "calibre" in p:
                    buckets["Calibre"] += 1
                elif "wattpad" in p or "convertwattpad" in p:
                    buckets["wattpad"] += 1
                elif "videos\\history" in p:
                    buckets["Videos history"] += 1
                elif "\\downloads\\" in p:
                    buckets["Downloads"] += 1
                    odd.append(m["path"])
                elif ".vscode" in p or ".gradle" in p or ".android" in p:
                    buckets["dev dotdirs"] += 1
                elif "onedrive" in p:
                    buckets["OneDrive other"] += 1
                    odd.append(m["path"])
                else:
                    buckets["other"] += 1
                    odd.append(m["path"])
        for k, n in buckets.most_common():
            print("%5d %s" % (n, k))
        print("--- Downloads / OneDrive-other / other members ---")
        for p in odd:
            print("   ", p)
    else:
        which = sys.argv[1] if len(sys.argv) > 1 else "personal"
        top = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        v = sorted(groups.get(which, []), key=lambda x: -x[2])
        print("%d sets in territory %s" % (len(v), which))
        for s, phys, rec in v[:top]:
            print("\n== set %s  %d names / %d phys  %.2f GB each, "
                  "reclaim %.2f GB  sha %s"
                  % (s["id"], s["n"], phys, s["bytes_logical"] / 1e9,
                     rec / 1e9, s["sha256"]))
            for m in s["members"]:
                print("   %s%s %.2f GB  %s"
                      % ("[PROT] " if m.get("protected") else "",
                         "[shared-ino] " if m.get("shared") else "",
                         m["bytes_disk"] / 1e9, m["path"]))
