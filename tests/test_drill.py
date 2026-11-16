"""Protocol-upgrade drill: protocol-drill/drill.py's schema diff and report, without stellar-core."""
import json
import unittest

from tests.helpers import ROOT, load_module

dr = load_module("drill", "protocol-drill/drill.py")


def schema(**types):
    return {"types": types}


def enum(*members):
    return {"k": "enum", "members": [[m, i] for i, m in enumerate(members)]}


def union(*labels):
    return {"k": "union", "arms": [{"labels": [lab]} for lab in labels]}


class Diff(unittest.TestCase):
    def test_no_change(self):
        s = schema(MemoType=enum("MEMO_NONE", "MEMO_TEXT"))
        d = dr.diff(s, s)
        self.assertEqual(d, {"types_added": [], "types_removed": [], "types_changed": [],
                             "cells_added": [], "cells_removed": []})

    def test_new_enum_member_and_union_arm_are_new_cells(self):
        old = schema(MemoType=enum("MEMO_NONE"), Memo=union("MEMO_NONE"))
        new = schema(MemoType=enum("MEMO_NONE", "MEMO_TEXT"), Memo=union("MEMO_NONE", "MEMO_TEXT"))
        d = dr.diff(old, new)
        self.assertEqual(d["cells_added"], ["arm:Memo.MEMO_TEXT", "enum:MemoType.MEMO_TEXT"])
        self.assertEqual(d["types_changed"], ["Memo", "MemoType"])
        self.assertEqual(d["types_added"], [])

    def test_added_and_removed_types(self):
        old = schema(A={"k": "typedef", "t": {"r": "uint"}}, Gone=enum("X"))
        new = schema(A={"k": "typedef", "t": {"r": "uint"}}, TestNextType={"k": "typedef", "t": {"r": "int"}})
        d = dr.diff(old, new)
        self.assertEqual(d["types_added"], ["TestNextType"])
        self.assertEqual(d["types_removed"], ["Gone"])
        self.assertEqual(d["cells_removed"], ["enum:Gone.X"])
        self.assertEqual(d["cells_added"], [])

    def test_real_upgrade_28_to_30(self):
        old = json.loads((ROOT / "schema/schema-v28.0.json").read_text())
        new = json.loads((ROOT / "schema/schema.json").read_text())
        d = dr.diff(old, new)
        # CAP-0084's muxed contract address is new in protocol 30; the muxed account address is older.
        self.assertIn("arm:SCAddress.SC_ADDRESS_TYPE_MUXED_CONTRACT", d["cells_added"])
        self.assertNotIn("arm:SCAddress.SC_ADDRESS_TYPE_MUXED_ACCOUNT", d["cells_added"])
        self.assertEqual(d["cells_removed"], [])


class Report(unittest.TestCase):
    def test_committed_report_is_what_its_data_renders(self):
        data = json.loads((ROOT / "protocol-drill/drill.json").read_text())
        self.assertEqual(dr.report(data), (ROOT / "protocol-drill/REPORT.md").read_text(),
                         "REPORT.md was edited by hand or drill.json changed; rerun protocol-drill/drill.py")

    def test_no_new_cells_says_no_schema_change_is_needed(self):
        data = json.loads((ROOT / "protocol-drill/drill.json").read_text())
        data["diffs"]["v30.0 -> next"] = {"types_added": ["TestNextType"], "types_changed": [], "types_removed": [],
                                         "cells_added": [], "cells_removed": []}
        self.assertIn("needs no schema change", dr.report(data))
        data["diffs"]["v30.0 -> next"]["cells_added"] = ["arm:X.NEW"]
        self.assertNotIn("needs no schema change", dr.report(data))


if __name__ == "__main__":
    unittest.main()
