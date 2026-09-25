"""Mutation operators (PROTOCOL.md section 5). Deterministic given the seed.

Each operator takes a correct output and returns a mutant that is wrong by
construction, or None when it doesn't apply to that seed (for example, no
negatable verb in the summary). Non-applicable pairs are recorded, not hidden.
"""
import random
import re

from . import gates, schema

MUTATION_SEED = 11

NEGATIONS = (("fails", "works"), ("failing", "working"), ("broken", "working"),
             ("crashes", "runs"), ("cannot", "can"), ("can't", "can"),
             ("doesn't", "does"), ("does not", "does"), ("not working", "working"),
             ("errors", "succeeds"), ("missing", "present"), ("works", "fails"),
             ("supports", "lacks"))

OPERATORS = ("category_random", "category_plausible", "product_area_plausible",
             "priority_off_by_one", "needs_human_flip", "summary_invented_number",
             "summary_invented_entity", "summary_swapped", "summary_negated",
             "field_missing", "field_extra", "enum_case")


def _fit(summary):
    """Keep a mutated summary within the length limit so only the intended defect is present."""
    if len(summary) <= schema.SUMMARY_MAX_CHARS:
        return summary
    return summary[:schema.SUMMARY_MAX_CHARS - 1].rsplit(" ", 1)[0] + "."


def _source(issue):
    return f"{issue['title']}\n{issue['body']}"


def category_random(out, issue, rng, pool, tax):
    return {**out, "category": rng.choice([c for c in tax.categories if c != out["category"]])}


def category_plausible(out, issue, rng, pool, tax):
    options = tax.category_confusable.get(out["category"])
    return {**out, "category": rng.choice(options)} if options else None


def product_area_plausible(out, issue, rng, pool, tax):
    options = tax.area_neighbors.get(out["product_area"])
    return {**out, "product_area": rng.choice(options)} if options else None


def priority_off_by_one(out, issue, rng, pool, tax):
    i = tax.rank(out["priority"])
    steps = [s for s in (-1, 1) if 0 <= i + s < len(tax.priorities)]
    return {**out, "priority": tax.priorities[i + rng.choice(steps)]}


def needs_human_flip(out, issue, rng, pool, tax):
    return {**out, "needs_human": not out["needs_human"]}


def summary_invented_number(out, issue, rng, pool, tax):
    src = _source(issue)
    known = {gates._norm_num(t) for t in gates.NUMBER.findall(src)}
    while True:
        version = f"{rng.randint(0, 3)}.{rng.randint(1, 60)}.{rng.randint(0, 20)}"
        if version not in known and version not in src:
            break
    base = out["summary"].rstrip(". ")
    suffix = f" since v{version}."
    base = base[:schema.SUMMARY_MAX_CHARS - len(suffix)].rsplit(" ", 1)[0] if len(base) + len(suffix) > schema.SUMMARY_MAX_CHARS else base
    return {**out, "summary": base + suffix}


def summary_invented_entity(out, issue, rng, pool, tax):
    src = _source(issue).lower()
    s = out["summary"]
    # Replace a capitalized word that the issue does mention: a named thing, correctly sourced.
    words = [m for m in re.finditer(r"\b[A-Z][A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)*\b", s)
             if m.group(0).lower() in src and m.group(0) not in gates.ENTITY_STOPLIST]
    replacements = [e for e in tax.entity_pool if e.lower() not in src and e not in s]
    if not words or not replacements:
        return None
    m = rng.choice(words)
    return {**out, "summary": _fit(s[:m.start()] + rng.choice(replacements) + s[m.end():])}


def summary_swapped(out, issue, rng, pool, tax):
    others = [p for p in pool if p["issue_id"] != issue["id"]]
    same = [p for p in others if p["output"]["category"] == out["category"]]
    candidates = same or others
    if not candidates:
        return None
    return {**out, "summary": rng.choice(candidates)["output"]["summary"]}


def summary_negated(out, issue, rng, pool, tax):
    s = out["summary"]
    for a, b in NEGATIONS:
        m = re.search(rf"\b{re.escape(a)}\b", s, re.IGNORECASE)
        if m:
            rep = b if s[m.start()].islower() else b.capitalize()
            return {**out, "summary": _fit(s[:m.start()] + rep + s[m.end():])}
    return None


def field_missing(out, issue, rng, pool, tax):
    drop = rng.choice(sorted(tax.model.model_fields))
    return {k: v for k, v in out.items() if k != drop}


def field_extra(out, issue, rng, pool, tax):
    return {**out, "confidence": 0.9}


def enum_case(out, issue, rng, pool, tax):
    return {**out, "category": out["category"].capitalize()}


def generate(seeds, issues_by_id, tax, seed=MUTATION_SEED):
    """seeds: [{"issue_id", "output"}] of correct outputs. Returns mutant records."""
    rng = random.Random(seed)
    mutants = []
    for s in sorted(seeds, key=lambda s: s["issue_id"]):
        issue = issues_by_id[s["issue_id"]]
        for op in OPERATORS:
            mutated = globals()[op](dict(s["output"]), issue, rng, seeds, tax)
            mutants.append({
                "mutant_id": f"{s['issue_id']}:{op}",
                "issue_id": s["issue_id"],
                "operator": op,
                "applicable": mutated is not None,
                "output": mutated,
            })
    return mutants
