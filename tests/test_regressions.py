"""Pinned regression tests: one per real failure found against real Sim output."""
import httpx

from simtriage import report
from simtriage.sim_client import SimClient


def _telemetry_for(cost):
    class D:
        attempts = outputs = [{"issue_id": "x", "repeat": 0, "http_status": 200, "exec_status": "completed",
                               "log": {"cost": cost, "spans": []}}]
        def ids(self, split):
            return ["x"]
    return report.telemetry(D(), "all")


def test_2026_09_25_null_cost_items_do_not_crash_telemetry():
    # Real Sim log: {'total': 0.007189, 'items': None} for ~24% of v1 runs.
    t = _telemetry_for({"total": 0.007189, "items": None})
    assert t["model_cost_per_100_runs_usd"] == round(100 * (0.007189 - 0.005), 4)
    assert t["model_cost_derived_from_total"] == 1


def test_2026_09_25_get_log_waits_for_cost_items():
    polls = {"n": 0}

    def handler(request):
        polls["n"] += 1
        items = None if polls["n"] < 3 else [{"category": "model", "cost": 0.002}]
        return httpx.Response(200, json={"data": {"status": "completed",
                                                  "cost": {"total": 0.007, "items": items}}})
    c = SimClient("http://sim", "k", transport=httpx.MockTransport(handler))
    _, log, _ = c.get_log("r", sleep=lambda s: None)
    assert log["cost"]["items"] and polls["n"] == 3


# Pinned to the 11 real summary_entities failures on v1 outputs, reviewed by hand
# on 2026-09-25 (data/*/adjudications.jsonl). The v2 match must clear the
# formatting-only false alarms and still flag both true defects.
import json
from pathlib import Path

import pytest

from simtriage import gates


def _issue(ds, iid):
    for line in Path(f"data/{ds}/issues.jsonl").open():
        r = json.loads(line)
        if r["id"] == iid:
            return f"{r['title']}\n{r['body']}"
    raise KeyError(iid)


@pytest.mark.parametrize("ds,iid,token", [
    ("sim", "sim-1579", "OpenAI-compatible"),
    ("sim", "sim-1724", "UNAUTHORIZED_INVALID_API_KEY"),
    ("sim", "sim-2580", "Next.js"),
    ("sim", "sim-906", "Stripe-only"),
    ("k8s", "k8s-133915", "ContainerOS-specific"),
    ("k8s", "k8s-137700", "Manager's"),
])
def test_2026_09_26_formatting_false_alarms_cleared(ds, iid, token):
    src = _issue(ds, iid)
    assert not gates.entity_supported(token, src, match="v1")      # the pre-registered gate failed here
    assert gates.entity_supported(token, src, match="v2")


@pytest.mark.parametrize("ds,iid,token", [
    ("sim", "sim-720", "Compose"),
    ("sim", "sim-1098", "CVEs"),
])
def test_2026_09_26_true_defects_still_flagged(ds, iid, token):
    assert not gates.entity_supported(token, _issue(ds, iid), match="v2")


@pytest.mark.parametrize("ds,iid,token", [
    ("sim", "sim-1204", "Windows"),        # issue says "Win11"
    ("sim", "sim-1889", "SSL"),            # issue says "local issuer certificate"
    ("sim", "sim-801", "OpenAI-compatible"),  # issue says "compatibility"
])
def test_2026_09_26_semantic_false_alarms_remain_known_limit(ds, iid, token):
    # These need meaning, not string matching; documented as a known limit.
    assert not gates.entity_supported(token, _issue(ds, iid), match="v2")
