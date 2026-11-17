"""harness/replay/adapters/wallet-backend/adapter.py, setup_protocols: a protocol the commit has no
validator for is dropped and recorded; every other protocol-setup failure stays an error."""
import unittest

from tests.helpers import load_module

wb = load_module("wb_adapter_setup", "harness/replay/adapters/wallet-backend/adapter.py")

PANIC = 'panic: executing root command: building validators: no validator registered for protocol "%s"\n'


class FakeSetup:
    """protocol-setup as a commit runs it: `known` are the protocols the commit has a validator for."""

    def __init__(self, known, other_failure=None):
        self.known, self.other_failure, self.calls = known, other_failure, []

    def __call__(self, ids):
        self.calls.append(list(ids))
        if self.other_failure is not None:
            return 1, self.other_failure
        for p in ids:
            if p not in self.known:
                return 2, PANIC % p
        return 0, "set up %s\n" % ", ".join(ids)


class SetupProtocols(unittest.TestCase):
    def test_one_unavailable_is_dropped_and_setup_reruns(self):
        fake = FakeSetup(known={"SEP41"})
        verdict, protocols, unavailable, log = wb.setup_protocols(fake, ["SEP41", "BLEND"])
        self.assertEqual(verdict, "ok")
        self.assertEqual(protocols, ["SEP41"])
        self.assertEqual(unavailable, ["BLEND"])
        self.assertEqual(fake.calls, [["SEP41", "BLEND"], ["SEP41"]])
        self.assertIn('no validator registered for protocol "BLEND"', log)  # both runs are in the log
        self.assertIn("set up SEP41", log)

    def test_all_unavailable_replays_without_protocol_production(self):
        fake = FakeSetup(known=set())
        verdict, protocols, unavailable, _ = wb.setup_protocols(fake, ["SEP41", "BLEND"])
        # the last call exits non-zero too; that is "none available", not an adapter error
        self.assertEqual(verdict, "none_available")
        self.assertEqual(protocols, [])
        self.assertEqual(unavailable, ["SEP41", "BLEND"])
        self.assertEqual(len(fake.calls), 2)

    def test_any_other_failure_is_an_error(self):
        for output in ("pq: connection refused\n",
                       PANIC % "SOMETHING_NOT_REQUESTED",  # names a protocol we did not ask for
                       ""):
            with self.subTest(output=output):
                fake = FakeSetup(known={"SEP41", "BLEND"}, other_failure=output)
                verdict, protocols, unavailable, _ = wb.setup_protocols(fake, ["SEP41", "BLEND"])
                self.assertEqual(verdict, "failed")
                self.assertEqual((protocols, unavailable), ([], []))
                self.assertEqual(len(fake.calls), 1)

    def test_a_failure_after_a_drop_is_still_an_error(self):
        calls = []

        def setup(ids):
            calls.append(list(ids))
            return (2, PANIC % "BLEND") if "BLEND" in ids else (1, "migration missing\n")
        verdict, _, unavailable, _ = wb.setup_protocols(setup, ["SEP41", "BLEND"])
        self.assertEqual((verdict, unavailable), ("failed", ["BLEND"]))

    def test_no_protocol_setup_command(self):
        fake = FakeSetup(known=set(), other_failure='Error: unknown command "protocol-setup" for "wallet-backend"\n')
        self.assertEqual(wb.setup_protocols(fake, ["SEP41", "BLEND"])[0], "no_command")

    def test_success(self):
        fake = FakeSetup(known={"SEP41", "BLEND"})
        self.assertEqual(wb.setup_protocols(fake, ["SEP41", "BLEND"]), ("ok", ["SEP41", "BLEND"], [], "set up SEP41, BLEND\n"))


if __name__ == "__main__":
    unittest.main()
