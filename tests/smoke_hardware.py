"""Tiny real binary smoke test, not a benchmark result."""
import tempfile
import time
from pathlib import Path
from tsbench.hardware import cpu, memory, disk, build_memory_binary

config={
    "cpu":{"samples":1,"sample_seconds":1,"max_prime":4000},
    "memory":{"backend":"stream_style_v1","samples":1,"sample_seconds":1,
              "working_set_mib":512,"minimum_cache_multiple":1},
    "disk":{"file_size_mib":32,"reserve_mib":128,"runtime_seconds":1,
            "ramp_seconds":0,"jobs":1,"ioengine":"libaio","mixed_read_percent":70}
}
deadline=time.monotonic()+100
with tempfile.TemporaryDirectory() as d:
    raw=Path(d)/"raw"
    a=cpu(config,deadline,raw)
    build_memory_binary(Path(d)/"tsbench-stream")
    b=memory(config,deadline,raw,Path(d)/"tsbench-stream")
    c=disk(config,deadline,Path(d),raw)
    assert a["single_events_per_sec"]>0 and a["multi_events_per_sec"]>0,a
    assert b["status"]=="validated",b
    assert b["single"]["triad_mib_per_sec"]>0 and b["multi"]["copy_mib_per_sec"]>0,b
    assert len(c)==7,c
    assert c["mixed_random_70r30w_qd16"]["total_iops"]>0,c
    assert all(v["iops"]>0 for k,v in c.items() if k!="mixed_random_70r30w_qd16"),c
    assert c["mixed_random_70r30w_qd16"]["read"]["iops"]>0,c
    assert c["mixed_random_70r30w_qd16"]["write"]["iops"]>0,c
    assert len(list(raw.iterdir()))==12,"Missing hardware evidence"
    assert all(d not in p.read_text() for p in raw.iterdir()),"Scratch path leaked"
    assert not (Path(d)/"fio-benchmark.bin").exists(),"Disk scratch file survived"
print("CPU, RAM and all seven fio read/write jobs passed")
