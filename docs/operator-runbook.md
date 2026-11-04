# Operator runbook: three-run VM campaign

This document is for an external Codex/Claude controller operating a dedicated VM over SSH. The controller must run **outside** the measured VM.

## Prerequisites

- Use an isolated Ubuntu 24.04 or 26.04 x86_64 VM, with 6+ GiB available disk and no production workloads.
- Review the source and run installation once: clone the repo and execute `bash install.sh` on the target.
- Preinstall sysbench, fio, git, Node, Codex CLI and official Herdr before measuring.
- Authenticate Codex on the target with permission to use `gpt-6.1-terra` at `xhigh`. The controller must not copy auth data.
- Verify the exact model/version and that the Herdr server can launch interactive Codex agents.
- Price, SKU and region are supplied by the operator from a dated published price source.

## Run sequence

1. Run `tsbench doctor`. Stop and report every preflight failure, no silent fallback to another LLM or OS.
2. Start run 1 with `tsbench run --profile full --provider PROVIDER --plan SKU --region REGION --price-monthly PRICE --currency CURRENCY --price-source URL --includes-mandatory-fees`. Include the fee flag only if every mandatory recurring fee is included.
3. Record run ID/status; treat a failed, rate-limited or incomplete result as ineligible. Do not edit frozen task definitions to force success.
4. Repeat in **at least one-hour-separated windows**, collecting three valid runs. The controller does not need a server daemon or scheduler; the host agent may initiate each new invocation.
5. Inspect `tsbench status` and ensure `eligible_runs` contains exactly three distinct IDs with a consistent config.
6. Invoke `tsbench export`. It creates the owned archive under `~/.local/share/tsbench/exports/benchmark-export.tar.gz` and prints the SHA256 and campaign ID. No automatic uploads take place.
7. Copy this archive to a separate operator-controlled machine using SSH/SCP or SFTP. Compute SHA256 on that machine and confirm an **exact match**. Inspect the archive and preserve an independent backup.
8. Only now invoke the native `tsbench uninstall --purge --campaign CAMPAIGN_ID --verified-export SHA256` on the target.
9. Verify the reported uninstall status is `purged`, not `purged_with_residuals`; check that `~/.local/share/tsbench` and the benchmark-owned `~/.local/bin/tsbench` symlink no longer exist.
10. Retain the external archive and machine/price manifest for the provider comparison. Do not post results publicly without reviewing dates, model/API constraints and comparable OS cohorts.

## Safety rules for autonomous controllers

- Never run broad `rm -rf` commands to clean the benchmark. Use the built-in uninstall.
- Never remove Codex, Herdr, user projects, authentication files or pre-existing system packages.
- Never treat `not_tested`, `inconclusive`, `externally_constrained` or `rate_limited` as poor VM performance.
- Never claim a validated concurrency stage is the VM's maximum capacity.
- Never publish raw Codex events or environment variables.
- If the archive cannot be copied and verified externally, **do not purge**. Export or fix the failure first.
- A manual source checkout is user-owned and not deleted by the native uninstaller. Remove it only with an explicit, independent owner decision.

## Publication gate

For each provider/SKU/region/OS cohort, publish medians only after 3 complete comparable runs at separated times. Show observed dispersion and expose the exact spec, benchmark version, dated price source, measured data and limitations.
