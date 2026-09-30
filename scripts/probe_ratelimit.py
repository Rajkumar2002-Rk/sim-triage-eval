"""Reproduce the 429 RATE_LIMITED responses on a self-hosted Sim install.

Fires N synchronous executes of a workflow that has no model call (so it's free)
at a fixed concurrency, and records the status, timing and every rate-limit
header of each response. The headers on a 429 show which bucket fired.

  export SIM_API_KEY=... SIM_PROBE_WORKFLOW_ID=...
  uv run python scripts/probe_ratelimit.py --n 150 --concurrency 8
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

INTERESTING = ("ratelimit", "rate-limit", "retry-after", "x-request-id")


def one(client, url, key, i, t0):
    start = time.perf_counter()
    try:
        r = client.post(url, headers={"X-API-Key": key}, json={"input": {}})
    except httpx.HTTPError as e:
        return {"i": i, "status": None, "error": f"{type(e).__name__}: {e}"}
    try:
        body = r.json()
    except ValueError:
        body = {"_text": r.text[:300]}
    err = body.get("error") if isinstance(body, dict) else None
    return {
        "i": i,
        "sent_at_s": round(start - t0, 3),
        "status": r.status_code,
        "ms": round((time.perf_counter() - start) * 1000, 1),
        "headers": {k: v for k, v in r.headers.items() if any(w in k.lower() for w in INTERESTING)},
        "error": err,
        "exec_status": (body.get("data") or {}).get("status") if isinstance(body, dict) else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--base-url", default=os.environ.get("SIM_BASE_URL", "http://localhost:3000"))
    args = ap.parse_args()
    key, wf = os.environ.get("SIM_API_KEY"), os.environ.get("SIM_PROBE_WORKFLOW_ID")
    if not key or not wf:
        raise SystemExit("set SIM_API_KEY and SIM_PROBE_WORKFLOW_ID")
    url = f"{args.base_url.rstrip('/')}/api/v2/workflows/{wf}/execute"

    t0 = time.perf_counter()
    with httpx.Client(timeout=60) as client, ThreadPoolExecutor(args.concurrency) as pool:
        results = list(pool.map(lambda i: one(client, url, key, i, t0), range(args.n)))
    elapsed = time.perf_counter() - t0

    counts = {}
    for r in results:
        counts[str(r["status"])] = counts.get(str(r["status"]), 0) + 1
    limited = [r for r in results if r["status"] == 429]
    summary = {
        "requests": args.n, "concurrency": args.concurrency, "seconds": round(elapsed, 2),
        "requests_per_second": round(args.n / elapsed, 1), "status_counts": counts,
        "first_429_index": limited[0]["i"] if limited else None,
        "first_429_after_s": limited[0]["sent_at_s"] if limited else None,
        "headers_on_first_429": limited[0]["headers"] if limited else None,
        "error_on_first_429": limited[0]["error"] if limited else None,
        "headers_on_first_200": next((r["headers"] for r in results if r["status"] == 200), None),
    }
    out = Path("runs/diagnostics")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"ratelimit_probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"saved {path}")


if __name__ == "__main__":
    main()
