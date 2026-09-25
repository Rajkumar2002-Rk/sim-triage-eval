"""Human adjudication in the terminal (PROTOCOL.md section 7). No model calls.

Two queues:
  key   Sim issues where the v1 model's bug/feature call disagrees with the
        reporter's template choice. The reviewer is shown the issue only, not
        either side's answer, and asked to classify it blind. The verdict
        (reporter right / model right / neither) is derived afterwards.
  gates Every label-free gate failure on a real v1 output (both datasets). The
        reviewer sees the issue, the summary and the flagged detail, and marks
        it a true defect or a false alarm.

Saves after every answer to data/<ds>/adjudications.jsonl; rerunning resumes.
"""
import json
import re
import shutil
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from . import gates, report


class Quit(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(path, rec):
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _existing(path, kind):
    p = Path(path)
    if not p.exists():
        return set()
    return {r["record_id"] for r in map(json.loads, p.open()) if r.get("kind") == kind}


def _ask(prompt, options):
    menu = "  ".join(f"{i}={o}" for i, o in enumerate(options, 1))
    while True:
        raw = input(f"{prompt}\n  {menu}   (q = save and quit)\n> ").strip().lower()
        if raw == "q":
            raise Quit
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]


def _show(header, issue):
    width = min(shutil.get_terminal_size().columns, 110)
    print("\033[2J\033[H", end="")
    print(header)
    print("=" * width)
    print(textwrap.fill(issue["title"], width))
    print("-" * width)
    print(issue["body"])
    print("=" * width)


def key_queue(root=".", version="v1"):
    d = report.Data(root, "sim", version)
    out = []
    for e in report.natural_errors(d, "all"):
        i = e["issue_id"]
        obj, _ = gates.parse(e["output"])
        model = d.tax.grade_category((obj or {}).get("category"))
        out.append({"record_id": f"{i}:category_coarse", "issue_id": i,
                    "reporter": d.key[i]["category_coarse"], "model": model})
    return d, out


def gate_queue(root=".", version="v1"):
    items = []
    for ds in ("sim", "k8s"):
        d = report.Data(root, ds, version)
        for split in ("dev", "test", "queue"):
            for i, o in sorted(d.primary(split).items()):
                for r in gates.label_free(o["triage"], d.issues[i], d.tax).results:
                    if r.status == gates.FAIL:
                        items.append({"dataset": ds, "record_id": f"{i}:{r.gate}", "issue_id": i,
                                      "gate": r.gate, "detail": r.detail, "split": split,
                                      "summary": (o["triage"] or {}).get("summary") if isinstance(o["triage"], dict) else None,
                                      "issue": d.issues[i]})
    return items


def _evidence(issue, detail):
    """Lines of the issue that mention any part of the flagged token (evidence, not a verdict)."""
    parts = {p.lower() for tok in detail.split(",") for p in re.split(r"[-'’_ ]", tok) if len(p) >= 3}
    lines = [l.strip() for l in (issue["title"] + "\n" + issue["body"]).splitlines()
             if any(p in l.lower() for p in parts)]
    return lines[:6]


def run_key(root=".", version="v1"):
    d, queue = key_queue(root, version)
    path = Path(root) / "data/sim/adjudications.jsonl"
    done = _existing(path, "key_disagreement")
    todo = [q for q in queue if q["record_id"] not in done]
    try:
        for n, q in enumerate(todo, 1):
            _show(f"[{len(done) + n}/{len(queue)}]  {q['issue_id']}   (blind: no one's answer is shown)",
                  d.issues[q["issue_id"]])
            human = _ask("What is this issue?", ["bug", "feature", "neither"])
            notes = input("note (optional)\n> ").strip()
            final = {"neither": "other"}.get(human, human)
            verdict = ("reporter_right" if final == q["reporter"] else
                       "model_right" if final == q["model"] else "neither")
            _append(path, {"kind": "key_disagreement", "record_id": q["record_id"], "issue_id": q["issue_id"],
                           "field": "category_coarse", "human": final, "reporter": q["reporter"],
                           "model": q["model"], "verdict": verdict, "final": final, "reason": notes,
                           "at": _now()})
    except (Quit, KeyboardInterrupt, EOFError):
        pass
    left = len(queue) - len(_existing(path, "key_disagreement"))
    print(f"\nkey disagreements: {len(queue) - left}/{len(queue)} done")
    return 0 if left == 0 else 1


def run_gates(root=".", version="v1"):
    queue = gate_queue(root, version)
    done = {ds: _existing(Path(root) / f"data/{ds}/adjudications.jsonl", "gate_failure") for ds in ("sim", "k8s")}
    todo = [q for q in queue if q["record_id"] not in done[q["dataset"]]]
    try:
        for n, q in enumerate(todo, 1):
            _show(f"[{n}/{len(todo)} left]  {q['dataset']} {q['issue_id']}  gate: {q['gate']}", q["issue"])
            print(f"AI SUMMARY: {q['summary']!r}")
            print(f"FLAGGED:    {q['detail']}")
            ev = _evidence(q["issue"], q["detail"])
            if ev:
                print("Issue lines mentioning part of it:")
                for l in ev:
                    print(f"   | {l[:140]}")
            verdict = _ask("Is the flagged thing a real problem in the summary?",
                           ["true_defect", "false_alarm"])
            notes = input("why, in a few words\n> ").strip()
            _append(Path(root) / f"data/{q['dataset']}/adjudications.jsonl",
                    {"kind": "gate_failure", "record_id": q["record_id"], "issue_id": q["issue_id"],
                     "gate": q["gate"], "detail": q["detail"], "split": q["split"],
                     "verdict": verdict, "reason": notes, "at": _now()})
    except (Quit, KeyboardInterrupt, EOFError):
        pass
    left = sum(q["record_id"] not in _existing(Path(root) / f"data/{q['dataset']}/adjudications.jsonl",
                                               "gate_failure") for q in queue)
    print(f"\ngate failures: {len(queue) - left}/{len(queue)} done")
    return 0 if left == 0 else 1
