import json

import httpx

from simtriage import evaluator, report
from simtriage.sim_client import SimClient
from test_report import project  # noqa: F401  (fixture)


def fake_eval(scores):
    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            assert set(body["input"]) == {"issue", "triage_output"}
            return httpx.Response(200, json={"data": {"runId": "e1", "status": "completed",
                "output": {**scores, "model": "claude-sonnet-4-6", "cost": {"total": 0.01}}}})
        return httpx.Response(200, json={"data": {"status": "completed", "totalDurationMs": 900}})
    return SimClient("http://sim", "k", transport=httpx.MockTransport(handler))


def test_inputs_cover_seeds_mutants_and_natural_errors(project):  # noqa: F811
    d = report.Data(".", "v1")
    report.write_mutants(d)
    d = report.Data(".", "v1")
    rows = evaluator.build_inputs(d)
    kinds = [r["kind"] for r in rows]
    assert kinds.count("seed") == 3 and kinds.count("natural") == 1
    assert kinds.count("mutant") == sum(m["applicable"] for m in d.mutants)
    assert len({r["input_id"] for r in rows}) == len(rows)


def test_score_one_extracts_metric_scores(project):  # noqa: F811
    d = report.Data(".", "v1")
    row = {"input_id": "seed:sim-1", "kind": "seed", "issue_id": "sim-1", "operator": None,
           "output": {"category": "bug"}}
    rec = evaluator.score_one(fake_eval({"classification": 5, "faithfulness": 4, "consistency": 5}),
                              "wf", row, d.issues["sim-1"], 0)
    assert rec["ok"] and rec["scores"] == {"classification": 5, "faithfulness": 4, "consistency": 5}
    bad = evaluator.score_one(fake_eval({"classification": 5}), "wf", row, d.issues["sim-1"], 0)
    assert not bad["ok"]


def test_flag_rule_is_two_of_three_at_cutoff_three(project):  # noqa: F811
    d = report.Data(".", "v1")
    mk = lambda i, rep, c: {"input_id": i, "repeat": rep, "ok": True,
                            "scores": {"classification": c, "faithfulness": 5, "consistency": 5}}
    d.evaluator = [mk("a", 0, 3), mk("a", 1, 5), mk("a", 2, 2),     # 2 of 3 at or below 3 -> flagged
                   mk("b", 0, 3), mk("b", 1, 4), mk("b", 2, 5),     # 1 of 3 -> not flagged
                   mk("c", 0, 1)]                                   # only 1 valid repeat -> no verdict
    assert report.evaluator_flags(d) == {"a": True, "b": False}
    assert report.evaluator_flags(d, cutoff=4)["b"] is True
