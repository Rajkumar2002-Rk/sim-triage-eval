"""Terminal labeling tool. Labels are the only independent ground truth.

- Shows one issue at a time in a fixed shuffled order; saves after every issue.
- Only accepts values from schema.py; flags consistency-rule conflicts at once.
- Never shows model output or maintainer labels.
- `recheck` mode relabels a seeded random subset blind, into a separate file.
"""
import json
import os
import random
import shutil
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from . import schema

ORDER_SEED = 7


def load_issues(path):
    return [json.loads(l) for l in open(path)]


def load_labels(path):
    p = Path(path)
    return {r["id"]: r for r in map(json.loads, p.open())} if p.exists() else {}


def save_labels(path, labels):
    tmp = Path(str(path) + ".tmp")
    with tmp.open("w") as f:
        for k in sorted(labels, key=lambda k: int(k.split("-")[1])):
            f.write(json.dumps(labels[k]) + "\n")
    os.replace(tmp, path)


def show(issue, pos, total, done):
    width = min(shutil.get_terminal_size().columns, 110)
    print("\033[2J\033[H", end="")
    print(f"[{pos}/{total}]  labeled so far: {done}   {issue['id']}   {issue['url']}")
    print("=" * width)
    print(textwrap.fill(issue["title"], width))
    print("-" * width)
    print(issue["body"])
    print("=" * width)


class Back(Exception):
    pass


class Quit(Exception):
    pass


def ask_choice(name, options):
    menu = "  ".join(f"{i}={o}" for i, o in enumerate(options, 1))
    while True:
        raw = input(f"{name}: {menu}\n> ").strip().lower()
        if raw == "q":
            raise Quit
        if raw == "b":
            raise Back
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        print("  not a valid choice (b = back, q = save and quit)")


def ask_bool(name):
    while True:
        raw = input(f"{name}? y/n\n> ").strip().lower()
        if raw in ("q",):
            raise Quit
        if raw == "b":
            raise Back
        if raw in ("y", "n"):
            return raw == "y"


def label_one(issue):
    while True:
        rec = {
            "category": ask_choice("category", schema.CATEGORIES),
            "priority": ask_choice("priority", schema.PRIORITIES),
            "product_area": ask_choice("product_area", schema.PRODUCT_AREAS),
            "needs_human": ask_bool("needs_human"),
        }
        broken = schema.rule_violations(rec)
        if broken:
            desc = {rid: d for rid, d, _ in schema.RULES}
            for rid in broken:
                print(f"  CONFLICT {rid}: {desc[rid]}")
            if input("  [r]elabel or [k]eep (keeping means the rule may be wrong)?\n> ").strip().lower() != "k":
                continue
        notes = input("notes (optional, enter to skip)\n> ").strip()
        rec.update(id=issue["id"], notes=notes, rule_conflicts=broken,
                   labeled_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return rec


def run(issues_path, labels_path, only_ids=None):
    issues = load_issues(issues_path)
    random.Random(ORDER_SEED).shuffle(issues)
    if only_ids is not None:
        issues = [i for i in issues if i["id"] in only_ids]
    labels = load_labels(labels_path)
    todo = [i for i in issues if i["id"] not in labels]
    idx = 0
    try:
        while idx < len(todo):
            issue = todo[idx]
            show(issue, len(labels) + 1, len(issues), len(labels))
            try:
                labels[issue["id"]] = label_one(issue)
                save_labels(labels_path, labels)
                idx += 1
            except Back:
                if idx > 0:
                    idx -= 1
                    labels.pop(todo[idx]["id"], None)
                    save_labels(labels_path, labels)
    except (Quit, KeyboardInterrupt, EOFError):
        pass
    print(f"\nsaved {len(labels)}/{len(issues)} labels to {labels_path}")
    return 0 if len(labels) == len(issues) else 1


def recheck_ids(labels_path, n, seed):
    ids = sorted(load_labels(labels_path))
    return set(random.Random(seed).sample(ids, n))
