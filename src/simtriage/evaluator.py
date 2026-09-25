"""Send seeds, mutants and natural errors through the deployed Evaluator workflow.

Input ids: "seed:<issue>", "<issue>:<operator>" (mutants), "natural:<issue>".

Default (pre-registered): every seed, mutant and natural error, 3 runs each,
ordered repeat-major. `sample=True` is a cheaper plan kept for budget-limited
reruns: at most PER_OPERATOR mutants per operator, SEED_CAP seeds, NATURAL_CAP
natural errors, one run each plus VARIANCE_N inputs run three times.
"""
import random
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import report
from .runner import execute_with_backoff
from .sim_client import flatten_spans

METRICS = ("classification", "faithfulness", "consistency")
PER_OPERATOR, SEED_CAP, NATURAL_CAP, VARIANCE_N, SAMPLE_SEED = 40, 60, 60, 50, 20260925


def format_issue(issue):
    return f"TITLE: {issue['title']}\n\nBODY:\n{issue['body']}"


def format_output(output):
    return output if isinstance(output, str) else json.dumps(output, indent=2)


def _sample(rows, n, rng):
    rows = sorted(rows, key=lambda r: r["input_id"])
    return rows if n is None or len(rows) <= n else sorted(rng.sample(rows, n), key=lambda r: r["input_id"])


def build_inputs(d, per_operator=PER_OPERATOR, seed_cap=SEED_CAP, natural_cap=NATURAL_CAP,
                 sample_seed=SAMPLE_SEED):
    """Deterministic sample; pass None caps for the full set."""
    rng = random.Random(sample_seed)
    seeds = [{"input_id": f"seed:{s['issue_id']}", "kind": "seed", "issue_id": s["issue_id"],
              "operator": None, "output": s["output"]} for s in report.seeds(d)]
    rows = _sample(seeds, seed_cap, rng)
    by_op = {}
    for m in d.mutants:
        if m["applicable"]:
            by_op.setdefault(m["operator"], []).append(
                {"input_id": m["mutant_id"], "kind": "mutant", "issue_id": m["issue_id"],
                 "operator": m["operator"], "output": m["output"]})
    for op in sorted(by_op):
        rows += _sample(by_op[op], per_operator, rng)
    natural = [{"input_id": f"natural:{e['issue_id']}", "kind": "natural", "issue_id": e["issue_id"],
                "operator": None, "output": e["output"]} for e in report.natural_errors(d)]
    rows += _sample(natural, natural_cap, rng)
    return rows


def variance_ids(rows, n=VARIANCE_N, sample_seed=SAMPLE_SEED):
    ids = sorted(r["input_id"] for r in rows)
    return set(ids if len(ids) <= n else random.Random(sample_seed + 1).sample(ids, n))


def load_rubric(dataset):
    """The customer's rubric as the judge sees it: same rules the triage agent got."""
    return Path(f"prompts/{dataset}/evaluator_system.md").read_text()


def score_one(client, workflow_id, row, issue, repeat, rubric, retries=2, sleep=time.sleep):
    status, body, client_ms, attempts, waits = execute_with_backoff(
        client, workflow_id, {"rubric": rubric, "issue": format_issue(issue),
                              "triage_output": format_output(row["output"])}, retries, sleep=sleep)
    if status is None:
        return {"input_id": row["input_id"], "issue_id": row["issue_id"], "repeat": repeat,
                "http_status": None, "ok": False, "error": attempts, "rate_limited_waits_s": waits}
    data = body.get("data", {}) if isinstance(body, dict) else {}
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    scores = {m: output.get(m) for m in METRICS}
    rec = {"input_id": row["input_id"], "issue_id": row["issue_id"], "kind": row["kind"],
           "operator": row["operator"], "repeat": repeat, "http_status": status,
           "run_id": data.get("runId"), "exec_status": data.get("status"),
           "ok": status == 200 and all(isinstance(v, (int, float)) for v in scores.values()),
           "scores": scores, "model": output.get("model"), "cost": output.get("cost"),
           "error": data.get("error"), "client_ms": round(client_ms, 1), "raw_output": output,
           "rate_limited_waits_s": waits,
           "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if rec["run_id"]:
        _, log, waited = client.get_log(rec["run_id"])
        rec["log"] = {"status": log.get("status"), "total_ms": log.get("totalDurationMs"),
                      "poll_wait_s": waited, "spans": flatten_spans(log.get("traceSpans"))}
    return rec


def plan_jobs(rows, extra_repeats=2, variance_n=VARIANCE_N):
    """Sampled plan: repeat 0 for every row, repeats 1..extra for the variance subset."""
    var = variance_ids(rows, variance_n)
    return [(r, 0) for r in rows] + [(r, k) for r in rows if r["input_id"] in var
                                     for k in range(1, extra_repeats + 1)]


def plan_full(rows, repeats=3):
    """Pre-registered plan: every row `repeats` times, ordered repeat-major (every row's
    first check before any second check), so an interrupted run still covers everything once."""
    return [(r, k) for k in range(repeats) for r in rows]


def run(client, workflow_id, d, concurrency=3, out_path=None, limit=None, sample=False, repeats=3):
    out_path = out_path or d.run_dir / "evaluator.jsonl"
    rows = build_inputs(d) if sample else build_inputs(d, None, None, None)
    rows = rows[:limit] if limit else rows
    skip = done_keys_eval(out_path)
    plan = plan_jobs(rows) if sample else plan_full(rows, repeats)
    jobs = [(r, k) for r, k in plan if (r["input_id"], k) not in skip]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    rubric = load_rubric(d.dataset)
    with open(out_path, "a") as f, ThreadPoolExecutor(concurrency) as pool:
        for rec in pool.map(lambda j: score_one(client, workflow_id, j[0], d.issues[j[0]["issue_id"]],
                                                j[1], rubric), jobs):
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(f"{rec['input_id']} r{rec['repeat']} {'ok' if rec['ok'] else 'FAIL'} {rec.get('scores')}")
    return len(rows), len(jobs)


def done_keys_eval(out_path):
    p = Path(out_path)
    if not p.exists():
        return set()
    # Only a successfully scored check is done; any failure (rate limit, provider
    # error, unparseable scores) is retried on the next run.
    return {(r["input_id"], r["repeat"]) for r in map(json.loads, p.open()) if r.get("ok")}
