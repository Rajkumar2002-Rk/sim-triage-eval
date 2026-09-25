import json

import pytest

from simtriage import cli, report
from simtriage.stats import cohen_kappa, macro_f1, percentile, wilson

ISSUES = {
    "sim-1": {"id": "sim-1", "title": "[BUG] Docker migrations fail", "body": "Postgres migration fails on Ubuntu 22.04."},
    "sim-2": {"id": "sim-2", "title": "Slack threads", "body": "Please support posting to Slack threads."},
    "sim-3": {"id": "sim-3", "title": "SQL injection in logs API", "body": "The logs endpoint builds SQL from input."},
    "sim-4": {"id": "sim-4", "title": "How do variables work?", "body": "Is <start.x> the right syntax?"},
}
LABELS = {
    "sim-1": dict(category="bug", priority="high", product_area="self_hosting", needs_human=True),
    "sim-2": dict(category="feature_request", priority="medium", product_area="integrations", needs_human=False),
    "sim-3": dict(category="security", priority="urgent", product_area="logs_observability", needs_human=True),
    "sim-4": dict(category="question", priority="low", product_area="execution_engine", needs_human=False),
}
QUEUE_ISSUE = {"id": "sim-5", "title": "Untagged", "body": "Postgres migration fails on Ubuntu 22.04."}
SUMMARY = {"sim-1": "Postgres migration fails on Ubuntu 22.04.", "sim-2": "Request to post to Slack threads.",
           "sim-3": "Logs endpoint builds SQL from input.", "sim-4": "Asks about variable syntax."}


def out(issue_id, repeat, **over):
    triage = {**LABELS[issue_id], "summary": SUMMARY[issue_id], **over}
    return {"issue_id": issue_id, "repeat": repeat, "version": "v1", "http_status": 200,
            "exec_status": "completed", "triage": triage, "client_ms": 800 + repeat,
            "log": {"status": "completed", "total_ms": 700, "cost": {"total": 0.001},
                    "spans": [{"type": "agent", "duration_ms": 690}]}}


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "data/sim").mkdir(parents=True)
    (tmp_path / "runs/sim/v1").mkdir(parents=True)
    w = lambda p, rows: (tmp_path / p).write_text("".join(json.dumps(r) + "\n" for r in rows))
    w("data/sim/issues.jsonl", list(ISSUES.values()) + [QUEUE_ISSUE])
    w("data/sim/answer_key.jsonl", [{"id": k, **v} for k, v in LABELS.items()])
    (tmp_path / "data/sim/split.json").write_text(json.dumps(
        {"dev": ["sim-1", "sim-2"], "test": ["sim-3", "sim-4"], "queue": ["sim-5"]}))
    outputs = []
    for r in range(3):
        outputs += [out("sim-1", r), out("sim-2", r),
                    out("sim-3", r, priority="high"),                  # natural error, label-free gates can't see it
                    out("sim-4", r, category="bug" if r == 2 else "question")]  # unstable on repeat 2
    outputs.append({**out("sim-1", 0), "issue_id": "sim-5"})
    w("runs/sim/v1/outputs.jsonl", outputs)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_wilson_known_values():
    w = wilson(8, 10)
    assert w["p"] == 0.8 and w["lo"] == pytest.approx(0.4902, abs=1e-3) and w["hi"] == pytest.approx(0.9433, abs=1e-3)
    assert wilson(0, 0) is None


def test_kappa_and_f1_and_percentile():
    assert cohen_kappa(list("aabb"), list("aabb")) == 1.0
    assert cohen_kappa(list("abab"), list("aabb")) == 0.0
    assert macro_f1(["a", "b"], ["a", "a"], ["a", "b", "c"]) == pytest.approx((2 / 3 + 0) / 2, abs=1e-4)
    assert percentile([1, 2, 3, 4], 0.5) == 2.5


def test_field_metrics_and_stability(project):
    d = report.Data(".", "sim", "v1")
    f = report.field_metrics(d, "all")
    assert f["category"]["accuracy"]["k"] == 4          # repeat 0 is the primary output
    assert f["priority"]["accuracy"]["k"] == 3 and f["priority"]["within_one"]["k"] == 4
    assert f["all_graded_fields"]["k"] == 3
    s = report.stability(d, "all")
    assert s["category"]["k"] == 3 and s["priority"]["k"] == 4


def test_seeds_natural_errors_and_mutation_recall(project):
    d = report.Data(".", "sim", "v1")
    assert [s["issue_id"] for s in report.seeds(d)] == ["sim-1", "sim-2", "sim-4"]
    ne = report.natural_error_detection(d)
    assert ne["n_errors"] == 1 and ne["label_free"]["k"] == 0   # wrong priority is invisible without labels
    n_seeds, n_mut = report.write_mutants(d)
    assert n_seeds == 3 and n_mut == 3 * 12
    d = report.Data(".", "sim", "v1")
    mr = report.mutation_recall(d)["by_operator"]
    assert mr["needs_human_flip"]["label_dependent"]["p"] == 1.0
    assert mr["field_extra"]["label_free"]["p"] == 1.0


def test_cli_exit_codes(project):
    assert cli.main(["report", "--dataset", "sim", "--version", "v1", "--split", "all"]) == 0
    assert cli.main(["report", "--dataset", "sim", "--version", "v1", "--split", "all", "--fail-under", "0.9"]) == 1
    assert cli.main(["report", "--dataset", "sim", "--version", "v9"]) == 3
    assert cli.main(["report"]) == 2
    assert cli.main(["mutate", "--dataset", "sim", "--version", "v1"]) == 0
    assert cli.main(["report", "--dataset", "sim", "--version", "v1", "--split", "all",
                     "--metric", "label_free_mutation_recall", "--json", "out/r.json"]) == 0
    assert json.loads((project / "out/r.json").read_text())["mutation"]["by_operator"]


def test_excluded_issue_is_dropped_everywhere(project):
    (project / "data/sim/excluded.json").write_text(json.dumps({"sim-4": "calibration"}))
    d = report.Data(".", "sim", "v1")
    assert "sim-4" not in d.ids("all") and "sim-4" not in d.ids("test")
    assert report.field_metrics(d, "all")["category"]["accuracy"]["n"] == 3


def test_queue_is_not_graded_but_gets_gate_rates(project):
    d = report.Data(".", "sim", "v1")
    assert "sim-5" not in d.ids("all") and d.ids("queue") == ["sim-5"]
    assert report.build(d, "all")["queue_gate_failure_rates"]["schema"]["fail"]["n"] == 1


def test_partial_key_grades_only_keyed_fields(project):
    (project / "data/sim/answer_key.jsonl").write_text("".join(
        json.dumps({"id": k, "category_coarse": "feature" if k == "sim-2" else "bug"}) + "\n" for k in LABELS))
    d = report.Data(".", "sim", "v1")
    f = report.field_metrics(d, "all")
    assert set(f) == {"category", "all_graded_fields"}
    # sim-3 predicted 'security' -> graded as bug (match); sim-4 'question' -> other (miss)
    assert f["category"]["accuracy"]["k"] == 3


def test_adjudicated_key_is_a_view_not_an_edit(project):
    (project / "data/sim/adjudications.jsonl").write_text(json.dumps(
        {"kind": "key_disagreement", "issue_id": "sim-3", "field": "priority", "final": "high",
         "verdict": "model_right", "reason": "x"}) + "\n")
    orig = report.Data(".", "sim", "v1", "original")
    adj = report.Data(".", "sim", "v1", "adjudicated")
    assert orig.key["sim-3"]["priority"] == "urgent" and adj.key["sim-3"]["priority"] == "high"
    assert report.key_disagreements(adj)["key_was_wrong"]["k"] == 1


def test_majority_baseline_is_chosen_on_dev(project):
    d = report.Data(".", "sim", "v1")
    f = report.field_metrics(d, "test")
    # dev = sim-1 (high), sim-2 (medium): tie broken by first seen -> "high"; test has urgent, low
    assert f["priority"]["majority_baseline"]["always"] == "high"
    assert f["priority"]["majority_baseline"]["k"] == 0
