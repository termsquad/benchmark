"""Small local state file for three-run campaigns, no daemon or database."""
from __future__ import annotations
import uuid
from pathlib import Path
from .common import BenchmarkError, atomic_json, load_json, utc_now


def state_dir() -> Path:
    return Path.home()/".local"/"share"/"tsbench"


def state_file(root: Path) -> Path:
    return root/"campaign.json"


def initialize(root: Path, suite_version: str, config_hash: str, benchmark_commit: str | None = None) -> dict:
    path = state_file(root)
    if path.exists():
        state = load_json(path)
        if state["config_sha256"] != config_hash or state["suite_version"] != suite_version:
            raise BenchmarkError("Existing campaign has another suite/config; export and uninstall before changing it")
        previous = state.get("benchmark_commit")
        if previous is None and state.get("eligible_runs"):
            prior_result = load_json(root/"results"/state["eligible_runs"][0]/"results.json")
            previous = prior_result.get("provenance",{}).get("benchmark_commit")
            if not previous:
                raise BenchmarkError("Cannot identify prior eligible run's benchmark commit")
        if benchmark_commit and previous and previous != benchmark_commit:
            state.setdefault("prior_cohorts",[]).append({"benchmark_commit":previous,
                "eligible_runs":state.get("eligible_runs",[]),
                "eligible_timestamps":state.get("eligible_timestamps",[])})
            state["eligible_runs"] = []
            state["eligible_timestamps"] = []
        if benchmark_commit and state.get("benchmark_commit") != benchmark_commit:
            state["benchmark_commit"] = benchmark_commit
            state.pop("export_receipt",None)
            atomic_json(path,state)
        return state
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    state = {"campaign_id":str(uuid.uuid4()),"suite_version":suite_version,
             "config_sha256":config_hash,"created_at":utc_now(),"eligible_runs":[],
             "all_runs":[],"benchmark_commit":benchmark_commit}
    atomic_json(path,state)
    return state


def record(root: Path, result: dict) -> dict:
    path = state_file(root)
    state = load_json(path)
    if result["run_id"] not in state["all_runs"]:
        state["all_runs"].append(result["run_id"])
        state.pop("export_receipt",None)
    commit_ok = (not state.get("benchmark_commit") or
                 result.get("provenance",{}).get("benchmark_commit")==state["benchmark_commit"])
    if result["status"]=="complete" and not commit_ok:
        state.setdefault("warnings",[]).append("run_revision_mismatch:"+result["run_id"])
    if result["status"]=="complete" and commit_ok and result["run_id"] not in state["eligible_runs"]:
        # Avoid three back-to-back samples being treated as time-separated evidence.
        from datetime import datetime
        eligible = state.get("eligible_timestamps",[])
        now = datetime.fromisoformat(result["finished_at"])
        if all(abs((now-datetime.fromisoformat(x)).total_seconds())>=3600 for x in eligible):
            state["eligible_runs"].append(result["run_id"])
            state.setdefault("eligible_timestamps",[]).append(result["finished_at"])
        else:
            state.setdefault("warnings",[]).append("run_not_time_separated:"+result["run_id"])
    atomic_json(path,state)
    return state
