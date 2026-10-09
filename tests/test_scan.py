"""scan.py tests: helpers, a real fixture-tree walk, and the rollup invariant."""
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan
from _fixture import build


class CloudTags(unittest.TestCase):
    """Reparse-tag discrimination is what keeps the walk out of junction loops."""

    def test_onedrive_tags_recognized(self):
        for x in range(16):
            tag = 0x9000001A | (x << 12)
            self.assertTrue(scan.is_cloud_tag(tag), hex(tag))

    def test_junction_and_symlink_not_cloud(self):
        self.assertFalse(scan.is_cloud_tag(scan.IO_REPARSE_TAG_MOUNT_POINT))
        self.assertFalse(scan.is_cloud_tag(scan.IO_REPARSE_TAG_SYMLINK))

    def test_zero_and_garbage(self):
        self.assertFalse(scan.is_cloud_tag(0))
        self.assertFalse(scan.is_cloud_tag(0x8000001A))


class PathForms(unittest.TestCase):
    def test_win_unwin_roundtrip(self):
        for p in (r'C:\Users\x', r'D:\deep\path\file.txt'):
            self.assertEqual(p, scan.unwin(scan.win(p)))

    def test_win_adds_long_path_prefix(self):
        self.assertTrue(scan.win(r'C:\x').startswith('\\\\?\\'))

    def test_win_idempotent(self):
        once = scan.win(r'C:\x')
        self.assertEqual(once, scan.win(once))

    def test_unc_path(self):
        w = scan.win(r'\\server\share\dir')
        self.assertTrue(w.startswith('\\\\?\\UNC\\'))
        self.assertEqual(r'\\server\share\dir', scan.unwin(w))


class ExtGroups(unittest.TestCase):
    # Extensions that exist in two groups on purpose - the later group in
    # EXT_GROUPS wins the dict comp. Pinned so the winners stay the intended
    # ones: .ts is TypeScript here (more common than MPEG-TS on this drive)
    # and .sql is a database script.
    KNOWN_OVERLAPS = {'ts': 'code', 'sql': 'database'}

    def test_overlaps_are_exactly_the_known_set(self):
        seen = {}
        overlaps = {}
        for grp, exts in scan.EXT_GROUPS.items():
            for e in exts.split():
                if e in seen:
                    overlaps[e] = (seen[e], grp)
                seen[e] = grp
        self.assertEqual(set(self.KNOWN_OVERLAPS), set(overlaps))
        for ext, winner in self.KNOWN_OVERLAPS.items():
            self.assertEqual(winner, scan.EXT_TO_GROUP[ext])

    def test_common_exts_mapped(self):
        self.assertEqual('video', scan.EXT_TO_GROUP['mp4'])
        self.assertEqual('installer', scan.EXT_TO_GROUP['exe'])
        self.assertEqual('image', scan.EXT_TO_GROUP['jpg'])


class FixtureScan(unittest.TestCase):
    """A real walk of a tiny tree, through finalize: indexes + rollup + flag."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.sid, cls.root = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def test_counts(self):
        row = self.db.execute(
            "SELECT n_dirs, n_files, complete FROM snapshots WHERE id=?",
            (self.sid,)).fetchone()
        self.assertEqual((4, 3, 1), tuple(row))   # root + sub + deep + empty; 3 files

    def test_rollup_invariant(self):
        # the property scan.py --verify exists to check, on data we control:
        # root subtree totals == the sums over files
        root = self.db.execute(
            "SELECT * FROM dirs WHERE snapshot_id=? AND depth=0",
            (self.sid,)).fetchone()
        files = self.db.execute(
            "SELECT COUNT(*), SUM(bytes_logical), SUM(bytes_disk) FROM files"
            " WHERE snapshot_id=?", (self.sid,)).fetchone()
        self.assertEqual(files[0], root['total_files'])
        self.assertEqual(files[1], root['total_bytes_logical'])
        self.assertEqual(files[2], root['total_bytes_disk'])
        self.assertEqual(3, root['total_dirs'])   # sub, deep, empty_dir

    def test_rollup_middle_level(self):
        sub = self.db.execute(
            "SELECT * FROM dirs WHERE snapshot_id=? AND name='sub'",
            (self.sid,)).fetchone()
        self.assertEqual(2, sub['total_files'])        # b.bin + deep/c.bin
        self.assertEqual(500, sub['total_bytes_logical'])
        self.assertEqual(1, sub['total_dirs'])         # deep

    def test_disk_size_cluster_rounding(self):
        # 100 logical bytes occupy one 4096 cluster on disk
        f = self.db.execute(
            "SELECT bytes_logical, bytes_disk FROM files WHERE snapshot_id=?"
            " AND name='a.bin'", (self.sid,)).fetchone()
        self.assertEqual(100, f['bytes_logical'])
        self.assertEqual(4096, f['bytes_disk'])

    def test_newest_mtime_propagates(self):
        root = self.db.execute(
            "SELECT newest_mtime FROM dirs WHERE snapshot_id=? AND depth=0",
            (self.sid,)).fetchone()
        leaf = self.db.execute(
            "SELECT MAX(mtime) FROM files WHERE snapshot_id=?", (self.sid,)).fetchone()
        self.assertAlmostEqual(leaf[0], root[0], places=0)

    def test_cloud_only_zero_for_local_files(self):
        n = self.db.execute(
            "SELECT COUNT(*) FROM files WHERE snapshot_id=? AND cloud_only=1",
            (self.sid,)).fetchone()[0]
        self.assertEqual(0, n)

    def test_junction_not_followed(self):
        # if we can make a junction, it must be recorded but not descended
        link = os.path.join(self.root, 'jlink')
        res = subprocess.run(['cmd', '/c', 'mklink', '/J', link, self.root],
                             capture_output=True)
        if res.returncode != 0:
            self.skipTest('cannot create a junction here: %s' % res.stderr[:200])
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp2:
                db, sid, _ = build(tmp2)
                # manual graft: re-walk the fixture root that now has a junction
                # build() scanned a different root; do a fresh walk on self.root
                cur = db.execute(
                    "INSERT INTO snapshots (root, started_at, elevated,"
                    " cluster_bytes) VALUES (?,?,?,?)",
                    (self.root, time.time(), 0, 4096))
                sid2 = cur.lastrowid
                db.commit()
                sc = scan.Scanner(db, self.root, 4096, quiet=True)
                sc.run(sid2)
                scan.rollup(db, sid2, verbose=False)
                jrow = db.execute(
                    "SELECT * FROM dirs WHERE snapshot_id=? AND name='jlink'",
                    (sid2,)).fetchone()
                self.assertIsNotNone(jrow, 'junction was not recorded at all')
                # and the walk did not loop: total dir count stays small
                n = db.execute("SELECT COUNT(*) FROM dirs WHERE snapshot_id=?",
                               (sid2,)).fetchone()[0]
                self.assertLessEqual(n, 6, 'walk followed the junction')
                db.close()
        finally:
            os.rmdir(link)   # rmdir removes the junction itself, not the target


if __name__ == '__main__':
    unittest.main()
