"""Build the Kubernetes dataset from the committed snapshot. Deterministic.

Answer key, per field, with its provenance:
  priority      set by a triager (the person whose `/priority` command applied the
                label is not the reporter). Only these issues are included.
  category      kind/* labels (list): mostly the reporter's template or /kind command.
  product_area  sig/* labels (list): the reporter or a triager.
Template headings, placeholders and prow command lines (`/kind`, `/sig`, ...) are
stripped: the form's headings reveal which template (kind) was used, and the
commands state the label outright. Anything a person typed is kept.
"""
import json
import random
import re
from pathlib import Path

SEED = 20260925
DEV_FRACTION = 0.6
MAX_BODY_CHARS = 8000
RAW = "data/k8s/raw/issues_2026-09-25.json"
PRIORITY = {f"priority/{p}": p for p in ("critical-urgent", "important-soon", "important-longterm", "backlog")}
TEMPLATE_HEADINGS = {  # .github/ISSUE_TEMPLATE/*.yaml field labels, lower-cased
    "what happened?", "what did you expect to happen?",
    "how can we reproduce it (as minimally and precisely as possible)?", "anything else we need to know?",
    "kubernetes version", "cloud provider", "os version", "install tools",
    "container runtime (cri) and version (if applicable)",
    "related plugins (cni, csi, ...) and versions (if applicable)",
    "what would you like to be added?", "why is this needed?",
    "which jobs are failing?", "which tests are failing?", "since when has it been failing?",
    "which jobs are flaking?", "which tests are flaking?", "since when has it been flaking?",
    "testgrid link", "reason for failure (if possible)", "relevant sig(s)",
}
HEADINGS_BARE = {h.rstrip("?:") for h in TEMPLATE_HEADINGS}
PLACEHOLDERS = {"paste output here", "_no response_", "<!-- paste output here -->"}
COMMAND = re.compile(r"^\s*(?:[-*]\s*)?/(kind|sig|priority|triage|area|assign|cc|label|remove-\w+|milestone|help|good-first-issue|lifecycle)\b.*$", re.I)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def clean_body(body):
    body = HTML_COMMENT.sub("", body)
    kept = []
    for line in body.splitlines():
        head = re.sub(r"^#{1,6}\s*", "", line.strip()).strip("* ").lower()
        if (head in TEMPLATE_HEADINGS or head.rstrip("?:") in HEADINGS_BARE
                or head in PLACEHOLDERS or COMMAND.match(line)):
            continue
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def priority_setter(x, p):
    """Who issued the `/priority p` that stands? None if it can't be traced."""
    who = [c["user"] for c in x["comments"] if re.search(rf"^\s*/priority\s+{p}\b", c["body"], re.M)]
    if re.search(rf"^\s*/priority\s+{p}\b", x["body"], re.M):
        who.insert(0, x["author"])
    return who[-1] if who else None


def main():
    raw = json.load(open(RAW))
    issues, key, skipped = [], [], {"not_one_priority": 0, "reporter_set": 0, "untraceable": 0, "empty": 0}
    for x in sorted(raw, key=lambda x: x["number"]):
        ps = [PRIORITY[l] for l in x["labels"] if l in PRIORITY]
        if len(ps) != 1:
            skipped["not_one_priority"] += 1
            continue
        setter = priority_setter(x, ps[0])
        if setter is None:
            skipped["untraceable"] += 1
            continue
        if setter == x["author"]:
            skipped["reporter_set"] += 1
            continue
        body = clean_body(x["body"])
        if len(x["title"] + body) < 40:
            skipped["empty"] += 1
            continue
        iid = f"k8s-{x['number']}"
        issues.append({"id": iid, "number": x["number"], "url": x["url"], "created_at": x["created_at"],
                       "title": x["title"].strip(),
                       "body": body[:MAX_BODY_CHARS] + ("\n[truncated]" if len(body) > MAX_BODY_CHARS else ""),
                       "truncated": len(body) > MAX_BODY_CHARS})
        rec = {"id": iid, "priority": ps[0], "priority_set_by": setter}
        kinds = sorted(l[5:].replace("-", "_") for l in x["labels"] if l.startswith("kind/"))
        sigs = sorted(l[4:] for l in x["labels"] if l.startswith("sig/"))
        if kinds:
            rec["category"] = kinds
        if sigs:
            rec["product_area"] = sigs
        key.append(rec)

    rng = random.Random(SEED)
    dev, test = [], []
    for p in PRIORITY.values():
        ids = sorted(k["id"] for k in key if k["priority"] == p)
        rng.shuffle(ids)
        cut = round(len(ids) * DEV_FRACTION)
        dev += ids[:cut]
        test += ids[cut:]

    out = Path("data/k8s")
    with open(out / "issues.jsonl", "w") as f:
        f.writelines(json.dumps(i) + "\n" for i in issues)
    with open(out / "answer_key.jsonl", "w") as f:
        f.writelines(json.dumps({k: v for k, v in r.items() if k != "priority_set_by"}) + "\n" for r in key)
    with open(out / "priority_provenance.jsonl", "w") as f:
        f.writelines(json.dumps({"id": r["id"], "priority_set_by": r["priority_set_by"]}) + "\n" for r in key)
    json.dump({"seed": SEED, "dev": sorted(dev), "test": sorted(test), "queue": []},
              open(out / "split.json", "w"), indent=1)
    print(f"kept={len(issues)} skipped={skipped} dev={len(dev)} test={len(test)}")
    print("with category key:", sum("category" in k for k in key), " with area key:", sum("product_area" in k for k in key))


if __name__ == "__main__":
    main()
