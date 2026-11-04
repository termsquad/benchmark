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
