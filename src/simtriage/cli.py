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

    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code else EXIT_OK
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
