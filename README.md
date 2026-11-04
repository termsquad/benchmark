# TermSquad Benchmark

Reproducible VM benchmarking for real AI coding agents. **v1.1.2** measures CPU, cache-exceeding STREAM-style RAM throughput, fio disk sequential/random/mixed I/O and Codex/Herdr multi-file coding workloads on Ubuntu 24.04 or 26.04 LTS. This revised workload and its observed-activity gate form a distinct cohort from earlier v1.1.0 and v1.1.1 implementations.

**Important:** The v1 campaign was stopped after one eligible run on each of Netcup and Contabo. Those runs are preliminary historical evidence, **not** publication-ready rankings. v1.1 is a separate statistical cohort and must not overwrite the v1 evidence.

**Warning:** this is an early implementation. It has not yet been validated through a complete 45-minute run on both supported Ubuntu releases. Do not publish provider rankings based solely on unverified runs.

## Requirements

- Dedicated, disposable test VM with Ubuntu Server 24.04 or 26.04 LTS on x86_64
- Python 3, python3-venv, **gcc with OpenMP/libgomp**, git, Node.js, sysbench, fio, Codex CLI, Herdr
- Working Codex authentication and access to **gpt-6.1-terra** at **xhigh**
- At least 6 GiB free storage for the fio file and safety reserve; enough memory for the selected concurrency stage
- Preinstalled tools. The timed run never invokes apt or installs packages.
- Benchmark tests create high CPU, RAM, disk, and API usage. They are not safe on production servers.

## Install

Review the source and dependencies, then on the VM:

~~~bash
git clone https://github.com/termsquad/benchmark.git
cd benchmark
bash install.sh
tsbench doctor
~~~

If a required system tool is missing, install it yourself after reviewing the command for your Ubuntu release. Setup never silently asks for sudo. Make sure your account has access to the specified Codex model and that Herdr can run agents before benchmarking.

The script creates an isolated Python virtual environment at ~/.local/share/tsbench/venv and an owned CLI symlink at ~/.local/bin/tsbench. It never overwrites an existing executable.

## Run

~~~bash
tsbench run --profile full --provider Netcup --plan "RS 4000" --region EU \
  --price-monthly 14.50 --currency EUR
tsbench status
~~~

Runs have a **hard target deadline of 2,700 seconds (45 minutes)** covering preflight, measurements, reporting, and cleanup. They produce JSON, Markdown and hashes under ~/.local/share/tsbench/results/<run-id>.

Hardware measurements remain separate from real coding agent results. Model/API variability is reported rather than assumed to be caused by the host. A stage that was not measured is **not** a failed stage.

### Campaign and comparisons

Run three full, eligible tests at least one hour apart. Avoid concurrent background workloads. For controlled comparisons, match the OS release, benchmark config, Codex and Herdr versions, model and fixture SHA.

~~~bash
tsbench compare path/to/a/results.json path/to/b/results.json
tsbench export
sha256sum ~/.local/share/tsbench/exports/benchmark-export.tar.gz
~~~

Copy the archive to another computer, independently verify its SHA256, and keep a backup. The default local archive is inside the benchmark-owned exports directory, which is removed during verified purge. Only then invoke the native uninstaller with the matching campaign ID and archive digest, as shown in status/export output:

~~~bash
tsbench uninstall --purge --campaign CAMPAIGN_ID --verified-export SHA256
~~~

To cancel an incomplete campaign safely, use `tsbench abort` **before** export, then after off-VM checksum verification, use `tsbench uninstall --purge --aborted --campaign CAMPAIGN_ID --verified-export SHA256`. This works even after only one eligible run. No scheduler or daemon is required.

Without --purge, uninstall removes benchmark-owned installation assets conservatively while **retaining local results**. Pre-existing Node, Codex, Herdr, sysbench, fio and credentials are never removed. Source checkouts cloned by the operator remain operator-owned.

**The machine cannot cryptographically prove that a remote copy exists.** The off-VM controller must verify the external archive and provide the matching digest. Do not use --purge without that external verification.

## Metrics

- CPU: sysbench events/s single and multi.
- RAM: fixed-source STREAM-style copy/scale/add/triad MiB/s, single and effective multi-vCPU, with a dataset larger than last-level cache. Not the official STREAM binary.
- Disk: fio sequential MiB/s, random 4K IOPS, p50/p95/p99 latency, queue depth 1 and 16, and 70/30 random read/write mixed IOPS.
- Coding: real multi-file Node.js API and application scenarios with immutable runner-owned validators. Legacy micro-tasks are retained only as smoke checks.
- Concurrency: 4, 8 and up to 16 Herdr-managed interactive Codex agents, bounded successive task queues, task pass fraction, completed tasks/min and an explicit insufficient-duration status. Sustained duration requires continuous observed `working` states for at least 75% of the target agents with tasks in flight; missing observations cannot validate it.
- Telemetry: CPU load, memory/swap use, Linux pressure stall counters and OOM events.

No arbitrary combined score. The LLM may interpret measurements but may not modify them. Pricing is optional operator-supplied metadata, never derived from IP address or provider naming.

## Security and limitations

All fio tests run against a newly created **regular file** inside a private benchmark scratch directory. No /dev raw block devices are touched. Temporary task worktrees are isolated. Herdr global server, external sessions and authentication are preserved.

Current limitations: even multi-file coding fixtures are simplified compared with production repositories; interactive Herdr/Codex behavior and server versions vary and CLI flags must be validated against installed versions. A passing stage is **not** proof of the maximum number of agents a VM can support. Current unit tests do not replace real Linux E2E runs.

See [v1.1 specification](docs/benchmark-v1.1-spec.md) for the updated contract and [v1 specification](docs/benchmark-v1-spec.md) for historical provenance.

## Development

~~~bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q tsbench
~~~

MIT licensed. Contributions welcome.
