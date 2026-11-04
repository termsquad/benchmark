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
from tsbench.agents import classify, _worker, parallel, single
from tsbench.inventory import oom_kills


class RunValidityTests(unittest.TestCase):
    def test_timeout_with_rate_limit_screen_is_external_not_host_failure(self):
        def herdr(args, *unused):
            if args[:2] == ["workspace", "create"]:
                return {"result": {"workspace": {"workspace_id": "w1"},
                                   "root_pane": {"pane_id": "w1:p1"}}}
            if args[:2] == ["agent", "prompt"]:
                from tsbench.agents import HerdrCommandError
                raise HerdrCommandError("timeout", "agent_error")
            return {}
        with patch("tsbench.agents.create_worktree", return_value=Path('/tmp/task')), \
             patch("tsbench.agents._herdr", side_effect=herdr), \
             patch("tsbench.agents.run_command", return_value={"returncode": 0,
                   "stdout": "Rate limit exceeded", "stderr": ""}):
            result = _worker(0, {"model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
                             time.monotonic()+60, Path('/tmp/base'), Path('/tmp'), [], "tsb")
        self.assertEqual(result["status"], "rate_limited")

    def test_herdr_timeout_is_recorded_as_timeout(self):
        def herdr(args, *unused):
            if args[:2] == ["workspace", "create"]:
                return {"result": {"workspace": {"workspace_id": "w1"},
                                   "root_pane": {"pane_id": "w1:p1"}}}
            if args[:2] == ["agent", "prompt"]:
                from tsbench.agents import HerdrCommandError
                raise HerdrCommandError("timeout", "agent_error")
            return {}
        with patch("tsbench.agents.create_worktree", return_value=Path('/tmp/task')), \
             patch("tsbench.agents._herdr", side_effect=herdr):
            result = _worker(0, {"model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
                             time.monotonic()+60, Path('/tmp/base'), Path('/tmp'), [], "tsb")
        self.assertEqual(result["status"], "timed_out")

    def test_early_done_does_not_fail_a_task_before_its_validator_passes(self):
        calls = []
        def herdr(args, *unused):
            calls.append(args)
            if args[:2] == ["workspace", "create"]:
                return {"result": {"workspace": {"workspace_id": "w1"},
                                   "root_pane": {"pane_id": "w1:p1"}}}
            if args[:2] in (["agent", "prompt"], ["agent", "get"]):
                return {"result": {"agent": {"agent_status": "done"}}}
            return {}
        with patch("tsbench.agents.create_worktree", return_value=Path('/tmp/task')), \
             patch("tsbench.agents._herdr", side_effect=herdr), \
             patch("tsbench.agents.validate_task", side_effect=[{"passed": False}, {"passed": True}]), \
             patch("tsbench.agents.time.sleep"):
            result = _worker(0, {"model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
                             time.monotonic()+60, Path('/tmp/base'), Path('/tmp'), [], "tsb")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(sum(args[:2] == ["agent", "prompt"] for args in calls), 1)

    def test_stalled_prompt_waits_without_resubmission_until_task_is_validated(self):
        calls = []
        states = iter(["idle", "working", "done"])
        def herdr(args, *unused):
            calls.append(args)
            if args[:2] == ["workspace", "create"]:
                return {"result": {"workspace": {"workspace_id": "w1"},
                                   "root_pane": {"pane_id": "w1:p1"}}}
            if args[:2] == ["agent", "prompt"]:
                from tsbench.agents import HerdrCommandError
                raise HerdrCommandError("agent_prompt_stalled", "agent_error")
            if args[:2] == ["agent", "get"]:
                return {"result": {"agent": {"agent_status": next(states)}}}
            return {}
        with patch("tsbench.agents.create_worktree", return_value=Path('/tmp/task')), \
             patch("tsbench.agents._herdr", side_effect=herdr), \
             patch("tsbench.agents.validate_task", side_effect=[{"passed": False}, {"passed": True}]), \
             patch("tsbench.agents.time.sleep"):
            result = _worker(0, {"model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
                             time.monotonic()+60, Path('/tmp/base'), Path('/tmp'), [], "tsb")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(sum(args[:2] == ["agent", "prompt"] for args in calls), 1)

    def test_single_agent_uses_supported_unattended_codex_flags(self):
        class FakeTelemetry:
            def start(self): return self
            def stop(self): return {}
        with patch("tsbench.agents.create_worktree", return_value=Path('/tmp/task')), \
             patch("tsbench.agents.Telemetry", FakeTelemetry), \
             patch("tsbench.agents.validate_task", return_value={"passed": True}), \
             patch("tsbench.agents.run_command", return_value={"returncode": 0, "stdout": ""}) as run_cmd:
            result = single({"model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
                            time.monotonic()+60, Path('/tmp/base'), Path('/tmp'))
        self.assertEqual(result["status"], "passed")
        argv = run_cmd.call_args.args[0]
        self.assertNotIn("--full-auto", argv)
        self.assertIn("workspace-write", argv)
        self.assertIn('approval_policy="never"', argv)

    def test_guest_oom_counter_is_read_from_vmstat(self):
        def read(path, *args, **kwargs):
            if str(path) == "/proc/vmstat":
                return "pgfault 100\noom_kill 3\n"
            raise FileNotFoundError(str(path))
        with patch("pathlib.Path.read_text", autospec=True, side_effect=read):
            self.assertEqual(oom_kills(), 3)

    def test_parallel_stage_with_unknown_oom_is_not_validated(self):
        class FakeTelemetry:
            def start(self): return self
            def stop(self): return {"oom_kills": None}
        config = {"parallel": {"stages": [{"count": 4, "seconds": 90}],
                               "minimum_free_mib_per_agent": 1, "max_memory_psi_some": 25}}
        def worker(index, *args):
            return {"task_id": index, "status": "passed"}
        with patch("tsbench.agents.meminfo", return_value={"MemAvailable": 1024**3}), \
             patch("tsbench.agents.psi", return_value={}), \
             patch("tsbench.agents.Telemetry", FakeTelemetry), \
             patch("tsbench.agents._worker", side_effect=worker):
            result = parallel(config, time.monotonic()+100, Path('/tmp/base'), Path('/tmp'))
        self.assertEqual(result[0]["status"], "inconclusive")

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
