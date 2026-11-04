"""Orchestrate bounded, non-destructive full benchmarks."""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import fcntl
import json
import shutil
import time
import uuid
from . import __version__
from .common import BenchmarkError, CommandTimeout, load_json, remaining, sha256_file, utc_now, run_command
from .inventory import inventory, verify_host, herdr_server_ready
from .fixtures import fixture_digest, create_base
from .real_tasks import digest as real_fixture_digest, create_real_base
from .hardware import cpu, memory, disk, verify_memory_build
from .agents import single, parallel
from .campaign import initialize, record
from .report import write_artifacts


@contextmanager
def exclusive(root: Path):
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (root/".lock").open("a+") as f:
        try:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise BenchmarkError("Another benchmark is running")
        yield


def run(config_file: Path, root: Path, *, provider: str | None = None,
        plan: str | None = None, region: str | None = None, price: float | None = None,
        currency: str | None = None, price_source: str | None = None,
        includes_mandatory_fees: bool | None = None) -> dict:
    config_file=config_file.absolute()
    config=load_json(config_file)  # benchmark.yaml is a deliberately JSON-compatible YAML document
    if config["maximum_seconds"]!=2700 or sum(config["phase_seconds"].values())!=2700:
        raise BenchmarkError("Full suite must use the published 2700 second budget")
    run_id=str(uuid.uuid4())
    started=time.monotonic()
    total_deadline=started+2700
    out=root/"results"/run_id
    scratch=root/"scratch"/run_id
    result={"schema_version":"1.0.0","suite_version":config["suite_version"],
            "run_id":run_id,"started_at":utc_now(),"finished_at":None,
            "elapsed_seconds":None,"status":"partial","machine":{},"price":{
                "monthly_amount":price,"currency":currency,
                "source_url":price_source or config.get("price",{}).get("source_url"),
                "checked_at":utc_now() if price_source else None,
                "includes_mandatory_fees":includes_mandatory_fees},
            "provenance":{"benchmark_version":__version__,"benchmark_commit":None,
                "suite_config_sha256":sha256_file(config_file),
                "fixture_sha256":real_fixture_digest() if config.get("agent_workload")=="real" else fixture_digest(),
                "codex_version":None,"herdr_version":None,
                "model":config["model"],"reasoning_effort":config["reasoning_effort"]},
            "cpu":{},"memory":{},"disk":{},"agents":{"single":{},"parallel":[]},
            "phases":{},"warnings":[],"errors":[]}
    scratch.mkdir(parents=True,exist_ok=False)
    state=None
    try:
        with exclusive(root):
            ownership_path=root/"ownership.json"
            benchmark_commit=load_json(ownership_path).get("benchmark_commit") if ownership_path.exists() else None
            state=initialize(root,config["suite_version"],sha256_file(config_file),benchmark_commit)
            result["campaign_id"]=state["campaign_id"]
            if ownership_path.exists():
                result["provenance"]["benchmark_commit"]=benchmark_commit
            section="preflight"
            elapsed=time.monotonic()
            phase_deadline=min(total_deadline,elapsed+config["phase_seconds"][section])
            machine=inventory(root)
            machine.update({"provider":provider,"plan":plan,"region":region})
            result["machine"]=machine
            tools=machine["tools"]
            result["provenance"]["codex_version"]=tools.get("codex")
            result["provenance"]["herdr_version"]=tools.get("herdr")
            errors=verify_host(machine,require_agents=True)
            memory_build,memory_errors=verify_memory_build(root)
            errors.extend(memory_errors)
            if memory_build is not None:
                result["provenance"]["memory_build"]=memory_build
            if not errors:
                for label,argv in (("Codex auth",["codex","login","status"]),
                                   ("Herdr server",["herdr","status","server","--json"])):
                    check=run_command(argv,remaining(phase_deadline,12))
                    if (not herdr_server_ready(check) if label=="Herdr server" else check["returncode"]!=0):
                        errors.append(label+" unavailable")
            if errors:
                result["errors"].extend(errors)
                result["status"]="invalid_environment"
                return result
            if machine["pressure"]["memory"].get("avg10",0)>20:
                result["warnings"].append("environment_contended")
            result["phases"][section]={"status":"complete","elapsed_seconds":round(time.monotonic()-elapsed,2)}
            base=create_real_base(scratch) if config.get("agent_workload")=="real" else create_base(scratch)
            all_ok=True
            for section,fn in (("cpu",cpu),("memory",memory),("disk",disk),
                               ("single",single),("parallel",parallel)):
                phase_start=time.monotonic()
                # Total runtime includes 3 minutes reserved for report and cleanup.
                phase_deadline=min(total_deadline-config["phase_seconds"]["report"],
                                   phase_start+config["phase_seconds"][section])
                try:
                    if section=="disk":
                        value=fn(config,phase_deadline,scratch/"disk",out/"raw")
                    elif section=="memory":
                        value=fn(config,phase_deadline,out/"raw",root/"bin"/"tsbench-stream")
                    elif section=="parallel":
                        value=fn(config,phase_deadline,base,scratch,out/"raw")
                    elif section=="single":
                        value=fn(config,phase_deadline,base,scratch)
                    else:
                        value=fn(config,phase_deadline,out/"raw")
                    if section in ("single","parallel"):
                        result["agents"][section]=value
                    else:
                        result[section]=value
                    # A complete measurement is not the same as a fast/successful host.
                    # Keep negative observed capacity results eligible for comparison.
                    phase_ok = (value.get("status")=="validated" if section=="memory" else
                                value.get("status") in ("passed","failed_tests","scope_violation")
                                if section=="single" else
                                bool(value) and all(s.get("status") in ("measured","failed_host") or
                                    (s.get("status")=="not_tested" and
                                     s.get("reason")=="resource_admission") for s in value)
                                if section=="parallel" else True)
                    if not phase_ok:
                        all_ok=False
                    result["phases"][section]={"status":"complete" if phase_ok else "inconclusive",
                                                "elapsed_seconds":round(time.monotonic()-phase_start,2)}
                except Exception as exc:
                    all_ok=False
                    result["phases"][section]={"status":"failed","reason":type(exc).__name__,
                                                "elapsed_seconds":round(time.monotonic()-phase_start,2)}
                    result["errors"].append(section+": "+type(exc).__name__)
                if remaining(total_deadline,1)==0: break
            single_ok=result["agents"].get("single",{}).get("status") in (
                "passed","failed_tests","scope_violation")
            stages=result["agents"].get("parallel",[])
            valid_stage=any(s.get("status") in ("measured","failed_host") for s in stages)
            expected=[int(s["count"]) for s in config["parallel"]["stages"]]
            stages_complete=([s.get("concurrency") for s in stages]==expected and
                             all(s.get("status") in ("measured","failed_host") or
                                 (s.get("status")=="not_tested" and s.get("reason")=="resource_admission")
                                 for s in stages))
            result["status"]="complete" if all_ok and single_ok and valid_stage and stages_complete else "partial"
            return result
    except (KeyboardInterrupt,Exception) as exc:
        result["errors"].append(type(exc).__name__)
        if isinstance(exc,CommandTimeout): result["status"]="timed_out"
        return result
    finally:
        # Report creation and cleanup are part of the strict global budget.
        try:
            shutil.rmtree(scratch)
        except Exception:
            result["warnings"].append("cleanup_incomplete")
            result["status"]="partial"
        result["finished_at"]=utc_now()
        result["elapsed_seconds"]=round(time.monotonic()-started,3)
        if result["elapsed_seconds"]>=2700:
            result["status"]="timed_out"
            result["warnings"].append("global_deadline_exceeded")
        write_artifacts(out,result,config_file)
        if state is not None:
            record(root,result)
