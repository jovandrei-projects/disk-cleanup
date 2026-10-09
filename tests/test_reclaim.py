"""reclaim.py tests: the never-touch guard, path sizing, propose scoping.

Nothing here sends anything to the bin except the @slow self-test wrapper,
which runs reclaim's own designed-for-that --self-test on %TEMP% scratch.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reclaim
import scan
from _fixture import build

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
slow = unittest.skipIf(os.environ.get('QUICK_TESTS'), 'skipped by --quick')


class GuardReason(unittest.TestCase):
    """The never-touch list is the project's whole safety net - pin it hard."""

    def test_protected_prefixes(self):
        for p in (r'C:\Windows', r'C:\Windows\System32',
                  r'c:\program files\app',          # case-insensitive
                  r'C:\Program Files (x86)\x', r'C:\ProgramData\x',
                  r'C:\$Recycle.Bin\x', r'C:\System Volume Information\x',
                  r'C:\Config.Msi\x', r'C:\Recovery\x', r'C:\$SysReset\x',
                  r'E:\atmosphere\x', r'E:\Nintendo\x', r'E:\emuMMC\x'):
            self.assertEqual('protected system area', reclaim.guard_reason(p), p)

    def test_protected_files(self):
        for p in (r'C:\hiberfil.sys', r'c:\PAGEFILE.SYS', r'C:\swapfile.sys'):
            self.assertEqual('protected system file', reclaim.guard_reason(p), p)

    def test_profile_root_exact(self):
        # the incident guard: the profile itself is refused while paths under
        # it may be fine
        home = os.path.expanduser('~')
        self.assertIn('profile root', reclaim.guard_reason(home))
        self.assertIn('profile root',
                      reclaim.guard_reason(os.path.dirname(home)))  # C:\Users
        # ...but a real file under the profile is allowed
        f = tempfile.NamedTemporaryFile(dir=home, suffix='.tmp', delete=False)
        f.close()
        try:
            self.assertIsNone(reclaim.guard_reason(f.name, running=[]))
        finally:
            os.unlink(f.name)

    def test_drive_root_and_relative(self):
        # 'C:\' is caught by the length check before the drive-root branch
        self.assertEqual('not an absolute drive path',
                         reclaim.guard_reason('C:\\'))
        self.assertEqual('not an absolute drive path',
                         reclaim.guard_reason('relative\\path'))
        self.assertEqual('not an absolute drive path',
                         reclaim.guard_reason('x'))

    def test_nonexistent(self):
        self.assertEqual('not on disk',
                         reclaim.guard_reason(r'C:\nope-no-such-path-zzz'))

    def test_tool_itself(self):
        self.assertEqual("inside this tool's own directory",
                         reclaim.guard_reason(os.path.join(HERE, 'app.py')))

    def test_allows_scratch_file(self):
        f = tempfile.NamedTemporaryFile(suffix='.txt', delete=False)
        f.close()
        try:
            self.assertIsNone(reclaim.guard_reason(f.name, running=[]))
        finally:
            os.unlink(f.name)

    def test_appdata_of_running_app(self):
        # %TEMP% lives under AppData\Local\Temp - its 'temp' token matches a
        # (faked) running temp.exe, so the guard must refuse
        f = tempfile.NamedTemporaryFile(suffix='.bin', delete=False)
        f.close()
        try:
            running = [r'C:\somewhere\temp.exe']
            self.assertIn('running app',
                          reclaim.guard_reason(f.name, running=running))
        finally:
            os.unlink(f.name)

    def test_appdata_of_idle_app_allowed(self):
        # same shape of path, no running exe matches -> allowed
        f = tempfile.NamedTemporaryFile(suffix='.bin', delete=False)
        f.close()
        try:
            running = [r'C:\Windows\System32\calc.exe']
            self.assertIsNone(reclaim.guard_reason(f.name, running=running))
        finally:
            os.unlink(f.name)


class AppDataTarget(unittest.TestCase):
    def test_parses_app_dir(self):
        # group(0) spans up to two segments under local|roaming|locallow
        root, tokens = reclaim._appdata_target(
            r'c:\users\andry\appdata\local\devin\cache')
        self.assertIn(r'appdata\local\devin', root)
        self.assertIn('devin', tokens)

    def test_programs_seg_skipped_for_tokens(self):
        # ...\Local\Programs\Devin\... -> the app is Devin, not Programs
        root, tokens = reclaim._appdata_target(
            r'c:\users\andry\appdata\local\programs\devin\x')
        self.assertIn('devin', tokens)
        self.assertNotIn('programs', tokens)

    def test_non_appdata_is_none(self):
        self.assertIsNone(reclaim._appdata_target(r'c:\users\andry\documents'))


class CoveringParents(unittest.TestCase):
    def test_dedupes_to_minimal_set(self):
        paths = [r'C:\a\b\f1', r'C:\a\b\f2', r'C:\a\c\f3']
        self.assertEqual([r'C:\a\b', r'C:\a\c'],
                         sorted(reclaim.covering_parents(paths)))

    def test_child_under_marked_parent_collapses(self):
        paths = [r'C:\a\b\f1', r'C:\a\f2']
        self.assertEqual([r'C:\a'], reclaim.covering_parents(paths))


class Propose(unittest.TestCase):
    """propose() over the fixture db - scoping, stale pruning, guard blocking."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db, cls.sid, cls.root = build(cls.tmp.name)
        cls.db.execute(
            "CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY,"
            " path TEXT NOT NULL UNIQUE, choice TEXT NOT NULL,"
            " decided_at REAL NOT NULL, note TEXT)")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def _mark(self, path):
        self.db.execute("INSERT OR REPLACE INTO decisions (path, choice,"
                        " decided_at) VALUES (?, 'delete', ?)",
                        (path, time.time()))
        self.db.commit()

    def test_only_scope_limits_the_batch(self):
        # the incident regression: unscoped run_batch swept every real mark
        target = os.path.join(self.root, 'a.bin')
        other = os.path.join(self.root, 'sub', 'b.bin')
        self._mark(target)
        self._mark(other)
        res = reclaim.propose(self.db, self.sid, only={target})
        self.assertEqual([target], [e['path'] for e in res['entries']])
        self.db.execute("DELETE FROM decisions")

    def test_stale_mark_is_consumed(self):
        # a mark whose path vanished is deleted from decisions, not listed
        gone = os.path.join(self.root, 'ghost.bin')
        self._mark(gone)
        res = reclaim.propose(self.db, self.sid, only={gone})
        self.assertEqual(1, res['pruned'])
        n = self.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        self.assertEqual(0, n)

    def test_file_mark_resolves_size(self):
        target = os.path.join(self.root, 'a.bin')
        self._mark(target)
        res = reclaim.propose(self.db, self.sid, only={target})
        e = res['entries'][0]
        self.assertEqual('file', e['src'])
        self.assertEqual(4096, e['bytes_disk'])
        self.assertEqual(1, res['actionable'])
        self.assertTrue(res['can_run'])
        self.db.execute("DELETE FROM decisions")

    def test_protected_mark_blocks_the_whole_batch(self):
        self._mark(r'C:\Windows\System32\kernel32.dll')
        res = reclaim.propose(self.db, self.sid,
                              only={r'C:\Windows\System32\kernel32.dll'})
        self.assertFalse(res['can_run'])
        self.assertTrue(res['blocked'])
        self.db.execute("DELETE FROM decisions")


class SelfTest(unittest.TestCase):
    @slow
    def test_reclaim_self_test_passes(self):
        if not os.path.isfile(os.path.join(HERE, 'data', 'inventory.sqlite3')):
            self.skipTest('no snapshot db on this machine')
        res = subprocess.run([sys.executable, 'reclaim.py', '--self-test'],
                             cwd=HERE, capture_output=True, text=True,
                             timeout=120)
        self.assertEqual(0, res.returncode,
                         (res.stdout + res.stderr)[-3000:])
        self.assertIn('PASSED', res.stdout)


if __name__ == '__main__':
    unittest.main()
