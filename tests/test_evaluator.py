import json

import httpx

from simtriage import evaluator, report
from simtriage.sim_client import SimClient
from test_report import project  # noqa: F401  (fixture)


def fake_eval(scores):
    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            assert set(body["input"]) == {"rubric", "issue", "triage_output"}
            return httpx.Response(200, json={"data": {"runId": "e1", "status": "completed",
                "output": {**scores, "model": "claude-sonnet-4-6", "cost": {"total": 0.01}}}})
        return httpx.Response(200, json={"data": {"status": "completed", "totalDurationMs": 900}})
    return SimClient("http://sim", "k", transport=httpx.MockTransport(handler))


def test_inputs_cover_seeds_mutants_and_natural_errors(project):  # noqa: F811
    d = report.Data(".", "sim", "v1")
    report.write_mutants(d)
    d = report.Data(".", "sim", "v1")
    rows = evaluator.build_inputs(d)
    kinds = [r["kind"] for r in rows]
    assert kinds.count("seed") == 3 and kinds.count("natural") == 1
    assert kinds.count("mutant") == sum(m["applicable"] for m in d.mutants)
    assert len({r["input_id"] for r in rows}) == len(rows)


def test_score_one_extracts_metric_scores(project):  # noqa: F811
    d = report.Data(".", "sim", "v1")
    row = {"input_id": "seed:sim-1", "kind": "seed", "issue_id": "sim-1", "operator": None,
           "output": {"category": "bug"}}
    rec = evaluator.score_one(fake_eval({"classification": 5, "faithfulness": 4, "consistency": 5}),
                              "wf", row, d.issues["sim-1"], 0, "RUBRIC")
    assert rec["ok"] and rec["scores"] == {"classification": 5, "faithfulness": 4, "consistency": 5}
    bad = evaluator.score_one(fake_eval({"classification": 5}), "wf", row, d.issues["sim-1"], 0, "RUBRIC")
    assert not bad["ok"]


def test_flag_rules_majority_primary_and_single_secondary(project):  # noqa: F811
    d = report.Data(".", "sim", "v1")
    mk = lambda i, rep, c: {"input_id": i, "repeat": rep, "ok": True,
                            "scores": {"classification": c, "faithfulness": 5, "consistency": 5}}
    d.evaluator = [mk("a", 0, 3), mk("a", 1, 5), mk("a", 2, 2),     # 2 of 3 flag -> flagged
                   mk("b", 0, 3), mk("b", 1, 4), mk("b", 2, 5),     # 1 of 3 -> not flagged; single says flagged
                   mk("c", 0, 1)]                                   # only 1 run -> no majority verdict
    assert report.evaluator_flags(d) == {"a": True, "b": False}
    assert report.evaluator_flags(d, rule="single") == {"a": True, "b": True, "c": True}
    st = report.evaluator_stability(d)
    assert st["verdict_identical_across_3_runs"]["k"] == 0 and st["verdict_identical_across_3_runs"]["n"] == 2


def test_full_plan_is_repeat_major():
    rows = [{"input_id": f"x{i}"} for i in range(4)]
    jobs = evaluator.plan_full(rows, 3)
    assert [k for _, k in jobs] == [0] * 4 + [1] * 4 + [2] * 4


def test_sampling_is_capped_deterministic_and_complete_when_full(project):  # noqa: F811
    d = report.Data(".", "sim", "v1")
    report.write_mutants(d)
    d = report.Data(".", "sim", "v1")
    a = evaluator.build_inputs(d, per_operator=1, seed_cap=2, natural_cap=1)
    b = evaluator.build_inputs(d, per_operator=1, seed_cap=2, natural_cap=1)
    assert a == b
    ops = [r["operator"] for r in a if r["kind"] == "mutant"]
    assert len(ops) == len(set(ops))                         # at most one per operator
    assert sum(r["kind"] == "seed" for r in a) == 2
    full = evaluator.build_inputs(d, None, None, None)
    assert sum(r["kind"] == "mutant" for r in full) == sum(m["applicable"] for m in d.mutants)


def test_plan_jobs_repeats_only_the_variance_subset():
    rows = [{"input_id": f"x{i}"} for i in range(10)]
    jobs = evaluator.plan_jobs(rows, extra_repeats=2, variance_n=3)
    assert sum(k == 0 for _, k in jobs) == 10 and len(jobs) == 10 + 3 * 2


def test_failed_checks_are_retried(tmp_path):
    out = tmp_path / "e.jsonl"
    out.write_text(json.dumps({"input_id": "a", "repeat": 0, "http_status": 200, "ok": False}) + "\n"
                   + json.dumps({"input_id": "b", "repeat": 0, "http_status": 200, "ok": True}) + "\n")
    assert evaluator.done_keys_eval(out) == {("b", 0)}
