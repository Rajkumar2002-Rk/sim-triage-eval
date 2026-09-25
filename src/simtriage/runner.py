"""Run issues through the deployed triage workflow and record everything.

One JSONL record per (issue, repeat). Resumable: records with a response are
skipped on rerun. Transport errors are retried, and every attempt is recorded,
because the execution failure rate is itself a result.
"""
import json
import time
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


def is_done(r):
    """A record counts as done unless it never reached Sim or Sim rate-limited it."""
    return r.get("http_status") not in (None, 429)


def done_keys(out_path):
    p = Path(out_path)
    if not p.exists():
        return set()
    return {(r["issue_id"], r["repeat"]) for r in map(json.loads, p.open()) if is_done(r)}


def retry_after_s(body, default=15.0, cap=120.0):
    """Seconds to wait from Sim's 429 body (details.retryAfter is an ISO time)."""
    try:
        at = body["error"]["details"]["retryAfter"]
        wait = (datetime.fromisoformat(at.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()
        return min(cap, max(1.0, wait + 0.5))
    except (KeyError, TypeError, ValueError):
        return default


def execute_with_backoff(client, workflow_id, inputs, retries=2, max_rate_limited=8, sleep=time.sleep):
    """Returns (status, body, client_ms, transport_errors, rate_limited_waits)."""
    transport, waits = [], []
    while True:
        try:
            status, body, client_ms = client.execute(workflow_id, inputs)
        except httpx.TransportError as e:
            transport.append(f"{type(e).__name__}: {e}")
            if len(transport) > retries:
                return None, None, None, transport, waits
            continue
        if status == 429 and len(waits) < max_rate_limited:
            w = retry_after_s(body)
            waits.append(round(w, 1))
            sleep(w)
            continue
        return status, body, client_ms, transport, waits


def run_one(client, workflow_id, issue, repeat, version, retries=2, sleep=time.sleep):
    status, body, client_ms, attempts, waits = execute_with_backoff(
        client, workflow_id, {"title": issue["title"], "body": issue["body"]}, retries, sleep=sleep)
    if status is None:
        return {"issue_id": issue["id"], "repeat": repeat, "version": version,
                "http_status": None, "transport_errors": attempts, "rate_limited_waits_s": waits}

    data = body.get("data", {}) if isinstance(body, dict) else {}
    run_id = data.get("runId")
    output = data.get("output")
    triage, how = extract_triage(output)
    rec = {
        "issue_id": issue["id"], "repeat": repeat, "version": version,
        "workflow_id": workflow_id, "run_id": run_id, "http_status": status,
        "transport_errors": attempts, "rate_limited_waits_s": waits, "exec_status": data.get("status"),
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
