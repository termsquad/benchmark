"""Bounded host-resource sampling, deliberately no user process content."""
from __future__ import annotations
from pathlib import Path
import threading
import time
from .inventory import meminfo, psi, oom_kills


def _cpu_sample():
    try:
        parts = list(map(int,Path("/proc/stat").read_text().splitlines()[0].split()[1:]))
        return sum(parts), parts[3]+(parts[4] if len(parts)>4 else 0)
    except (OSError,ValueError,IndexError):
        return (0,0)


class Telemetry:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.samples = []
        self.initial_oom = oom_kills()
        self.last = _cpu_sample()

    def start(self):
        self.thread = threading.Thread(target=self._loop,daemon=True)
        self.thread.start()
        return self

    def _loop(self):
        while not self.stop_event.wait(2.0):
            current = _cpu_sample()
            total = current[0]-self.last[0]
            idle = current[1]-self.last[1]
            self.last = current
            mem = meminfo()
            sample = {"at":round(time.monotonic(),2),
                      "cpu_percent":round(100*(1-idle/total),2) if total>0 else None,
                      "memory_used_bytes":mem.get("MemTotal",0)-mem.get("MemAvailable",0),
                      "memory_available_bytes":mem.get("MemAvailable"),
                      "swap_used_bytes":mem.get("SwapTotal",0)-mem.get("SwapFree",0),
                      "memory_psi_some_avg10":psi("memory").get("avg10"),
                      "cpu_psi_some_avg10":psi("cpu").get("avg10"),
                      "io_psi_some_avg10":psi("io").get("avg10")}
            if len(self.samples)<1400:
                self.samples.append(sample)

    def summary(self):
        current = oom_kills()
        def peak(key):
            values = [x[key] for x in self.samples if x.get(key) is not None]
            return max(values) if values else None
        return {"peak_cpu_percent":peak("cpu_percent"),
                "peak_memory_used_bytes":peak("memory_used_bytes"),
                "peak_swap_used_bytes":peak("swap_used_bytes"),
                "peak_memory_psi_some_avg10":peak("memory_psi_some_avg10"),
                "peak_io_psi_some_avg10":peak("io_psi_some_avg10"),
                "oom_kills":max(0,current-self.initial_oom) if current is not None and self.initial_oom is not None else None,
                "oom_scope":"guest" if current is not None and self.initial_oom is not None else "unavailable",
                "sample_count":len(self.samples)}

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        return self.summary()
