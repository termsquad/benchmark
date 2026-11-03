"""Compare like-for-like verified runs, rejecting incompatible cohorts."""
from __future__ import annotations
from collections import defaultdict
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
    return (item["suite_version"],p["suite_config_sha256"],p["fixture_sha256"],
            m["architecture"],m["os_version"],p["codex_version"],p["herdr_version"],
            p["model"],p["reasoning_effort"])


def compare(paths: list[Path]) -> dict:
    runs = [verified(p) for p in paths]
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
                 "run_count":len(group),"publication_eligible":len(group)>=3,
                 "cpu_single_events_per_sec_median":med("cpu","single_events_per_sec"),
                 "cpu_multi_events_per_sec_median":med("cpu","multi_events_per_sec"),
                 "memory_read_mib_per_sec_median":med("memory","read_mib_per_sec"),
                 "memory_write_mib_per_sec_median":med("memory","write_mib_per_sec"),
                 "single_agent_elapsed_seconds_median":None}
        success = [r["agents"]["single"]["elapsed_seconds"] for r in group
                   if r.get("agents",{}).get("single",{}).get("status")=="passed"]
        entry["single_agent_elapsed_seconds_median"] = round(median(success),3) if success else None
        output.append(entry)
    return {"cohort":list(signature(runs[0])),"providers":output,
            "warning":"At least 3 valid time-separated runs per VM are required for publication."}
