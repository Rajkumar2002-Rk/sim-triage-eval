"""Build the labeled-set candidates from simstudioai/sim GitHub issues.

Input: raw `gh issue list --json number,title,body,labels,createdAt,author,url,state`
dump. Output (all deterministic, seed below):
  data/issues.jsonl          100 issues: id, number, url, created_at, title, body
  data/split.json            60 dev / 40 held-out test ids
  data/maintainer_labels_HIDDEN.jsonl   Sim's own labels; do not open until labeling is done

Selection rules (decided before seeing any model output):
  - created on or after 2025-08-01 (after the triage model's training data)
  - author is not a bot and not core team (>= 50 commits to the repo)
  - body has at least 150 characters
  - body is truncated to MAX_BODY_CHARS; the truncated text is what the workflow
    sees and what the summary gates check against
  - personal email addresses are replaced with "[email]". Placeholder and company
    domains, and npm-style `pkg@1.2.3` versions, are kept. (In the 2026-09-25
    draw the only matches were example.com, sim.ai and `@1.1.2` versions.)
  - stratified by maintainer label (bug / feature / unlabeled) in proportion to the pool
"""
import json
import random
import re
import sys

SEED = 20260925
N_TOTAL, N_DEV = 100, 60
MAX_BODY_CHARS = 8000
CUTOFF = "2025-08-01"
CORE_TEAM = {"waleedlatif1", "icecrasher321", "emir-karabeg", "TheodoreSpeaks",
             "Sg312", "aadamgough", "BillLeoutsakosvl346", "j15z"}


EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
KEEP_DOMAINS = {"example.com", "example.org", "sim.ai"}


def redact(text):
    def sub(m):
        domain = m.group(1).lower()
        if domain in KEEP_DOMAINS or domain[0].isdigit():
            return m.group(0)
        return "[email]"
    return EMAIL.sub(sub, text)


def stratum(issue):
    names = {l["name"] for l in issue["labels"]}
    return "bug" if "bug" in names else "feature" if "feature" in names else "unlabeled"


def main(raw_path):
    raw = json.load(open(raw_path))
    pool = [x for x in raw
            if x["createdAt"] >= CUTOFF
            and not x["author"].get("is_bot")
            and x["author"]["login"] not in CORE_TEAM
            and len(x["body"] or "") >= 150]
    pool.sort(key=lambda x: x["number"])
    rng = random.Random(SEED)

    by = {}
    for x in pool:
        by.setdefault(stratum(x), []).append(x)
    quotas = {k: round(N_TOTAL * len(v) / len(pool)) for k, v in by.items()}
    quotas[max(quotas, key=quotas.get)] += N_TOTAL - sum(quotas.values())
    chosen = [x for k, v in sorted(by.items()) for x in rng.sample(v, quotas[k])]
    rng.shuffle(chosen)

    # Stratified dev/test split.
    dev, test = [], []
    for k in sorted(by):
        ids = [x["number"] for x in chosen if stratum(x) == k]
        cut = round(len(ids) * N_DEV / N_TOTAL)
        dev += ids[:cut]
        test += ids[cut:]

    with open("data/issues.jsonl", "w") as f:
        for x in sorted(chosen, key=lambda x: x["number"]):
            body = redact(x["body"])
            truncated = len(body) > MAX_BODY_CHARS
            if truncated:
                body = body[:MAX_BODY_CHARS] + "\n[truncated]"
            f.write(json.dumps({"id": f"sim-{x['number']}", "number": x["number"],
                                "url": x["url"], "created_at": x["createdAt"],
                                "title": redact(x["title"]), "body": body,
                                "truncated": truncated}) + "\n")
    json.dump({"seed": SEED, "dev": sorted(f"sim-{n}" for n in dev),
               "test": sorted(f"sim-{n}" for n in test)},
              open("data/split.json", "w"), indent=1)
    with open("data/maintainer_labels_HIDDEN.jsonl", "w") as f:
        for x in sorted(chosen, key=lambda x: x["number"]):
            f.write(json.dumps({"id": f"sim-{x['number']}", "state": x["state"],
                                "labels": sorted(l["name"] for l in x["labels"])}) + "\n")

    print(f"pool={len(pool)} strata={ {k: len(v) for k, v in by.items()} } quotas={quotas}")
    print(f"chosen={len(chosen)} dev={len(dev)} test={len(test)} "
          f"truncated={sum(len(x['body']) > MAX_BODY_CHARS for x in chosen)}")


if __name__ == "__main__":
    main(sys.argv[1])
