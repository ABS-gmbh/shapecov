"""security/check.py on a throwaway git repository: one passing layout, and each rule failing."""
import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import load_module, write_tree

sc = load_module("security_check", "security/check.py")
SHA = "11d5960a326750d5838078e36cf38b85af677262"
DIGEST = "sha256:" + "a" * 64
GOOD_WORKFLOW = """name: ci
on:
  push:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@%s # v4.4.0
      - uses: ./.github/actions/local
      - name: Title
        env:
          TITLE: ${{ github.event.pull_request.title }}
        run: |
          echo "$TITLE"
""" % SHA


@unittest.skipUnless(shutil.which("git"), "needs git")
class SecurityCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.saved = (sc.ROOT, sc.LOCK)
        sc.ROOT, sc.LOCK = self.dir, self.dir / "security/images.lock.json"
        write_tree(self.dir, {
            "security/images.lock.json": {"images": {"golang:1.26": {"digest": DIGEST},
                                                     "golang:1.27.3": {"digest": DIGEST, "named_by": "a Dockerfile"}}},
            "tools/build.py": 'IMAGE = "golang:1.26"\nsh(["docker", "network", "create", "--internal", NET])\n',
            ".github/workflows/ci.yml": GOOD_WORKFLOW,
            "linter/action.yml": "runs:\n  using: composite\n  steps:\n    - uses: actions/setup-go@%s\n" % SHA,
            "linter/results/r.json": {"findings": [], "note": "run in /work"},
        })
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)
        self.track()

    def tearDown(self):
        sc.ROOT, sc.LOCK = self.saved
        self.tmp.cleanup()

    def track(self):
        subprocess.run(["git", "add", "-A"], cwd=self.dir, check=True)

    def run_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sc.main()
        return rc, out.getvalue()

    def assertFails(self, files, needle):
        write_tree(self.dir, files)
        self.track()
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn(needle, out)

    def test_clean_layout_passes(self):
        rc, out = self.run_check()
        self.assertEqual(rc, 0, out)
        self.assertIn("images: 2 pinned by digest", out)
        self.assertIn("2 third-party action references", out)

    def test_image_not_in_the_lock(self):
        self.assertFails({"tools/run.sh": "docker run python:3.14-slim true\n"},
                         "image python:3.14-slim is not pinned")

    def test_latest_tag(self):
        self.assertFails({"tools/run.sh": "docker run golang:latest true\n"}, "uses the tag latest")

    def test_lock_entry_nobody_names(self):
        self.assertFails({"tools/build.py": 'sh(["docker", "network", "create", "--internal", NET])\n'},
                         "golang:1.26 is named by no code")

    def test_action_by_tag(self):
        self.assertFails({".github/workflows/ci.yml": GOOD_WORKFLOW.replace("@" + SHA, "@v4")},
                         "actions/checkout@v4 is not pinned to a commit SHA")

    def test_action_from_another_owner(self):
        self.assertFails({".github/workflows/ci.yml": GOOD_WORKFLOW.replace("actions/checkout", "someone/checkout")},
                         "someone/checkout@%s is not from actions" % SHA)

    def test_write_permission_not_allowed(self):
        self.assertFails({".github/workflows/ci.yml": GOOD_WORKFLOW.replace("contents: read", "contents: write")},
                         "contents: write is not an allowed write permission")

    def test_no_top_level_permissions(self):
        self.assertFails({".github/workflows/ci.yml": GOOD_WORKFLOW.replace("permissions:\n  contents: read\n", "")},
                         "no top-level permissions")

    def test_pull_request_target(self):
        self.assertFails({".github/workflows/ci.yml": GOOD_WORKFLOW.replace("  pull_request:", "  pull_request_target:")},
                         "pull_request_target trigger")

    def test_untrusted_text_in_a_run_block(self):
        bad = GOOD_WORKFLOW.replace('echo "$TITLE"', 'echo "${{ github.event.pull_request.title }}"')
        self.assertFails({".github/workflows/ci.yml": bad}, "run interpolates untrusted text")

    def test_untrusted_text_in_env_is_fine(self):
        rc, out = self.run_check()
        self.assertNotIn("untrusted", out)

    def test_a_secret_in_a_workflow(self):
        bad = GOOD_WORKFLOW.replace("TITLE: ${{ github.event.pull_request.title }}", "TOKEN: ${{ secrets.NPM_TOKEN }}")
        self.assertFails({".github/workflows/ci.yml": bad}, "references a secret")

    def test_network_without_internal(self):
        self.assertFails({"tools/build.py": 'IMAGE = "golang:1.26"\nsh(["docker", "network", "create", NET])\n'},
                         "a Docker network is created without --internal")

    def test_home_directory_in_evidence(self):
        self.assertFails({"linter/results/r.json": {"note": "run in /Users/alice/shapecov"}},
                         "names a home directory (/Users/alice/)")


if __name__ == "__main__":
    unittest.main()
