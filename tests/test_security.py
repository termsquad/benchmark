"""Security, lifecycle, timing and comparison regression tests."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tsbench.common import BenchmarkError, CommandTimeout, load_json, run_command
from tsbench.campaign import initialize, record
from tsbench.compare import compare
from tsbench.report import write_artifacts
from tsbench.uninstall import export_campaign, uninstall


class SubprocessTests(unittest.TestCase):
    def test_interrupt_stops_owned_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / "child.pid"
            child = "import os,time;open(%r,'w').write(str(os.getpid()));time.sleep(30)" % str(pidfile)
            parent = ("from tsbench.common import run_command\n"
                      "try:\n run_command([%r,'-c',%r],30)\n"
                      "except KeyboardInterrupt: pass\n") % (sys.executable, child)
            process = subprocess.Popen([sys.executable, "-c", parent],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            child_pid = None
            try:
                deadline = time.monotonic() + 5
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(pidfile.exists(), "child did not start")
                child_pid = int(pidfile.read_text())
                process.send_signal(signal.SIGINT)
                process.wait(timeout=5)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if child_pid is not None:
                    try: os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError: pass

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
    def test_different_benchmark_commits_cannot_share_a_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "benchmark.yaml"
            config.write_text("{}")
            files = []
            for i in range(2):
                payload = {"run_id": str(i), "suite_version": "1.0", "status": "complete",
                           "machine": {"architecture": "x86_64", "os_version": "26.04", "tools": {}},
                           "provenance": {"benchmark_commit": str(i), "suite_config_sha256": "abc",
                                          "fixture_sha256": "abc", "codex_version": "1", "herdr_version": "1",
                                          "model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
                           "cpu": {}, "memory": {}, "disk": {},
                           "agents": {"single": {}, "parallel": []},
                           "warnings": [], "errors": [], "price": {}, "elapsed_seconds": 1}
                folder = root / str(i)
                write_artifacts(folder, payload, config)
                files.append(folder / "results.json")
            with self.assertRaises(BenchmarkError):
                compare(files)

    def test_three_runs_without_time_separation_are_not_publication_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "benchmark.yaml"
            config.write_text("{}")
            files = []
            for i, minute in enumerate((0, 10, 20)):
                payload = {"run_id": str(i), "suite_version": "1.0", "status": "complete",
                           "finished_at": f"2026-11-03T10:{minute:02}:00+00:00",
                           "machine": {"architecture": "x86_64", "os_version": "26.04", "tools": {}},
                           "provenance": {"suite_config_sha256": "abc", "fixture_sha256": "abc",
                                          "codex_version": "1", "herdr_version": "1",
                                          "model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
                           "cpu": {}, "memory": {}, "disk": {},
                           "agents": {"single": {}, "parallel": []},
                           "warnings": [], "errors": [], "price": {}, "elapsed_seconds": 1}
                folder = root / str(i)
                write_artifacts(folder, payload, config)
                files.append(folder / "results.json")
            self.assertFalse(compare(files)["providers"][0]["publication_eligible"])

    def test_duplicate_run_ids_cannot_count_as_three_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "benchmark.yaml"
            config.write_text("{}")
            payload = {"run_id": "same", "suite_version": "1.0", "status": "complete",
                       "machine": {"architecture": "x86_64", "os_version": "26.04", "tools": {}},
                       "provenance": {"suite_config_sha256": "abc", "fixture_sha256": "abc",
                                      "codex_version": "1", "herdr_version": "1",
                                      "model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
                       "cpu": {}, "memory": {}, "disk": {},
                       "agents": {"single": {}, "parallel": []},
                       "warnings": [], "errors": [], "price": {}, "elapsed_seconds": 1}
            folder = root / "result"
            write_artifacts(folder, payload, config)
            with self.assertRaises(BenchmarkError):
                compare([folder / "results.json"] * 3)

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
