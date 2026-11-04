# TermSquad Benchmark v1.1.3, targeted corrections

**Baseline:** commit `3391d030349b11f85f73bc482ac91dbcd520ec6d`, suite `1.1.2`.  
**Scope:** address the real Netcup/Contabo E2E pilot without rebuilding the benchmark.

## Historical pilot evidence

Both 1.1.2 runs were **partial** and both campaigns have **zero eligible runs**.
Each VM completed the hardware tests and the single Codex task, but all 4/8/16-agent
stages fell short of the old 120-second **continuous** Herdr working threshold.
The raw archives and original reports must be kept unmodified.

The old continuous lengths (4/8/16) were:
- Netcup: 54.1 / 66.2 / 68.6 seconds.
- Contabo: 69.0 / 87.2 / 72.2 seconds.

The v1.1.2 raw records also show `failed_tests`, early terminal states,
timeouts and other agent errors. These are **not proof** that the VM hardware
caused the failure. Some task contracts were under-specified.

## Focused fixes in 1.1.3

### Validity versus capacity

A stage is **measured** if work was attempted, Herdr activity has sufficient
sampling coverage and the required host telemetry is available. A correctly
measured but below-target stage has `status=measured` and
`capacity_status=below_target_observed`; it does **not** invalidate the full
run merely for lacking 120 sustained seconds or a 75% pass fraction.

Unknown external rate/quota effects or missing activity evidence remain
`externally_constrained` or `inconclusive_telemetry` and cannot silently
become valid host-capacity observations. Guest OOM remains a distinct
resource-limit signal.

### Effective concurrency

Measure:
- **Cumulative qualifying seconds:** add sampled intervals with at least
  75% of benchmark-owned agents in Herdr `working`, each paired with an
  in-flight task interval.
- **Mean occupancy:** sampled busy agent-seconds divided by the total
  possible agent-seconds in the stage.
- **Longest uninterrupted qualifying window:** retain separately as a
  diagnostic, not the sole eligibility gate.
- **Coverage:** only accept actual bounded Herdr samples, never synthesize
  activity across missing samples or long gaps. At least 85% of the
  stage's duration must be covered for a valid observation.
- **Task quality:** retain completed, failed, stalled, timed-out, and
  model-external errors, correct tasks/min, pass fraction and latency.

The cumulative 120-second target remains a **capacity objective**, not a
minimum duration imposed on the validity of an execution.

### Agent completion

Herdr's `agent prompt --wait` observes lifecycle transitions, **not**
a reliable turn-specific completion ID. A `done` or `idle` status alone is
insufficient to call an agent's task finished.

After a returned/premature terminal state the controller:
1. Checks the immutable task validator.
2. Verifies that the relevant source files stopped changing.
3. Waits a bounded confirmation grace (12 seconds by default).
4. Returns `failed_tests` only after observed Herdr activity and stable
   terminal state with no test success.
5. Resets the grace if working resumes or source changes.

An unobserved stalled prompt must not be mistaken for a completed coding
task. Inherited no-duplicate-prompt protections remain unchanged.

### Fixture clarity

Clarify the exact **per-unit floor-before-quantity** discount calculation
required by the already immutable price validator. Specify coalescing
duplicate SKUs, positive integer quantities, immutable inventory updates
and observable errors for insufficient stock. Keep all independent
validators and reference solutions. Do **not** drop failing scenarios,
change assertions to inflate pass rates, or assume model mistakes are
host failures.

### Host and per-agent instrumentation

Preserve CPU PSI in the stage summary and full bounded resource sample
series. Include best-effort per-worktree RSS based on Linux `/proc` CWD
matching, with no process arguments, PIDs, secrets, source content or raw
agent messages. The RSS estimate may include shared pages and miss
subprocesses that leave the worktree; never call it exact process PSS.

## Version and campaign policy

The methodology and task prompts have changed, so **suite 1.1.3 is a new
statistical cohort**. Do not replace historical 1.1.2 evidence in-place,
and never merge 1.1.2 and 1.1.3 in one controlled comparison.

Before installing 1.1.3, export/checksum the old partial 1.1.2 run on
the controller. Safely terminate the previous campaign and use the
native `abort`/verified `uninstall --purge --aborted` flow, then install
the frozen new commit. Preserve Codex, Herdr, credentials, user files and
TermSquad services. Do not bulk-delete worktrees or global Herdr services.

Do not begin three-run provider campaigns until CI is green and at
least one **genuine** E2E validation run on each VM confirms no leaked
sessions, realistic task completion and the 45-minute hard boundary.
No claim of real E2E validation is made by these code changes alone.

## References

- Historical raw archives `v112-netcup.tar.gz` and `v112-contabo.tar.gz`.
- Official Herdr agent automation: https://herdr.dev/tui/docs/agent-automation/
- Canonical methodology: `docs/benchmark-v1.1-spec.md`.
