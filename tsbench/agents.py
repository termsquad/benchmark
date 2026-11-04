"""Real Codex + Herdr execution with objective external validation."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json
import re
import time
import uuid
from .common import BenchmarkError, CommandTimeout, require_success, run_command, remaining
from .fixtures import task_prompt, create_worktree, validate_task
from .telemetry import Telemetry
from .inventory import meminfo, psi
from . import real_tasks


def classify(output: str) -> str:
    text = output.lower()
    if re.search(r"rate.?limit|429|quota exceeded|usage limit", text):
        return "rate_limited"
    if re.search(r"unauthorized|authentication failed|authentication_error|login required|401", text):
        return "authentication_error"
    return "agent_error"


def _usage_from_codex_jsonl(output: str) -> dict | None:
    # Retain usage counters only. Never persist prompt text or raw agent events.
    for line in reversed(output.splitlines()):
        try:
            event=json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event,dict):
            continue
        usage=event.get("usage")
        if event.get("type")=="turn.completed" and isinstance(usage,dict):
            return {key:int(value) for key,value in usage.items()
                    if key in ("input_tokens","output_tokens","cached_input_tokens")
                    and isinstance(value,int) and not isinstance(value,bool)}
    return None


class HerdrCommandError(BenchmarkError):
    def __init__(self, code: str, category: str):
        super().__init__("Herdr command failed: " + code + ": " + category)
        self.code = code
        self.category = category


def single(config: dict, deadline: float, base: Path, scratch: Path) -> dict:
    worktree = create_worktree(base,scratch,"single")
    real_mode=config.get("agent_workload")=="real"
    task_id=15 if real_mode else 16
    telemetry = Telemetry().start()
    start = time.monotonic()
    cmd = ["codex","exec","--model",config["model"],"-c",
           'model_reasoning_effort="'+config["reasoning_effort"]+'"',
           "-c",'approval_policy="never"',"--sandbox","workspace-write",
           "--json",real_tasks.task_prompt(task_id) if real_mode else task_prompt(task_id)]
    try:
        response = run_command(cmd,remaining(deadline,450),cwd=worktree,max_output=180000)
        verdict = real_tasks.validate_task(task_id,worktree) if real_mode else validate_task(task_id,worktree)
        outcome = ("passed" if verdict["passed"] and response["returncode"]==0 else
                   "failed_tests" if response["returncode"]==0 else
                   classify(response["stderr"]+"\n"+response["stdout"]))
        return {"status":outcome,"elapsed_seconds":round(time.monotonic()-start,3),
                "validator":verdict,"surface":"codex_exec","token_usage":_usage_from_codex_jsonl(response["stdout"]),
                "telemetry":telemetry.stop(),
                "external_service_constrained":outcome=="rate_limited"}
    except CommandTimeout:
        return {"status":"timed_out","elapsed_seconds":round(time.monotonic()-start,3),
                "telemetry":telemetry.stop(),"surface":"codex_exec"}
    except Exception as exc:
        return {"status":"infrastructure_error","reason":type(exc).__name__,"elapsed_seconds":round(time.monotonic()-start,3),
                "telemetry":telemetry.stop(),"surface":"codex_exec"}
    finally:
        telemetry.stop()


def _herdr(args: list[str], deadline: float, limit: float = 35) -> dict:
    response = run_command(["herdr",*args],remaining(deadline,limit),max_output=12000)
    if response["returncode"]!=0:
        code = "unknown"
        try:
            error = json.loads(response["stderr"]).get("error",{})
            candidate = error.get("code", "")
            if isinstance(candidate,str) and re.fullmatch(r"[a-z0-9_]{1,80}",candidate):
                code = candidate
        except (ValueError,AttributeError):
            pass
        raise HerdrCommandError(code,classify(response["stderr"]+"\n"+response["stdout"]))
    try:
        return json.loads(response["stdout"])
    except json.JSONDecodeError:
        raise BenchmarkError("Unexpected Herdr JSON")


def _wait_for_task_result(name: str, task_id: int, worktree: Path, deadline: float) -> str:
    # A stalled prompt or an early idle/done signal can precede actual work.
    # Never resend it; let the objective validator run until the fixed deadline.
    last_status = None
    while remaining(deadline,1)>0:
        agent = _herdr(["agent","get",name],deadline,5).get("result",{}).get("agent",{})
        status = agent.get("agent_status")
        last_status = status
        if status == "blocked":
            return "agent_error"
        if status in ("idle","done"):
            if validate_task(task_id,worktree,timeout=remaining(deadline,10))["passed"]:
                return "passed"
        time.sleep(min(1.0,remaining(deadline,1)))
    return "failed_tests" if last_status in ("idle","done") else "timed_out"


def _classify_timeout(name: str, deadline: float) -> str:
    # Inspect transiently for explicit provider/auth errors; never save the text.
    try:
        response = run_command(["herdr","agent","read",name,"--source","recent-unwrapped","--lines","100"],
                               remaining(deadline,2),max_output=12000)
        category = classify(response["stdout"]+"\n"+response["stderr"])
        return category if category in ("rate_limited","authentication_error") else "timed_out"
    except Exception:
        return "timed_out"


def _worker(index: int, config: dict, deadline: float, base: Path, scratch: Path, created: list, prefix: str) -> dict:
    name = (prefix+str(index).zfill(2))[:31]
    started = time.monotonic()
    try:
        worktree = create_worktree(base,scratch,name)
        ws = _herdr(["workspace","create","--cwd",str(worktree),"--label","tsbench-"+name,"--no-focus"],deadline)
        data = ws.get("result",{})
        workspace = data["workspace"]["workspace_id"]
        pane = data["root_pane"]["pane_id"]
        created.append(workspace)
        # Codex identifies a Git worktree's shared fixture base as the project
        # root. An inline TOML table avoids dotted-path parsing of paths with dots.
        trust = ("projects={"+json.dumps(str(base))+'={trust_level="trusted"},'+
                 json.dumps(str(worktree))+'={trust_level="trusted"}}')
        _herdr(["agent","start",name,"--kind","codex","--pane",pane,"--timeout","25000",
                "--","-m",config["model"],"-c",
                'model_reasoning_effort="'+config["reasoning_effort"]+'"',"-c",trust,
                "--sandbox","workspace-write","--ask-for-approval","never"],deadline,32)
        wait_ms = max(3000,int(remaining(deadline,360)*1000)-3000)
        try:
            prompted = _herdr(["agent","prompt",name,task_prompt(index),"--wait","--timeout",str(wait_ms)],deadline,wait_ms/1000+2)
        except HerdrCommandError as exc:
            if exc.code != "agent_prompt_stalled":
                raise
            status = _wait_for_task_result(name,index,worktree,deadline)
            return {"task_id":index,"status":status,"elapsed_seconds":round(time.monotonic()-started,3)}
        if prompted.get("result",{}).get("agent",{}).get("agent_status")=="blocked":
            return {"task_id":index,"status":"agent_error","reason_code":"agent_blocked",
                    "elapsed_seconds":round(time.monotonic()-started,3)}
        validated = validate_task(index,worktree)
        status = "passed" if validated["passed"] else _wait_for_task_result(name,index,worktree,deadline)
        return {"task_id":index,"status":status,
                "elapsed_seconds":round(time.monotonic()-started,3)}
    except CommandTimeout:
        return {"task_id":index,"status":"timed_out","elapsed_seconds":round(time.monotonic()-started,3)}
    except HerdrCommandError as exc:
        status = _classify_timeout(name,deadline) if exc.code=="timeout" else exc.category
        return {"task_id":index,"status":status,"reason_code":exc.code,
                "elapsed_seconds":round(time.monotonic()-started,3)}
    except Exception as exc:
        category = classify(str(exc))
        return {"task_id":index,"status":category,"elapsed_seconds":round(time.monotonic()-started,3)}


def _wait_real(name: str, task_id: int, worktree: Path, deadline: float) -> str:
    """Preserve the v1 Codex fix: no duplicate prompts on early 'done' states."""
    last_status=None
    while remaining(deadline,1)>0:
        agent=_herdr(["agent","get",name],deadline,5).get("result",{}).get("agent",{})
        status=agent.get("agent_status")
        last_status=status
        if status=="blocked":
            return "agent_error"
        if status in ("idle","done") and real_tasks.validate_task(
                task_id,worktree,timeout=remaining(deadline,10))["passed"]:
            return "passed"
        time.sleep(min(1.0,remaining(deadline,1)))
    return "failed_tests" if last_status in ("idle","done") else "timed_out"


def _worker_real(index: int, config: dict, deadline: float, base: Path,
                 scratch: Path, created: list, prefix: str, count: int) -> dict:
    """One owned Herdr workspace per worker, multiple independent real code tasks."""
    name=(prefix+str(index).zfill(2))[:31]
    started=time.monotonic()
    outcomes=[]
    try:
        worktree=create_worktree(base,scratch,name)
        response=_herdr(["workspace","create","--cwd",str(worktree),
                         "--label","tsbench-"+name,"--no-focus"],deadline)
        data=response.get("result",{})
        workspace=data["workspace"]["workspace_id"]
        pane=data["root_pane"]["pane_id"]
        created.append(workspace)
        # Use exactly the same narrow worktree/base trust as the v1 Codex fix.
        trust=("projects={"+json.dumps(str(base))+'={trust_level="trusted"},'+
               json.dumps(str(worktree))+'={trust_level="trusted"}}')
        _herdr(["agent","start",name,"--kind","codex","--pane",pane,"--timeout","25000",
                "--","-m",config["model"],"-c",
                'model_reasoning_effort="'+config["reasoning_effort"]+'"',"-c",trust,
                "--sandbox","workspace-write","--ask-for-approval","never"],deadline,32)
        max_tasks=int(config["parallel"]["max_tasks_per_agent"].get(str(count),2))
        for round_index in range(max_tasks):
            if remaining(deadline,30)<30:
                break
            task_id=(index+count*round_index)%real_tasks.TASK_COUNT
            task_started=time.monotonic()
            try:
                wait_ms=max(3000,int(remaining(deadline,180)*1000)-3000)
                response=_herdr(["agent","prompt",name,real_tasks.task_prompt(task_id),
                                 "--wait","--timeout",str(wait_ms)],deadline,wait_ms/1000+2)
                agent=response.get("result",{}).get("agent",{})
                if agent.get("agent_status")=="blocked":
                    status="agent_error"
                else:
                    verdict=real_tasks.validate_task(task_id,worktree)
                    status="passed" if verdict["passed"] else _wait_real(name,task_id,worktree,deadline)
            except HerdrCommandError as exc:
                if exc.code=="agent_prompt_stalled":
                    status=_wait_real(name,task_id,worktree,deadline)
                elif exc.code=="timeout":
                    status=_classify_timeout(name,deadline)
                else:
                    status=exc.category
            except CommandTimeout:
                status=_classify_timeout(name,deadline)
            outcomes.append({"task_id":task_id,"status":status,
                             "elapsed_seconds":round(time.monotonic()-task_started,3)})
            if status in ("rate_limited","authentication_error","timed_out","agent_error"):
                break
        passed=sum(task["status"]=="passed" for task in outcomes)
        failure=next((task["status"] for task in outcomes if task["status"]!="passed"),None)
        return {"worker":index,"task_id":index,"attempted":len(outcomes),
                "passed":passed,"status":failure or ("passed" if outcomes else "not_tested"),
                "task_results":outcomes,"elapsed_seconds":round(time.monotonic()-started,3)}
    except (CommandTimeout,HerdrCommandError) as exc:
        status=_classify_timeout(name,deadline) if isinstance(exc,CommandTimeout) else exc.category
        return {"worker":index,"task_id":index,"status":status,"attempted":len(outcomes),
                "passed":sum(t["status"]=="passed" for t in outcomes),"task_results":outcomes,
                "elapsed_seconds":round(time.monotonic()-started,3)}
    except Exception as exc:
        return {"worker":index,"task_id":index,"status":classify(str(exc)),
                "attempted":len(outcomes),"passed":sum(t["status"]=="passed" for t in outcomes),
                "task_results":outcomes,"elapsed_seconds":round(time.monotonic()-started,3)}


def parallel(config: dict, deadline: float, base: Path, scratch: Path) -> list[dict]:
    results = []
    prefix = "tsb"+uuid.uuid4().hex[:7]
    for stage in config["parallel"]["stages"]:
        count = int(stage["count"])
        stage_start = time.monotonic()
        stage_deadline = min(deadline,stage_start+stage["seconds"])
        worker_deadline = stage_deadline-max(15,count*3)  # reserve Herdr workspace cleanup
        free = meminfo().get("MemAvailable",0)/1048576
        pressure = psi("memory").get("avg10",0)
        if free < count*config["parallel"]["minimum_free_mib_per_agent"] or pressure > config["parallel"]["max_memory_psi_some"]:
            results.append({"concurrency":count,"status":"not_tested","reason":"resource_admission",
                            "free_memory_mib":round(free,1),"memory_psi_some_avg10":pressure})
            continue
        created = []
        telemetry = Telemetry().start()
        tasks = []
        try:
            with ThreadPoolExecutor(max_workers=count) as executor:
                real_mode=config.get("agent_workload")=="real"
                futures = [executor.submit(_worker_real,index,config,worker_deadline,base,scratch,
                                           created,prefix+str(count),count) if real_mode else
                           executor.submit(_worker,index,config,worker_deadline,base,scratch,
                                           created,prefix+str(count))
                           for index in range(count)]
                for f in as_completed(futures):
                    tasks.append(f.result())
            elapsed = time.monotonic()-stage_start
            attempted = sum(x.get("attempted",1) for x in tasks)
            passed = sum(x.get("passed",1 if x["status"]=="passed" else 0) for x in tasks)
            constrained = any(x["status"] in ("rate_limited","authentication_error") for x in tasks)
            metrics = telemetry.stop()
            real_mode=config.get("agent_workload")=="real"
            minimum=config["parallel"].get("minimum_observed_seconds",0) if real_mode else 0
            status = ("externally_constrained" if constrained else
                      "failed_host" if (metrics["oom_kills"] or 0)>0 else
                      "inconclusive" if metrics["oom_kills"] is None else
                      "insufficient_sustained_load" if real_mode and elapsed<minimum else
                      "validated" if attempted>=count and passed/max(attempted,1)>=.75 else "inconclusive")
            results.append({"concurrency":count,"status":status,"passed":passed,
                            "attempted":attempted,"workload":"multi_file" if real_mode else "micro_smoke",
                            "minimum_sustained_seconds":minimum,
                            "throughput_per_minute":round(passed/max(elapsed,1)*60,4),
                            "elapsed_seconds":round(elapsed,3),"tasks":sorted(tasks,key=lambda x:x["task_id"]),
                            "telemetry":metrics})
        finally:
            telemetry.stop()
            failed_cleanup=False
            for workspace in created:
                try:
                    # Never stop the Herdr server; close only workspaces created by this stage.
                    _herdr(["workspace","close",str(workspace)],stage_deadline,4)
                except Exception:
                    failed_cleanup=True
            if failed_cleanup and results and results[-1].get("concurrency")==count:
                results[-1]["status"]="cleanup_incomplete"
                results[-1]["cleanup_incomplete"]=True
    return results
