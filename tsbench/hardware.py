"""Pinned sysbench and fio measurements. Never open raw devices."""
from __future__ import annotations
from pathlib import Path
import re
import json
import shutil
import time
from .common import BenchmarkError, run_command, require_success, remaining
from .inventory import meminfo


def _mean(numbers: list[float]) -> float:
    return round(sum(numbers)/len(numbers), 3) if numbers else 0.0


def _save_raw(folder: Path | None, name: str, text: str) -> None:
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder/name).write_text(text,encoding="utf-8")


def _sanitize_fio(value, target: Path):
    if isinstance(value,dict):
        return {k:_sanitize_fio(v,target) for k,v in value.items() if k!="hostname"}
    if isinstance(value,list):
        return [_sanitize_fio(v,target) for v in value]
    if isinstance(value,str):
        return value.replace(str(target),"<benchmark-file>")
    return value


def cpu(config: dict, deadline: float, raw_dir: Path | None = None) -> dict:
    p = config["cpu"]
    results = {}
    for name, threads in (("single", 1), ("multi", max(1, len(__import__("os").sched_getaffinity(0))))):
        samples = []
        for sample in range(p["samples"]):
            cmd = ["sysbench","cpu","--cpu-max-prime="+str(p["max_prime"]),
                   "--threads="+str(threads),"--time="+str(p["sample_seconds"]),"run"]
            raw = require_success(run_command(cmd, remaining(deadline,p["sample_seconds"]+12)), "sysbench cpu")
            _save_raw(raw_dir,"cpu-"+name+"-"+str(sample+1)+".txt",raw)
            match = re.search(r"events per second:\s*([\d.]+)",raw)
            if not match: raise BenchmarkError("sysbench cpu throughput missing")
            samples.append(float(match.group(1)))
        results[name+"_events_per_sec"] = _mean(samples)
        results[name+"_samples"] = samples
        results[name+"_threads"] = threads
    return results


MEMORY_BUILD_FLAGS = ("-O3", "-std=c11", "-fopenmp", "-march=x86-64")


def build_memory_binary(destination: Path) -> dict:
    """Build only from the audited package source, into a private owned directory."""
    source = Path(__file__).with_name("stream.c")
    if not source.is_file():
        raise BenchmarkError("Frozen memory workload source missing")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists() or destination.is_symlink():
        raise BenchmarkError("Refusing to replace an existing memory workload binary")
    response = run_command(["gcc", *MEMORY_BUILD_FLAGS, str(source), "-lm", "-o", str(destination)], 45)
    require_success(response, "gcc stream-style memory binary")
    destination.chmod(0o700)
    from .common import sha256_file
    return {"source_sha256":sha256_file(source),"binary_sha256":sha256_file(destination),
            "flags":list(MEMORY_BUILD_FLAGS)}


def _last_level_cache_bytes() -> int | None:
    root = Path("/sys/devices/system/cpu/cpu0/cache")
    sizes = []
    for index in root.glob("index*"):
        try:
            level = int((index/"level").read_text().strip())
            label = (index/"size").read_text().strip().upper()
            multiplier = 1024**{"K":1,"M":2,"G":3}[label[-1]]
            sizes.append((level,int(label[:-1])*multiplier))
        except (OSError,ValueError,IndexError,KeyError):
            continue
    if not sizes:
        return None
    highest=max(level for level,_ in sizes)
    return max(size for level,size in sizes if level==highest)


def memory(config: dict, deadline: float, raw_dir: Path | None = None,
           executable: Path | None = None) -> dict:
    p = config["memory"]
    if p.get("backend")!="stream_style_v1":
        raise BenchmarkError("Expected memory backend stream_style_v1")
    if executable is None or not executable.is_file():
        raise BenchmarkError("Run tsbench setup to compile the memory workload first")
    working_mib = int(p["working_set_mib"])
    available = meminfo().get("MemAvailable",0)
    llc = _last_level_cache_bytes()
    results = {"backend":"stream_style_v1","working_set_mib":working_mib,
               "last_level_cache_bytes":llc,"status":"validated"}
    if available < (working_mib+512)*1048576:
        return {**results,"status":"limited","reason":"insufficient_available_ram"}
    if llc is None or working_mib*1048576 < llc*int(p["minimum_cache_multiple"]):
        return {**results,"status":"limited","reason":"cannot_prove_working_set_exceeds_cache"}
    import os
    threads = max(1,len(os.sched_getaffinity(0)))
    for mode,count in (("single",1),("multi",threads)):
        samples=[]
        for i in range(int(p["samples"])):
            command=[str(executable),str(count),str(working_mib),str(p["sample_seconds"])]
            raw=require_success(run_command(command,remaining(deadline,p["sample_seconds"]+25)),"STREAM-style RAM "+mode)
            parsed=json.loads(raw)
            if (parsed.get("backend")!="stream_style_v1" or
                parsed.get("threads")!=count or parsed.get("working_set_mib")!=working_mib or
                parsed.get("passes",0)<5 or not parsed.get("checksum",0)>0):
                raise BenchmarkError("Invalid memory backend provenance or checksum")
            for key in ("copy","scale","add","triad"):
                value=parsed.get(key+"_mib_per_sec")
                if not isinstance(value,(int,float)) or not 0<value<10**7:
                    raise BenchmarkError("Invalid memory bandwidth: "+key)
            _save_raw(raw_dir,"memory-"+mode+"-"+str(i+1)+".json",json.dumps(parsed,indent=2)+"\\n")
            samples.append(parsed)
        results[mode]={"threads":count,"samples":len(samples),
                       **{key+"_mib_per_sec":_mean([v[key+"_mib_per_sec"] for v in samples])
                          for key in ("copy","scale","add","triad")}}
    return results

def disk(config: dict, deadline: float, scratch: Path, raw_dir: Path | None = None) -> dict:
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
        prefill = require_success(run_command(prepare, remaining(deadline,180)), "fio prefill")
        _save_raw(raw_dir,"fio-prepare.json",json.dumps(_sanitize_fio(json.loads(prefill),target),indent=2)+"\n")
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
            parsed = json.loads(raw)
            _save_raw(raw_dir,"fio-"+name+".json",json.dumps(_sanitize_fio(parsed,target),indent=2)+"\n")
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
