"""Runs tests/browser_sidebar_loading.mjs when a browser and a running server are configured (CHROMIUM, FF_PORT); skipped otherwise."""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "browser_sidebar_loading.mjs"


@unittest.skipUnless(os.environ.get("CHROMIUM") and os.environ.get("FF_PORT") and shutil.which("node"),
                     "needs node, CHROMIUM and a running server on FF_PORT")
class SidebarLoadingBrowserTest(unittest.TestCase):
    def test_loading_line_disappears_when_list_renders(self):
        proc = subprocess.run(["node", str(SCRIPT)], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("FAIL", proc.stdout)


if __name__ == "__main__":
    unittest.main()
