# TermSquad Benchmark

Reproducible VM benchmarking designed for actual AI coding agents using external models. Measure CPU, RAM **read/write**, disk **sequential/random read/write**, and Codex/Herdr agent concurrency on Ubuntu 24.04 or 26.04 LTS.

**Warning:** this is an early implementation. It has not yet been validated through a complete 45-minute run on both supported Ubuntu releases. Do not publish provider rankings based solely on unverified runs.

## Requirements

- Dedicated, disposable test VM with Ubuntu Server 24.04 or 26.04 LTS on x86_64
- Python 3, python3-venv, git, Node.js, sysbench, fio, Codex CLI, Herdr
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
tsbench export --output ~/benchmark-export.tar.gz
sha256sum ~/benchmark-export.tar.gz
~~~

Copy the archive to another computer, independently verify its SHA256, and keep a backup. Only then invoke the native uninstaller with the matching campaign ID and archive digest, as shown in status/export output:

~~~bash
tsbench uninstall --purge --campaign CAMPAIGN_ID --verified-export SHA256
~~~

Without --purge, uninstall removes benchmark-owned installation assets conservatively while **retaining local results**. Pre-existing Node, Codex, Herdr, sysbench, fio and credentials are never removed. Source checkouts cloned by the operator remain operator-owned.

**The machine cannot cryptographically prove that a remote copy exists.** The off-VM controller must verify the external archive and provide the matching digest. Do not use --purge without that external verification.

## Metrics

- CPU: sysbench events/s single and multi.
- RAM: sysbench MiB/s read and write.
- Disk: fio sequential MiB/s, random 4K IOPS, p50/p95/p99 latency, queue depth 1 and 16.
- Coding: immutable Node validators for a single Codex task.
- Concurrency: 4, 8 and up to 16 Herdr-managed interactive Codex agents, task pass fraction and completed tasks/min.
- Telemetry: CPU load, memory/swap use, Linux pressure stall counters and OOM events.

No arbitrary combined score. The LLM may interpret measurements but may not modify them. Pricing is optional operator-supplied metadata, never derived from IP address or provider naming.

## Security and limitations

All fio tests run against a newly created **regular file** inside a private benchmark scratch directory. No /dev raw block devices are touched. Temporary task worktrees are isolated. Herdr global server, external sessions and authentication are preserved.

Current limitations: the reference agent tasks intentionally have low complexity; interactive Herdr/ Codex behavior and server versions vary, and CLI flags must be validated against installed versions. A passing stage is **not** proof of the maximum number of agents a VM can support. Current unit tests do not replace real Linux E2E runs.

See [technical specification](docs/benchmark-v1-spec.md) for the full measurement, safety and publication contract.

## Development

~~~bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q tsbench
~~~

MIT licensed. Contributions welcome.
