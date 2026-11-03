"""Linux inventory, including cgroup constraints and host pressure."""
from __future__ import annotations
import os
from pathlib import Path
import platform
import shutil
import subprocess
from .common import BenchmarkError


def os_release() -> dict:
    result = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                result[k] = v.strip('"')
    except OSError:
        pass
    return result


def meminfo() -> dict:
    result = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            result[k] = int(v.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    return result


def psi(kind: str) -> dict:
    try:
        line = Path("/proc/pressure/" + kind).read_text().splitlines()[0]
        return {k:float(v) for k,v in (x.split("=") for x in line.split()[1:])}
    except (OSError, IndexError, ValueError):
        return {}


def oom_kills() -> int | None:
    try:
        for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines():
            if line.startswith("oom_kill "):
                return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def version(binary: str) -> str | None:
    if not shutil.which(binary):
        return None
    try:
        p = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=5)
        return (p.stdout or p.stderr).strip().splitlines()[0][:160] if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return None


def inventory(workspace: Path) -> dict:
    release = os_release()
    usage = shutil.disk_usage(workspace)
    cpu = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":",1)[1].strip()
                break
    except OSError:
        pass
    return {"os_version":release.get("VERSION_ID"),"os_name":release.get("NAME"),
            "kernel":platform.release(),"architecture":platform.machine(),
            "vcpu":os.cpu_count(),"cpu_model":cpu,
            "ram_bytes":meminfo().get("MemTotal"),"memory_available_bytes":meminfo().get("MemAvailable"),
            "swap_bytes":meminfo().get("SwapTotal"),"disk_bytes":usage.total,
            "disk_free_bytes":usage.free,"filesystem":str(workspace.resolve()),
            "pressure":{"cpu":psi("cpu"),"memory":psi("memory"),"io":psi("io")},
            "tools":{name:version(name) for name in ("python3","sysbench","fio","git","node","codex","herdr")}}


def verify_host(machine: dict, require_agents: bool) -> list[str]:
    errors = []
    if machine["os_name"] != "Ubuntu" or machine["os_version"] not in ("24.04","26.04"):
        errors.append("Only Ubuntu 24.04 and 26.04 are supported")
    if machine["architecture"] not in ("x86_64","amd64"):
        errors.append("Only x86_64 is supported")
    required = ("sysbench","fio","git","node") + (("codex","herdr") if require_agents else ())
    for name in required:
        if not machine["tools"].get(name):
            errors.append("Missing or unavailable: " + name)
    return errors
