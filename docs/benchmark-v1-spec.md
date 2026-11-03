# TermSquad Benchmark v1, Technical Specification

**Status:** Ready for implementation  
**Date:** 2026-11-03  
**Owner:** TermSquad  
**Target repository:** `termsquad/benchmark` (independent, intended to be open source)  
**Canonical document path:** `docs/benchmark-v1-spec.md`

## 1. Purpose

Build a small, reproducible CLI benchmark for evaluating virtual machines as **always-on computers for AI coding agents**. It must deliver evidence to compare infrastructure providers and plans, choose suitable machines for TermSquad, and later publish transparent results on the TermSquad marketing site.

The benchmark measures **both** (a) CPU, memory and disk performance and (b) actual coding-agent behavior with an external LLM. The external model is part of the intended environment, not something to simulate away. Hardware measurements remain separate so that remote-model latency and service limits are not incorrectly presented as VM performance.

**Primary questions**

1. How fast is this VM for CPU, memory reads/writes, and disk reads/writes?
2. How well does a real Codex coding agent complete a verifiable task on it?
3. How does useful throughput, stability and resource pressure change at 4, 8 and up to 16 simultaneous agents?
4. Which tested VM offers the best performance at its actual recurring monthly cost?

### Non-goals for v1

- No browser dashboard, central database, hosted benchmark service, auto-provisioning or automatic publication.
- No changes to TermSquad's production control plane, runtime or users' machines.
- No self-hosted LLM, artificial model emulator or replacing real Codex tasks with synthetic-only tasks.
- No arbitrary universal score or unsupported claim of a VM's theoretical maximum number of agents.
- No benchmarks involving GPU inference or dedicated GPU instances.

## 2. Execution contract

| Setting | v1 contract |
| --- | --- |
| Supported OS | **Ubuntu Server 24.04 LTS or Ubuntu Server 26.04 LTS**, detected at runtime |
| Initial architecture | `x86_64` / `amd64`; other architectures are out of scope for v1 |
| Execution target | Linux VM with SSH access, or local shell inside that VM |
| Harness | Codex CLI, with **GPT-6.1 Terra** (`gpt-6.1-terra`) and `xhigh` reasoning |
| Agent orchestration | Herdr official installation and supported agent/pane/workspace primitives |
| Duration | **Hard deadline of 45 minutes (2,700 seconds)** from `tsbench run` start to process exit, including preflight, report and cleanup |
| Profiles | `full` (required for v1); optional `hardware` subcommand for debugging, not a valid full ranking run |
| Output | Machine-readable JSON, Markdown report, sanitized raw benchmark artifacts |
| Ranking eligibility | At least 3 **independent complete runs**, conducted at different times; report the median and dispersion |
| Post-benchmark lifecycle | After 3 valid runs, export/verify results externally and remove benchmark-owned installation/data from the target VM |

Ubuntu 24.04 and 26.04 are both supported. **Never silently rewrite or upgrade the guest OS.** Store the exact OS/kernel and versions in every result. Full agent-to-agent comparisons should be made inside the same OS cohort, architecture, benchmark-suite version and pinned toolchain, or labeled **cross-OS / not directly controlled**. A separate combined table may describe both OSes but must expose this difference and avoid strong causal claims about providers.

`tsbench setup` may prepare dependencies **before** the timed run; its duration is not part of the 45 minutes. Setup must document changes and seek confirmation before using `sudo`. The timed `run` performs no package installations, automatic updates, OS upgrades or downloads of unknown versions. Failed preflight reports `invalid_environment` rather than consuming the remainder of the test window.

The benchmark is intended for **fresh, dedicated test VMs**, not production machines with user projects. The CLI must state its CPU, memory and disk load before starting. Prefer a self-contained benchmark-owned installation prefix so uninstalling it does not affect system tools. The 45-minute deadline applies to each run, not to a later remote export and final uninstall.

## 3. High-level design

```text
External operator / Codex controller (off-target VM)
           |
           | SSH or interactive shell command
           v
       tsbench run
           |
           +-- preflight & VM inventory
           +-- CPU measurements (sysbench)
           +-- RAM measurements (sysbench)
           +-- Disk measurements (fio)
           +-- Single real Codex coding task
           +-- Concurrent real Codex coding tasks (Herdr)
           +-- resource telemetry + validators
           |
           v
   results.json + report.md + sanitized raw/
           |
           +-- controller pulls + verifies artifacts after each run
           |
           +-- after run 3: controller invokes safe uninstall
           v
   tsbench compare (local, no backend)
           |
           v
   future public comparison pages (separate project)
```

- The **benchmark runner is deterministic** and is the only authority for collected metrics, status, validation and derived calculations.
- The **LLM executes the coding tasks**, while an external controller may interpret the finished report. The controller must not consume meaningful CPU/RAM on the VM under test.
- Task prompts, fixture repositories, dependency locks, test validators, binaries and configuration are versioned/pinned. Do not let a controller LLM improvise tasks or adjust parameters between providers.
- The full benchmark works without deploying the TermSquad control plane; Herdr is included specifically for realistic session-based concurrency.

## 4. Time budget

| Phase | Maximum elapsed time |
| --- | ---: |
| Preflight and VM inventory | 3 min |
| CPU | 4 min |
| RAM | 4 min |
| Disk I/O | 9 min |
| Single coding agent | 8 min |
| Parallel coding agents | 14 min |
| Report and cleanup | 3 min |
| **Total** | **45 min** |

These are **ceilings**, not minimum durations. Each subprocess receives a deadline shorter than its phase budget. The runner uses a monotonic clock and a global deadline, terminates benchmark-owned processes on timeout, attempts bounded per-run cleanup and writes partial results safely. If per-run cleanup cannot complete before the deadline, mark `cleanup_incomplete` and give explicit manual instructions; never claim a valid completed run. Final installation removal after the third run is a separate post-run operation and is **not included** in the 45-minute per-run measurement budget.

Within the agent phases, maintain the fixed published per-stage timeout configuration across all tested machines. A timeout is a real outcome and must not be hidden. The report generator is **local and deterministic**; any optional LLM narrative happens **after** `run` and outside the 45-minute benchmark.

## 5. Preflight and environment inventory

Collect at minimum:

- UUID run ID, UTC timestamps, benchmark Git commit/tag, fixture commit and configuration digest.
- `/etc/os-release`, kernel, CPU architecture, vCPU count, CPU model, hypervisor (where observable), available CPU flags and cgroup limits.
- Physical/available memory, configured swap, filesystem type, mount path, disk total/free space and reported virtual disk device.
- CPU/RAM load at baseline; warnings for competing heavy workloads.
- Tool versions: Python, sysbench, fio, Git, Node/package manager, Codex CLI, Herdr, fixture toolchain.
- Agent model ID, reasoning effort, Codex configuration, auth readiness and observed rate-limit/quota errors. Never persist credentials.
- Provider, exact SKU/plan, region, CPU type if supplied by provider, currency, recurring monthly price, mandatory IPv4/storage charges, promotion status, effective price date and data source. **These are metadata explicitly supplied by the operator**, never guessed from an IP address or inferred from performance.

Preflight checks:

1. Ubuntu version is either `24.04` or `26.04`; architecture is `x86_64`.
2. All binaries and fixture dependencies are present, executable and verified against the benchmark manifest.
3. Agent can authenticate to Codex without exposing or printing a token; Herdr supports the capabilities required for agent start/prompt/wait/read and pane/workspace creation.
4. Chosen workspace is writable, safe and has adequate free capacity, measured after reserving a safety margin. The runner cannot operate on filesystem root or raw block devices as its test target.
5. No prior benchmark-owned agents or subprocesses from another active run; enforce one active run per machine with a local lock.
6. Record CPU/memory idle baseline; mark high background load and `environment_contended`, so results cannot be presented as standard.

If any critical preflight check fails, terminate with a structured explanation. A missing service entitlement, model, Codex authentication or unsupported Herdr capability **must not trigger a silent fallback** to another model, reasoning effort, or agent runtime.

## 6. Hardware suite

### 6.1 CPU (4-minute phase)

Use `sysbench cpu` with a pinned tool version and published parameters:

- Single-thread run and all-available-vCPU run (`threads = measured effective CPU allowance`, not an assumed count).
- At least two timed sampling windows per mode, with small warmups.
- Capture events/s, elapsed time, per-thread fairness, CPU utilization and change between early/late samples as a short-run stability indicator.
- Do not present a 4-minute CPU test as proof of hours-long sustained performance or thermal stability.

### 6.2 RAM (4-minute phase)

Use `sysbench memory` with explicit `--memory-oper=read` and `write` modes, and fixed access mode/scope/working-set rules:

- Test read and write separately using at least two sampling windows per mode.
- Report read throughput and write throughput in **MiB/s**, plus total/available RAM, swap activity and memory PSI if supported.
- Configure the per-thread working set to avoid trivially measuring tiny L1/L2-cache-only loops, while maintaining a conservative memory cap. Record actual block size, working-set size and thread count.
- Label this **effective synthetic memory throughput**, not a physical DIMM bandwidth or RAM speed rating. If adequate working-set sizing is impossible, mark the metric `limited` rather than mislabeling it.

### 6.3 Disk I/O (9-minute phase)

Use `fio` on a **regular file inside a benchmark-owned temporary directory** on the selected filesystem, **never** a `/dev/*` block device. Prefer `direct=1` where the filesystem supports it; if unavailable, report the test as not directly comparable rather than silently switching to cached I/O.

Required workloads:

| Workload | Block size | Queue depth | Primary values |
| --- | --- | --- | --- |
| Sequential read | 1 MiB | 4 | MiB/s |
| Sequential write | 1 MiB | 4 | MiB/s |
| Random read | 4 KiB | 1 | IOPS, p95 latency |
| Random write | 4 KiB | 1 | IOPS, p95 latency |
| Random read (queued) | 4 KiB | 16 | IOPS, p95 latency |
| Random write (queued) | 4 KiB | 16 | IOPS, p95 latency |

- Prefer a documented, portable `fio` I/O engine available on both supported Ubuntu versions; pin the chosen engine in the suite config and record it. An engine fallback changes comparability and must be explicit.
- Set `time_based=1`, an explicit `runtime`, `ramp_time`, fixed job count, deterministic order, and `--output-format=json` (or equivalent verified JSON output). Allocate enough room for file creation/warmup, all six measured jobs and safe cleanup **inside 9 minutes**.
- Use a fixed target file size, default **2 GiB**, subject to required free-space safety checks. If there is insufficient space, mark disk tests `skipped_insufficient_space` (do not fill the disk or silently use a tiny fully cached file).
- Prepare/prefill data for read tests, do not report read performance from unwritten/sparse/uninitialized files, and log preparation times separately.
- Report write amplification / I/O throttling only if directly observable. Measure `fsync`/write durability separately in a future version rather than imply sequential write bandwidth equals durability.
- Capture both raw `fio` stats and normalized MiB/s, IOPS and latency p50/p95/p99, with units and queue-depth configuration.

Disk I/O should not share the phase with running agents: avoid workload interference during raw hardware measurement.

## 7. Real agent workload suite

### 7.1 Fixed model and environment

All agent runs use:

- **Codex CLI** using **`gpt-6.1-terra`** and **`model_reasoning_effort=xhigh`** (verify installed CLI supports these before execution).
- The same Codex CLI version, sandbox/approval settings, tool permissions, fixture, prompts, limits and external-network policy across runs.
- A **small, versioned development repository**, initially TypeScript/Node with lockfile, fixed dependencies and deterministic tests. Add Rust or other fixture later, not as a v1 requirement.
- Pre-installed dependency cache prepared **before** `run`, so package-network installation latency is not inadvertently the main benchmark.
- Fixed independent tasks that modify code, run tests and satisfy externally validated acceptance criteria.

For unattended execution, scope file write access to the benchmark fixture and scratch directory. Do not grant the benchmark agent administrative privileges. Verify exact Codex command-line flags via `codex --help` at implementation time. One documented noninteractive command shape is:

```bash
codex exec --model gpt-6.1-terra \
  -c 'model_reasoning_effort="xhigh"' \
  --json --full-auto '<versioned task prompt>'
```

The Herdr interactive invocation uses its native `agent start` / `agent prompt` surface and passes the equivalent Codex flags after `--` where supported. `codex exec` and the interactive Herdr path are **different execution surfaces**. Record which was used; do not merge their timing measurements without flagging the distinction.

### 7.2 Fixture and task correctness

Create and commit a reproducible benchmark fixture with at least **17 independent small coding tasks** (one baseline task, sixteen concurrency task definitions) of similar expected scope. The same frozen task definition may be used again in a different concurrency stage **only** in a fresh isolated worktree reset to its original commit; assign distinct task instances per agent and stage. Each task has:

- Task ID, frozen prompt, initial repository commit/worktree, immutable tests or acceptance harness and fixed timeout.
- No task may depend on another, change common shared files, access private data or require human approval.
- Objective success validator runs outside the writable agent worktree, using immutable tests/hash-verified task definitions. The agent must not be able to edit the validator or scoring rules.
- Avoid intentionally very hard tasks; tasks should be feasible within short bounded trials so throughput can be measured. Record task-specific difficulty variation and avoid cherry-picking.
- Deterministic completion requires exit/settled state **and** acceptance-test pass, not merely an agent text claiming success.

Freeze prompts, fixture code, dependencies and validator versions before the first cross-provider comparison. An update changes the `suite_version` and constitutes a new comparison cohort.

### 7.3 Single agent (8-minute phase)

Execute one fixed task with Codex and record:

- Outcome: `passed`, `failed_tests`, `agent_error`, `rate_limited`, `timed_out` or `infrastructure_error`.
- Wall-clock runtime, validator runtime, number of edited files, tests passed/failed.
- CPU time, process-group peak RSS where observable, peak system memory, swap, CPU and memory PSI.
- Codex session/turn identifiers if available, token usage if exposed and CLI event timestamps. Do **not** invent exact inference time vs local execution time when the CLI does not expose enough evidence. Unknown values remain `null`.
- The run is only a successful **coding-agent task** when immutable acceptance tests pass.

### 7.4 Parallel agents (14-minute phase)

Run up to **4, 8, 16** simultaneous Codex agents via Herdr in distinct panes and independent worktrees. The single-agent phase is the **1-agent baseline**; do not repeat it unnecessarily inside the parallel phase.

- Stage budgets: **4 agents: 4 min; 8 agents: 5 min; 16 agents: 5 min**. Stages are sequential and fit within the 14-minute phase including controlled startup/teardown overhead.
- Within each stage, submit distinct frozen tasks near-simultaneously and measure start skew; store start times, terminal states and validation outcomes.
- Attempt the next stage only if the environment has enough available RAM/disk for the estimated startup footprint and remains below critical memory-pressure/OOM guardrails. Record the exact admission rule, estimated per-agent footprint and skipped-stage reason.
- If prior stages fail, continue only where safe and time allows; never cause intentional host OOM merely to achieve 16 agents.
- A started agent is **not** a successful agent. The stage's primary metric is **correctly completed tasks per wall-clock minute**, accompanied by pass count and completion fraction; report timeouts/censored jobs explicitly.
- Record peak aggregate CPU/RAM/swap, PSI pressure, peak process count, OOM events, stage wall time and distribution of completion times.
- Detect API quota exhaustion, HTTP/model errors and remote rate limits separately from Linux resource pressure. Remote-service failures make the affected stage **externally constrained**, not evidence that the VM can run fewer agents.
- Set a stage to `validated` only if **at least 75%** of the assigned tasks pass their immutable validators before the stage deadline, **zero OOM kills** are observed, and no external rate-limit/quota condition compromised the stage. Record insufficient pass rate as `inconclusive` unless a measurable host resource fault explains it. Keep the pass fraction and all measured timings visible, even when a stage is not validated.
- `highest_validated_concurrency` is the highest stage meeting these criteria, **not** the theoretical maximum number of concurrent agents. Keep `not_tested`, `inconclusive`, `externally_constrained` and `failed_host` separate. Never attribute an agent timeout to weak hardware without supporting system telemetry.
- Never use `agent wait`/idle state alone as proof of task completion. Run independent validators and capture results for each worktree.

### 7.5 Agent lifecycle and per-run cleanup

- Verify Herdr syntax/capabilities against the **installed** version, not a hardcoded assumption; use returned pane/agent IDs and supported API/CLI options.
- Never shut down Herdr's server globally, delete unrelated workspace data or terminate unrelated user agents.
- Create a unique benchmark workspace and identify every agent/pane/process started by this run.
- On timeout/cancel, stop only benchmark-owned processes and close only benchmark-owned panes; preserve structured outcomes even when a task fails.
- Agent credentials remain in the VM's standard Codex auth store. Never copy them to outputs or the controller.

## 8. Telemetry and external-service effects

Gather system metrics at least every **2 seconds** during agent phases, with bounded memory and file sizes:

- CPU utilization and effective CPU quota; CPU PSI when present.
- Memory used/available, process RSS, swap in/out, memory PSI `some`/`full` when present.
- Disk read/write bytes and I/O PSI when available.
- OOM kill counters and agent/process exit statuses.
- Per-agent task state changes, tool events and model-usage telemetry **only if observed**, with timestamps.

Be transparent: with an externally hosted LLM, wall-clock agent performance is a combination of VM behavior, network, remote inference, quota and agent choices. Do not claim to isolate remote-model latency if observability cannot support it. Include `external_service_constrained`, `rate_limit_observed` and `remote_timing_observed` flags to prevent unjustified VM conclusions.

Optional minimal network diagnostics may record DNS and HTTPS connection latency to the configured endpoint without stressing or probing provider infrastructure. These diagnostics are **context**, not part of the hardware-performance score.

## 9. CLI and configuration

Required commands:

```bash
# One-time, explicit environment preparation; outside benchmark timing.
tsbench setup

# Read-only compatibility checks (except small ephemeral scratch files).
tsbench doctor

# Hard deadline 45 minutes, generates results under ./results/<run-id>/.
tsbench run --profile full --config benchmark.yaml

# Local comparison: no cloud backend required.
tsbench compare results/run-a/results.json results/run-b/results.json

# Read the benchmark campaign progress on this VM.
tsbench status

# First-class built-in uninstaller. Removes only benchmark-owned files;
# preserves any results that have not been verified off-VM.
tsbench uninstall

# After the third eligible run, the external LLM/controller verifies the export
# and invokes the benchmark's own full-cleanup command, not custom rm scripts.
tsbench uninstall --purge --campaign <campaign-id> --verified-export <sha256>
```

Recommended options: `--output-dir`, `--provider`, `--plan`, `--region`, `--price-monthly`, `--currency`, `--price-source`, `--dry-run` and `--json`. Do not embed prices in code or silently assume a billing period or exchange rate.

`benchmark.yaml` is versioned and supplies the **published immutable test parameters**: phase budgets, fio jobs, sysbench configs, fixture hash, task IDs/prompts, model selection, Herdr concurrency stages and safety thresholds. CLI overrides that change workload parameters must produce a new config digest and make the result ineligible for the standard ranking until verified.

The tool must be usable by a controller LLM over SSH without requiring a separate hosted service. The runner itself must not need an LLM to produce valid reports. Each target VM has a small benchmark-owned campaign state identifying the suite/config and the three eligible run IDs; no background daemon, scheduler or cloud database is required. When using the recommended SSH controller, the controller is responsible for external artifact verification and invoking the benchmark's built-in `tsbench uninstall` command after the third eligible run. This is an explicit tool invocation by the LLM/controller, **not** a bespoke cleanup script, a resident daemon or deletion performed implicitly by `tsbench run`. The command is available independently at any time; before a verified export it may remove install-only assets, but must preserve the only copies of results.

## 10. Result format

Each run writes:

```text
results/<run-id>/
  results.json        # canonical, schema-versioned metrics
  report.md           # human-readable summary from verified metrics
  raw/                # bounded, sanitized fio/sysbench/Codex/Herdr data
  manifest.json       # hashes/provenance for files and configuration
```

Minimum logical JSON structure (example with placeholders, **not benchmark data**):

```json
{
  "schema_version": "1.0.0",
  "suite_version": "1.0.0",
  "run_id": "<uuid>",
  "status": "complete | partial | invalid_environment | timed_out",
  "started_at": "<UTC ISO-8601>",
  "finished_at": "<UTC ISO-8601>",
  "elapsed_seconds": null,
  "machine": {
    "provider": "<operator supplied>",
    "plan": "<operator supplied>",
    "region": "<operator supplied>",
    "os_version": "24.04 | 26.04",
    "kernel": "<kernel>",
    "architecture": "x86_64",
    "vcpu": null,
    "ram_bytes": null,
    "disk_bytes": null,
    "cpu_model": "<cpu model>"
  },
  "price": {
    "monthly_amount": null,
    "currency": "<ISO 4217>",
    "source_url": null,
    "checked_at": null,
    "includes_mandatory_fees": null
  },
  "provenance": {
    "benchmark_commit": "<git SHA>",
    "suite_config_sha256": "<sha256>",
    "fixture_sha256": "<sha256>",
    "codex_version": "<version>",
    "herdr_version": "<version>",
    "model": "gpt-6.1-terra",
    "reasoning_effort": "xhigh"
  },
  "cpu": {"single_events_per_sec": null, "multi_events_per_sec": null},
  "memory": {"read_mib_per_sec": null, "write_mib_per_sec": null},
  "disk": {
    "sequential_read_mib_per_sec": null,
    "sequential_write_mib_per_sec": null,
    "random_read_qd1_iops": null,
    "random_write_qd1_iops": null,
    "random_read_qd16_iops": null,
    "random_write_qd16_iops": null,
    "latencies": {}
  },
  "agents": {
    "single": {"status": "<status>", "elapsed_seconds": null},
    "parallel": [
      {"concurrency": 4, "status": "<status>", "passed": null, "throughput_per_minute": null},
      {"concurrency": 8, "status": "<status>", "passed": null, "throughput_per_minute": null},
      {"concurrency": 16, "status": "<status>", "passed": null, "throughput_per_minute": null}
    ],
    "rate_limit_observed": false,
    "external_service_constrained": false
  },
  "warnings": [],
  "errors": []
}
```

The **implementation schema** must define numeric types, nullability, units, phase status and latency dimensions precisely. The example above illustrates structure only. Partial results use explicit per-phase `status` and `reason`, never zero as a placeholder for missing throughput.

Sanitize artifacts to avoid storing API keys, bearer tokens, SSH credentials, arbitrary machine environment variables, private repository paths, IP addresses or unredacted personal data. The fixture itself contains only public benchmark data. If raw agent traces cannot be safely redacted, omit the trace from publishable outputs.

## 11. Comparison methodology and publication rules

For any two VM runs, compare like with like:

1. Same `suite_version`, fixture hash, configuration digest and measurable benchmark parameters.
2. Same OS version and architecture for a **controlled provider ranking**, or explicit cross-OS disclaimer.
3. Same Codex/Herdr versions, model and reasoning effort for agent comparisons.
4. Similar time window where practical; run across several time windows to control cloud and model variability.
5. Price must use a published, **recurring** monthly amount with required charges and a dated source; show currency and exchange-rate date if converted.

Publish four **separate** comparisons, not one invented overall percentage:

- **Hardware:** CPU, RAM read/write and disk sequential/random read/write.
- **Single agent:** accepted task pass result and task elapsed time; failed attempts cannot rank as faster successes.
- **Parallel agents:** correctly completed tasks/min at the **same concurrency stage**, with completion fraction, resource pressure and external-quota caveats.
- **Value:** a clearly specified metric divided by effective recurring cost, e.g. verified completed tasks/min per monthly USD, and only when numerator is comparable and price is sourced.

Never rank a stage that is `not_tested`, `partial`, `externally_constrained`, or `invalid_environment` as if it were an ordinary completed measurement. The benchmark must be able to conclude **insufficient comparable evidence**.

**Publication eligibility:** three comparable top-level runs per VM that completed their scheduled measurement phases without environment errors, in separated time windows. A deliberately skipped concurrency stage may be reported as untested but may not be ranked; display median and range/interquartile interval when available (do not suggest statistical certainty from n=3). Show dates, exact VM SKU and region, OS, versions, full methodology and access to sanitized raw data. Clearly distinguish TermSquad-controlled results from any future community-submitted results.

## 12. Installation ownership, three-run campaign and final uninstall

**Goal:** After the third **valid** benchmark execution on a target VM, leave no benchmark-owned runtime, fixture, worktree, temporary test file or result behind, while preserving every component that belonged to the VM before setup. Do not attempt to erase normal OS audit trails, shell history or package-manager logs; "no trace" cannot be guaranteed at the OS/provider level.

### 12.1 Installation and provenance

- `tsbench setup` records an ownership manifest of everything it creates or installs, including exact paths, initial presence/version of dependencies, and the current campaign ID. Prefer an isolated benchmark-owned directory/virtual environment for the CLI, fixtures and pinned user-space assets. Avoid a persistent background service.
- Treat pre-existing Codex CLI, Herdr, Python, Git, Node, sysbench, fio, repositories, auth credentials, user workspaces, and TermSquad services as **user-owned**, never uninstall or reset them. Do not remove Codex auth files or Herdr's global server/state.
- If a missing system package requires `apt`/`sudo`, obtain explicit authorization before installation, record whether it was already present, and do not blindly run `apt autoremove`. Remove a package installed solely by the benchmark only if provenance and dependency checks demonstrate this is safe; otherwise report the residual package and offer an explicit manual action. No OS changes are permitted during timed `run`.
- All paths eligible for deletion must be under the recorded benchmark-owned root, checked using canonical paths with symlink traversal and path escaping rejected. Never run a generic home-directory wipe or delete files by a broad process-name match.

### 12.2 After each run

- Stop only run-owned Codex processes and Herdr panes/workspaces, remove run-owned worktrees and disk stress files, and clear benchmark-generated temporary files, including on timeouts or cancellation.
- Keep the CLI, pinned fixtures, setup dependencies and the three-run campaign metadata available for the following execution. Keep the current run's output until the external controller has copied and verified it.
- Only a **complete**, environment-valid full run under the exact campaign config counts toward the three-run threshold. Partial, cancelled, externally constrained, invalid-environment and timed-out runs do **not** increment the counter. Runs must have distinct IDs and timestamps and occur in separated time windows for eventual ranking eligibility. Retries must not overwrite earlier results.

### 12.3 After the third eligible run

1. The **external SSH controller** copies every run's result folder (JSON, Markdown, provenance and sanitized raw evidence) to an operator-controlled location outside the target VM. It verifies checksums against `manifest.json`, checks that three distinct compatible runs exist, and records a receipt/digest of the verified export. Never upload to a public endpoint implicitly.
2. Only after successful verification, the LLM/controller invokes **the native benchmark command** `tsbench uninstall --purge --campaign <campaign-id> --verified-export <sha256>` on the target. All removal logic is implemented and tested **inside the `tsbench` package**: it checks the campaign and receipt/digest, stops benchmark-owned processes and removes benchmark-owned install prefix, fixture clones, remaining temp files, campaign metadata, and local results. Do not implement one-off `rm -rf` commands in the controller. Since the package must remove its own executable/installation, it may use a tiny, benchmark-owned one-shot cleanup helper launched by the command after it exits; this helper is not a daemon or background service.
3. The controller performs a final remote audit of the ownership manifest's paths and reports `purged`, `purged_with_residuals` or `purge_failed`. It does not declare a successful clean uninstall when any benchmark-owned artifact is known to remain.
4. If exporting, checksum verification or uninstall fails, **fail closed**: preserve unexported results, report the reason and provide `tsbench uninstall`/manual remediation instructions. Never sacrifice evidence to achieve cleanup.

The plain `tsbench uninstall` command is always available, including when the operator abandons the campaign before run three. It cleans benchmark-owned installation and temporary artifacts conservatively and preserves any results not verified off-VM. Full removal of results requires `--purge` and a verified external export. The default direct-on-VM workflow does **not** delete the only local copy of results automatically. Without an external controller/export destination, present `export_required` after run three and require explicit verified export before purge. This is intentional: it prevents losing the data needed for marketing analysis. Uninstall is **post-run** and may take extra time beyond the 45-minute benchmark deadline.

### 12.4 Validation

Tests must cover: first/second run preservation, counting only valid third runs, checksum/export errors, interruption during cleanup, retained user-owned tools and credentials, pre-existing benchmark dependencies, uninstaller idempotency, malicious/symlinked paths, and residual-file reporting on Ubuntu 24.04 and 26.04.

## 13. Safety, reliability and failure handling

- All disk benchmarks operate only inside a validated temporary directory, with disk-space reserve and cleanup on success, error, Ctrl+C and timeout; no raw-device benchmarking.
- Limit total test-file size and disk writes; report write intensity. No destructive tests on existing filesystems or partitions.
- Restrict working directory, user privileges, permissions and process groups. Avoid root for routine execution.
- Apply timeouts to every subprocess and propagate global deadline. Do not kill other users' processes or Herdr server.
- Use atomic writes for `results.json`; preserve partial measurements after failures and show a clear completion status.
- Check credentials without printing them. Do not upload results or telemetry automatically.
- Maintain local-only results by default; future publication requires an explicit user/operator action and sanitization.
- Handle unsupported fio direct I/O, no swap/PSI available, quota errors, absent Herdr, insufficient RAM/disk, failed tests and OOM as explicit statuses.

## 14. Minimal implementation layout

```text
termsquad-benchmark/
├── README.md
├── pyproject.toml
├── benchmark.yaml
├── docs/
│   └── benchmark-v1-spec.md
├── tsbench/
│   ├── cli.py
│   ├── runner.py
│   ├── inventory.py
│   ├── telemetry.py
│   ├── scoring.py
│   ├── report.py
│   ├── campaign.py
│   ├── uninstall.py
│   ├── hardware/
│   │   ├── cpu.py
│   │   ├── memory.py
│   │   └── disk.py
│   └── agents/
│       ├── codex.py
│       ├── herdr.py
│       ├── single.py
│       └── parallel.py
├── fixtures/
│   └── coding-tasks/
├── schemas/
│   └── result.schema.json
└── tests/
```

Favor one Python package, standard library where practical and thin wrappers around established upstream binaries. No microservices, separate database or second agent orchestration framework.

## 15. Delivery plan

### Milestone A, safe hardware runner

- Implement CLI, preflight, pinned tools, sysbench CPU/RAM, fio disk, telemetry, 45-minute global deadline, JSON and Markdown output.
- Prove it runs on Ubuntu 24.04 and Ubuntu 26.04 and enforces scratch-disk safety.

### Milestone B, real agent suite

- Build/version benchmark fixture and objective validators.
- Integrate Codex with exact GPT-6.1 Terra/xhigh and Herdr with installed-version capability checks.
- Implement single-agent and progressive 4/8/16-agent phases with proper timeouts, external-error classifications and resource telemetry.

### Milestone C, comparison and pilot

- Add `tsbench compare`, metadata/price handling, report validity labels and methodology instructions.
- Implement benchmark-owned install provenance, 3-run campaign counting, external result checksums and controller-triggered third-run uninstall; prove no user-owned tools, sessions or credentials are removed.
- Run first pilots on two candidate VM plans; review correctness, runtime, resource footprint and output quality before additional providers.
- Publish marketing pages **later**, driven by verified benchmark data and a separate review process.

## 16. Definition of done

1. `tsbench setup`, `doctor`, `run --profile full` and `compare` work as documented.
2. Full runs finish or time out **within 2,700 seconds**, including cleanup/report, with structured partial results on failure.
3. Ubuntu 24.04 and 26.04 are both supported; neither is automatically changed. OS differences are recorded and flagged in comparisons.
4. CPU single/multicore, RAM read/write, and disk sequential/random read/write (including IOPS and latency) are measured with units, versioned parameters and raw evidence.
5. GPT-6.1 Terra/xhigh tasks really run with Codex. No silent substitutions. Task success requires immutable validation.
6. Herdr launches parallel agents in isolated benchmark-owned workspaces; supports stages up to 16 where resources/quota permit; `not_tested` is never called `failed`.
7. Rate limits, agent errors and remote-service effects are distinguished from host resource problems wherever observed.
8. No credentials, sensitive environment variables or private user files appear in artifacts; routine operation does not require root.
9. Three comparable complete runs can be aggregated to median-based reports; incompatible runs are rejected or clearly labeled.
10. Tests cover timeouts, cancellation, low disk space, missing tool/auth, absent direct I/O, malformed fixture, failed validators, quota limits and interrupted cleanup.
11. README documents reproducible commands, costs/limits, safety warnings, supported OSes and how to interpret incomplete results.
12. After 3 valid runs, the external LLM/controller verifies exports, invokes the benchmark's own `tsbench uninstall` command for full cleanup and audits the result; earlier, invalid or failed runs do not cause a purge. The same built-in command is available for conservative removal before run three. Any unexported result is preserved. Pre-existing tools, user data, Herdr sessions and Codex credentials remain untouched.
13. Cleanup tests cover ownership tracking, safe package handling, interrupted/partial purge and symlink/path escape defenses.

## 17. Source references and implementation verification

The following upstream references justify the selected external interfaces. **Verify actual installed CLI versions and capabilities during implementation.**

- Ubuntu releases: https://ubuntu.com/project/docs/release-team/list-of-releases/
- GPT-6.1 Terra model ID and reasoning options: https://developers.openai.com/api/docs/models/gpt-6.1-terra
- Codex CLI reference: https://developers.openai.com/codex/cli/reference/
- Herdr CLI and agent automation: https://herdr.dev/tui/docs/agent-automation/
- sysbench: https://github.com/akopytov/sysbench
- fio options, JSON and latency statistics: https://fio.readthedocs.io/en/latest/fio_doc.html
- Linux pressure stall information: https://www.kernel.org/doc/html/latest/accounting/psi.html

---

**Implementation principle:** Accurate, reproducible measurements first. Keep the runner simple, transparent and bounded. Real external-model coding agents are essential to the product-oriented workload, while CPU, RAM and disk results remain independently measurable.