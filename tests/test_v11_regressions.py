"""Regression tests for objective v1.1 measurements."""
import json
import io
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tsbench import agents
from tsbench.common import BenchmarkError
from tsbench.hardware import memory, _expected_memory_checksum, _last_level_cache_bytes
from tsbench.activity import sustained_working_seconds
from tsbench.real_tasks import create_real_base, validate_task, TASK_COUNT, SCENARIOS
from tsbench.fixtures import create_worktree
from reference_solutions import REFERENCES


class AgentQueueTests(unittest.TestCase):
    def test_failed_real_task_wait_is_bounded_by_its_own_timeout(self):
        def herdr(args,*unused):
            if args[:2]==['workspace','create']:
                return {'result':{'workspace':{'workspace_id':'w1'},
                                  'root_pane':{'pane_id':'w1:p1'}}}
            return {'result':{'agent':{'agent_status':'done'}}}
        cfg={'model':'gpt-6.1-terra','reasoning_effort':'xhigh',
             'parallel':{'max_tasks_per_agent':{'4':1}}}
        before=time.monotonic()
        with patch('tsbench.agents.create_worktree',return_value=Path('/tmp/task')), \
             patch('tsbench.agents._herdr',side_effect=herdr), \
             patch('tsbench.agents.real_tasks.validate_task',return_value={'passed':False}), \
             patch('tsbench.agents._wait_real',return_value='failed_tests') as wait:
            result=agents._worker_real(0,cfg,before+500,Path('/tmp/base'),
                                       Path('/tmp'),[],'tsb',4,before)
        self.assertEqual(result['status'],'failed_tests')
        self.assertLessEqual(wait.call_args.args[3],before+181)

    def test_contracts_state_observable_csv_and_webhook_results(self):
        from tsbench.real_tasks import task_prompt
        csv=task_prompt(2)
        webhook=task_prompt(5)
        self.assertIn('omit malformed emails',csv)
        self.assertIn('first valid row for each ID',csv)
        self.assertIn('{accepted,duplicate}',webhook)
        self.assertIn('accepted:false,duplicate:false',webhook)

    def test_real_worker_reports_herdr_start_timeout_as_timeout(self):
        def herdr(args,*unused):
            if args[:2]==["workspace","create"]:
                return {"result":{"workspace":{"workspace_id":"w1"},
                                  "root_pane":{"pane_id":"w1:p1"}}}
            raise agents.HerdrCommandError("timeout","agent_error")
        cfg={"model":"gpt-6.1-terra","reasoning_effort":"xhigh",
             "parallel":{"max_tasks_per_agent":{"16":2}}}
        with patch("tsbench.agents.create_worktree",return_value=Path("/tmp/task")), \
             patch("tsbench.agents._herdr",side_effect=herdr), \
             patch("tsbench.agents._classify_timeout",return_value="timed_out"):
            result=agents._worker_real(0,cfg,time.monotonic()+120,Path("/tmp/base"),
                                       Path("/tmp"),[],"tsb",16,time.monotonic())
        self.assertEqual(result["status"],"timed_out")

    def test_sustained_duration_requires_continuous_observed_working_tasks(self):
        names=["a","b","c","d"]
        tasks=[{"worker":i,"task_results":[{"started_offset_seconds":0,
                  "finished_offset_seconds":140}]} for i in range(4)]
        samples=[{"at":float(t),"working":names[:3]} for t in range(0,141,2)]
        self.assertEqual(sustained_working_seconds(samples,tasks,names,0,3),140)
        samples[35]["working"]=["a"]
        self.assertLess(sustained_working_seconds(samples,tasks,names,0,3),120)

    def test_sixteen_agent_worker_does_not_reuse_its_completed_task(self):
        prompts = []
        def herdr(args, *unused):
            if args[:2] == ["workspace", "create"]:
                return {"result": {"workspace": {"workspace_id": "w1"},
                                   "root_pane": {"pane_id": "w1:p1"}}}
            return {"result": {"agent": {"agent_status": "done"}}}
        def prompt(task_id):
            prompts.append(task_id)
            return "task " + str(task_id)
        cfg={"model":"gpt-6.1-terra","reasoning_effort":"xhigh",
             "parallel":{"max_tasks_per_agent":{"16":2}}}
        with patch("tsbench.agents.create_worktree",return_value=Path("/tmp/task")), \
             patch("tsbench.agents._herdr",side_effect=herdr), \
             patch("tsbench.agents.real_tasks.task_prompt",side_effect=prompt), \
             patch("tsbench.agents.real_tasks.validate_task",return_value={"passed":True}), \
             patch("tsbench.agents.real_tasks.changes_within_scope",return_value=True):
            result=agents._worker_real(0,cfg,time.monotonic()+120,Path("/tmp/base"),
                                       Path("/tmp"),[],"tsb",16,time.monotonic())
        self.assertEqual(result["passed"],2)
        self.assertEqual(len(set(prompts)),2)

    def test_waiting_tasks_without_observed_working_agents_are_not_sustained(self):
        class FakeTelemetry:
            def start(self): return self
            def stop(self): return {"oom_kills":0}
        class NoActivity:
            def __init__(self,*args,**kwargs): pass
            def start(self): return self
            def stop(self): return {"samples":[],"available":True,"complete":True}
        cfg={"agent_workload":"real","parallel":{"stages":[{"count":4,"seconds":200}],
             "minimum_observed_seconds":120,"minimum_free_mib_per_agent":1,
             "max_memory_psi_some":25,"max_tasks_per_agent":{"4":1}}}
        def worker(index,*args):
            return {"task_id":index,"status":"passed","attempted":1,"passed":1,
                    "task_results":[{"status":"passed","elapsed_seconds":10+index,
                                     "started_offset_seconds":0,"finished_offset_seconds":130}]}
        with tempfile.TemporaryDirectory() as tmp, \
             patch("tsbench.agents.meminfo",return_value={"MemAvailable":2*1024**3}), \
             patch("tsbench.agents.psi",return_value={}), \
             patch("tsbench.agents.Telemetry",FakeTelemetry), \
             patch("tsbench.agents.HerdrActivityMonitor",NoActivity,create=True), \
             patch("tsbench.agents._worker_real",side_effect=worker):
            result=agents.parallel(cfg,time.monotonic()+210,Path("/tmp/base"),Path("/tmp"),Path(tmp))
            evidence=json.loads((Path(tmp)/"agents-4-activity.json").read_text())
            self.assertEqual(evidence["samples"],[])
        self.assertNotEqual(result[0]["status"],"validated")
        self.assertEqual(result[0]["task_status_counts"],{"passed":4})
        self.assertEqual(result[0]["task_latency_median_seconds"],11.5)
        self.assertEqual(result[0]["task_latency_p95_seconds"],13)


class MemoryChecksumTests(unittest.TestCase):
    def test_cache_working_set_accounts_for_distinct_cache_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for cpu,shared in ((0,"0"),(1,"1")):
                index=root/("cpu"+str(cpu))/"cache"/"index3"
                index.mkdir(parents=True)
                for name,value in {"level":"3","type":"Unified","size":"16M",
                                   "shared_cpu_list":shared}.items():
                    (index/name).write_text(value)
            with patch("os.sched_getaffinity",return_value={0,1},create=True):
                self.assertEqual(_last_level_cache_bytes(root),32*1024**2)
            for cpu in (0,1):
                (root/("cpu"+str(cpu))/"cache"/"index3"/"shared_cpu_list").write_text("0-1")
            with patch("os.sched_getaffinity",return_value={0,1},create=True):
                self.assertEqual(_last_level_cache_bytes(root),16*1024**2)

    def test_doctor_rejects_missing_memory_binary(self):
        from tsbench.cli import main
        machine={"tools":{},"pressure":{"memory":{}}}
        def command(args,*unused,**kwargs):
            return {"returncode":0,"stdout":'{"running":true}' if args[0]=="herdr" else ""}
        with tempfile.TemporaryDirectory() as tmp, \
             patch("tsbench.cli.state_dir",return_value=Path(tmp)), \
             patch("tsbench.cli.inventory",return_value=machine), \
             patch("tsbench.cli.verify_host",return_value=[]), \
             patch("tsbench.cli.shutil.which",return_value="/usr/bin/tool"), \
             patch("tsbench.common.run_command",side_effect=command), \
             redirect_stdout(io.StringIO()) as output:
            code=main(["doctor"])
        self.assertEqual(code,2)
        self.assertTrue(any("memory" in e.lower() for e in json.loads(output.getvalue())["errors"]))

    def test_checksum_reference_matches_known_kernel_result(self):
        self.assertAlmostEqual(_expected_memory_checksum(64,55),3.20495944,places=7)

    def test_positive_but_incorrect_checksum_is_rejected(self):
        cfg={"memory":{"backend":"stream_style_v1","working_set_mib":512,
                       "minimum_cache_multiple":4,"samples":1,"sample_seconds":1}}
        sample={"backend":"stream_style_v1","threads":1,"working_set_mib":512,
                "passes":5,"checksum":1.0,
                **{name+"_mib_per_sec":1000.0 for name in ("copy","scale","add","triad")}}
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/"stream"
            binary.touch()
            with patch("tsbench.hardware.meminfo",return_value={"MemAvailable":2*1024**3}), \
                 patch("tsbench.hardware._last_level_cache_bytes",return_value=8*1024**2), \
                 patch("tsbench.hardware.run_command",return_value={"returncode":0,"stdout":json.dumps(sample)}), \
                 patch("os.sched_getaffinity",return_value={0},create=True):
                with self.assertRaises(BenchmarkError):
                    memory(cfg,time.monotonic()+60,executable=binary)


class ReportTests(unittest.TestCase):
    def test_mixed_disk_report_has_both_directions_and_latency(self):
        from tsbench.report import render
        result={"machine":{},"run_id":"r","status":"partial","provenance":{"model":"m","reasoning_effort":"x"},
                "agents":{},"disk":{"mixed_random_70r30w_qd16":{
                    "read":{"iops":7,"latency_p95_ms":1.2,"latency_p99_ms":1.5},
                    "write":{"iops":3,"latency_p95_ms":2.2,"latency_p99_ms":2.5}}}}
        report=render(result)
        self.assertIn("7 read IOPS",report)
        self.assertIn("3 write IOPS",report)
        self.assertIn("1.2 ms",report)
        self.assertNotIn("Disk mixed_random_70r30w_qd16 | not measured",report)
        self.assertNotIn("uses a cache-exceeding working set",report)


class ReferenceValidatorTests(unittest.TestCase):
    def test_fixture_includes_real_file_backed_api_work(self):
        self.assertTrue(any("file-backed" in scenario["title"].lower() and
                            "node:fs" in scenario["tests"] for scenario in SCENARIOS))

    def test_scope_rejects_changes_outside_assigned_task(self):
        from tsbench.real_tasks import changes_within_scope
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            tree=create_worktree(create_real_base(root),root,"scope")
            source=tree/"tasks"/"00"/"src"/"price.js"
            source.write_text("exports.lineTotal=()=>0;\n")
            self.assertTrue(changes_within_scope(tree,{0},10))
            (tree/"README.md").write_text("out of scope")
            self.assertFalse(changes_within_scope(tree,{0},10))

    def test_reference_solutions_pass_every_immutable_validator(self):
        self.assertEqual(len(REFERENCES),len(SCENARIOS))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            tree=create_worktree(create_real_base(root),root,"reference")
            for index in range(TASK_COUNT):
                source=tree/"tasks"/str(index).zfill(2)/"src"
                for name,code in REFERENCES[index%len(REFERENCES)].items():
                    (source/name).write_text(code,encoding="utf-8")
                self.assertTrue(validate_task(index,tree)["passed"],"reference task "+str(index))
