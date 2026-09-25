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
