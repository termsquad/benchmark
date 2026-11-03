# Agent instructions

This repository implements the canonical contract in `docs/benchmark-v1-spec.md`.

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
