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


def _data(args):
    from . import report
    d = report.Data(".", args.version)
    if not d.outputs:
        print(f"no recorded outputs for {args.version} in runs/{args.version}/", file=sys.stderr)
        return None
    return d


def cmd_mutate(args):
    from . import report
    d = _data(args)
    if d is None:
        return EXIT_NO_DATA
    n_seeds, n_mut = report.write_mutants(d)
    if n_seeds == 0:
        print("no correct outputs to use as seeds", file=sys.stderr)
        return EXIT_NO_DATA
    print(f"{n_seeds} seeds -> {n_mut} mutants in runs/{args.version}/mutants.jsonl")
    return EXIT_OK


def cmd_evaluate(args):
    import os

    from . import evaluator
    from .sim_client import SimClient
    key = os.environ.get("SIM_API_KEY")
    wf = args.workflow_id or os.environ.get("SIM_EVAL_WORKFLOW_ID")
    if not key or not wf:
        print("set SIM_API_KEY and SIM_EVAL_WORKFLOW_ID (or --workflow-id)", file=sys.stderr)
        return EXIT_USAGE
    d = _data(args)
    if d is None:
        return EXIT_NO_DATA
    if not d.mutants:
        print(f"no mutants; run `simtriage mutate --version {args.version}` first", file=sys.stderr)
        return EXIT_NO_DATA
    client = SimClient(os.environ.get("SIM_BASE_URL", "http://localhost:3000"), key)
    n_inputs, n_jobs = evaluator.run(client, wf, d, args.repeats, args.concurrency, limit=args.limit)
    print(f"{n_inputs} inputs, {n_jobs} evaluator runs recorded")
    return EXIT_OK


METRICS = ("pass_rate", "label_free_mutation_recall")


def cmd_report(args):
    import json

    from . import report
    d = _data(args)
    if d is None:
        return EXIT_NO_DATA
    if not d.labels:
        print("no labels; nothing to score against", file=sys.stderr)
        return EXIT_NO_DATA
    rep = report.build(d, args.split)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep, indent=2) + "\n")
    value = (rep["regression_pass_rate"] if args.metric == "pass_rate"
             else report.overall_label_free_mutation_recall(d))
    if value is None:
        print(f"metric {args.metric} has no data", file=sys.stderr)
        return EXIT_NO_DATA
    f = rep["fields"]
    print(f"{d.version} / {args.split}: category {f['category']['accuracy']['p']:.2f}  "
          f"priority {f['priority']['accuracy']['p']:.2f}  area {f['product_area']['accuracy']['p']:.2f}  "
          f"needs_human {f['needs_human']['accuracy']['p']:.2f}")
    print(f"{args.metric} = {value['p']:.3f} [{value['lo']:.3f}, {value['hi']:.3f}] (n={value['n']})")
    if args.fail_under is not None and value["p"] < args.fail_under:
        print(f"FAIL: {args.metric} {value['p']:.3f} < --fail-under {args.fail_under}")
        return EXIT_BELOW
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

    mu = sub.add_parser("mutate", help="generate the mutant set from correct outputs")
    mu.add_argument("--version", required=True)
    mu.set_defaults(fn=cmd_mutate)

    ev = sub.add_parser("evaluate", help="score seeds, mutants and natural errors with the Sim Evaluator workflow")
    ev.add_argument("--version", required=True)
    ev.add_argument("--repeats", type=int, default=3)
    ev.add_argument("--concurrency", type=int, default=4)
    ev.add_argument("--limit", type=int, help="only the first N inputs (for a dry run)")
    ev.add_argument("--workflow-id")
    ev.set_defaults(fn=cmd_evaluate)

    rp = sub.add_parser("report", help="rebuild all numbers offline from committed files")
    rp.add_argument("--version", required=True)
    rp.add_argument("--split", choices=("dev", "test", "all"), default="test")
    rp.add_argument("--metric", choices=METRICS, default="pass_rate")
    rp.add_argument("--fail-under", type=float)
    rp.add_argument("--json", help="write the full report here")
    rp.set_defaults(fn=cmd_report)

    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code else EXIT_OK
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
