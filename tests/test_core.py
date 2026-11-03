import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tsbench.common import BenchmarkError, atomic_json, load_json, owned_path, sha256_file
from tsbench.fixtures import SPECS, task_prompt, fixture_digest, create_base, create_worktree, validate_task
from tsbench.campaign import initialize, record
from tsbench.compare import compare
from tsbench.report import write_artifacts


class BasicTests(unittest.TestCase):
    def test_config(self):
        cfg=load_json(Path("benchmark.yaml"))
        self.assertEqual(cfg["maximum_seconds"],2700)
        self.assertEqual(sum(cfg["phase_seconds"].values()),2700)
        self.assertEqual(cfg["parallel"]["stages"][-1]["count"],16)

    def test_tasks_are_frozen_and_distinct(self):
        self.assertEqual(len(SPECS),17)
        self.assertEqual(len(set(x[0] for x in SPECS)),17)
        self.assertEqual(len(fixture_digest()),64)
        self.assertIn("solution.js",task_prompt(0))

    def test_owned_paths_reject_escape_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"owned"
            root.mkdir()
            self.assertEqual(owned_path(root/"data",root),root/"data")
            with self.assertRaises(BenchmarkError):
                owned_path(root.parent/"other",root)
            (root/"link").symlink_to(root.parent)
            with self.assertRaises(BenchmarkError):
                owned_path(root/"link"/"oops",root)

    def test_campaign_distinct_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            initialize(root,"1.0","abc")
            for index,stamp in enumerate(("2026-11-03T10:00:00+00:00","2026-11-03T10:05:00+00:00",
                                           "2026-11-03T12:00:00+00:00")):
                record(root,{"run_id":str(index),"status":"complete","finished_at":stamp})
            state=load_json(root/"campaign.json")
            self.assertEqual(state["eligible_runs"],["0","2"])

    def test_fixture_worktree_and_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            base=create_base(root)
            tree=create_worktree(base,root,"sample")
            self.assertFalse(validate_task(0,tree)["passed"])
            (tree/"tasks"/"00"/"solution.js").write_text("module.exports = n => n*2;\n")
            self.assertTrue(validate_task(0,tree)["passed"])


if __name__=="__main__":
    unittest.main()
