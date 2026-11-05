import json
from pathlib import Path
import tempfile
import unittest

from scripts.create_manual_test_data import create_dataset


class ManualTestDataTests(unittest.TestCase):
    def test_creates_isolated_cases_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create_dataset(Path(temporary) / "cases")
            self.assertEqual(len(list((root / "images").glob("*.png"))), 6)
            self.assertEqual(len(list((root / "warning-two-annotations").glob("*.json"))), 2)
            self.assertEqual(len(list((root / "warning-many-annotations").glob("*.json"))), 6)
            document = json.loads((root / "original-annotations/manual_001.json").read_text())
            self.assertEqual([(s["label"], s["group_id"]) for s in document["shapes"]],
                             [("cat", 3), ("cat", 3), ("dog", 4)])
            self.assertEqual(list((root / "class-review").iterdir()), [])
            with self.assertRaises(ValueError):
                create_dataset(root)
