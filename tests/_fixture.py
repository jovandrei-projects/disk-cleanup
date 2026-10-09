"""Shared fixture: a tiny real directory tree scanned into a temp sqlite db.

Layout:
    <tmp>/root/
        a.bin            100 bytes
        sub/
            b.bin        200 bytes
            deep/
                c.bin    300 bytes
        empty_dir/

The db runs through scan.finalize (indexes + rollup + complete flag), so it
is shaped exactly like a real snapshot - views and queries work on it.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scan


def build(tmpdir):
    root = os.path.join(tmpdir, 'root')
    os.makedirs(os.path.join(root, 'sub', 'deep'))
    os.makedirs(os.path.join(root, 'empty_dir'))
    for rel, n in (('a.bin', 100), ('sub/b.bin', 200), ('sub/deep/c.bin', 300)):
        with open(os.path.join(root, *rel.split('/')), 'wb') as fh:
            fh.write(bytes(n))

    db_path = os.path.join(tmpdir, 'inventory.sqlite3')
    db = scan.connect(db_path)
    db.row_factory = __import__('sqlite3').Row
    cur = db.execute(
        "INSERT INTO snapshots (root, started_at, elevated, cluster_bytes,"
        " volume_total_bytes, volume_free_bytes) VALUES (?,?,?,?,?,?)",
        (os.path.abspath(root), time.time(), 0, 4096, 1000, 400))
    sid = cur.lastrowid
    db.commit()
    sc = scan.Scanner(db, os.path.abspath(root), 4096, quiet=True)
    sc.run(sid)
    scan.finalize(db, sid)
    return db, sid, root
