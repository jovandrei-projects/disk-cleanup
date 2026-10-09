"""Browser smoke: the viewer in real headless Chromium via Playwright.

Spawns app.py on a test port against the real scan database (same as the
HTTP smoke test - skipped when no scan exists), loads the page, clicks a
tab, and fails on any uncaught JS error. All clicks are view switches;
nothing mutating is touched. Skipped under --quick and when playwright or
its browser binaries are absent (python -m playwright install chromium).
"""
import os
import subprocess
import sys
import time
import unittest
import urllib.request

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
slow = unittest.skipIf(os.environ.get('QUICK_TESTS'), 'skipped by --quick')
REAL_DB = os.path.join(HERE, 'data', 'inventory.sqlite3')
TEST_PORT = 18870


def wait_http(url, proc, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                r.read()
            return
        except Exception:
            if proc.poll() is not None:
                raise AssertionError('app.py exited: %s' % proc.returncode)
            time.sleep(1)
    raise AssertionError('app.py never answered %s' % url)


@unittest.skipUnless(sync_playwright, 'playwright not installed')
class ViewerPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(REAL_DB):
            raise unittest.SkipTest('no scan database on this machine')

    @slow
    def test_viewer_boots_and_tab_switches(self):
        proc = subprocess.Popen(
            [sys.executable, 'app.py', '--port', str(TEST_PORT),
             '--no-browser'], cwd=HERE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        errors = []
        try:
            base = 'http://127.0.0.1:%d' % TEST_PORT
            wait_http(base + '/api/snapshot', proc)
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception as exc:
                    raise unittest.SkipTest(
                        'chromium not launchable (python -m playwright '
                        'install chromium): %s' % exc)
                try:
                    page = browser.new_page()
                    page.on('pageerror', lambda e: errors.append(
                        'pageerror: %s' % e))
                    page.on('console', lambda m: errors.append(
                        'console.error: %s' % m.text)
                        if m.type == 'error'
                        and 'Failed to load resource' not in m.text else None)
                    page.goto(base + '/', timeout=30000)
                    self.assertIn('Disk cleanup', page.title())

                    # view + tab bar populate once the snapshot loads
                    page.wait_for_selector('#view > *', timeout=20000)
                    page.wait_for_selector('#tabs *', timeout=20000)

                    # read-only click: switch to another top tab if present
                    tabs = page.locator('#tabs *')
                    if tabs.count() > 1:
                        before = page.locator('#view').inner_text()
                        tabs.nth(1).click()
                        page.wait_for_function(
                            "document.getElementById('view')"
                            " && document.getElementById('view')"
                            "   .childElementCount > 0",
                            timeout=15000)
                        self.assertNotEqual(
                            '', page.locator('#view').inner_text())
                finally:
                    browser.close()
            self.assertEqual([], errors)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == '__main__':
    unittest.main()
