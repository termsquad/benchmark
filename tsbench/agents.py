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


def single(config: dict, deadline: float, base: Path, scratch: Path) -> dict:
    worktree = create_worktree(base,scratch,"single")
    telemetry = Telemetry().start()
    start = time.monotonic()
    cmd = ["codex","exec","--model",config["model"],"-c",
           'model_reasoning_effort="'+config["reasoning_effort"]+'"',
           "--json","--full-auto",task_prompt(16)]
    try:
        response = run_command(cmd,remaining(deadline,450),cwd=worktree,max_output=180000)
        verdict = validate_task(16,worktree)
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
        raise BenchmarkError("Herdr command failed: "+" ".join(args[:2])+": "+classify(response["stderr"]))
    try:
        return json.loads(response["stdout"])
    except json.JSONDecodeError:
        raise BenchmarkError("Unexpected Herdr JSON")


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
        _herdr(["agent","prompt",name,task_prompt(index),"--wait","--timeout",str(wait_ms)],deadline,wait_ms/1000+2)
        validated = validate_task(index,worktree)
        return {"task_id":index,"status":"passed" if validated["passed"] else "failed_tests",
                "elapsed_seconds":round(time.monotonic()-started,3)}
    except CommandTimeout:
        return {"task_id":index,"status":"timed_out","elapsed_seconds":round(time.monotonic()-started,3)}
    except Exception as exc:
        category = classify(str(exc))
        return {"task_id":index,"status":category,"elapsed_seconds":round(time.monotonic()-started,3)}


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
                futures = [executor.submit(_worker,index,config,worker_deadline,base,scratch,created,prefix+str(count))
                           for index in range(count)]
                for f in as_completed(futures):
                    tasks.append(f.result())
            elapsed = time.monotonic()-stage_start
            passed = sum(x["status"]=="passed" for x in tasks)
            constrained = any(x["status"] in ("rate_limited","authentication_error") for x in tasks)
            metrics = telemetry.stop()
            status = ("externally_constrained" if constrained else
                      "failed_host" if (metrics["oom_kills"] or 0)>0 else
                      "validated" if passed/count>=.75 else "inconclusive")
            results.append({"concurrency":count,"status":status,"passed":passed,
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
