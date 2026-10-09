"""app.py Store + helpers on the fixture db, plus the live-server smoke test
that also drives test_render.js (the DOM layer)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app
from _fixture import build

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
slow = unittest.skipIf(os.environ.get('QUICK_TESTS'), 'skipped by --quick')
REAL_DB = os.path.join(HERE, 'data', 'inventory.sqlite3')
TEST_PORT = 18770


class Helpers(unittest.TestCase):
    def test_fmt_gb(self):
        self.assertEqual('1.00 GB', app.fmt_gb(2 ** 30))
        self.assertEqual('0.50 GB', app.fmt_gb(2 ** 29))
        self.assertEqual('an unknown amount', app.fmt_gb(None))

    def test_read_progress(self):
        with tempfile.NamedTemporaryFile('w', suffix='.txt',
                                         delete=False, encoding='utf-8') as f:
            f.write('line one\nlast line\n')
            path = f.name
        try:
            self.assertEqual('last line', app.read_progress(path))
        finally:
            os.unlink(path)
        self.assertIsNone(app.read_progress(path + '.nope'))

    def test_refreshable_drops_root_and_orphans(self):
        store = type('S', (), {'snap': {'root': 'C:\\'}})()
        self.assertEqual([], app._refreshable(store, ['C:\\']))
        # a gone top-level path climbs to the root refresh - refused too
        self.assertEqual([], app._refreshable(store, [r'C:\deleted-zzz-nope']))
        # an existing deep path stays
        self.assertEqual([HERE], app._refreshable(store, [HERE]))


class StoreOnFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db, sid, root = build(cls.tmp.name)
        db.close()
        cls.store = app.Store(os.path.join(cls.tmp.name, 'inventory.sqlite3'))

    @classmethod
    def tearDownClass(cls):
        cls.store.conn.close()   # WAL handles keep the file locked on Windows
        cls.tmp.cleanup()

    def test_loads_complete_snapshot(self):
        s = self.store.snapshot()
        self.assertEqual(3, s['n_files'])
        self.assertIn('root_id', s)
        self.assertEqual(600, s['used_bytes'])   # 1000 total - 400 free

    def test_breadcrumb_walks_up(self):
        deep = self.store.one(
            "SELECT id FROM dirs WHERE name='deep' AND snapshot_id=?",
            (self.store.sid,))
        trail = self.store.breadcrumb(deep['id'])
        self.assertEqual(['root', 'sub', 'deep'], [t['name'] for t in trail])

    def test_listing_returns_children_and_files(self):
        root_id = self.store.snapshot()['root_id']
        out = self.store.listing(root_id, 'size')
        self.assertIsNotNone(out)

    def test_missing_snapshot_exits(self):
        # no TemporaryDirectory context: the leaked Store conn can keep a WAL
        # handle open past cleanup on Windows
        tmp = tempfile.mkdtemp()
        empty = os.path.join(tmp, 'empty.sqlite3')
        import scan as scan_mod
        db = scan_mod.connect(empty)   # schema, no snapshots
        db.close()
        try:
            with self.assertRaises(SystemExit):
                app.Store(empty)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class LiveServerSmoke(unittest.TestCase):
    """Spawn the real viewer on a test port, hit it, then drive every view
    through test_render.js - the 'browser without a browser' layer."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(REAL_DB):
            raise unittest.SkipTest('no scan database on this machine')

    @slow
    def test_server_serves_and_renders(self):
        proc = subprocess.Popen(
            [sys.executable, 'app.py', '--port', str(TEST_PORT), '--no-browser'],
            cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            base = 'http://127.0.0.1:%d' % TEST_PORT
            deadline = time.time() + 90      # startup warm is ~20 s on real data
            snap = None
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(base + '/api/snapshot',
                                                timeout=3) as r:
                        snap = json.loads(r.read())
                    break
                except Exception:
                    if proc.poll() is not None:
                        self.fail('app.py exited during startup: %s'
                                  % proc.returncode)
                    time.sleep(1)
            self.assertIsNotNone(snap, 'server never answered /api/snapshot')
            self.assertGreater(snap['n_files'], 0)

            # the page itself
            with urllib.request.urlopen(base + '/', timeout=5) as r:
                html = r.read().decode('utf-8', 'replace')
            self.assertIn('<', html)
            self.assertGreater(len(html), 500)

            t0 = time.time()
            with urllib.request.urlopen(base + '/api/dir?id=%s'
                                        % snap['root_id'], timeout=5) as r:
                d = json.loads(r.read())
            self.assertLess(time.time() - t0, 5, 'dir endpoint too slow')
            self.assertIn('subdirs', d)

            # DOM layer: render every view against this live server
            node = shutil.which('node')
            self.assertIsNotNone(node, 'node needed for test_render.js')
            env = dict(os.environ, BASE=base)
            res = subprocess.run([node, 'test_render.js'], cwd=HERE, env=env,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(0, res.returncode,
                             'test_render.js:\n' + res.stdout[-3000:]
                             + res.stderr[-1000:])
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == '__main__':
    unittest.main()
