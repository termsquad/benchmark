"""Security, lifecycle, timing and comparison regression tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tsbench.common import BenchmarkError, CommandTimeout, load_json, run_command
from tsbench.campaign import initialize, record
from tsbench.compare import compare
from tsbench.report import write_artifacts
from tsbench.uninstall import export_campaign, uninstall


class SubprocessTests(unittest.TestCase):
    def test_timeout_kills_process_group(self):
        with self.assertRaises(CommandTimeout):
            run_command(["python3","-c","import time;time.sleep(4)"],.1)

    def test_no_unbounded_output(self):
        result=run_command(["python3","-c","print('A'*1000)"],3,max_output=32)
        self.assertEqual(len(result["stdout"]),32)


class CampaignUninstallTests(unittest.TestCase):
    def test_purge_reports_residual_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".local" / "share" / "tsbench"
            with patch("pathlib.Path.home", return_value=home):
                state = initialize(root, "1.0", "aaa")
                for i, hour in enumerate((1, 3, 5)):
                    rid = "run-" + str(i)
                    record(root, {"run_id": rid, "status": "complete",
                                  "finished_at": f"2026-11-03T{hour:02}:00:00+00:00"})
                    folder = root / "results" / rid
                    folder.mkdir(parents=True)
                    (folder / "manifest.json").write_text(json.dumps({"files": {}}))
                receipt = export_campaign(root, home / "export.tar.gz")
                residual = root / "unrecognized-file"
                residual.write_text("retain")
                result = uninstall(root, purge=True, campaign=state["campaign_id"],
                                   verified_export=receipt["sha256"])
                self.assertEqual(result["status"], "purged_with_residuals")
                self.assertTrue(residual.exists())

    def test_purge_rejects_missing_external_receipt_and_preserves_user_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            root=home/".local"/"share"/"tsbench"
            user=home/"user-notes.txt"
            user.write_text("keep")
            with patch("pathlib.Path.home",return_value=home):
                state=initialize(root,"1.0","aaa")
                for i,hour in enumerate((1,3,5)):
                    rid="run-"+str(i)
                    record(root,{"run_id":rid,"status":"complete",
                                 "finished_at":"2026-11-03T"+str(hour).zfill(2)+":00:00+00:00"})
                    folder=root/"results"/rid
                    folder.mkdir(parents=True)
                    (folder/"results.json").write_text("{}")
                    (folder/"report.md").write_text("data")
                    import hashlib
                    hashes={n:hashlib.sha256((folder/n).read_bytes()).hexdigest()
                            for n in ("results.json","report.md")}
                    (folder/"manifest.json").write_text(json.dumps({"files":hashes}))
                with self.assertRaises(BenchmarkError):
                    uninstall(root,purge=True,campaign=state["campaign_id"],verified_export="fake")
                self.assertTrue((root/"results"/"run-0").exists())
                receipt=export_campaign(root,home/"export.tar.gz")
                self.assertTrue(Path(receipt["file"]).exists())
                result=uninstall(root,purge=True,campaign=state["campaign_id"],
                                 verified_export=receipt["sha256"])
                self.assertEqual(result["status"],"purged")
                self.assertFalse(root.exists())
                self.assertEqual(user.read_text(),"keep")

    def test_conservative_uninstall_keeps_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            root=home/".local"/"share"/"tsbench"
            with patch("pathlib.Path.home",return_value=home):
                initialize(root,"1.0","aaa")
                (root/"results").mkdir()
                (root/"venv").mkdir()
                out=uninstall(root)
                self.assertEqual(out["status"],"conservative_uninstall")
                self.assertTrue((root/"results").exists())
                self.assertFalse((root/"venv").exists())


class ComparisonTests(unittest.TestCase):
    def test_incompatible_os_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/"benchmark.yaml"
            config.write_text("{}")
            files=[]
            for i,osver in enumerate(("24.04","26.04")):
                directory=Path(tmp)/str(i)
                payload={"run_id":str(i),"suite_version":"1.0","status":"complete",
                         "machine":{"architecture":"x86_64","os_version":osver,"tools":{}},
                         "provenance":{"suite_config_sha256":"abc","fixture_sha256":"abc",
                           "codex_version":"1","herdr_version":"1","model":"gpt-6.1-terra",
                           "reasoning_effort":"xhigh"},
                         "cpu":{},"memory":{},"disk":{},"agents":{"single":{},"parallel":[]},
                         "warnings":[],"errors":[],"price":{},"elapsed_seconds":1}
                write_artifacts(directory,payload,config)
                files.append(directory/"results.json")
            with self.assertRaises(BenchmarkError):
                compare(files)


if __name__=="__main__":
    unittest.main()
