"""Conservative, ownership-scoped uninstall with export receipt checks."""
from __future__ import annotations
import hashlib
import json
import fcntl
import os
from pathlib import Path
import shutil
import tarfile
from .common import BenchmarkError, atomic_json, load_json, owned_path, sha256_file


def export_campaign(root: Path, destination: Path) -> dict:
    state = load_json(root/"campaign.json")
    result_root = root/"results"
    manifest_paths = [result_root/run/"manifest.json" for run in state["all_runs"]]
    for manifest in manifest_paths:
        data = load_json(manifest)
        for name,digest in data["files"].items():
            if sha256_file(manifest.parent/name)!=digest:
                raise BenchmarkError("Export blocked: corrupted result evidence")
    destination = destination.expanduser().absolute()
    if destination.is_relative_to(root.resolve()):
        owned_path(destination,root)
        if not destination.is_relative_to((root/"exports").absolute()):
            raise BenchmarkError("Managed export destination must be under the owned exports folder")
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        raise BenchmarkError("Destination already exists")
    with tarfile.open(destination,"w:gz") as tar:
        tar.add(root/"campaign.json",arcname="campaign.json")
        for run in state["all_runs"]:
            directory=owned_path(result_root/run,root)
            tar.add(directory,arcname="results/"+run,recursive=True)
    digest=sha256_file(destination)
    state["export_receipt"]={"sha256":digest,"campaign_id":state["campaign_id"],
                            "archive":str(destination)}
    atomic_json(root/"campaign.json",state)
    return {"sha256":digest,"file":str(destination),"campaign_id":state["campaign_id"]}


def uninstall(root: Path, purge: bool = False, campaign: str | None = None,
              verified_export: str | None = None) -> dict:
    root = root.expanduser().absolute()
    expected = (Path.home()/".local"/"share"/"tsbench").absolute()
    if root!=expected or root.is_symlink():
        raise BenchmarkError("Uninstall refuses non-canonical state root")
    if not root.exists():
        return {"status":"already_uninstalled","remaining_results":False}
    lock=root/".lock"
    if lock.is_symlink():
        raise BenchmarkError("Refusing symlinked benchmark lock")
    with lock.open("a+") as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise BenchmarkError("Refusing uninstall while a benchmark is active")
        return _uninstall_locked(root,purge,campaign,verified_export)


def _uninstall_locked(root: Path, purge: bool, campaign: str | None,
                      verified_export: str | None) -> dict:
    root = root.expanduser().absolute()
    expected = (Path.home()/".local"/"share"/"tsbench").absolute()
    if root!=expected or root.is_symlink():
        raise BenchmarkError("Uninstall refuses non-canonical state root")
    state_path = root/"campaign.json"
    if not state_path.exists():
        return {"status":"already_uninstalled","remaining_results":False}
    state=load_json(state_path)
    result_dir=owned_path(root/"results",root)
    if purge:
        if campaign!=state["campaign_id"] or len(state["eligible_runs"])<3:
            raise BenchmarkError("Purge requires the matching campaign and three eligible runs")
        receipt=state.get("export_receipt",{})
        if not verified_export or verified_export!=receipt.get("sha256"):
            raise BenchmarkError("Purge requires a matching externally verified SHA256 receipt")
    # Only remove manifest-owned state under our fixed private root. Never touch global
    # Codex, Herdr, Python, Node, sysbench, fio, auth stores or third-party projects.
    for name in ("scratch","tmp","venv") + (("exports",) if purge else ()):
        path=owned_path(root/name,root)
        if path.exists():
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()
    wrapper=Path.home()/".local"/"bin"/"tsbench"
    if wrapper.is_symlink() and wrapper.resolve().is_relative_to(root):
        wrapper.unlink()
    if purge:
        owned_path(result_dir,root)
        if result_dir.exists(): shutil.rmtree(result_dir)
        for file in ("campaign.json","ownership.json","benchmark.yaml",".lock"):
            path=owned_path(root/file,root)
            path.unlink(missing_ok=True)
        if not any(root.iterdir()): root.rmdir()
        return {"status":"purged","remaining_results":False}
    return {"status":"conservative_uninstall","remaining_results":result_dir.exists(),
            "message":"Results retained until verified export and three eligible runs"}
