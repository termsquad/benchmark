"""Regression tests for v1.1.3: measurement validity, Herdr settlement, and workloads."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tsbench.activity import activity_statistics
from tsbench.agents import _wait_real
from tsbench.real_tasks import task_prompt
from tsbench.report import render


class BusyTimeTests(unittest.TestCase):
    @staticmethod
    def workers(seconds=210):
        return [{"worker": i, "task_results": [
            {"started_offset_seconds": 0.0, "finished_offset_seconds": float(seconds)}
        ]} for i in range(4)]

    def test_accumulated_busy_time_and_longest_uninterrupted_are_separate(self):
        names = ["a", "b", "c", "d"]
        # Sub-second state transitions can break a continuous chain without
        # erasing minutes of objectively observed concurrent work.
        samples = [{"at": float(i), "working": names[:3]} for i in range(0, 211, 2)]
        for second in (50, 100, 150):
            samples[second//2]["working"] = ["a"]
        stats=activity_statistics(samples,self.workers(),names,0,210,3)
        self.assertGreaterEqual(stats["qualifying_seconds"], 120)
        self.assertLess(stats["longest_continuous_seconds"], 120)
        self.assertGreater(stats["mean_agent_occupancy"],.5)
        self.assertTrue(stats["telemetry_complete"])

    def test_missing_samples_do_not_count_as_busy_and_reduce_coverage(self):
        names=["a","b","c","d"]
        samples=[{"at":float(i),"working":names[:3]} for i in range(0,211,2)]
        for second in range(30,151,2):
            samples[second//2]["working"]=None
        stats=activity_statistics(samples,self.workers(),names,0,210,3)
        self.assertFalse(stats["telemetry_complete"])
        self.assertLess(stats["telemetry_coverage_fraction"],.85)
        self.assertLess(stats["qualifying_seconds"],120)

    def test_herdr_states_alone_do_not_count_without_inflight_tasks(self):
        stats=activity_statistics(
            [{"at":float(i),"working":["a","b","c","d"]} for i in range(0,201,2)],
            [{"worker":i,"task_results":[]} for i in range(4)],
            ["a","b","c","d"],0,200,3)
        self.assertEqual(stats["qualifying_seconds"],0)
        self.assertEqual(stats["mean_agent_occupancy"],0)


class SettledAgentTests(unittest.TestCase):
    def test_premature_done_must_not_fail_a_task_that_later_succeeds(self):
        status=iter(["done","done","working","done"])
        validations=iter([{"passed":False},{"passed":False},{"passed":True}])
        def herdr(*args,**kwargs):
            return {"result":{"agent":{"agent_status":next(status)}}}
        with patch("tsbench.agents._herdr",side_effect=herdr), \
             patch("tsbench.agents.real_tasks.validate_task",side_effect=validations), \
             patch("tsbench.agents._task_code_signature",return_value=("unchanged",)), \
             patch("tsbench.agents.time.sleep",return_value=None):
            result=_wait_real("agent",0,Path("/tmp/unused"),time.monotonic()+30,
                              saw_working=True,settled_grace_seconds=10)
        self.assertEqual(result,"passed")

    def test_stably_settled_failed_task_does_not_wait_180_seconds(self):
        original_sleep=time.sleep
        with patch("tsbench.agents._herdr",
                   return_value={"result":{"agent":{"agent_status":"done"}}}), \
             patch("tsbench.agents.real_tasks.validate_task",return_value={"passed":False}), \
             patch("tsbench.agents._task_code_signature",return_value=("unchanged",)), \
             patch("tsbench.agents.time.sleep",side_effect=lambda unused:original_sleep(.006)):
            start=time.monotonic()
            result=_wait_real("agent",0,Path("/tmp/unused"),start+2,
                              saw_working=True,settled_grace_seconds=.024)
        self.assertEqual(result,"failed_tests")
        self.assertLess(time.monotonic()-start,1)

    def test_unobserved_prompt_stall_is_not_turned_into_failed_tests(self):
        original_sleep=time.sleep
        with patch("tsbench.agents._herdr",
                   return_value={"result":{"agent":{"agent_status":"done"}}}), \
             patch("tsbench.agents.real_tasks.validate_task",return_value={"passed":False}), \
             patch("tsbench.agents._task_code_signature",return_value=("unchanged",)), \
             patch("tsbench.agents.time.sleep",side_effect=lambda unused:original_sleep(.004)):
            result=_wait_real("agent",0,Path("/tmp/unused"),time.monotonic()+.05,
                              saw_working=False,settled_grace_seconds=.01)
        self.assertEqual(result,"timed_out")


class FixtureAndReportTests(unittest.TestCase):
    def test_price_and_inventory_contracts_define_objective_semantics(self):
        self.assertIn("floor(priceCents*(100-discountPercent)/100)",task_prompt(0))
        self.assertIn("coalesce repeated SKU quantities",task_prompt(3))
        self.assertIn("Never mutate inputs",task_prompt(3))

    def test_report_shows_capacity_independently_from_measurement_status(self):
        result={"machine":{},"run_id":"sample","status":"complete",
                "provenance":{"model":"gpt-6.1-terra","reasoning_effort":"xhigh"},
                "agents":{"single":{"status":"passed"},"parallel":[{
                    "concurrency":16,"status":"measured",
                    "capacity_status":"below_target_observed",
                    "passed":8,"attempted":16,
                    "throughput_per_minute":3.7,
                    "observed_sustained_seconds":50,
                    "activity_statistics":{"longest_continuous_seconds":12}
                }]}}
        md=render(result)
        self.assertIn("measurement=measured",md)
        self.assertIn("capacity=below_target_observed",md)
        self.assertIn("longest continuous 12",md)


if __name__=="__main__":
    unittest.main()
