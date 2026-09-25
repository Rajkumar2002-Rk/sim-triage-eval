"""Out-of-sample issues (filed before the 2025-08-01 cutoff) for building and
smoke-testing the workflow while labeling is in progress. Never used in results."""
import json
import sys

sys.path.insert(0, "scripts")
from sample_issues import MAX_BODY_CHARS, redact  # noqa: E402

NUMBERS = (658, 403, 824, 378, 623, 720, 433, 802)
raw = {x["number"]: x for x in json.load(open("data/raw/sim_issues_2026-09-25.json"))}
sample = {json.loads(l)["number"] for l in open("data/issues.jsonl")}
assert not set(NUMBERS) & sample
with open("data/practice_issues.jsonl", "w") as f:
    for n in NUMBERS:
        x = raw[n]
        body = redact(x["body"])
        f.write(json.dumps({"id": f"practice-{n}", "number": n, "url": x["url"],
                            "created_at": x["createdAt"], "title": redact(x["title"]),
                            "body": body[:MAX_BODY_CHARS], "truncated": len(body) > MAX_BODY_CHARS}) + "\n")
print(f"wrote {len(NUMBERS)} practice issues")
