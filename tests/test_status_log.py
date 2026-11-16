"""STATUS.md generator: .github/scripts/status_log.py, on a throwaway git repository."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import run_script

SCRIPT = ".github/scripts/status_log.py"


@unittest.skipUnless(shutil.which("git"), "needs git")
class StatusLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")

        def git(*args, date=None):
            e = dict(env, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date) if date else env
            subprocess.run(["git", *args], cwd=self.dir, env=e, check=True, capture_output=True)

        git("init", "-q", "-b", "main")
        git("commit", "-q", "--allow-empty", "-m", "First commit", date="2026-11-14T10:00:00Z")
        git("commit", "-q", "--allow-empty", "-m", "Second commit", date="2026-11-15T23:30:00Z")
        git("tag", "-a", "v0.1.0", "-m", "release")
        git("commit", "-q", "--allow-empty", "-m", "Third commit", date="2026-11-16T00:30:00Z")

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_is_newest_first_by_utc_day_with_the_release(self):
        rc, out = run_script(SCRIPT, cwd=self.dir)
        self.assertEqual(rc, 0, out)
        text = (self.dir / "STATUS.md").read_text()
        days = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(days, ["## 16 November 2026", "## 15 November 2026", "## 14 November 2026"])
        self.assertLess(text.index("Third commit"), text.index("Second commit"))
        self.assertLess(text.index("Release [v0.1.0]"), text.index("Second commit"))
        self.assertGreater(text.index("Release [v0.1.0]"), text.index("## 15 November 2026"))

    def test_shallow_clone_is_refused(self):
        clone = self.dir / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file://%s" % self.dir, str(clone)],
                       check=True, capture_output=True)
        rc, out = run_script(SCRIPT, cwd=clone)
        self.assertNotEqual(rc, 0)
        self.assertIn("shallow clone", out)


if __name__ == "__main__":
    unittest.main()
