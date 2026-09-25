"""simtriage CLI.

Exit codes: 0 pass, 1 below threshold (or incomplete), 2 usage error, 3 no data.
"""
import argparse
import sys
from pathlib import Path

EXIT_OK, EXIT_BELOW, EXIT_USAGE, EXIT_NO_DATA = 0, 1, 2, 3


def cmd_label(args):
    from . import labeling
    if not Path(args.issues).exists():
        print(f"no issues file: {args.issues}", file=sys.stderr)
        return EXIT_NO_DATA
    if args.recheck:
        if not Path(args.labels).exists():
            print("recheck needs existing labels", file=sys.stderr)
            return EXIT_NO_DATA
        ids = labeling.recheck_ids(args.labels, args.recheck, args.seed)
        return labeling.run(args.issues, args.recheck_out, only_ids=ids)
    return labeling.run(args.issues, args.labels)


def cmd_run(args):
    import json
    import os

    from . import runner
    from .sim_client import SimClient

    key = os.environ.get("SIM_API_KEY")
    wf = args.workflow_id or os.environ.get("SIM_TRIAGE_WORKFLOW_ID")
    if not key or not wf:
        print("set SIM_API_KEY and SIM_TRIAGE_WORKFLOW_ID (or --workflow-id)", file=sys.stderr)
        return EXIT_USAGE
    if not Path(args.issues).exists():
        print(f"no issues file: {args.issues}", file=sys.stderr)
        return EXIT_NO_DATA
    issues = [json.loads(l) for l in open(args.issues)]
    if args.split != "all":
        ids = set(json.load(open(args.split_file))[args.split])
        issues = [i for i in issues if i["id"] in ids]
    if not issues:
        print("no issues selected", file=sys.stderr)
        return EXIT_NO_DATA
    out = args.out or f"runs/{args.version}/outputs.jsonl"
    client = SimClient(os.environ.get("SIM_BASE_URL", "http://localhost:3000"), key)
    try:
        n = runner.run(client, wf, issues, args.version, out, args.repeats, args.concurrency)
    except runner.ContaminationError as e:
        print(f"refused: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(f"recorded {n} runs to {out}")
    return EXIT_OK


def main(argv=None):
    p = argparse.ArgumentParser(prog="simtriage")
    sub = p.add_subparsers(dest="cmd", required=True)

    lab = sub.add_parser("label", help="hand-label issues in the terminal")
    lab.add_argument("--issues", default="data/issues.jsonl")
    lab.add_argument("--labels", default="data/labels.jsonl")
    lab.add_argument("--recheck", type=int, metavar="N",
                     help="blind-relabel N seeded random already-labeled issues")
    lab.add_argument("--recheck-out", default="data/labels_recheck.jsonl")
    lab.add_argument("--seed", type=int, default=20260926)
    lab.set_defaults(fn=cmd_label)

    rn = sub.add_parser("run", help="run issues through the deployed Sim workflow")
    rn.add_argument("--issues", default="data/issues.jsonl")
    rn.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    rn.add_argument("--split-file", default="data/split.json")
    rn.add_argument("--version", required=True, help="prompt version tag, e.g. v1")
    rn.add_argument("--repeats", type=int, default=3)
    rn.add_argument("--concurrency", type=int, default=4)
    rn.add_argument("--workflow-id")
    rn.add_argument("--out")
    rn.set_defaults(fn=cmd_run)

    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code else EXIT_OK
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
