"""simtriage CLI.

Exit codes: 0 pass, 1 below threshold, 2 usage error, 3 no data.
"""
import argparse
import json
import os
import sys
from pathlib import Path

EXIT_OK, EXIT_BELOW, EXIT_USAGE, EXIT_NO_DATA = 0, 1, 2, 3
DATASETS = ("sim", "k8s")
METRICS = ("pass_rate", "label_free_mutation_recall")


def _client():
    from .sim_client import SimClient
    return SimClient(os.environ.get("SIM_BASE_URL", "http://localhost:3000"), os.environ["SIM_API_KEY"])


def _data(args):
    from . import report
    d = report.Data(".", args.dataset, args.version, getattr(args, "key", "original"))
    if not d.outputs:
        print(f"no recorded outputs in {d.run_dir}/", file=sys.stderr)
        return None
    return d


def cmd_run(args):
    from . import runner
    env = f"SIM_{args.dataset.upper()}_WORKFLOW_ID"
    wf = args.workflow_id or os.environ.get(env)
    if not os.environ.get("SIM_API_KEY") or not wf:
        print(f"set SIM_API_KEY and {env} (or --workflow-id)", file=sys.stderr)
        return EXIT_USAGE
    path = Path(args.issues or f"data/{args.dataset}/issues.jsonl")
    if not path.exists():
        print(f"no issues file: {path}", file=sys.stderr)
        return EXIT_NO_DATA
    issues = [json.loads(l) for l in path.open()]
    if args.split != "file":
        split = json.load(open(f"data/{args.dataset}/split.json"))
        ids = set(split["dev"] + split["test"]) if args.split == "all" else set(split[args.split])
        issues = [i for i in issues if i["id"] in ids]
    if args.limit:
        issues = issues[:args.limit]
    if not issues:
        print("no issues selected", file=sys.stderr)
        return EXIT_NO_DATA
    out = args.out or f"runs/{args.dataset}/{args.version}/outputs.jsonl"
    try:
        n = runner.run(_client(), wf, issues, args.version, out, args.repeats, args.concurrency,
                       dataset=None if args.split == "file" else args.dataset)
    except runner.ContaminationError as e:
        print(f"refused: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(f"recorded {n} runs to {out}")
    return EXIT_OK


def cmd_mutate(args):
    from . import report
    d = _data(args)
    if d is None:
        return EXIT_NO_DATA
    n_seeds, n_mut = report.write_mutants(d)
    if n_seeds == 0:
        print("no correct outputs to use as seeds", file=sys.stderr)
        return EXIT_NO_DATA
    print(f"{n_seeds} seeds -> {n_mut} mutants in {d.run_dir}/mutants.jsonl")
    return EXIT_OK


def cmd_evaluate(args):
    from . import evaluator
    wf = args.workflow_id or os.environ.get("SIM_EVAL_WORKFLOW_ID")
    if not args.dry_run and (not os.environ.get("SIM_API_KEY") or not wf):
        print("set SIM_API_KEY and SIM_EVAL_WORKFLOW_ID (or --workflow-id)", file=sys.stderr)
        return EXIT_USAGE
    d = _data(args)
    if d is None:
        return EXIT_NO_DATA
    if not d.mutants:
        print(f"no mutants; run `simtriage mutate --dataset {args.dataset} --version {args.version}`",
              file=sys.stderr)
        return EXIT_NO_DATA
    if args.dry_run:
        rows = evaluator.build_inputs(d) if args.sample else evaluator.build_inputs(d, None, None, None)
        jobs = evaluator.plan_jobs(rows) if args.sample else evaluator.plan_full(rows, args.repeats)
        print(f"{args.dataset}: {len(rows)} inputs, {len(jobs)} evaluator calls planned")
        return EXIT_OK
    n_inputs, n_jobs = evaluator.run(_client(), wf, d, args.concurrency, limit=args.limit,
                                     sample=args.sample, repeats=args.repeats)
    print(f"{n_inputs} inputs, {n_jobs} evaluator runs recorded")
    return EXIT_OK


def cmd_adjudicate(args):
    from . import adjudicate
    return (adjudicate.run_key if args.queue == "key" else adjudicate.run_gates)(".", args.version)


def cmd_report(args):
    from . import report
    d = _data(args)
    if d is None:
        return EXIT_NO_DATA
    if not d.key:
        print("no answer key; nothing to score against", file=sys.stderr)
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
    for f, m in rep["fields"].items():
        acc = m.get("accuracy", m) if isinstance(m, dict) else None
        if acc:
            print(f"  {f:18s} {acc['p']:.3f} [{acc['lo']:.3f}, {acc['hi']:.3f}] n={acc['n']}")
    print(f"{d.dataset}/{d.version}/{args.split}: {args.metric} = {value['p']:.3f} "
          f"[{value['lo']:.3f}, {value['hi']:.3f}] (n={value['n']})")
    if args.fail_under is not None and value["p"] < args.fail_under:
        print(f"FAIL: {args.metric} {value['p']:.3f} < --fail-under {args.fail_under}")
        return EXIT_BELOW
    return EXIT_OK


def main(argv=None):
    p = argparse.ArgumentParser(prog="simtriage")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, version_required=True):
        sp.add_argument("--dataset", choices=DATASETS, required=True)
        sp.add_argument("--version", required=version_required, help="prompt version, e.g. v1")

    rn = sub.add_parser("run", help="run issues through the deployed Sim triage workflow")
    common(rn)
    rn.add_argument("--split", choices=("dev", "test", "all", "queue", "file"), default="dev",
                    help="'file' = every issue in --issues (for out-of-sample practice files)")
    rn.add_argument("--issues")
    rn.add_argument("--repeats", type=int, default=3)
    rn.add_argument("--concurrency", type=int, default=4)
    rn.add_argument("--limit", type=int, help="only the first N selected issues (smoke tests)")
    rn.add_argument("--workflow-id")
    rn.add_argument("--out")
    rn.set_defaults(fn=cmd_run)

    mu = sub.add_parser("mutate", help="generate the mutant set from correct outputs")
    common(mu)
    mu.set_defaults(fn=cmd_mutate)

    ev = sub.add_parser("evaluate", help="score seeds, mutants and natural errors with Sim's Evaluator")
    common(ev)
    ev.add_argument("--concurrency", type=int, default=3)
    ev.add_argument("--limit", type=int, help="only the first N inputs")
    ev.add_argument("--repeats", type=int, default=3)
    ev.add_argument("--sample", action="store_true",
                    help="cheaper sampled plan (40 per operator, 1 run + variance subset)")
    ev.add_argument("--dry-run", action="store_true", help="print the planned call count; no API calls")
    ev.add_argument("--workflow-id")
    ev.set_defaults(fn=cmd_evaluate)

    ad = sub.add_parser("adjudicate", help="human review: blind key disagreements or gate failures")
    ad.add_argument("--queue", choices=("key", "gates"), required=True)
    ad.add_argument("--version", default="v1")
    ad.set_defaults(fn=cmd_adjudicate)

    rp = sub.add_parser("report", help="rebuild all numbers offline from committed files")
    common(rp)
    rp.add_argument("--split", choices=("dev", "test", "all", "queue"), default="test")
    rp.add_argument("--key", choices=("original", "adjudicated"), default="original",
                    help="original = independent answer key (primary)")
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
