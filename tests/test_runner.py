import json

import httpx
import pytest

from simtriage import runner
from simtriage.sim_client import SimClient, extract_triage

TRIAGE = {"category": "bug", "priority": "high", "product_area": "self_hosting",
          "needs_human": True, "summary": "Migrations fail."}


def fake_sim(log_running_polls=2, output=None):
    """A fake Sim that returns the log as 'running' for a few polls, like the real one."""
    state = {"polls": 0}
    output = output or {**TRIAGE, "model": "claude-haiku-4-5", "tokens": {"total": 9}, "cost": {"total": 0.001}}

    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            assert set(body["input"]) == {"title", "body"}
            return httpx.Response(200, json={"data": {"runId": "r1", "status": "completed",
                                                      "output": output, "durationMs": 700}})
        state["polls"] += 1
        status = "running" if state["polls"] <= log_running_polls else "completed"
        return httpx.Response(200, json={"data": {"status": status, "totalDurationMs": 705,
            "traceSpans": [{"type": "workflow", "name": "Workflow Execution", "status": "success",
                            "duration": 705, "children": [{"type": "agent", "name": "Agent",
                            "status": "success", "duration": 700, "model": "claude-haiku-4-5"}]}]}})
    return httpx.MockTransport(handler), state


def test_extract_structured_fields_drops_only_metadata():
    out = {**TRIAGE, "model": "m", "tokens": {}, "cost": {}, "providerTiming": {}, "toolCalls": {}}
    assert extract_triage(out) == (TRIAGE, "fields")


def test_extract_keeps_invented_extra_field():
    got, _ = extract_triage({**TRIAGE, "confidence": 0.9, "model": "m"})
    assert got["confidence"] == 0.9


def test_extract_content_only_returns_raw_text():
    assert extract_triage({"content": '{"a": 1}', "model": "m"}) == ('{"a": 1}', "content")


def test_extract_prefers_fields_when_content_echoed():
    got, how = extract_triage({**TRIAGE, "content": json.dumps(TRIAGE), "model": "m"})
    assert got == TRIAGE and how == "fields"


def test_log_polled_until_terminal():
    transport, state = fake_sim(log_running_polls=3)
    c = SimClient("http://sim", "k", transport=transport)
    status, log, waited = c.get_log("r1", sleep=lambda s: None)
    assert log["status"] == "completed" and state["polls"] == 4


def test_run_one_records_output_and_telemetry():
    transport, _ = fake_sim()
    c = SimClient("http://sim", "k", transport=transport)
    rec = runner.run_one(c, "wf", {"id": "x-1", "title": "t", "body": "b"}, 0, "v1")
    assert rec["triage"] == TRIAGE
    assert rec["log"]["status"] == "completed"
    assert [s["name"] for s in rec["log"]["spans"]] == ["Workflow Execution", "Agent"]


def test_transport_errors_are_retried_and_recorded():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("refused")
    c = SimClient("http://sim", "k", transport=httpx.MockTransport(handler))
    rec = runner.run_one(c, "wf", {"id": "x-1", "title": "t", "body": "b"}, 0, "v1", retries=2)
    assert rec["http_status"] is None and len(rec["transport_errors"]) == 3 and calls["n"] == 3


def test_guard_requires_answer_key_before_outputs(tmp_path):
    with pytest.raises(runner.ContaminationError):
        runner.guard_key_frozen("sim", tmp_path)
    (tmp_path / "data/sim").mkdir(parents=True)
    (tmp_path / "data/sim/answer_key.jsonl").write_text("")
    runner.guard_key_frozen("sim", tmp_path)


def test_run_is_resumable(tmp_path, monkeypatch):
    transport, _ = fake_sim(log_running_polls=0)
    c = SimClient("http://sim", "k", transport=transport)
    issues = [{"id": "x-1", "title": "t", "body": "b"}]
    out = tmp_path / "o.jsonl"
    assert runner.run(c, "wf", issues, "v1", out, repeats=2) == 2
    assert runner.run(c, "wf", issues, "v1", out, repeats=2) == 0
    assert runner.run(c, "wf", issues, "v1", out, repeats=3) == 1


def test_rate_limited_calls_wait_and_retry():
    calls = {"n": 0}

    def handler(request):
        if request.method == "POST":
            calls["n"] += 1
            if calls["n"] <= 2:
                return httpx.Response(429, json={"error": {"code": "RATE_LIMITED",
                                      "details": {"retryAfter": "2000-01-01T00:00:00Z"}}})
            return httpx.Response(200, json={"data": {"runId": "r1", "status": "completed",
                                                      "output": {**TRIAGE, "model": "m"}}})
        return httpx.Response(200, json={"data": {"status": "completed"}})
    slept = []
    c = SimClient("http://sim", "k", transport=httpx.MockTransport(handler))
    rec = runner.run_one(c, "wf", {"id": "x-1", "title": "t", "body": "b"}, 0, "v1", sleep=slept.append)
    assert rec["http_status"] == 200 and rec["triage"] == TRIAGE
    assert rec["rate_limited_waits_s"] == [1.0, 1.0] and slept == [1.0, 1.0]   # past retryAfter -> min wait


def test_retry_after_parsing():
    from datetime import datetime, timedelta, timezone
    soon = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    assert 9 <= runner.retry_after_s({"error": {"details": {"retryAfter": soon}}}) <= 11.5
    assert runner.retry_after_s({"nope": 1}) == 15.0


def test_rate_limited_records_are_not_done(tmp_path):
    out = tmp_path / "o.jsonl"
    out.write_text(json.dumps({"issue_id": "a", "repeat": 0, "http_status": 429}) + "\n"
                   + json.dumps({"issue_id": "b", "repeat": 0, "http_status": 200}) + "\n")
    assert runner.done_keys(out) == {("b", 0)}
