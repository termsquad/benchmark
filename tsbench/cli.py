"""TermSquad Benchmark command line interface."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
from .common import BenchmarkError, atomic_json, load_json, sha256_file
from .campaign import state_dir, state_file, initialize, abort_campaign
from .inventory import inventory, verify_host, herdr_server_ready
from .runner import run as run_benchmark
from .compare import compare as compare_runs
from .uninstall import uninstall, export_campaign


def parser():
    p = argparse.ArgumentParser(prog="tsbench",description="VM benchmark for real AI coding agents")
    sub=p.add_subparsers(dest="command",required=True)
    setup=sub.add_parser("setup",help="Prepare local campaign state; does not install apt packages")
    setup.add_argument("--config",type=Path,default=Path("benchmark.yaml"))
    doc=sub.add_parser("doctor",help="Read-only compatibility checks")
    doc.add_argument("--hardware-only",action="store_true")
    run=sub.add_parser("run",help="Run strict 45-minute full benchmark")
    run.add_argument("--profile",choices=["full"],default="full")
    run.add_argument("--config",type=Path,default=Path("benchmark.yaml"))
    for flag in ("provider","plan","region","currency"):
        run.add_argument("--"+flag)
    run.add_argument("--price-monthly",type=float)
    run.add_argument("--price-source",help="URL documenting recurring monthly plan cost")
    run.add_argument("--includes-mandatory-fees",action="store_true",default=None)
    cmp=sub.add_parser("compare",help="Compare verified JSON results in compatible cohorts")
    cmp.add_argument("results",type=Path,nargs="+")
    sub.add_parser("status",help="Show local 3-run campaign progress")
    sub.add_parser("abort",help="Stop campaign permanently; preserve and export all existing runs")
    exp=sub.add_parser("export",help="Build a checksum-verifiable campaign archive")
    exp.add_argument("--output",type=Path,help="Archive path; defaults to managed exports directory")
    delete=sub.add_parser("uninstall",help="Remove only benchmark-owned installation assets")
    delete.add_argument("--purge",action="store_true",help="Remove local results after confirmed external export")
    delete.add_argument("--aborted",action="store_true",help="Allow purge of an explicitly aborted campaign")
    delete.add_argument("--campaign")
    delete.add_argument("--verified-export")
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    root=state_dir()
    try:
        if args.command=="setup":
            config=args.config.expanduser().absolute()
            cfg=load_json(config)
            from .common import run_command
            revision=run_command(["git","-C",str(config.parent),"rev-parse","HEAD"],5) if shutil.which("git") else {"returncode":1}
            benchmark_commit=revision.get("stdout","").strip() if revision["returncode"]==0 else None
            state=initialize(root,cfg["suite_version"],sha256_file(config),benchmark_commit)
            # Copy the immutable config into our own state so benchmark runs can be
            # invoked later from any directory. Never overwrite a different config.
            pinned=root/"benchmark.yaml"
            if not pinned.exists():
                shutil.copy2(config,pinned)
            elif sha256_file(pinned)!=sha256_file(config):
                raise BenchmarkError("Pinned campaign configuration differs")
            atomic_json(root/"ownership.json",{"root":str(root),"benchmark_commit":benchmark_commit,"managed":["benchmark.yaml","campaign.json",
                "results","scratch","tmp","venv","ownership.json"]})
            from .hardware import build_memory_binary
            memory_binary=root/"bin"/"tsbench-stream"
            if not memory_binary.exists():
                memory_build=build_memory_binary(memory_binary)
                atomic_json(root/"memory-build.json",memory_build)
            output={"status":"prepared","campaign_id":state["campaign_id"],
                    "config":str(pinned),"missing_tools":verify_host(inventory(root),True)}
        elif args.command=="doctor":
            machine=inventory(Path.cwd())
            errors=verify_host(machine,not args.hardware_only)
            if not args.hardware_only and shutil.which("codex"):
                from .common import run_command
                auth=run_command(["codex","login","status"],10)
                if auth["returncode"]!=0:
                    errors.append("Codex authentication is not ready")
            if not args.hardware_only and shutil.which("herdr"):
                from .common import run_command
                status=run_command(["herdr","status","server","--json"],10)
                if not herdr_server_ready(status):
                    errors.append("Herdr server is not reachable")
            output={"status":"ready" if not errors else "invalid_environment","errors":errors,"machine":machine}
        elif args.command=="run":
            config=args.config
            if str(config)=="benchmark.yaml" and (root/"benchmark.yaml").exists():
                config=root/"benchmark.yaml"
            if not state_file(root).exists():
                raise BenchmarkError("Run tsbench setup first")
            result=run_benchmark(config,root,provider=args.provider,plan=args.plan,
                                 region=args.region,price=args.price_monthly,currency=args.currency,
                                 price_source=args.price_source,includes_mandatory_fees=args.includes_mandatory_fees)
            output={"status":result["status"],"run_id":result["run_id"],"results":str(root/"results"/result["run_id"])}
        elif args.command=="compare":
            output=compare_runs(args.results)
        elif args.command=="abort":
            from .runner import exclusive
            with exclusive(root):
                output=abort_campaign(root)
        elif args.command=="status":
            output=load_json(state_file(root))
            output["ready_for_export"]=len(output["eligible_runs"])>=3
        elif args.command=="export":
            destination=args.output or (root/"exports"/"benchmark-export.tar.gz")
            output=export_campaign(root,destination)
            output["instructions"]="Copy archive to a separate machine, verify SHA256 there, then invoke uninstall --purge with matching campaign and digest"
        elif args.command=="uninstall":
            output=uninstall(root,args.purge,args.campaign,args.verified_export,args.aborted)
        else:
            raise BenchmarkError("Unknown command")
        print(json.dumps(output,indent=2,sort_keys=True))
        if args.command=="doctor" and output["errors"]:
            return 2
        if args.command=="run" and output["status"]!="complete":
            return 2
        return 0
    except (OSError,KeyError,ValueError,BenchmarkError) as exc:
        print(json.dumps({"status":"error","reason":str(exc)}),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
