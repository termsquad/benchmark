# Cancel v1 safely and start v1.1

**Do not begin any additional v1 runs.** The exploratory cohort contains 1 eligible run on each of Netcup and Contabo, using frozen benchmark commit `2489bc6681f7228a3332f7fec805d914a5b8107d`. Keep original output folders, copied evidence and checksums. The v1 PR remains historical, not a ranking.

## Remote cancellation of an existing v1 installation

The v1 binary predates native abort. Execute **v1.1's native CLI implementation** against the v1 campaign state without first calling v1.1 setup or changing the v1 pinned configuration.

1. On the controller, verify that the v1 result folders and their manifests exist and retain independent copies.
2. On each target VM, independently confirm no running benchmark, Herdr workspaces or tsbench-owned processes.
3. Obtain the reviewed `feat/benchmark-v1.1` source checkout in a separate directory. Pin a specific validated commit and run its Python module directly with `PYTHONPATH=/path/to/v1.1-src python3 -m tsbench abort`.
4. Run `PYTHONPATH=/path/to/v1.1-src python3 -m tsbench export --output /path/to/owned-or-private-export.tar.gz`. Export must contain **all** prior runs and raw evidence, not just eligible runs.
5. Copy the archive outside the VM. On the controller, verify the copied bytes with SHA-256 and inspect campaign ID and expected v1 run evidence.
6. Invoke `PYTHONPATH=/path/to/v1.1-src python3 -m tsbench uninstall --purge --aborted --campaign CAMPAIGN_ID --verified-export VERIFIED_SHA256` on the target.
7. Verify `purged` status and that the `~/.local/share/tsbench` state and installer-owned command symlink are gone. If `purged_with_residuals`, do not issue broad deletes.
8. The old manually cloned source checkout, system packages and Codex/Herdr installed by an **external controller** are not automatically assumed benchmark-owned. Audit these separately, preserving pre-existing user installations and credentials.

If any external verification fails, stop, retain local v1 evidence, and **do not purge**.

## Start v1.1

1. Use a clean installation of a single, frozen v1.1 commit on each VM.
2. Run `bash install.sh`, then `tsbench doctor`; the installer compiles the frozen STREAM-style workload using system gcc.
3. Run one genuine full v1.1 E2E test on a dedicated VM before beginning any three-run campaign.
4. Keep model `gpt-6.1-terra`, `xhigh`, Codex and Herdr versions, fixture digest and config identical within the cohort. Ubuntu 24.04 and 26.04 are separate comparison cohorts.
5. If validation succeeds, take three complete runs per VM at least one hour apart, copy and verify artifacts, then use native export/uninstall.
6. Do not merge draft PRs or publish VM rankings until the real sustained workload and native cleanup have passed E2E.

## Codex fixes retained from v1

- Correct unattended Codex CLI flags and Herdr 0.9.5 JSON status parsing.
- Trust limited to generated Git fixture base and worker worktree.
- No premature validator failures when a Herdr agent returns idle/done; no repeated prompts on stalled responses.
- Explicit classification of rate-limits, authentication errors and timeouts.
- Host-guest OOM counters, process-group kill on interruption, worktree cleanup, result hashes and raw evidence sanitization.
- Valid cohorts require matching revision, config, model and tools; duplicate and insufficiently separated runs never satisfy the publication gate.

All these behaviors remain regression-tested in the v1.1 branch. Never delete or bypass the inherited tests to make CI pass.
