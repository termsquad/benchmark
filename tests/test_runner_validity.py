"""Regression coverage for campaign eligibility of incomplete stages."""
import tempfile
import unittest
import io
import json
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tsbench.common import load_json
from tsbench.runner import run
from tsbench.cli import main
from tsbench.agents import classify, _worker


class RunValidityTests(unittest.TestCase):
    def test_herdr_trusts_only_the_generated_fixture_and_worktree(self):
        base = Path('/tmp/tsbench.test/fixture-base')
        worktree = Path('/tmp/tsbench.test/task-01')
        calls = []
        def herdr(args, *unused):
            calls.append(args)
            if args[:2] == ["workspace", "create"]:
                return {"result": {"workspace": {"workspace_id": "w1"},
                                   "root_pane": {"pane_id": "w1:p1"}}}
            return {}
        with patch("tsbench.agents.create_worktree", return_value=worktree), \
             patch("tsbench.agents._herdr", side_effect=herdr), \
             patch("tsbench.agents.validate_task", return_value={"passed": True}):
            result = _worker(0, {"model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
                             time.monotonic()+60, base, base.parent, [], "tsb")
        self.assertEqual(result["status"], "passed")
        start = next(args for args in calls if args[:2] == ["agent", "start"])
        override = next(arg for arg in start if arg.startswith("projects="))
        self.assertEqual(override, "projects={" + json.dumps(str(base)) +
                         '={trust_level="trusted"},' + json.dumps(str(worktree)) +
                         '={trust_level="trusted"}}')

    def test_herdr_wrapped_authentication_error_remains_external(self):
        self.assertEqual(classify("Herdr command failed: authentication_error"),
                         "authentication_error")

    def test_doctor_rejects_herdr_server_that_is_not_running(self):
        machine = {"tools": {}, "pressure": {"memory": {}}}

        def command(args, *unused, **kwargs):
            if args[0] == "herdr":
                return {"returncode": 0, "stdout": json.dumps({"running": False})}
            return {"returncode": 0, "stdout": ""}

        with patch("tsbench.cli.inventory", return_value=machine), \
             patch("tsbench.cli.verify_host", return_value=[]), \
             patch("tsbench.cli.shutil.which", return_value="/usr/bin/tool"), \
             patch("tsbench.common.run_command", side_effect=command), \
             redirect_stdout(io.StringIO()) as output:
            code = main(["doctor"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "invalid_environment")

    def test_inconclusive_parallel_stage_does_not_count_as_complete(self):
        config = Path(__file__).resolve().parents[1] / "benchmark.yaml"
        machine = {"tools": {}, "pressure": {"memory": {}}}
        stages = [
            {"concurrency": 4, "status": "validated"},
            {"concurrency": 8, "status": "inconclusive"},
            {"concurrency": 16, "status": "not_tested", "reason": "resource_admission"},
        ]
        with tempfile.TemporaryDirectory() as tmp, \
             patch("tsbench.runner.inventory", return_value=machine), \
             patch("tsbench.runner.verify_host", return_value=[]), \
             patch("tsbench.runner.run_command", return_value={"returncode": 0, "stdout": '{"running": true}'}), \
             patch("tsbench.runner.create_base", return_value=Path(tmp)), \
             patch("tsbench.runner.cpu", return_value={}), \
             patch("tsbench.runner.memory", return_value={}), \
             patch("tsbench.runner.disk", return_value={}), \
             patch("tsbench.runner.single", return_value={"status": "passed"}), \
             patch("tsbench.runner.parallel", return_value=stages):
            root = Path(tmp) / "state"
            result = run(config, root)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(load_json(root / "campaign.json")["eligible_runs"], [])
