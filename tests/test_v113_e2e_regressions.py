"""Regressions discovered while auditing the v1.1.3 pilot."""
import tempfile
import time
import unittest
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch

from reference_solutions import REFERENCES
from tsbench import agents, real_tasks
from tsbench.activity import activity_statistics
from tsbench.common import CommandTimeout


class FixtureContracts(unittest.TestCase):
    def _worktree(self, root, index=0):
        base=real_tasks.create_real_base(root)
        worktree=real_tasks.create_worktree(base,root,'reference')
        for name,code in REFERENCES[index].items():
            (worktree/'tasks'/str(index).zfill(2)/'src'/name).write_text(code)
        return worktree

    def test_discount_validator_rejects_rounding_after_quantity(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree=self._worktree(Path(tmp))
            price=worktree/'tasks/00/src/price.js'
            price.write_text("exports.lineTotal=(p,q,d=0)=>{if(q<=0)throw Error('quantity');return Math.floor(p*q*(100-d)/100)};")
            self.assertFalse(real_tasks.validate_task(0,worktree)['passed'])

    def test_reference_respects_per_unit_rounding(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            worktree=self._worktree(Path(tmp))
            code="const assert=require('node:assert/strict');const {lineTotal}=require('./src/price');assert.equal(lineTotal(101,2,50),100)"
            result=subprocess.run(['node','-e',code],cwd=worktree/'tasks/00',capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_reference_rejects_invalid_price_and_discount(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            worktree=self._worktree(Path(tmp))
            code="const a=require('node:assert/strict'),{lineTotal}=require('./src/price');for(const [p,d] of [[-1,0],[1.5,0],[100,-1],[100,101]])a.throws(()=>lineTotal(p,1,d))"
            result=subprocess.run(['node','-e',code],cwd=worktree/'tasks/00',capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_validator_rejects_non_positive_inventory_quantities(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree=self._worktree(Path(tmp),3)
            stock=worktree/'tasks/03/src/stock.js'
            stock.write_text("exports.reserve=(stock,items)=>{const r={...stock};for(const {sku,qty} of items){if(!(sku in r))throw Error('unknown sku');if(r[sku]<qty)throw Error('stock');r[sku]-=qty}return r};")
            self.assertFalse(real_tasks.validate_task(3,worktree)['passed'])

    def test_validator_timeout_is_infrastructure_not_failed_tests(self):
        with patch('tsbench.real_tasks.run_command',side_effect=CommandTimeout('timeout')):
            verdict=real_tasks.validate_task(0,Path('/tmp/unused'))
        self.assertEqual(verdict.get('error'),'validator_timeout')


class TimingEvidence(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'),'requires Linux procfs')
    def test_owned_worktree_rss_observes_live_process_without_sensitive_fields(self):
        from tsbench.telemetry import _owned_process_rss
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); worktree=root/'task-tsbtest'; worktree.mkdir()
            process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'],cwd=worktree)
            try:
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    values=_owned_process_rss(root)
                    if values.get('tsbtest',{}).get('rss_bytes',0)>0:
                        break
                    time.sleep(.05)
                self.assertGreater(values.get('tsbtest',{}).get('rss_bytes',0),0)
                self.assertEqual(set(values['tsbtest']),{'rss_bytes','processes'})
            finally:
                process.terminate(); process.wait(timeout=3)

    def test_blocked_agent_with_explicit_quota_is_classified_externally(self):
        with patch('tsbench.agents._herdr',return_value={'result':{'agent':{'agent_status':'blocked'}}}), \
             patch('tsbench.agents.run_command',return_value={'stdout':'429 rate limit','stderr':'','returncode':0}):
            result=agents._wait_real('agent',0,Path('/tmp/no'),time.monotonic()+10)
        self.assertEqual(result,'rate_limited')

    def test_validator_infrastructure_error_is_not_coding_failure(self):
        with patch('tsbench.agents._herdr',return_value={'result':{'agent':{'agent_status':'done'}}}), \
             patch('tsbench.agents.real_tasks.validate_task',return_value={'passed':False,'error':'validator_timeout'}):
            result=agents._wait_real('agent',0,Path('/tmp/no'),time.monotonic()+10)
        self.assertEqual(result,'infrastructure_error')

    def test_resource_coverage_requires_complete_adjacent_samples(self):
        from tsbench.telemetry import resource_telemetry_coverage
        keys=['cpu_percent','memory_used_bytes','memory_available_bytes','swap_used_bytes',
              'memory_psi_some_avg10','cpu_psi_some_avg10','io_psi_some_avg10']
        samples=[{'at':i,**{key:0 for key in keys}} for i in (0,2,4,6,8,10)]
        self.assertEqual(resource_telemetry_coverage(samples,0,10),1)
        samples[2]['cpu_psi_some_avg10']=None
        self.assertEqual(resource_telemetry_coverage(samples,0,10),0.6)

    def test_activity_is_clipped_to_stage_boundaries(self):
        names=['a','b','c','d']
        tasks=[{'worker':i,'task_results':[{'started_offset_seconds':-1,'finished_offset_seconds':2}]} for i in range(4)]
        s=activity_statistics([{'at':-1,'working':names},{'at':2,'working':names}],tasks,names,0,1,3)
        self.assertLessEqual(s['qualifying_seconds'],1)
        self.assertLessEqual(s['observed_agent_seconds'],4)
        self.assertLessEqual(s['mean_agent_occupancy'],1)

    def test_deadline_before_grace_is_timeout_not_failed_tests(self):
        real_sleep=time.sleep
        with patch('tsbench.agents._herdr',return_value={'result':{'agent':{'agent_status':'done'}}}), \
             patch('tsbench.agents.real_tasks.validate_task',return_value={'passed':False}), \
             patch('tsbench.agents._task_code_signature',return_value=('unchanged',)), \
             patch('tsbench.agents.time.sleep',side_effect=lambda _:real_sleep(.004)):
            result=agents._wait_real('a',0,Path('/tmp/no'),time.monotonic()+.04,saw_working=True,settled_grace_seconds=10)
        self.assertEqual(result,'timed_out')


class EligibilityEvidence(unittest.TestCase):
    def test_runner_rejects_stage_with_false_measurement_valid(self):
        from tsbench.runner import run
        config=Path(__file__).resolve().parents[1]/'benchmark.yaml'
        stages=[{'concurrency':n,'status':'measured','measurement_valid':n!=8}
                for n in (4,8,16)]
        machine={'tools':{},'pressure':{'memory':{}}}
        with tempfile.TemporaryDirectory() as tmp, \
             patch('tsbench.runner.inventory',return_value=machine), \
             patch('tsbench.runner.verify_host',return_value=[]), \
             patch('tsbench.runner.verify_memory_build',return_value=({},[])), \
             patch('tsbench.runner.run_command',return_value={'returncode':0,'stdout':'{"running":true}'}), \
             patch('tsbench.runner.create_real_base',return_value=Path(tmp)), \
             patch('tsbench.runner.cpu',return_value={}), \
             patch('tsbench.runner.memory',return_value={'status':'validated'}), \
             patch('tsbench.runner.disk',return_value={}), \
             patch('tsbench.runner.single',return_value={'status':'passed'}), \
             patch('tsbench.runner.parallel',return_value=stages):
            result=run(config,Path(tmp)/'state')
        self.assertEqual(result['status'],'partial')

    def _run(self, worker, oom=0):
        class Telemetry:
            def __init__(self): self.samples=[]
            def start(self): return self
            def stop(self): return {'oom_kills':oom,'sample_count':0}
        class Activity:
            def __init__(self,*args): pass
            def start(self): return self
            def stop(self): return {'available':True,'complete':True,'samples':[]}
        cfg={'agent_workload':'real','parallel':{'stages':[{'count':4,'seconds':200}],
             'minimum_observed_seconds':120,'minimum_free_mib_per_agent':1,
             'max_memory_psi_some':25,'max_tasks_per_agent':{'4':2}}}
        occupancy={'qualifying_seconds':120,'longest_continuous_seconds':120,'telemetry_complete':True,
                   'telemetry_coverage_fraction':1,'mean_agent_occupancy':1}
        with patch('tsbench.agents.meminfo',return_value={'MemAvailable':2*1024**3}), \
             patch('tsbench.agents.psi',return_value={}), patch('tsbench.agents.Telemetry',Telemetry), \
             patch('tsbench.agents.HerdrActivityMonitor',Activity), \
             patch('tsbench.agents.activity_statistics',return_value=occupancy), \
             patch('tsbench.agents._worker_real',side_effect=worker):
            return agents.parallel(cfg,time.monotonic()+210,Path('/tmp/base'),Path('/tmp'))[0]

    def test_later_rate_limit_cannot_be_hidden_by_first_failed_task(self):
        def worker(i,*args):
            tasks=[{'status':'failed_tests'},{'status':'rate_limited'}] if i==0 else [{'status':'passed'}]
            return {'worker':i,'task_id':i,'status':'failed_tests' if i==0 else 'passed',
                    'attempted':len(tasks),'passed':0 if i==0 else 1,'task_results':tasks}
        self.assertEqual(self._run(worker)['status'],'externally_constrained')

    def test_missing_resource_telemetry_cannot_be_valid(self):
        def worker(i,*args):
            return {'worker':i,'task_id':i,'status':'passed','attempted':1,'passed':1,
                    'task_results':[{'status':'passed'}]}
        self.assertEqual(self._run(worker)['status'],'inconclusive_telemetry')

    def test_unknown_oom_cannot_be_reported_as_sustained_capacity(self):
        def worker(i,*args):
            return {'worker':i,'task_id':i,'status':'passed','attempted':1,'passed':1,
                    'task_results':[{'status':'passed'}]}
        stage=self._run(worker,oom=None)
        self.assertEqual(stage['status'],'inconclusive')
        self.assertEqual(stage['capacity_status'],'not_measured')

    def test_unexplained_agent_error_cannot_be_valid_host_capacity(self):
        def worker(i,*args):
            return {'worker':i,'task_id':i,'status':'agent_error' if i==0 else 'passed',
                    'attempted':1,'passed':0 if i==0 else 1,
                    'task_results':[{'status':'agent_error' if i==0 else 'passed'}]}
        self.assertNotEqual(self._run(worker)['status'],'measured')
