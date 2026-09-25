"""Build the Sim dataset from the committed snapshot. Deterministic.

Answer key = the reporter's own template choice ("Bug report" -> bug,
"Feature request" -> feature), stored as `category_coarse`. Label-event history
shows who applied each label; in the 2026-09-25 snapshot only 1 of 311 issues
had a label applied by anyone other than the reporter.

Template artifacts ([BUG]/[REQUEST] title prefixes, template headings and
instruction text) are stripped so the model can't read the answer off the form.
Issues with no bug/feature label form the untriaged `queue` (no answer key).
Issues that are nothing but the untouched template are dropped (and listed).
"""
import json
import random
import re
from pathlib import Path

SEED = 20260925
DEV_FRACTION = 0.6
MAX_BODY_CHARS = 8000
MODEL_CUTOFF = "2025-08-01"   # issues on/after this postdate the triage model's training data
CORE_TEAM = {"waleedlatif1", "icecrasher321", "emir-karabeg", "TheodoreSpeaks",
             "Sg312", "aadamgough", "BillLeoutsakosvl346", "j15z"}
TITLE_PREFIX = re.compile(r"^\s*\[(BUG|REQUEST)\]\s*:?\s*", re.IGNORECASE)
TEMPLATE_LINES = {
    # Sim's .github/ISSUE_TEMPLATE/bug_report.md
    "describe the bug", "a clear and concise description of what the bug is.",
    "to reproduce", "steps to reproduce the behavior:", "go to '...'", "click on '....'",
    "scroll down to '....'", "see error", "expected behavior",
    "a clear and concise description of what you expected to happen.", "screenshots",
    "if applicable, add screenshots to help explain your problem.", "additional context",
    "add any other context about the problem here.",
    # feature_request.md
    "is your feature request related to a problem? please describe.",
    "a clear and concise description of what the problem is. ex. i'm always frustrated when [...]",
    "describe the solution you'd like", "a clear and concise description of what you want to happen.",
    "describe alternatives you've considered",
    "a clear and concise description of any alternative solutions or features you've considered.",
    "add any other context or screenshots about the feature request here.",
}
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
KEEP_DOMAINS = {"example.com", "example.org", "sim.ai"}


def redact(text):
    return EMAIL.sub(lambda m: m.group(0) if m.group(1).lower() in KEEP_DOMAINS
                     or m.group(1)[0].isdigit() else "[email]", text)


def norm(line):
    s = line.replace("\u2019", "'").replace("\u2018", "'")
    s = re.sub(r"^\s*(?:[-*>]|\d+\.)\s*", "", s.strip())
    return s.strip("*_#:. ").strip().lower()


# Template phrases that sometimes survive merged with the reporter's text on one
# line ("Describe the bug The block fails..."); stripped only at line start.
TEMPLATE_SET = {norm(t) for t in TEMPLATE_LINES}
_LEADING = sorted((t for t in TEMPLATE_SET if len(t) < 60), key=len, reverse=True)


def strip_leading_template(line):
    changed = True
    while changed:
        changed = False
        low = norm(line)
        for t in _LEADING:
            if low.startswith(t) and low != t:
                idx = line.lower().replace("\u2019", "'").find(t)
                if idx != -1:
                    line = line[idx + len(t):].lstrip(" *_:#")
                    changed = True
                    break
    return line


def clean_body(body):
    kept = []
    for line in body.splitlines():
        if norm(line) in TEMPLATE_SET:
            continue
        rest = strip_leading_template(line)
        if norm(rest) not in TEMPLATE_SET:
            kept.append(rest)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return redact(text)


def main():
    raw = json.load(open("data/sim/raw/issues_2026-09-25.json"))
    events = {int(k): v for k, v in json.load(open("data/sim/raw/label_events_2026-09-25.json")).items()}
    pool = sorted((x for x in raw if not x["author"].get("is_bot")
                   and x["author"]["login"] not in CORE_TEAM and len(x["body"] or "") >= 150),
                  key=lambda x: x["number"])

    issues, key, queue, empty = [], [], [], []
    for x in pool:
        iid = f"sim-{x['number']}"
        body = clean_body(x["body"])
        if len(TITLE_PREFIX.sub("", x["title"]).strip() + body) < 40:
            empty.append(iid)      # nothing but the untouched template: nothing to triage
            continue
        issues.append({"id": iid, "number": x["number"], "url": x["url"], "created_at": x["createdAt"],
                       "after_model_cutoff": x["createdAt"] >= MODEL_CUTOFF,
                       "title": redact(TITLE_PREFIX.sub("", x["title"])).strip(),
                       "body": body[:MAX_BODY_CHARS] + ("\n[truncated]" if len(body) > MAX_BODY_CHARS else ""),
                       "truncated": len(body) > MAX_BODY_CHARS})
        labels = {l["name"] for l in x["labels"]} & {"bug", "feature"}
        if len(labels) == 1:
            lab = labels.pop()
            setters = {e["actor"] for e in events.get(x["number"], [])
                       if e["event"] == "labeled" and e["label"] == lab}
            source = "reporter_template" if setters <= {x["author"]["login"]} else "maintainer"
            key.append({"id": iid, "category_coarse": lab, "key_source": source})
        else:
            queue.append(iid)

    rng = random.Random(SEED)
    dev, test = [], []
    for cls in ("bug", "feature"):
        ids = sorted(k["id"] for k in key if k["category_coarse"] == cls)
        rng.shuffle(ids)
        cut = round(len(ids) * DEV_FRACTION)
        dev += ids[:cut]
        test += ids[cut:]

    out = Path("data/sim")
    with open(out / "issues.jsonl", "w") as f:
        f.writelines(json.dumps(i) + "\n" for i in issues)
    with open(out / "answer_key.jsonl", "w") as f:
        f.writelines(json.dumps(k) + "\n" for k in key)
    json.dump({"seed": SEED, "dev": sorted(dev), "test": sorted(test), "queue": sorted(queue)},
              open(out / "split.json", "w"), indent=1)
    src = {s: sum(k["key_source"] == s for k in key) for s in ("reporter_template", "maintainer")}
    print(f"dropped {len(empty)} template-only issues: {empty}")
    print(f"pool={len(issues)} keyed={len(key)} {src} queue={len(queue)} dev={len(dev)} test={len(test)}")
    print("bug/feature:", sum(k["category_coarse"] == "bug" for k in key), sum(k["category_coarse"] == "feature" for k in key))


if __name__ == "__main__":
    main()
