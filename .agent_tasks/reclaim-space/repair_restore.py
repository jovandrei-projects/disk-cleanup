"""Finish the manifest restore that self_test interrupted.

self_test ran run_batch over the real delete marks, then restore_manifest in
manifest order. Children that had their own bin entries restored before their
marked parent dir, recreating that path, so the parent's restore_pair failed
with "target already exists" and its $R stayed in the bin. For each such
entry: move the partial on-disk dir aside, restore the bin $R into place,
merge the aside subtree in (file sets are disjoint - a file binned alone is
not inside the parent's $R), then drop the empty shell.
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import reclaim

MANIFEST = os.path.join(reclaim.DATA_DIR, "manifests",
                        "batch-20261007-204733.jsonl")


def merge_into(src_root, dst_root):
    """Move every file under src_root into dst_root. Returns (moved, hits)."""
    moved, collisions = 0, []
    for root, dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        dst_dir = dst_root if rel == "." else os.path.join(dst_root, rel)
        for d in dirs:
            dd = os.path.join(dst_dir, d)
            if os.path.exists(dd) and not os.path.isdir(dd):
                collisions.append(dd)
            else:
                os.makedirs(dd, exist_ok=True)
        for f in files:
            s, dd = os.path.join(root, f), os.path.join(dst_dir, f)
            if os.path.exists(dd):
                collisions.append(dd)
            else:
                os.rename(s, dd)
                moved += 1
    return moved, collisions


def main():
    pending = []
    for line in open(MANIFEST, encoding="utf-8"):
        rec = json.loads(line)
        if (rec.get("action") != "recycle" or rec.get("covered_by")
                or not rec.get("ok")):
            continue
        if rec.get("bin_i") and os.path.exists(reclaim.win(rec["bin_i"])):
            pending.append(rec)
    print("%d entries still in the bin" % len(pending))

    fails = 0
    for rec in pending:
        p = rec["path"]
        aside = p + ".__partial__"
        try:
            if os.path.exists(p):
                os.rename(p, aside)          # same volume -> instant
                moved_aside = True
            else:
                moved_aside = False
            reclaim.restore_pair(p, rec["bin_i"], rec["bin_r"],
                                 rec.get("attrs"))
            if moved_aside:
                moved, collisions = merge_into(aside, p)
                if collisions:
                    fails += 1
                    print("COLLISIONS under %s: %r" % (p, collisions))
                # only remove the shell once it holds no files at all
                left = sum(len(f) for _, _, f in os.walk(aside))
                if left == 0:
                    shutil.rmtree(aside)
                else:
                    fails += 1
                    print("LEFTOVER files in %s: %d" % (aside, left))
                print("merged %-8d files -> %s" % (moved, p))
            else:
                print("restored        -> %s" % p)
        except OSError as exc:
            fails += 1
            print("FAIL %s - %s" % (p, exc))
            # best effort: put the partial back where it was
            if os.path.exists(aside) and not os.path.exists(p):
                os.rename(aside, p)
    print("done, %d failure(s)" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
