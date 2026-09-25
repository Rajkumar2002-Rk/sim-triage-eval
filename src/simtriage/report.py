"""Build every reported number from committed files. No network, no secrets."""
import json
from collections import defaultdict
from pathlib import Path

from . import gates, mutations, schema
from .gates import FAIL
from .stats import cohen_kappa, macro_f1, percentile, wilson

FIELDS = gates.LABEL_FIELDS


def load_jsonl(path):
    p = Path(path)
    return [json.loads(l) for l in p.open() if l.strip()] if p.exists() else []


def by_id(rows, key="id"):
    return {r[key]: r for r in rows}


class Data:
    def __init__(self, root=".", version="v1"):
        r = Path(root)
        self.version = version
        self.issues = by_id(load_jsonl(r / "data/issues.jsonl"))
        self.labels = by_id(load_jsonl(r / "data/labels.jsonl"))
        self.split = json.load(open(r / "data/split.json"))
        self.outputs = [o for o in load_jsonl(r / f"runs/{version}/outputs.jsonl")
                        if o.get("version") == version]
        self.mutants = load_jsonl(r / f"runs/{version}/mutants.jsonl")
        self.evaluator = load_jsonl(r / f"runs/{version}/evaluator.jsonl")
        self.adjudications = by_id(load_jsonl(r / "data/adjudications.jsonl"), "record_id")
        self.recheck = by_id(load_jsonl(r / "data/labels_recheck.jsonl"))
        self.maintainer = by_id(load_jsonl(r / "data/maintainer_labels_HIDDEN.jsonl"))

    def ids(self, split):
        return sorted(self.issues) if split == "all" else sorted(self.split[split])

    def primary(self, split):
        """Repeat 0 of each issue: the output the metrics are computed on."""
        ids = set(self.ids(split))
        return {o["issue_id"]: o for o in self.outputs if o["repeat"] == 0 and o["issue_id"] in ids}


def ok_exec(o):
    return o.get("http_status") == 200 and o.get("exec_status") == "completed"


def parsed(o):
    obj, _ = gates.parse(o.get("triage"))
    return obj


def field_metrics(d, split):
    prim = d.primary(split)
    ids = [i for i in d.ids(split) if i in prim and i in d.labels]
    out = {}
    for f in FIELDS:
        gold = [d.labels[i][f] for i in ids]
        pred = [(parsed(prim[i]) or {}).get(f) for i in ids]
        m = {"accuracy": wilson(sum(g == p for g, p in zip(gold, pred)), len(ids))}
        if f == "category":
            m["macro_f1"] = macro_f1(gold, pred, schema.CATEGORIES)
        if f == "product_area":
            m["macro_f1"] = macro_f1(gold, pred, schema.PRODUCT_AREAS)
        if f == "priority":
            near = sum(p in schema.PRIORITIES and abs(schema.priority_rank(p) - schema.priority_rank(g)) <= 1
                       for g, p in zip(gold, pred))
            m["within_one"] = wilson(near, len(ids))
        if f == "needs_human":
            tp = sum(g is True and p is True for g, p in zip(gold, pred))
            m["precision_true"] = wilson(tp, sum(p is True for p in pred))
            m["recall_true"] = wilson(tp, sum(g is True for g in gold))
        out[f] = m
    all_four = sum(all((parsed(prim[i]) or {}).get(f) == d.labels[i][f] for f in FIELDS) for i in ids)
    out["all_four_fields"] = wilson(all_four, len(ids))
    return out


def stability(d, split):
    ids = set(d.ids(split))
    runs = defaultdict(list)
    for o in d.outputs:
        if o["issue_id"] in ids:
            runs[o["issue_id"]].append(parsed(o))
    full = {i: r for i, r in runs.items() if len(r) >= 2}
    res = {}
    for f in FIELDS:
        same = sum(len({json.dumps((x or {}).get(f)) for x in r}) == 1 for r in full.values())
        res[f] = wilson(same, len(full))
    return res


def gate_rates(d, split):
    prim = d.primary(split)
    res = {}
    for g in gates.LABEL_FREE:
        statuses = [gates.label_free(o.get("triage"), d.issues[i]).by_gate()[g].status for i, o in prim.items()]
        res[g] = {"fail": wilson(statuses.count(FAIL), len(statuses)), "skipped": statuses.count("skip")}
    return res


def telemetry(d, split):
    ids = set(d.ids(split))
    outs = [o for o in d.outputs if o["issue_id"] in ids]
    agent_ms = [s["duration_ms"] for o in outs for s in (o.get("log") or {}).get("spans", [])
                if s.get("type") == "agent"]
    costs = [((o.get("log") or {}).get("cost") or {}).get("total") for o in outs]
    costs = [c for c in costs if isinstance(c, (int, float))]
    return {
        "runs": len(outs),
        "execution_failures": wilson(sum(not ok_exec(o) for o in outs), len(outs)),
        "client_ms": {"p50": percentile([o.get("client_ms") for o in outs], 0.5),
                      "p95": percentile([o.get("client_ms") for o in outs], 0.95)},
        "server_total_ms": {"p50": percentile([(o.get("log") or {}).get("total_ms") for o in outs], 0.5),
                            "p95": percentile([(o.get("log") or {}).get("total_ms") for o in outs], 0.95)},
        "agent_block_ms": {"p50": percentile(agent_ms, 0.5), "p95": percentile(agent_ms, 0.95)},
        "cost_per_100_runs_usd": round(100 * sum(costs) / len(costs), 4) if costs else None,
        "log_poll_wait_s_max": max(((o.get("log") or {}).get("poll_wait_s") or 0) for o in outs) if outs else None,
    }


def seeds(d):
    """Correct outputs: pass every label-free gate and match the label on all four fields."""
    prim = d.primary("all")
    out = []
    for i, o in sorted(prim.items()):
        obj = parsed(o)
        if (i in d.labels and obj is not None
                and gates.label_free(obj, d.issues[i]).passed_all()
                and all(obj.get(f) == d.labels[i][f] for f in FIELDS)):
            out.append({"issue_id": i, "output": obj})
    return out


def natural_errors(d, split="all"):
    prim = d.primary(split)
    errs = []
    for i, o in sorted(prim.items()):
        obj = parsed(o)
        if i in d.labels and (obj is None or any(obj.get(f) != d.labels[i][f] for f in FIELDS)):
            errs.append({"issue_id": i, "output": o.get("triage")})
    return errs


def caught(output, issue, label):
    v = gates.check(output, issue, label)
    free = bool(v.failed(gates.LABEL_FREE))
    dep = bool(v.failed(gates.LABEL_DEPENDENT))
    return {"label_free": free, "label_dependent": dep, "union": free or dep}


def evaluator_flags(d, cutoff=3, min_votes=2):
    """input_id -> flagged, under the pre-registered rule (any metric <= cutoff in >= 2 of 3 repeats)."""
    votes = defaultdict(list)
    for r in d.evaluator:
        scores = r.get("scores") or {}
        vals = [scores.get(m) for m in ("classification", "faithfulness", "consistency")]
        if r.get("ok") and all(isinstance(v, (int, float)) for v in vals):
            votes[r["input_id"]].append(min(vals) <= cutoff)
    return {k: sum(v) >= min_votes for k, v in votes.items() if len(v) >= min_votes}


def mutation_recall(d):
    flags = evaluator_flags(d)
    per = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    not_applicable = defaultdict(int)
    for m in d.mutants:
        if not m["applicable"]:
            not_applicable[m["operator"]] += 1
            continue
        c = caught(m["output"], d.issues[m["issue_id"]], d.labels[m["issue_id"]])
        if m["mutant_id"] in flags:
            c["evaluator"] = flags[m["mutant_id"]]
        for checker, hit in c.items():
            per[m["operator"]][checker][0] += hit
            per[m["operator"]][checker][1] += 1
    table = {op: {ch: wilson(k, n) for ch, (k, n) in v.items()} for op, v in per.items()}
    return {"by_operator": table, "not_applicable": dict(not_applicable)}


def evaluator_sweep(d):
    """Detection on mutants and flag rate on seeds for every cutoff (1 to 4). All shown."""
    seed_ids = {f"seed:{s['issue_id']}" for s in seeds(d)}
    mutant_ids = {m["mutant_id"] for m in d.mutants if m["applicable"]}
    rows = {}
    for cutoff in (1, 2, 3, 4):
        flags = evaluator_flags(d, cutoff=cutoff)
        rows[cutoff] = {
            "mutant_detection": wilson(sum(flags.get(i, False) for i in mutant_ids & set(flags)),
                                       len(mutant_ids & set(flags))),
            "seed_flag_rate": wilson(sum(flags.get(i, False) for i in seed_ids & set(flags)),
                                     len(seed_ids & set(flags))),
        }
    return rows


def label_reliability(d):
    out = {}
    common = sorted(set(d.recheck) & set(d.labels))
    if common:
        out["recheck_n"] = len(common)
        for f in FIELDS:
            a = [d.labels[i][f] for i in common]
            b = [d.recheck[i][f] for i in common]
            out[f] = {"agreement": wilson(sum(x == y for x, y in zip(a, b)), len(a)),
                      "kappa": cohen_kappa(a, b)}
    mapping = {"bug": {"bug"}, "feature": {"feature_request", "integration_request"}}
    pairs = []
    for i, lab in d.labels.items():
        m = set(d.maintainer.get(i, {}).get("labels", [])) & set(mapping)
        if len(m) == 1:
            pairs.append(lab["category"] in mapping[m.pop()])
    if pairs:
        out["maintainer_bug_feature_agreement"] = wilson(sum(pairs), len(pairs))
    return out


def natural_error_detection(d, split="all"):
    """Real model mistakes (disagree with labels): which checkers notice them without labels?"""
    errs = natural_errors(d, split)
    flags = evaluator_flags(d)
    lf = sum(bool(gates.label_free(e["output"], d.issues[e["issue_id"]]).failed()) for e in errs)
    judged = [e for e in errs if f"natural:{e['issue_id']}" in flags]
    ev = sum(flags[f"natural:{e['issue_id']}"] for e in judged)
    return {"n_errors": len(errs), "label_free": wilson(lf, len(errs)),
            "evaluator": wilson(ev, len(judged))}


def overall_label_free_mutation_recall(d):
    k = n = 0
    for m in d.mutants:
        if m["applicable"]:
            k += caught(m["output"], d.issues[m["issue_id"]], d.labels[m["issue_id"]])["label_free"]
            n += 1
    return wilson(k, n)


def regression_pass_rate(d, split):
    prim = d.primary(split)
    ids = [i for i in prim if i in d.labels]
    ok = sum(gates.check(prim[i].get("triage"), d.issues[i], d.labels[i]).passed_all() for i in ids)
    return wilson(ok, len(ids))


def build(d, split):
    return {
        "version": d.version, "split": split,
        "n_labeled": len(d.labels), "n_outputs": len(d.outputs),
        "fields": field_metrics(d, split),
        "stability_across_repeats": stability(d, split),
        "label_free_gate_failure_rates": gate_rates(d, split),
        "regression_pass_rate": regression_pass_rate(d, split),
        "telemetry": telemetry(d, split),
        "mutation": mutation_recall(d) if d.mutants else None,
        "natural_errors": natural_error_detection(d, split),
        "evaluator_sweep": evaluator_sweep(d) if d.evaluator else None,
        "label_reliability": label_reliability(d),
    }


def write_mutants(d, path=None):
    path = path or f"runs/{d.version}/mutants.jsonl"
    seed_rows = seeds(d)
    muts = mutations.generate(seed_rows, d.issues)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for m in muts:
            f.write(json.dumps(m) + "\n")
    return len(seed_rows), len(muts)
