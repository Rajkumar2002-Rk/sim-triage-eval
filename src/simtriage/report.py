"""Build every reported number from committed files. No network, no secrets.

Layout per dataset (customer) `ds`:
  data/<ds>/issues.jsonl        issue text as the workflow saw it
  data/<ds>/answer_key.jsonl    independent answer key; a record holds only the
                                fields that have one; a value may be a list of
                                acceptable answers
  data/<ds>/split.json          dev / test (have a key) and queue (no key)
  data/<ds>/adjudications.jsonl human decisions made after seeing outputs
  runs/<ds>/<version>/          outputs, mutants, evaluator scores
"""
import json
from collections import defaultdict
from pathlib import Path

from . import gates, mutations, schema
from .gates import FAIL
from .stats import macro_f1, percentile, wilson

FIELDS = schema.FIELDS
SIM_BASE_EXECUTION_FEE = 0.005   # BASE_EXECUTION_CHARGE in Sim's lib/billing/constants.ts
EVAL_METRICS = ("classification", "faithfulness", "consistency")


def load_jsonl(path):
    p = Path(path)
    return [json.loads(l) for l in p.open() if l.strip()] if p.exists() else []


def by_id(rows, key="id"):
    return {r[key]: r for r in rows}


def apply_adjudications(key, adjudications):
    """Answer key after the human settled key-vs-model disagreements.
    The committed answer key is never edited; this is a derived view."""
    out = {k: dict(v) for k, v in key.items()}
    for a in adjudications:
        if a.get("kind") == "key_disagreement" and a["issue_id"] in out:
            out[a["issue_id"]][a["field"]] = a["final"]
    return out


def best_records(rows, key):
    """One record per key: the last one that reached Sim and wasn't rate-limited,
    else the last attempt. Every attempt stays in the file for telemetry."""
    best = {}
    for r in rows:
        k = tuple(r[f] for f in key)
        done = r.get("http_status") not in (None, 429)
        if done or k not in best or best[k].get("http_status") in (None, 429):
            best[k] = r
    return list(best.values())


class Data:
    def __init__(self, root=".", dataset="sim", version="v1", key="original"):
        r = Path(root)
        base = r / "data" / dataset
        self.dataset, self.version, self.key_mode = dataset, version, key
        self.tax = schema.get(dataset)
        self.issues = by_id(load_jsonl(base / "issues.jsonl"))
        self.adjudications = load_jsonl(base / "adjudications.jsonl")
        self.key = by_id(load_jsonl(base / "answer_key.jsonl"))
        if key == "adjudicated":
            self.key = apply_adjudications(self.key, self.adjudications)
        for k in self.key.values():
            k.pop("id", None)
        self.split = json.load(open(base / "split.json"))
        ex = base / "excluded.json"
        self.excluded = set(json.load(open(ex))) if ex.exists() else set()
        run = r / "runs" / dataset / version
        self.attempts = [o for o in load_jsonl(run / "outputs.jsonl") if o.get("version") == version]
        self.outputs = best_records(self.attempts, ("issue_id", "repeat"))
        self.mutants = load_jsonl(run / "mutants.jsonl")
        self.eval_attempts = load_jsonl(run / "evaluator.jsonl")
        self.evaluator = best_records(self.eval_attempts, ("input_id", "repeat"))
        self.run_dir = run

    def ids(self, split):
        """'all' means every issue that has an answer key (dev + test)."""
        ids = (self.split["dev"] + self.split["test"]) if split == "all" else self.split.get(split, [])
        return sorted(i for i in ids if i not in self.excluded and i in self.issues)

    def primary(self, split):
        """Repeat 0 of each issue: the output the metrics are computed on."""
        ids = set(self.ids(split))
        return {o["issue_id"]: o for o in self.outputs if o["repeat"] == 0 and o["issue_id"] in ids}


def ok_exec(o):
    return o.get("http_status") == 200 and o.get("exec_status") == "completed"


def parsed(o):
    obj, _ = gates.parse(o.get("triage"))
    return obj


def _single(v):
    return v[0] if isinstance(v, list) and len(v) == 1 else (None if isinstance(v, list) else v)


def field_metrics(d, split):
    prim = d.primary(split)
    tax = d.tax
    out = {}
    for f in FIELDS:
        kf = {i: schema.key_field(f, d.key.get(i, {})) for i in d.ids(split) if i in prim}
        ids = [i for i, k in kf.items() if k]
        if not ids:
            continue
        preds = {i: (parsed(prim[i]) or {}).get(f) for i in ids}
        hits = [gates.matches(kf[i], preds[i], d.key[i][kf[i]], tax) for i in ids]
        m = {"accuracy": wilson(sum(hits), len(ids)), "graded_against": sorted({kf[i] for i in ids}),
             "majority_baseline": majority_baseline(d, f, ids)}
        single = [i for i in ids if _single(d.key[i][kf[i]]) is not None]
        gold = [_single(d.key[i][kf[i]]) for i in single]
        if f == "category":
            pred = [tax.grade_category(preds[i]) if kf[i] == "category_coarse" else preds[i] for i in single]
            m["macro_f1"] = macro_f1(gold, pred, sorted(set(gold)))
        if f == "product_area":
            m["macro_f1"] = macro_f1(gold, [preds[i] for i in single], sorted(set(gold)))
        if f == "priority":
            near = sum(preds[i] in tax.priorities and abs(tax.rank(preds[i]) - tax.rank(g)) <= 1
                       for i, g in zip(single, gold))
            m["within_one"] = wilson(near, len(single))
            m["confusion"] = {g: {p: sum(1 for i, gg in zip(single, gold) if gg == g and preds[i] == p)
                                  for p in tax.priorities} for g in tax.priorities}
        if f == "needs_human":
            tp = sum(gold[k] is True and preds[i] is True for k, i in enumerate(single))
            m["precision_true"] = wilson(tp, sum(preds[i] is True for i in single))
            m["recall_true"] = wilson(tp, sum(g is True for g in gold))
        out[f] = m
    ids = [i for i in d.ids(split) if i in prim and d.key.get(i)]
    all_ok = sum(not gates.label_dependent(prim[i].get("triage"), d.key[i], tax).failed()
                 and bool(parsed(prim[i])) for i in ids)
    out["all_graded_fields"] = wilson(all_ok, len(ids))
    return out


def majority_baseline(d, field, ids):
    """Accuracy of always answering the most common dev-split key value.
    Chosen on dev only, so it isn't fitted to the split being scored."""
    from collections import Counter
    counts = Counter()
    for i in d.ids("dev"):
        kf = schema.key_field(field, d.key.get(i, {}))
        if kf:
            v = d.key[i][kf]
            counts.update(v if isinstance(v, list) else [v])
    if not counts:
        return None
    guess = counts.most_common(1)[0][0]
    hits = 0
    for i in ids:
        v = d.key[i][schema.key_field(field, d.key[i])]
        hits += guess in v if isinstance(v, list) else guess == v
    return {"always": guess, **wilson(hits, len(ids))}


def stability(d, split):
    ids = set(d.ids(split))
    runs = defaultdict(list)
    for o in d.outputs:
        if o["issue_id"] in ids:
            runs[o["issue_id"]].append(parsed(o))
    full = {i: r for i, r in runs.items() if len(r) >= 2}
    return {f: wilson(sum(len({json.dumps((x or {}).get(f)) for x in r}) == 1 for r in full.values()),
                      len(full)) for f in FIELDS}


def gate_rates(d, split):
    prim = d.primary(split)
    res = {}
    for g in gates.LABEL_FREE:
        st = [gates.label_free(o.get("triage"), d.issues[i], d.tax).by_gate()[g].status
              for i, o in prim.items()]
        res[g] = {"fail": wilson(st.count(FAIL), len(st)), "skipped": st.count("skip")}
    return res


def telemetry(d, split):
    ids = set(d.ids(split))
    outs = [o for o in d.outputs if o["issue_id"] in ids]
    agent_ms = [s["duration_ms"] for o in outs for s in (o.get("log") or {}).get("spans", [])
                if s.get("type") == "agent"]
    costs, model_costs, derived = [], [], 0
    for o in outs:
        c = (o.get("log") or {}).get("cost") or {}
        if isinstance(c.get("total"), (int, float)):
            costs.append(c["total"])
            if c.get("items") is None:
                # Read before Sim wrote the breakdown; total = fixed fee + model cost.
                model_costs.append(max(0.0, c["total"] - SIM_BASE_EXECUTION_FEE))
                derived += 1
            else:
                model_costs.append(sum(i.get("cost", 0) for i in c["items"] if i.get("category") == "model"))
    pct = lambda vals: {"p50": percentile(vals, 0.5), "p95": percentile(vals, 0.95)}
    attempts = [o for o in d.attempts if o["issue_id"] in ids]
    rate_limited = (sum(o.get("http_status") == 429 for o in attempts)
                    + sum(len(o.get("rate_limited_waits_s") or []) for o in attempts))
    return {
        "runs": len(outs),
        "execution_failures": wilson(sum(not ok_exec(o) for o in outs), len(outs)),
        "sim_rate_limited_responses": rate_limited,
        "client_ms": pct([o.get("client_ms") for o in outs]),
        "server_total_ms": pct([(o.get("log") or {}).get("total_ms") for o in outs]),
        "agent_block_ms": pct(agent_ms),
        # Sim's logged total includes a fixed $0.005 "execution_fee" per run even when
        # billing is disabled (self-hosted); the model line is what the provider bills.
        "logged_cost_per_100_runs_usd": round(100 * sum(costs) / len(costs), 4) if costs else None,
        "model_cost_per_100_runs_usd": round(100 * sum(model_costs) / len(model_costs), 4) if model_costs else None,
        "model_cost_derived_from_total": derived,
        "log_poll_wait_s_max": max(((o.get("log") or {}).get("poll_wait_s") or 0) for o in outs) if outs else None,
    }


def seeds(d):
    """Correct outputs: pass every label-free gate and agree with every field the
    answer key has. Fields without a key are unverified; the report says so."""
    out = []
    for i, o in sorted(d.primary("all").items()):
        obj = parsed(o)
        if (obj is not None and d.key.get(i)
                and gates.label_free(obj, d.issues[i], d.tax).passed_all()
                and not gates.label_dependent(obj, d.key[i], d.tax).failed()):
            out.append({"issue_id": i, "output": obj})
    return out


def natural_errors(d, split="all"):
    errs = []
    for i, o in sorted(d.primary(split).items()):
        if d.key.get(i) and (parsed(o) is None
                             or gates.label_dependent(o.get("triage"), d.key[i], d.tax).failed()):
            errs.append({"issue_id": i, "output": o.get("triage")})
    return errs


def caught(output, issue, gold, tax):
    v = gates.check(output, issue, tax, gold)
    free = bool(v.failed(gates.LABEL_FREE))
    dep = bool(v.failed(gates.LABEL_DEPENDENT))
    return {"label_free": free, "label_dependent": dep, "union": free or dep}


def evaluator_flags(d, cutoff=3, rule="majority"):
    """input_id -> flagged (any metric <= cutoff).
    majority (primary, pre-registered): >= 2 of 3 valid runs flag; inputs with fewer
    than 3 valid runs get no verdict. single: the repeat-0 run alone (secondary)."""
    runs = defaultdict(dict)
    for r in d.evaluator:
        vals = [(r.get("scores") or {}).get(m) for m in EVAL_METRICS]
        if r.get("ok") and all(isinstance(v, (int, float)) for v in vals):
            runs[r["input_id"]][r["repeat"]] = min(vals) <= cutoff
    if rule == "single":
        return {k: v[0] for k, v in runs.items() if 0 in v}
    return {k: sum(v.values()) >= 2 for k, v in runs.items() if len(v) >= 3}


def evaluator_stability(d, cutoff=3):
    """On the variance subset (3 runs each): how often all 3 runs give the same verdict,
    and the per-metric score spread."""
    runs = defaultdict(list)
    for r in d.evaluator:
        vals = [(r.get("scores") or {}).get(m) for m in EVAL_METRICS]
        if r.get("ok") and all(isinstance(v, (int, float)) for v in vals):
            runs[r["input_id"]].append(vals)
    multi = {k: v for k, v in runs.items() if len(v) >= 3}
    same = sum(len({min(v) <= cutoff for v in vs}) == 1 for vs in multi.values())
    spread = {m: sum(max(v[j] for v in vs) - min(v[j] for v in vs) for vs in multi.values()) / len(multi)
              for j, m in enumerate(EVAL_METRICS)} if multi else None
    return {"verdict_identical_across_3_runs": wilson(same, len(multi)),
            "mean_score_range": {k: round(v, 3) for k, v in spread.items()} if spread else None}


def mutation_recall(d):
    flags = evaluator_flags(d)
    single = evaluator_flags(d, rule="single")
    per = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    not_applicable = defaultdict(int)
    for m in d.mutants:
        if not m["applicable"]:
            not_applicable[m["operator"]] += 1
            continue
        c = caught(m["output"], d.issues[m["issue_id"]], d.key[m["issue_id"]], d.tax)
        if m["mutant_id"] in flags:
            c["evaluator"] = flags[m["mutant_id"]]
            c["gates_or_evaluator"] = c["label_free"] or c["evaluator"]
        if m["mutant_id"] in single:
            c["evaluator_single_run"] = single[m["mutant_id"]]
        for checker, hit in c.items():
            per[m["operator"]][checker][0] += hit
            per[m["operator"]][checker][1] += 1
    graded = set(FIELDS) | {"category_coarse"}
    keyed = sorted({f for k in d.key.values() for f in k if f in graded})
    return {"by_operator": {op: {ch: wilson(k, n) for ch, (k, n) in v.items()} for op, v in per.items()},
            "not_applicable": dict(not_applicable),
            "fields_with_answer_key": keyed}


def evaluator_sweep(d):
    """Detection on mutants and flag rate on seeds for every cutoff (1 to 4). All shown."""
    seed_ids = {f"seed:{s['issue_id']}" for s in seeds(d)}
    mutant_ids = {m["mutant_id"] for m in d.mutants if m["applicable"]}
    rows = {}
    for cutoff in (1, 2, 3, 4):
        flags = evaluator_flags(d, cutoff=cutoff)
        judged_m, judged_s = mutant_ids & set(flags), seed_ids & set(flags)
        rows[cutoff] = {"mutant_detection": wilson(sum(flags[i] for i in judged_m), len(judged_m)),
                        "seed_flag_rate": wilson(sum(flags[i] for i in judged_s), len(judged_s))}
    return rows


def natural_error_detection(d, split="all"):
    """Real model mistakes: which checkers notice them without an answer key?"""
    errs = natural_errors(d, split)
    flags = evaluator_flags(d)
    lf = sum(bool(gates.label_free(e["output"], d.issues[e["issue_id"]], d.tax).failed()) for e in errs)
    judged = [e for e in errs if f"natural:{e['issue_id']}" in flags]
    return {"n_errors": len(errs), "label_free": wilson(lf, len(errs)),
            "evaluator": wilson(sum(flags[f"natural:{e['issue_id']}"] for e in judged), len(judged))}


def key_disagreements(d):
    """Summary of human adjudication of answer-key vs model disagreements."""
    adj = [a for a in d.adjudications if a.get("kind") == "key_disagreement"]
    if not adj:
        return None
    verdicts = defaultdict(int)
    for a in adj:
        verdicts[a["verdict"]] += 1
    return {"n": len(adj), "verdicts": dict(verdicts),
            "key_was_wrong": wilson(verdicts["model_right"] + verdicts["neither"], len(adj))}


def overall_label_free_mutation_recall(d):
    hits = [caught(m["output"], d.issues[m["issue_id"]], d.key[m["issue_id"]], d.tax)["label_free"]
            for m in d.mutants if m["applicable"]]
    return wilson(sum(hits), len(hits))


def regression_pass_rate(d, split):
    prim = d.primary(split)
    ids = [i for i in prim if d.key.get(i)]
    ok = sum(gates.check(prim[i].get("triage"), d.issues[i], d.tax, d.key[i]).passed_all() for i in ids)
    return wilson(ok, len(ids))


def build(d, split):
    return {
        "dataset": d.dataset, "version": d.version, "split": split, "answer_key": d.key_mode,
        "n_issues_with_key": len(d.ids("all")), "n_queue": len(d.ids("queue")),
        "n_outputs": len(d.outputs),
        "fields": field_metrics(d, split),
        "stability_across_repeats": stability(d, split),
        "label_free_gate_failure_rates": gate_rates(d, split),
        "queue_gate_failure_rates": gate_rates(d, "queue") if d.ids("queue") else None,
        "regression_pass_rate": regression_pass_rate(d, split),
        "telemetry": telemetry(d, split),
        "mutation": mutation_recall(d) if d.mutants else None,
        "natural_errors": natural_error_detection(d, split),
        "evaluator_sweep": evaluator_sweep(d) if d.evaluator else None,
        "evaluator_stability": evaluator_stability(d) if d.evaluator else None,
        "key_disagreements": key_disagreements(d),
    }


def write_mutants(d, path=None):
    path = Path(path or d.run_dir / "mutants.jsonl")
    seed_rows = seeds(d)
    muts = mutations.generate(seed_rows, d.issues, d.tax)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for m in muts:
            f.write(json.dumps(m) + "\n")
    return len(seed_rows), len(muts)
