"""Commands in the documentation start with python3: a stock macOS has no `python` on its PATH, so a
reader who copies `python script.py` from a document gets "command not found"."""
import re
import subprocess
import unittest

from tests.helpers import ROOT

# A command at the start of a line or of a code span: `python` followed by anything but `3`.
BARE = re.compile(r"(?:^|`)[ \t]*python[ \t]+(?!3)\S", re.M)
SKIP = ("harness/replay/out", "corpus/third_party")


def bare_python(text):
    """(line, snippet) for every command in the text that starts with a bare `python`."""
    return [(text.count("\n", 0, m.start()) + 1, text[m.start():m.start() + 50].strip()) for m in BARE.finditer(text)]


class DocsCommands(unittest.TestCase):
    def test_pattern(self):
        self.assertEqual([n for n, _ in bare_python("run `python tools/x.py`\npython y.py\n")], [1, 2])
        self.assertEqual(bare_python("run `python3 tools/x.py`, the `python-xdr` runner, Python 3.9\n"), [])

    def test_every_documented_command_uses_python3(self):
        files = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        found = []
        for f in files:
            if f.startswith(SKIP):
                continue
            with open(ROOT / f, encoding="utf-8") as fh:
                found += ["%s:%d: %s" % (f, n, s) for n, s in bare_python(fh.read())]
        self.assertEqual(found, [], "commands that start with a bare `python`; write python3")


if __name__ == "__main__":
    unittest.main()
