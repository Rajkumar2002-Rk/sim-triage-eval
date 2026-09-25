import builtins
import json

from simtriage import adjudicate, report
from test_report import project  # noqa: F401  (fixture)


def feed(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))


def test_key_queue_is_blind_and_verdict_is_derived(project, monkeypatch):  # noqa: F811
    (project / "data/sim/answer_key.jsonl").write_text("".join(
        json.dumps({"id": k, "category_coarse": v}) + "\n"
        for k, v in {"sim-1": "bug", "sim-2": "feature", "sim-3": "bug", "sim-4": "feature"}.items()))
    # fixture outputs: sim-3 'security' (-> bug, agrees), sim-4 'question' (-> other, disagrees)
    feed(monkeypatch, ["1", "reads like a crash"])            # human says bug
    shown = []
    monkeypatch.setattr(adjudicate, "_show", lambda header, issue: shown.append(header))
    assert adjudicate.run_key(".", "v1") == 0
    assert len(shown) == 1 and "blind" in shown[0]
    rec = json.loads((project / "data/sim/adjudications.jsonl").read_text())
    assert rec["issue_id"] == "sim-4" and rec["verdict"] == "neither" and rec["final"] == "bug"
    adj = report.Data(".", "sim", "v1", "adjudicated")
    assert adj.key["sim-4"]["category_coarse"] == "bug"


def test_gate_queue_records_verdicts_and_resumes(project, monkeypatch):  # noqa: F811
    lines = (project / "runs/sim/v1/outputs.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    first["triage"]["summary"] = "Migration fails on Kubernetes"          # entity not in sim-1
    lines[0] = json.dumps(first)
    (project / "runs/sim/v1/outputs.jsonl").write_text("\n".join(lines) + "\n")
    (project / "data/k8s").mkdir()
    for f in ("issues.jsonl", "answer_key.jsonl"):
        (project / "data/k8s" / f).write_text("")
    (project / "data/k8s/split.json").write_text(json.dumps({"dev": [], "test": [], "queue": []}))
    monkeypatch.setattr(adjudicate, "_show", lambda header, issue: None)
    feed(monkeypatch, ["2", "the issue says k8s elsewhere"])
    assert adjudicate.run_gates(".", "v1") == 0
    rec = json.loads((project / "data/sim/adjudications.jsonl").read_text())
    assert rec["gate"] == "summary_entities" and rec["verdict"] == "false_alarm"
    feed(monkeypatch, [])                                                  # nothing left to ask
    assert adjudicate.run_gates(".", "v1") == 0
    g = report.gate_adjudications(report.Data(".", "sim", "v1"))
    assert g["summary_entities"]["false_alarm"] == 1
