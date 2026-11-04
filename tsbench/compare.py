"""Compare like-for-like verified runs, rejecting incompatible cohorts."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from .common import BenchmarkError, load_json, sha256_file


def verified(path: Path) -> dict:
    result = load_json(path)
    manifest = load_json(path.parent/"manifest.json")
    if sha256_file(path)!=manifest["files"]["results.json"]:
        raise BenchmarkError("Results hash does not match manifest: "+str(path))
    if sha256_file(path.parent/"report.md")!=manifest["files"]["report.md"]:
        raise BenchmarkError("Report hash does not match manifest: "+str(path))
    return result


def signature(item: dict) -> tuple:
    m,p = item["machine"], item["provenance"]
    return (item["suite_version"],p.get("benchmark_commit"),p["suite_config_sha256"],p["fixture_sha256"],
            m["architecture"],m["os_version"],p["codex_version"],p["herdr_version"],
            p["model"],p["reasoning_effort"],m.get("tools",{}).get("node"),
            m.get("tools",{}).get("fio"),m.get("tools",{}).get("sysbench"),
            m.get("tools",{}).get("gcc"),p.get("memory_build",{}).get("binary_sha256"))


def time_separated(group: list[dict]) -> bool:
    try:
        times = [datetime.fromisoformat(r["finished_at"]) for r in group]
        if any(t.tzinfo is None or t.utcoffset() is None for t in times):
            return False
        times.sort()
        return all((b-a).total_seconds() >= 3600 for a,b in zip(times,times[1:]))
    except (KeyError, TypeError, ValueError):
        return False


def compare(paths: list[Path]) -> dict:
    runs = [verified(p) for p in paths]
    ids = [r.get("run_id") for r in runs]
    if any(not isinstance(run_id,str) or not run_id for run_id in ids) or len(set(ids)) != len(ids):
        raise BenchmarkError("Comparison requires distinct, nonempty run IDs")
    if len({signature(r) for r in runs})!=1:
        raise BenchmarkError("Incompatible suite/OS/model/toolchain cohorts, cannot produce controlled comparison")
    groups = defaultdict(list)
    for r in runs:
        if r["status"]!="complete":
            continue
        m = r["machine"]
        groups[(m.get("provider"),m.get("plan"),m.get("region"))].append(r)
    output = []
    for key,group in sorted(groups.items(),key=lambda x:str(x[0])):
        def med(*keys):
            values=[]
            for item in group:
                value=item
                for sub in keys:
                    value=value.get(sub) if isinstance(value,dict) else None
                if isinstance(value,(int,float)):
                    values.append(value)
            return round(median(values),3) if values else None
        entry = {"provider":key[0],"plan":key[1],"region":key[2],
                 "run_count":len(group),"publication_eligible":len(group)>=3 and time_separated(group),
                 "cpu_single_events_per_sec_median":med("cpu","single_events_per_sec"),
                 "cpu_multi_events_per_sec_median":med("cpu","multi_events_per_sec"),
                 "memory_single_triad_mib_per_sec_median":None,
                 "memory_multi_triad_mib_per_sec_median":None,
                 "single_agent_elapsed_seconds_median":None}
        success = [r["agents"]["single"]["elapsed_seconds"] for r in group
                   if r.get("agents",{}).get("single",{}).get("status")=="passed"]
        entry["single_agent_elapsed_seconds_median"] = round(median(success),3) if success else None
        validated_memory=[r for r in group if r.get("memory",{}).get("status")=="validated"]
        if len(validated_memory)==len(group):
            entry["memory_single_triad_mib_per_sec_median"]=med("memory","single","triad_mib_per_sec")
            entry["memory_multi_triad_mib_per_sec_median"]=med("memory","multi","triad_mib_per_sec")
        entry["disk"] = {key: med("disk",key,"mib_per_sec") for key in
                         ("sequential_read","sequential_write","random_read_qd1","random_write_qd1",
                          "random_read_qd16","random_write_qd16")}
        entry["mixed_disk_iops"]={
            mode: med("disk","mixed_random_70r30w_qd16",mode,"iops") for mode in ("read","write")}
        entry["parallel"]={}
        for count in (4,8,16):
            values = [stage["throughput_per_minute"]
                      for run in group for stage in run.get("agents",{}).get("parallel",[])
                      if stage.get("concurrency")==count
                      and stage.get("measurement_valid") is True
                      and stage.get("status") in ("measured","failed_host")
                      and isinstance(stage.get("throughput_per_minute"),(float,int))]
            # Publish stage-specific medians only with three eligible observations,
            # not merely a complete campaign with one observed stage.
            entry.setdefault("parallel_measured_runs",{})[str(count)]=len(values)
            entry["parallel"][str(count)] = round(median(values),4) if len(values)>=3 else None
        prices = [(r.get("price",{}) or {}) for r in group]
        known = [p for p in prices if isinstance(p.get("monthly_amount"),(int,float))
                 and p["monthly_amount"]>0 and p.get("currency") and p.get("source_url")
                 and p.get("includes_mandatory_fees") is True]
        if len(known)==len(group) and len({p["currency"] for p in known})==1:
            amount=round(median(p["monthly_amount"] for p in known),2)
            entry["price"]={"amount":amount,"currency":known[0]["currency"],"basis":"recurring monthly"}
            entry["value_at_4_agents"]=round(entry["parallel"]["4"]/amount,6) if entry["parallel"]["4"] else None
        else:
            entry["price"] = None
            entry["value_at_4_agents"] = None
        output.append(entry)
    return {"cohort":list(signature(runs[0])),"providers":output,
            "warning":"At least 3 valid time-separated runs per VM are required for publication."}
