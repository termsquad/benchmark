"""Conservative, bounded sampling of benchmark-owned Herdr agent states."""
from __future__ import annotations
import json
import threading
import time
from .common import run_command


class HerdrActivityMonitor:
    def __init__(self, names: set[str], interval: float = 2.0):
        self.names = names
        self.interval = interval
        self.stop_event = threading.Event()
        self.samples = []
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._loop,daemon=True)
        self.thread.start()
        return self

    def _loop(self):
        while not self.stop_event.is_set():
            started = time.monotonic()
            working = None
            try:
                response = run_command(["herdr","agent","list"],4,max_output=100000)
                data = json.loads(response["stdout"])
                agents = data["result"]["agents"]
                if response["returncode"]==0 and isinstance(agents,list):
                    working = [a["name"] for a in agents if isinstance(a,dict)
                               and a.get("name") in self.names and a.get("agent_status")=="working"]
            except (OSError,ValueError,KeyError,TypeError,RuntimeError):
                pass
            self.samples.append({"at":started,"working":working})
            self.stop_event.wait(self.interval)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        return {"samples":self.samples,"available":any(s["working"] is not None for s in self.samples),
                "complete":not self.thread or not self.thread.is_alive()}


def sustained_working_seconds(samples: list[dict], tasks: list[dict], names: list[str],
                              stage_start: float, minimum_active: int, max_gap: float = 7.0) -> float:
    """Longest continuous span with observed working agents and in-flight tasks."""
    intervals = {}
    for worker in tasks:
        index = worker.get("worker")
        if not isinstance(index,int) or not 0<=index<len(names):
            continue
        intervals[names[index]] = [(t["started_offset_seconds"],t["finished_offset_seconds"])
                                   for t in worker.get("task_results",[])
                                   if "started_offset_seconds" in t and "finished_offset_seconds" in t]
    current = longest = 0.0
    for first,second in zip(samples,samples[1:]):
        gap = second["at"]-first["at"]
        if (gap<=0 or gap>max_gap or first.get("working") is None or second.get("working") is None):
            current = 0.0
            continue
        start,end = first["at"]-stage_start,second["at"]-stage_start
        observed = set(first["working"]) & set(second["working"])
        active = {name for name in observed if any(a<=start and b>=end for a,b in intervals.get(name,[]))}
        if len(active)>=minimum_active:
            current += gap
            longest = max(longest,current)
        else:
            current = 0.0
    return longest


def activity_statistics(samples: list[dict], tasks: list[dict], names: list[str],
                        stage_start: float, stage_elapsed: float,
                        minimum_active: int, max_gap: float = 7.0) -> dict:
    """Observed working+in-flight occupancy; never infer work between missing samples.

    Total qualifying seconds are cumulative, while longest continuous seconds
    remain diagnostic. Agent-seconds measure the fraction of potential parallel
    worker-time actually observed as busy.
    """
    intervals = {}
    for worker in tasks:
        index = worker.get("worker")
        if not isinstance(index, int) or not 0 <= index < len(names):
            continue
        intervals[names[index]] = [
            (t["started_offset_seconds"], t["finished_offset_seconds"])
            for t in worker.get("task_results", [])
            if isinstance(t.get("started_offset_seconds"), (int, float))
            and isinstance(t.get("finished_offset_seconds"), (int, float))
            and t["finished_offset_seconds"] >= t["started_offset_seconds"]
        ]
    qualifying = covered = agent_seconds = current = longest = 0.0
    for first, second in zip(samples, samples[1:]):
        gap = second.get("at", 0) - first.get("at", 0)
        if (gap <= 0 or gap > max_gap or first.get("working") is None
                or second.get("working") is None):
            current = 0.0
            continue
        start=max(0.0, first["at"]-stage_start)
        end=min(max(stage_elapsed,0.0),second["at"]-stage_start)
        gap=end-start
        if gap<=0:
            current=0.0
            continue
        covered += gap
        common = set(first["working"]) & set(second["working"]) & set(names)
        active = sum(any(a <= start and b >= end for a, b in intervals.get(name, []))
                     for name in common)
        agent_seconds += active * gap
        if active >= minimum_active:
            qualifying += gap
            current += gap
            longest = max(current, longest)
        else:
            current = 0.0
    duration = max(stage_elapsed, 0.000001)
    return {
        "qualifying_seconds": round(qualifying, 3),
        "longest_continuous_seconds": round(longest, 3),
        "observed_agent_seconds": round(agent_seconds, 3),
        "mean_agent_occupancy": round(agent_seconds / (duration * max(len(names), 1)), 4),
        "qualifying_fraction": round(qualifying / duration, 4),
        "telemetry_coverage_fraction": round(min(1.0, covered / duration), 4),
        "telemetry_complete": len(samples) >= 3 and covered / duration >= 0.85,
    }
