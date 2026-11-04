# Agent instructions

This branch implements the revised contract in `docs/benchmark-v1.1-spec.md`, based on frozen v1 commit `2489bc6681f7228a3332f7fec805d914a5b8107d`. Preserve all inherited Codex E2E fixes and regression tests.

- Prefer small, reviewed changes to benchmark parameters. Any change to workloads, prompts or validators requires a new suite version and comparison cohort.
- Run `python3 -m unittest discover -s tests -v` and `python3 -m compileall -q tsbench` for changes.
- Never hardcode or fall back from `gpt-6.1-terra` / `xhigh` silently.
- All fio measurements use a fresh regular file, never raw `/dev` devices.
- Do not run destructive benchmarks on production VM workloads.
- Protect Codex auth, SSH credentials and agent conversation text.
- Do not terminate the global Herdr server or unrelated agents.
- A full test requires a prepared Ubuntu test VM and genuine Codex/Herdr credentials. Green CI does not prove full end-to-end validation.
- Preserve every result until it is verified outside the machine. Only the native uninstaller may remove owned campaign assets.
- For operator-controlled three-run campaigns, follow `docs/operator-runbook.md`.

- v1 historical cohort was explicitly stopped after one valid run per VM. Do not resume it, compare it statistically with v1.1, or delete its archived evidence.
- For safe abortion/cleanup of existing v1 installs, follow `docs/v1-to-v1.1-migration.md` rather than bypassing the native CLI.
- Use the compiled frozen STREAM-style binary, validate its source hash, measure enough memory beyond cache and report `limited` on unsupported hosts.
- Agent workload must use multi-file fixture tests and guard against premature Herdr idle/done signals, duplicate prompts, and rate-limit misclassification.

- v1.1.2 generated zero eligible runs in both pilot VMs; its raw evidence is immutable and **never** part of a v1.1.3 statistical cohort.
- v1.1.3 keeps task correctness, sustained capacity, and instrumented measurement validity as distinct signals; **never** force runs to be partial only because verified capacity is below target.
- Herdr idle/done cannot identify a particular completed turn. Preserve the bounded grace, observe source stability, and never resend failed prompts.
- Accumulated time with >=75% of agents observed working on in-flight tasks is the primary capacity diagnostic; the longest continuous span remains available separately. Do not count unsampled gaps as active.
- The CPU PSI and per-worktree RSS series contain no command lines, environment values, or raw agent messages; treat RSS as approximate due to shared pages and subprocess CWD differences.
