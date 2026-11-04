"""Local, deterministic human-readable reports with no LLM summary claims."""
from __future__ import annotations
from pathlib import Path
from .common import atomic_json, sha256_file


def _metric(obj: dict | None, key: str, unit: str = "") -> str:
    value = (obj or {}).get(key)
    return (str(value)+(" "+unit if unit else "")) if value is not None else "not measured"


def render(result: dict) -> str:
    m = result["machine"]
    cpu, memory, disk, agents = (result.get(x,{}) for x in ("cpu","memory","disk","agents"))
    rows = [
        "# TermSquad Benchmark",
        "",
        "Run: "+result["run_id"],
        "Status: **"+result["status"]+"**",
        "VM: "+str(m.get("provider") or "unspecified")+" / "+str(m.get("plan") or "unspecified"),
        "OS: "+str(m.get("os_version"))+"; "+str(m.get("vcpu"))+" vCPU",
        "Elapsed: "+_metric(result,"elapsed_seconds","s"),"",
        "## Hardware",
        "",
        "| Metric | Measured |","| --- | ---: |",
        "| CPU single | "+_metric(cpu,"single_events_per_sec","events/s")+" |",
        "| CPU multi | "+_metric(cpu,"multi_events_per_sec","events/s")+" |",
        "| RAM read | "+_metric(memory,"read_mib_per_sec","MiB/s")+" |",
        "| RAM write | "+_metric(memory,"write_mib_per_sec","MiB/s")+" |"]
    for key,value in disk.items():
        if isinstance(value,dict):
            rows.append("| Disk "+key+" | "+_metric(value,"mib_per_sec","MiB/s")+"; "+
                        _metric(value,"iops","IOPS")+"; p95 "+_metric(value,"latency_p95_ms","ms")+" |")
    rows += ["","## Agent workloads","",
             "Model: "+result["provenance"]["model"]+" / "+result["provenance"]["reasoning_effort"],
             "Single task: "+str(agents.get("single",{}).get("status","not_tested"))]
    for stage in agents.get("parallel",[]):
        rows.append(str(stage["concurrency"])+" agents: "+stage["status"]+
                    ", passed "+str(stage.get("passed","n/a"))+
                    ", completed/min "+str(stage.get("throughput_per_minute","n/a")))
    rows += ["","## Validity and limitations","",
             "Agent wall times include remote model latency. A rate-limited result is not evidence of poor VM performance.",
             "A validated concurrency stage is not a theoretical maximum supported by the VM."]
    if memory.get("status")=="limited":
        rows.append("Memory throughput is synthetic and limited: its working set may fit CPU cache.")
    for warning in result.get("warnings",[]):
        rows.append("- Warning: "+str(warning))
    for error in result.get("errors",[]):
        rows.append("- Error: "+str(error))
    rows += ["","Generated from measured JSON. No inferred values.",""]
    return "\n".join(rows)


def write_artifacts(folder: Path, result: dict, config_file: Path) -> None:
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'raw').mkdir(exist_ok=True)
    atomic_json(folder/"results.json",result)
    (folder/"report.md").write_text(render(result),encoding="utf-8")
    files = {name:sha256_file(folder/name) for name in ("results.json","report.md")}
    for path in sorted((folder/"raw").rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not permitted in raw evidence")
        if path.is_file():
            files[path.relative_to(folder).as_posix()] = sha256_file(path)
    manifest = {"run_id":result["run_id"],"suite_version":result["suite_version"],
                "files":files,
                "config_sha256":sha256_file(config_file)}
    atomic_json(folder/"manifest.json",manifest)
