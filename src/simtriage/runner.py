"""Run issues through the deployed triage workflow and record everything.

One JSONL record per (issue, repeat). Resumable: records with a response are
skipped on rerun. Transport errors are retried, and every attempt is recorded,
because the execution failure rate is itself a result.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .sim_client import extract_triage, flatten_spans


class ContaminationError(Exception):
    pass


def guard_key_frozen(dataset, root="."):
    """Outputs may only be produced once the dataset's answer key exists, so the
    key can't be shaped by what the model said."""
    if not (Path(root) / "data" / dataset / "answer_key.jsonl").exists():
        raise ContaminationError(f"data/{dataset}/answer_key.jsonl missing; build the "
                                 f"answer key before producing any model output")


def done_keys(out_path):
    p = Path(out_path)
    if not p.exists():
        return set()
    keys = set()
    for line in p.open():
        r = json.loads(line)
        if r.get("http_status") is not None:
            keys.add((r["issue_id"], r["repeat"]))
    return keys


def run_one(client, workflow_id, issue, repeat, version, retries=2):
    attempts = []
    for attempt in range(retries + 1):
        try:
            status, body, client_ms = client.execute(
                workflow_id, {"title": issue["title"], "body": issue["body"]})
            break
        except httpx.TransportError as e:
            attempts.append(f"{type(e).__name__}: {e}")
    else:
        return {"issue_id": issue["id"], "repeat": repeat, "version": version,
                "http_status": None, "transport_errors": attempts}

    data = body.get("data", {}) if isinstance(body, dict) else {}
    run_id = data.get("runId")
    output = data.get("output")
    triage, how = extract_triage(output)
    rec = {
        "issue_id": issue["id"], "repeat": repeat, "version": version,
        "workflow_id": workflow_id, "run_id": run_id, "http_status": status,
        "transport_errors": attempts, "exec_status": data.get("status"),
        "error": data.get("error") or (body.get("error") if isinstance(body, dict) else None),
        "client_ms": round(client_ms, 1), "server_ms": data.get("durationMs"),
        "triage": triage, "triage_source": how, "raw_output": output,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if run_id:
        log_status, log, waited = client.get_log(run_id)
        rec["log"] = {
            "http_status": log_status, "status": log.get("status"),
            "poll_wait_s": waited, "total_ms": log.get("totalDurationMs"),
            "cost": log.get("cost"), "spans": flatten_spans(log.get("traceSpans")),
        }
    return rec


def run(client, workflow_id, issues, version, out_path, repeats=3, concurrency=4, dataset=None):
    if dataset is not None:
        guard_key_frozen(dataset)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    skip = done_keys(out_path)
    jobs = [(i, r) for i in issues for r in range(repeats) if (i["id"], r) not in skip]
    with open(out_path, "a") as f, ThreadPoolExecutor(concurrency) as pool:
        for rec in pool.map(lambda j: run_one(client, workflow_id, j[0], j[1], version), jobs):
            f.write(json.dumps(rec) + "\n")
            f.flush()
            ok = rec.get("http_status") == 200 and rec.get("exec_status") == "completed"
            print(f"{rec['issue_id']} r{rec['repeat']} {'ok' if ok else 'FAIL'} "
                  f"{rec.get('client_ms', '-')}ms")
    return len(jobs)
