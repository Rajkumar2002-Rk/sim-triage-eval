"""Send seeds, mutants and natural errors through the deployed Evaluator workflow.

Input ids: "seed:<issue>", "<issue>:<operator>" (mutants), "natural:<issue>".
Each input is scored `repeats` times; the flag rule lives in report.evaluator_flags.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import report
from .sim_client import flatten_spans

METRICS = ("classification", "faithfulness", "consistency")


def format_issue(issue):
    return f"TITLE: {issue['title']}\n\nBODY:\n{issue['body']}"


def format_output(output):
    return output if isinstance(output, str) else json.dumps(output, indent=2)


def build_inputs(d):
    rows = [{"input_id": f"seed:{s['issue_id']}", "kind": "seed", "issue_id": s["issue_id"],
             "operator": None, "output": s["output"]} for s in report.seeds(d)]
    rows += [{"input_id": m["mutant_id"], "kind": "mutant", "issue_id": m["issue_id"],
              "operator": m["operator"], "output": m["output"]} for m in d.mutants if m["applicable"]]
    rows += [{"input_id": f"natural:{e['issue_id']}", "kind": "natural", "issue_id": e["issue_id"],
              "operator": None, "output": e["output"]} for e in report.natural_errors(d)]
    return rows


def load_rubric(dataset):
    """The customer's rubric as the judge sees it: same rules the triage agent got."""
    return Path(f"prompts/{dataset}/evaluator_system.md").read_text()


def score_one(client, workflow_id, row, issue, repeat, rubric, retries=2):
    for attempt in range(retries + 1):
        try:
            status, body, client_ms = client.execute(workflow_id, {
                "rubric": rubric, "issue": format_issue(issue),
                "triage_output": format_output(row["output"])})
            break
        except httpx.TransportError as e:
            err = f"{type(e).__name__}: {e}"
    else:
        return {"input_id": row["input_id"], "issue_id": row["issue_id"], "repeat": repeat,
                "http_status": None, "ok": False, "error": err}
    data = body.get("data", {}) if isinstance(body, dict) else {}
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    scores = {m: output.get(m) for m in METRICS}
    rec = {"input_id": row["input_id"], "issue_id": row["issue_id"], "kind": row["kind"],
           "operator": row["operator"], "repeat": repeat, "http_status": status,
           "run_id": data.get("runId"), "exec_status": data.get("status"),
           "ok": status == 200 and all(isinstance(v, (int, float)) for v in scores.values()),
           "scores": scores, "model": output.get("model"), "cost": output.get("cost"),
           "error": data.get("error"), "client_ms": round(client_ms, 1), "raw_output": output,
           "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if rec["run_id"]:
        _, log, waited = client.get_log(rec["run_id"])
        rec["log"] = {"status": log.get("status"), "total_ms": log.get("totalDurationMs"),
                      "poll_wait_s": waited, "spans": flatten_spans(log.get("traceSpans"))}
    return rec


def run(client, workflow_id, d, repeats=3, concurrency=4, out_path=None, limit=None):
    out_path = out_path or d.run_dir / "evaluator.jsonl"
    rows = build_inputs(d)[:limit] if limit else build_inputs(d)
    skip = done_keys_eval(out_path)
    jobs = [(r, k) for r in rows for k in range(repeats) if (r["input_id"], k) not in skip]
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
    return {(r["input_id"], r["repeat"]) for r in map(json.loads, p.open()) if r.get("http_status") is not None}
