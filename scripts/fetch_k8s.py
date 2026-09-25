"""Snapshot kubernetes/kubernetes issues that carry a priority label, with the
comments and label events needed to prove WHO set each priority.

Output: data/k8s/raw/issues_<date>.json (one record per issue).
Re-running later gives different data; the committed snapshot is the source of truth.
"""
import datetime
import json
import subprocess
import sys

REPO = "kubernetes/kubernetes"
QUERY = (f"repo:{REPO} is:issue created:>=2025-08-01 "
         "label:priority/critical-urgent,priority/important-soon,priority/important-longterm,priority/backlog")


def gh(path, *args):
    out = subprocess.run(["gh", "api", *args, path], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def search_all():
    items, page = [], 1
    while True:
        res = gh("search/issues", "-X", "GET", "-f", f"q={QUERY}", "-f", "per_page=100", "-f", f"page={page}")
        items += res["items"]
        if len(res["items"]) < 100 or len(items) >= res["total_count"]:
            return items
        page += 1


def main():
    issues = search_all()
    print(f"{len(issues)} issues", file=sys.stderr)
    out = []
    for i, it in enumerate(issues):
        n = it["number"]
        comments = gh(f"repos/{REPO}/issues/{n}/comments?per_page=100")
        events = gh(f"repos/{REPO}/issues/{n}/events?per_page=100")
        out.append({
            "number": n, "url": it["html_url"], "title": it["title"], "body": it.get("body") or "",
            "created_at": it["created_at"], "state": it["state"],
            "author": it["user"]["login"], "author_association": it.get("author_association"),
            "labels": sorted(l["name"] for l in it["labels"]),
            "comments": [{"user": c["user"]["login"], "assoc": c.get("author_association"),
                          "created_at": c["created_at"], "body": c.get("body") or ""} for c in comments],
            "label_events": [{"event": e["event"], "label": e["label"]["name"],
                              "actor": (e.get("actor") or {}).get("login"), "created_at": e["created_at"]}
                             for e in events if e["event"] in ("labeled", "unlabeled")],
        })
        if i % 50 == 0:
            print(f"  {i}/{len(issues)}", file=sys.stderr)
    path = f"data/k8s/raw/issues_{datetime.date.today()}.json"
    json.dump(out, open(path, "w"))
    print(path)


if __name__ == "__main__":
    main()
