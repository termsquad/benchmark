"""Bounded subprocesses, atomic files and safe owned paths."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


class BenchmarkError(RuntimeError):
    pass


class CommandTimeout(BenchmarkError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        result = json.load(f)
    if not isinstance(result, dict):
        raise BenchmarkError("Expected an object in " + str(path))
    return result


def owned_path(path: Path, root: Path, allow_root: bool = False) -> Path:
    root = root.expanduser().absolute()
    path = path.expanduser().absolute()
    if path == Path("/") or root == Path("/") or (not allow_root and path == root):
        raise BenchmarkError("Refusing unsafe root path")
    if not path.is_relative_to(root):
        raise BenchmarkError("Path escapes benchmark root")
    current = path
    while current != root.parent:
        if current.is_symlink():
            raise BenchmarkError("Refusing symlink in owned path: " + str(current))
        current = current.parent
    return path


def run_command(args: list[str], timeout: float, cwd: Path | None = None, max_output: int = 200000) -> dict:
    if timeout <= 0:
        raise CommandTimeout("No time left for subprocess")
    start = time.monotonic()
    proc = subprocess.Popen(
        args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True, text=True, encoding="utf-8", errors="replace"
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
        raise CommandTimeout("Command exceeded its time budget: " + args[0])
    return {"returncode":proc.returncode, "stdout":out[:max_output], "stderr":err[:max_output],
            "elapsed_seconds":round(time.monotonic()-start,3)}


def require_success(response: dict, command: str) -> str:
    if response["returncode"] != 0:
        raise BenchmarkError(command + " failed (exit " + str(response["returncode"]) + ")")
    return response["stdout"]


def remaining(deadline: float, cap: float) -> float:
    return max(0.0, min(float(cap), deadline - time.monotonic()))


def utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
