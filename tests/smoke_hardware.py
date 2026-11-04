"""Tiny real binary smoke test, not a benchmark result."""
import tempfile
import time
from pathlib import Path
from tsbench.hardware import cpu, memory, disk

config={
    "cpu":{"samples":1,"sample_seconds":1,"max_prime":4000},
    "memory":{"samples":1,"sample_seconds":1,"block_size":"1M","total_size":"1G"},
    "disk":{"file_size_mib":32,"reserve_mib":128,"runtime_seconds":1,
            "ramp_seconds":0,"jobs":1,"ioengine":"libaio"}
}
deadline=time.monotonic()+100
with tempfile.TemporaryDirectory() as d:
    raw=Path(d)/"raw"
    a=cpu(config,deadline,raw)
    b=memory(config,deadline,raw)
    c=disk(config,deadline,Path(d),raw)
    assert a["single_events_per_sec"]>0 and a["multi_events_per_sec"]>0,a
    assert b["read_mib_per_sec"]>0 and b["write_mib_per_sec"]>0,b
    assert len(c)==6,c
    assert all(x["iops"]>0 for x in c.values()),c
    assert len(list(raw.iterdir()))==11,"Missing hardware evidence"
    assert all(d not in p.read_text() for p in raw.iterdir()),"Scratch path leaked"
    assert not (Path(d)/"fio-benchmark.bin").exists(),"Disk scratch file survived"
print("CPU, RAM and all six fio read/write jobs passed")
