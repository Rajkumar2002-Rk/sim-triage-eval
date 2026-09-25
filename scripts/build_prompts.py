"""Assemble each dataset's triage prompt, evaluator prompt and response schema.

The rubric (prompts/<ds>/rubric.md) is the customer's rules. The triage agent
and the Evaluator get the identical rubric, so the comparison is fair.
triage_v1.md is generated; later versions (v2, ...) are hand-edited copies.
"""
import json
from pathlib import Path

from simtriage import schema

INTRO = {
    "sim": "You triage GitHub issues filed against Sim, an open-source platform for building and "
           "deploying AI agent workflows.",
    "k8s": "You triage GitHub issues filed against Kubernetes (kubernetes/kubernetes), following "
           "the project's own triage rules.",
}
SUMMARY = ("## summary\nOne line, at most 160 characters, stating the issue's core problem or request. "
           "Use only facts stated in the issue. Don't add names, versions, numbers, URLs, services or "
           "claims that aren't in the issue text.\n")


def main():
    for name, tax in schema.REGISTRY.items():
        d = Path("prompts") / name
        rubric = (d / "rubric.md").read_text().strip()
        (d / "triage_v1.md").write_text(
            f"{INTRO[name]} For each issue, return a JSON object with category, priority, product_area, "
            f"needs_human and summary. Judge only what the issue says.\n\n{rubric}\n\n{SUMMARY}")
        (d / "evaluator_system.md").write_text(
            f"You are reviewing the output of an automated triage system. {INTRO[name].replace('You triage', 'It triages')} "
            "You get the issue and the triage output. Score the output on each metric using the rubric "
            "below, which is the same rubric the triage system was given.\n\n"
            "Score what the output says, compared with what the issue says. A score of 5 means fully correct. "
            "A score of 1 means clearly wrong. Structural problems (a missing field, an extra field, a value "
            "outside the allowed set) count against the metric they affect.\n\n"
            f"{rubric}\n\n{SUMMARY}")
        s = tax.model.model_json_schema()
        for prop in s["properties"].values():
            prop.pop("title", None)
        for k in ("title", "description"):
            s.pop(k, None)
        s["additionalProperties"] = False
        (d / "response_format.json").write_text(json.dumps({"name": "triage", "strict": True, "schema": s}, indent=2) + "\n")
        print(f"{name}: {len((d / 'triage_v1.md').read_text())} chars prompt, "
              f"{len(tax.categories)} categories, {len(tax.areas)} areas")


if __name__ == "__main__":
    main()
