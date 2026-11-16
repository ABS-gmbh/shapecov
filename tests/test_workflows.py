"""ci.yml's `green` job: the one check to look at must depend on every other job."""
import re
import unittest

from tests.helpers import ROOT


def job_ids(text):
    """The job ids: two-space indented keys under `jobs:`."""
    body = text[text.index("\njobs:\n") + 6:]
    return re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", body, re.M)


def green_needs(text):
    """The ids in the green job's `needs: [...]` list (which may span lines)."""
    block = text[text.index("\n  green:\n"):]
    inner = re.search(r"\n    needs:\s*\[([^\]]*)\]", block).group(1)
    return [x.strip() for x in inner.split(",") if x.strip()]


class Green(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github/workflows/ci.yml").read_text()
        self.ids = job_ids(self.text)

    def test_green_needs_every_other_job(self):
        self.assertIn("green", self.ids)
        self.assertEqual(sorted(green_needs(self.text)), sorted(set(self.ids) - {"green"}))

    def test_green_runs_always_and_is_named_green(self):
        block = self.text[self.text.index("\n  green:\n"):]
        self.assertRegex(block, r"\n    name: green\n")
        self.assertRegex(block, r"\n    if: always\(\)\n")

    def test_replay_is_called_only_when_changes_says_so(self):
        block = self.text[self.text.index("\n  replay:\n"):self.text.index("\n  quickcheck:\n")]
        self.assertIn("needs: changes", block)
        self.assertIn("if: needs.changes.outputs.replay == 'true'", block)
        self.assertIn("uses: ./.github/workflows/replay.yml", block)

    def test_replay_runs_only_when_called_scheduled_or_by_hand(self):
        replay = (ROOT / ".github/workflows/replay.yml").read_text()
        on = replay[replay.index("\non:\n"):replay.index("\npermissions:")]
        self.assertIn("workflow_call:", on)
        self.assertNotIn("push:", on)  # a push to main reaches it through ci.yml only, so it never runs twice
        self.assertNotIn("pull_request:", on)


if __name__ == "__main__":
    unittest.main()
