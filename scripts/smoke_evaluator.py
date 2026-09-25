"""Send one recorded smoke output (a dev issue) through the deployed Evaluator
workflow and print the scores, model and trace. Checks the wiring only."""
import json
import os
import sys

from simtriage.evaluator import format_issue, format_output, load_rubric
from simtriage.sim_client import SimClient, flatten_spans

ds = sys.argv[1] if len(sys.argv) > 1 else "sim"
rec = json.loads(open(f"runs/{ds}/smoke/outputs.jsonl").readline())
issue = {json.loads(l)["id"]: json.loads(l) for l in open(f"data/{ds}/issues.jsonl")}[rec["issue_id"]]
c = SimClient(os.environ.get("SIM_BASE_URL", "http://localhost:3000"), os.environ["SIM_API_KEY"])
status, body, ms = c.execute(os.environ["SIM_EVAL_WORKFLOW_ID"], {
    "rubric": load_rubric(ds), "issue": format_issue(issue), "triage_output": format_output(rec["triage"])})
data = body.get("data", {})
out = data.get("output") or {}
print("http", status, "| status", data.get("status"), "| error", data.get("error"), f"| {ms:.0f} ms")
print("scores:", {k: out.get(k) for k in ("classification", "faithfulness", "consistency")})
print("model:", out.get("model"), "| cost:", out.get("cost"))
if data.get("runId"):
    _, log, _ = c.get_log(data["runId"])
    for s in flatten_spans(log.get("traceSpans")):
        print("  " * s["depth"], s["type"], s["name"], s["status"], s["duration_ms"])
