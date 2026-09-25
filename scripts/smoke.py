"""Day-1 smoke test: call a deployed Sim workflow, then fetch its run log.

Usage:
  export SIM_BASE_URL=http://localhost:3000
  export SIM_API_KEY=...          # from Sim settings > API keys
  export SIM_WORKFLOW_ID=...      # from the Deploy modal
  uv run --with httpx scripts/smoke.py "hello from python"
"""
import json
import os
import sys

import httpx

base = os.environ.get("SIM_BASE_URL", "http://localhost:3000").rstrip("/")
key = os.environ["SIM_API_KEY"]
wf = os.environ["SIM_WORKFLOW_ID"]
headers = {"X-API-Key": key, "Content-Type": "application/json"}
text = sys.argv[1] if len(sys.argv) > 1 else "hello"

with httpx.Client(timeout=120) as c:
    r = c.post(f"{base}/api/v2/workflows/{wf}/execute", headers=headers,
               json={"input": {"text": text}})
    print("execute:", r.status_code)
    print(json.dumps(r.json(), indent=2)[:600])
    r.raise_for_status()

    run_id = r.json().get("data", {}).get("runId")
    if not run_id:
        sys.exit("no runId in response; record this in FRICTION.md")
    # The log row is finalized slightly after execute returns; poll until terminal.
    import time
    for _ in range(20):
        log = c.get(f"{base}/api/v2/logs/{run_id}", headers=headers)
        d = log.json().get("data", {})
        if d.get("status") not in ("running", "queued", None):
            break
        time.sleep(0.25)
    print("log:", log.status_code, "status:", d.get("status"), "totalDurationMs:", d.get("totalDurationMs"))
    print("top-level keys:", sorted(d.keys()))

    def walk(spans, depth=0):
        for sp in spans or []:
            print("  " * depth, sp.get("type"), sp.get("name"), sp.get("status"),
                  sp.get("duration"), "ms", "keys=", sorted(sp.keys()))
            walk(sp.get("children"), depth + 1)

    spans = d.get("traceSpans") or (d.get("executionData") or {}).get("traceSpans")
    print("traceSpans found:", spans is not None)
    walk(spans)
