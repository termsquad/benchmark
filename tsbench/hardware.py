"""Pinned sysbench and fio measurements. Never open raw devices."""
from __future__ import annotations
from pathlib import Path
import re
import shutil
import time
from .common import BenchmarkError, run_command, require_success, remaining
from .inventory import meminfo


def _mean(numbers: list[float]) -> float:
    return round(sum(numbers)/len(numbers), 3) if numbers else 0.0


def cpu(config: dict, deadline: float) -> dict:
    p = config["cpu"]
    results = {}
    for name, threads in (("single", 1), ("multi", max(1, __import__("os").cpu_count() or 1))):
        samples = []
        for _ in range(p["samples"]):
            cmd = ["sysbench","cpu","--cpu-max-prime="+str(p["max_prime"]),
                   "--threads="+str(threads),"--time="+str(p["sample_seconds"]),"run"]
            raw = require_success(run_command(cmd, remaining(deadline,p["sample_seconds"]+12)), "sysbench cpu")
            match = re.search(r"events per second:\s*([\d.]+)",raw)
            if not match: raise BenchmarkError("sysbench cpu throughput missing")
            samples.append(float(match.group(1)))
        results[name+"_events_per_sec"] = _mean(samples)
        results[name+"_samples"] = samples
        results[name+"_threads"] = threads
    return results


def memory(config: dict, deadline: float) -> dict:
    p = config["memory"]
    results = {}
    for mode in ("read", "write"):
        samples = []
        for _ in range(p["samples"]):
            cmd = ["sysbench","memory","--memory-oper="+mode,
                   "--memory-block-size="+p["block_size"],"--memory-total-size="+p["total_size"],
                   "--threads=1","--time="+str(p["sample_seconds"]),"run"]
            raw = require_success(run_command(cmd, remaining(deadline,p["sample_seconds"]+12)), "sysbench memory")
            match = re.search(r"\(([\d.]+) MiB/sec\)", raw)
            if not match: raise BenchmarkError("sysbench memory throughput missing")
            samples.append(float(match.group(1)))
        results[mode+"_mib_per_sec"] = _mean(samples)
        results[mode+"_samples"] = samples
    return results


def disk(config: dict, deadline: float, scratch: Path) -> dict:
    p = config["disk"]
    scratch.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(scratch)
    size_mib = int(p["file_size_mib"])
    if usage.free < (size_mib + int(p["reserve_mib"])) * 1024**2:
        raise BenchmarkError("skipped_insufficient_space")
    target = scratch / "fio-benchmark.bin"
    if target.exists() or target.is_symlink():
        raise BenchmarkError("Benchmark disk target already exists")
    target.touch(mode=0o600, exist_ok=False)
    results = {}
    try:
        # Write the entire regular file to prevent empty/sparse-file read results.
        prepare = ["fio","--name=prepare","--filename="+str(target),"--size="+str(size_mib)+"M",
                   "--rw=write","--bs=1M","--ioengine=psync","--direct=1",
                   "--output-format=json"]
        require_success(run_command(prepare, remaining(deadline,180)), "fio prefill")
        jobs = [("sequential_read","read","1M",4),("sequential_write","write","1M",4),
                ("random_read_qd1","randread","4k",1),("random_write_qd1","randwrite","4k",1),
                ("random_read_qd16","randread","4k",16),("random_write_qd16","randwrite","4k",16)]
        for name, rw, bs, qd in jobs:
            cmd = ["fio","--name="+name,"--filename="+str(target),"--size="+str(size_mib)+"M",
                   "--rw="+rw,"--bs="+bs,"--iodepth="+str(qd),"--numjobs=1","--direct=1",
                   "--ioengine="+p["ioengine"],"--time_based=1",
                   "--runtime="+str(p["runtime_seconds"]),"--ramp_time="+str(p["ramp_seconds"]),
                   "--output-format=json","--group_reporting=1"]
            raw = require_success(run_command(cmd,remaining(deadline,p["runtime_seconds"]+p["ramp_seconds"]+20)), "fio "+name)
            import json
            parsed = json.loads(raw)
            job = parsed["jobs"][0]["read" if "read" in rw else "write"]
            clat = job.get("clat_ns") or {}
            pct = clat.get("percentile",{})
            results[name] = {"mib_per_sec":round(job.get("bw_bytes",0)/1048576,3),
                "iops":round(float(job.get("iops",0)),3),
                "latency_p50_ms":round(float(pct.get("50.000000",0))/1e6,4),
                "latency_p95_ms":round(float(pct.get("95.000000",0))/1e6,4),
                "latency_p99_ms":round(float(pct.get("99.000000",0))/1e6,4),
                "block_size":bs,"iodepth":qd}
        return results
    finally:
        target.unlink(missing_ok=True)
