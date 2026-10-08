"""Re-apply the delete marks the accidental self-test batch consumed.

run_batch deletes each processed mark once its path is recycled, and the
restore put every path back on disk - so the marks are re-inserted with
their original decided_at, returning the decisions table to what the user
saw before the batch. The scratch self-test path is skipped, as is the one
entry whose recycle failed (its mark was never consumed).
"""
import json, os, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import reclaim

mp = os.path.join(reclaim.DATA_DIR, "manifests", "batch-20261007-204733.jsonl")
paths = []
for l in open(mp, encoding="utf-8"):
    r = json.loads(l)
    if r.get("action") != "recycle" or not r.get("ok"):
        continue
    if "reclaim-selftest-" in r["path"]:
        continue
    if not os.path.exists(r["path"]):
        print("SKIP missing on disk:", r["path"])
        continue
    paths.append((r["path"], r.get("decided_at") or 0))

db = sqlite3.connect(os.path.join(reclaim.DATA_DIR, "inventory.sqlite3"))
cur = 0
for p, at in paths:
    db.execute("INSERT INTO decisions (path, choice, decided_at) VALUES (?,?,?)"
               " ON CONFLICT(path) DO UPDATE SET choice='delete', decided_at=?",
               (p, "delete", at, at))
    cur += 1
db.commit()
print("re-marked:", cur)
for row in db.execute("SELECT choice,count(*) FROM decisions GROUP BY choice"):
    print("decisions now:", row)
db.close()
