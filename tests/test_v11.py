"""v1.1 regression coverage: real multi-file workloads and canceled campaigns."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tsbench.common import BenchmarkError, sha256_file
from tsbench.campaign import initialize, record, abort_campaign
from tsbench.real_tasks import SCENARIOS, TASK_COUNT, create_real_base, task_prompt, validate_task, digest
from tsbench.fixtures import create_worktree
from tsbench.uninstall import export_campaign, uninstall


class RealTaskTests(unittest.TestCase):
    def test_all_scenarios_have_multiple_sources_and_external_verification(self):
        self.assertEqual(TASK_COUNT,16)
        self.assertGreaterEqual(len(SCENARIOS),8)
        self.assertEqual(len(digest()),64)
        for spec in SCENARIOS:
            self.assertGreaterEqual(len(spec["files"]),2)
            self.assertIn("assert.",spec["tests"])

    def test_original_tasks_fail_and_generated_worktrees_do_not_have_test_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=create_real_base(Path(tmp))
            worktree=create_worktree(base,Path(tmp),"validate")
            for index in range(TASK_COUNT):
                self.assertFalse(validate_task(index,worktree)["passed"],
                                 "Task "+str(index)+" must have failing tests before Codex acts")
                self.assertIn(str(index).zfill(2),task_prompt(index))
                task=worktree/"tasks"/str(index).zfill(2)
                self.assertFalse((task/"tests").exists())
            self.assertTrue((base/".git").is_dir())


class AbortedCampaignTests(unittest.TestCase):
    def test_abort_does_not_delete_evidence_and_allows_purge_only_with_verified_export(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            root=home/".local"/"share"/"tsbench"
            with patch("pathlib.Path.home",return_value=home):
                state=initialize(root,"1.0.0","fixed",benchmark_commit="original")
                rid="first-run"
                folder=root/"results"/rid
                folder.mkdir(parents=True)
                (folder/"results.json").write_text('{"status":"complete"}')
                (folder/"report.md").write_text("preliminary result")
                hashes={n:sha256_file(folder/n) for n in ("results.json","report.md")}
                (folder/"manifest.json").write_text(json.dumps({"files":hashes}))
                record(root,{"run_id":rid,"status":"complete",
                             "finished_at":"2026-11-03T10:00:00+00:00",
                             "provenance":{"benchmark_commit":"original"}})
                with self.assertRaises(BenchmarkError):
                    uninstall(root,purge=True,campaign=state["campaign_id"],
                              verified_export="fake",aborted=True)
                aborted=abort_campaign(root)
                self.assertEqual(aborted["status"],"aborted")
                self.assertEqual(len(aborted["eligible_runs"]),1)
                self.assertTrue((folder/"results.json").exists())
                with self.assertRaises(BenchmarkError):
                    initialize(root,"1.0.0","fixed",benchmark_commit="original")
                receipt=export_campaign(root,home/"external-results.tar.gz")
                with self.assertRaises(BenchmarkError):
                    uninstall(root,purge=True,campaign=state["campaign_id"],
                              verified_export="different",aborted=True)
                self.assertEqual(
                    uninstall(root,purge=True,campaign=state["campaign_id"],
                              verified_export=receipt["sha256"],aborted=True)["status"],"purged")
                self.assertFalse(root.exists())
                self.assertTrue((home/"external-results.tar.gz").exists())

    def test_aborted_purge_refuses_live_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            root=home/".local"/"share"/"tsbench"
            with patch("pathlib.Path.home",return_value=home):
                state=initialize(root,"1.0.0","fixed")
                with self.assertRaisesRegex(BenchmarkError,"abort"):
                    uninstall(root,purge=True,campaign=state["campaign_id"],
                              verified_export="digest",aborted=True)


if __name__=="__main__":
    unittest.main()
