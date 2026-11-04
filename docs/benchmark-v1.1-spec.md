# TermSquad Benchmark v1.1, Methodology and migration contract

**Status:** Implementation in progress. **Baseline:** v1 commit `2489bc6681f7228a3332f7fec805d914a5b8107d`.

## Why the v1 campaign is stopped

The exploratory v1 campaign produced one valid run each on Netcup and Contabo, not the three required to publish rankings. Preserve both raw results as historical evidence. Do not run second or third v1 passes. Do not report v1 medians or value rankings.

Observed v1 limitations:
1. sysbench memory tested a 1 MiB repeated working block, which may fit CPU cache; physical DRAM bandwidth is **not established**.
2. The 17 validator-backed JavaScript micro-tasks measure orchestration and model latency more than representative coding workloads.
3. Concurrency 4/8/16 finishes in under a minute per stage, insufficient to claim sustained operation.
4. Native `uninstall --purge` requires three runs, preventing safe cancellation after one verified run.
5. fio direct=1 bypasses OS page cache, not all host/storage caches. The existing suite lacks mixed reads/writes.
6. Model service latency, quota and usage must be distinguished from VM-limited performance.

## Version and reproducibility

- New suite version: **1.1.4**, a distinct cohort from 1.1.3, earlier v1.1 implementations and v1; new benchmark commit/config/fixture digests and campaign IDs.
- Keep model `gpt-6.1-terra`, effort `xhigh`, and Ubuntu 24.04/26.04 x86_64.
- Maintain 2,700 s maximum full-run budget including cleanup and evidence.
- Do not modify any v1 run JSON, archived manifests or v1 branch to force comparability.
- Never compare v1 and v1.1 in one statistical cohort. OS releases are also separate cohorts.
- Three complete runs separated by >= 60 minutes per machine are required for v1.1 publication; quote dispersion.

## Hardware

**CPU:** retain pinned sysbench single/multithread measurements and raw samples.

**Memory:** replace the 1 MiB sysbench test with a locally built, versioned, STREAM-style copy/scale/add/triad bandwidth workload using a working set far beyond last-level cache. Compile source with a fixed set of compiler flags, record source/build version, array size, thread count, effective CPU affinity, iterations and checksum. Measure one-thread and all-effective-vCPU cases, and flag insufficient working-set or available-RAM cases as limited instead of fabricating bandwidth. Do not claim to have run the official McCalpin STREAM binary unless it is actually used.

**Disk:** preserve all six fio tests, add 70% read / 30% write random 4 KiB at QD16 on an owned regular file, report independent read/write IOPS, p95/p99 and aggregate operations. Keep O_DIRECT; record file size, queue depth, OS filesystem, preconditioning and any storage-caching limitations. Never target raw devices or run destructive commands.

## Real agent workloads

Keep v1 micro-tasks exclusively as an orchestration smoke test, **not** a productivity ranking. Introduce a deterministic multi-file application fixture, a set of nontrivial feature/bug-fix/refactoring tasks, immutable runner-owned tests, test pass/fail, source hashes and strict per-task working directories. Include tasks involving API handlers, data validation, file I/O, concurrency logic, dependency-free Node tests and multiple-file edits. Enforce changes only in task-owned source, never allow edits to validators. Do not use an LLM to declare correctness.

## Sustained concurrency

Maintain fixed concurrency levels 4, 8 and 16, but run each stage for a reproducible time window using a task queue, not exactly one tiny task per agent. Record completed, attempted, correct, failed, skipped, timed-out, rate-limited and infrastructure-constrained tasks; sample resource pressure and OOM throughout. Report correct tasks/min, median/p95 end-to-end task duration, and local/remote observability where available. Do not equate a 16-agent pass with indefinitely sustainable 16-agent capacity. Never allow a worker to spill beyond the phase deadline or leave owned Herdr sessions behind.

The 1.1.2 cohort permits up to five distinct tasks per agent at each stage, within the unchanged phase deadlines. This corrects repeated task IDs and provides enough queued work to attempt the required sustained window; it does not lower the validation threshold. Sustained duration is the longest continuous interval with at least 75% of workers observed in Herdr's `working` state while their assigned tasks are in flight. Missing or interrupted observations cannot establish sustained load.

## Cancellation and uninstall

- Add native `tsbench abort` to record campaign status `aborted`, refusing while a run is active. Preserve evidence and prior valid run IDs.
- Permit `tsbench uninstall --purge --aborted --campaign ID --verified-export SHA` after exporting **all** existing runs and independently verifying the archive off-VM, even with fewer than three valid runs.
- Before an archive is externally verified, prohibit purge.
- Uninstall only owned files, symlinks and **explicitly tracked** installer-owned dependencies, never remove pre-existing Codex, Herdr, Python, apt packages or user sessions. Third-party packages installed by an external controller cannot be assumed owned by tsbench.
- An operator checkout stays user-owned unless it was explicitly registered as an installation-managed directory; the user may decide how to remove it.
- If cancellation is used for the v1 campaign, export and verify archived v1 results before using any upgraded uninstaller. Do not reset the v1 data to run v1.1.

## Acceptance gate for v1.1

1. Unit/integration tests pass Ubuntu 24.04 and 26.04, including a **real** short hardware smoke test.
2. Memory working set guaranteed beyond reported L3 with nontrivial observed bandwidth and independent checksum.
3. Mixed fio reports separate read/write statistics.
4. Multi-file coding tasks have tests that fail before changes and pass for a correct reference implementation; validators stay immutable.
5. A representative stage actually sustains the target load for multiple minutes (or is explicitly marked partial/limited).
6. Export, interrupted-run recovery, abort, preservation of unrelated data, and native uninstall are tested.
7. At least one full run on both actual Ubuntu versions with Codex and Herdr verifies real CLI compatibility, no owned process leaks and budget <=45m.
8. **Do not merge v1.1 to main or publish rankings based only on CI.**

Technical references:
- [STREAM dataset sizing considerations](https://learn.microsoft.com/en-us/azure/high-performance-computing/performance-benchmarking/stream-benchmark)
- [fio randrw and direct I/O](https://fio.readthedocs.io/en/latest/fio_doc.html)

The 1.1.2 cohort clarifies the CSV and webhook task contracts without changing their validators, and applies the existing 180-second task timeout to the entire Herdr task including follow-up validation waits. Early idle/done signals still do not cause premature failure or prompt resubmission.

## v1.1.4 pilot corrections

The 1.1.4 cohort strengthens the 1.1.3 discount and inventory validators, fixes their independent reference, clips activity intervals to stage bounds, and rejects missing resource telemetry, hidden external constraints and unresolved agent failures as conclusive capacity. Task timeouts before terminal confirmation and validator infrastructure errors are not coding-test failures. Fixtures or methodology changes require a distinct suite version and comparison cohort.
