"""Client for a deployed Sim workflow: execute over the API, then read the run log.

Quirk handled here (see FRICTION.md): a synchronous execute returns before the
run log is finalized, so the log is polled until its status is terminal.
"""
import time

import httpx

TERMINAL = {"completed", "failed", "cancelled", "paused", "error", "success"}
# Keys Sim adds to an Agent block's output alongside the model's fields.
AGENT_METADATA_KEYS = {"model", "tokens", "toolCalls", "providerTiming", "cost"}


class SimClient:
    def __init__(self, base_url, api_key, transport=None, timeout=180):
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(headers={"X-API-Key": api_key}, timeout=timeout,
                                 transport=transport)

    def execute(self, workflow_id, inputs):
        t0 = time.perf_counter()
        r = self.http.post(f"{self.base}/api/v2/workflows/{workflow_id}/execute",
                           json={"input": inputs})
        client_ms = (time.perf_counter() - t0) * 1000
        try:
            body = r.json()
        except ValueError:
            body = {"_non_json_body": r.text[:2000]}
        return r.status_code, body, client_ms

    def get_log(self, run_id, max_wait_s=15.0, interval_s=0.25, sleep=time.sleep):
        waited = 0.0
        while True:
            r = self.http.get(f"{self.base}/api/v2/logs/{run_id}")
            data = r.json().get("data", {}) if r.status_code == 200 else {}
            # The cost breakdown (cost.items) is written ~20ms after the status turns
            # terminal; wait for it too so telemetry isn't missing its line items.
            cost = data.get("cost") or {}
            settled = data.get("status") in TERMINAL and (not cost or cost.get("items") is not None)
            if settled or waited >= max_wait_s:
                return r.status_code, data, waited
            sleep(interval_s)
            waited += interval_s


def flatten_spans(spans, depth=0):
    out = []
    for sp in spans or []:
        out.append({"depth": depth, "type": sp.get("type"), "name": sp.get("name"),
                    "status": sp.get("status"), "duration_ms": sp.get("duration"),
                    "model": sp.get("model"), "tokens": sp.get("tokens")})
        out += flatten_spans(sp.get("children"), depth + 1)
    return out


def extract_triage(output):
    """Pull the model's triage object out of the workflow's API output.

    Returns (object or raw string, how). Only Sim's known metadata keys are
    removed, so an extra field the model invents survives and the schema gate
    sees it.
    """
    if not isinstance(output, dict):
        return output, "raw"
    fields = {k: v for k, v in output.items() if k not in AGENT_METADATA_KEYS}
    if set(fields) == {"content"}:
        return fields["content"], "content"
    # With structured output Sim may also echo the raw JSON text as `content`.
    if len(fields) > 1 and isinstance(fields.get("content"), str):
        fields = {k: v for k, v in fields.items() if k != "content"}
    return fields, "fields"
