"""Hardware evidence remains available and covered by the result manifest."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tsbench.hardware import cpu, memory, _sanitize_fio
from tsbench.report import write_artifacts
from tsbench.common import sha256_file


class RawEvidenceTests(unittest.TestCase):
    def test_small_memory_working_set_is_disclosed_as_limited(self):
        config = {"memory": {"backend": "stream_style_v1", "working_set_mib": 64,
                             "minimum_cache_multiple": 4, "samples": 1, "sample_seconds": 1}}
        with tempfile.TemporaryDirectory() as tmp:
            executable=Path(tmp)/"stream"
            executable.touch()
            with patch("tsbench.hardware.meminfo", return_value={"MemAvailable":2*1024**3}), \
                 patch("tsbench.hardware._last_level_cache_bytes",return_value=64*1024**2):
                result=memory(config,time.monotonic()+60,executable=executable)
        self.assertEqual(result["status"], "limited")
        self.assertIn("cache", result["reason"])

    def test_fio_evidence_redacts_host_and_test_file_path(self):
        target = Path('/home/admin/private/fio-benchmark.bin')
        raw = {"hostname": "private-host", "jobs": [{"job options": {"filename": str(target)},
                                                        "read": {"iops": 123}}]}
        sanitized = json.dumps(_sanitize_fio(raw, target))
        self.assertNotIn("private-host", sanitized)
        self.assertNotIn(str(target), sanitized)
        self.assertIn("123", sanitized)

    def test_cpu_measurements_are_preserved_in_manifest(self):
        output = "sysbench cpu\nevents per second: 123.45\n"
        config = {"cpu": {"samples": 2, "max_prime": 20000, "sample_seconds": 1}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "result" / "raw"
            raw.mkdir(parents=True)
            with patch("tsbench.hardware.run_command", return_value={"returncode": 0, "stdout": output}), \
                 patch("os.sched_getaffinity", return_value={0, 1}, create=True):
                result = cpu(config, time.monotonic()+60, raw)
            self.assertEqual(result["single_events_per_sec"], 123.45)
            self.assertEqual((raw/"cpu-single-1.txt").read_text(), output)
            cfg = root / "benchmark.yaml"
            cfg.write_text("{}")
            payload = {"run_id": "r1", "suite_version": "1", "status": "partial", "machine": {},
                       "provenance": {"model": "x", "reasoning_effort": "x"}, "agents": {}}
            write_artifacts(root / "result", payload, cfg)
            manifest = json.loads((root/"result"/"manifest.json").read_text())
            self.assertEqual(manifest["files"]["raw/cpu-single-1.txt"], sha256_file(raw/"cpu-single-1.txt"))
