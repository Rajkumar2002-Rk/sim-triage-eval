import random

import pytest

from simtriage import gates, mutations, schema

ISSUE = {"id": "sim-1", "title": "[BUG] Docker migrations fail",
         "body": "On Ubuntu 22.04 the Postgres migration fails with drizzle-orm 0.30.1 and exits 1."}
OTHER = {"id": "sim-2", "title": "Slack threads", "body": "Please support posting to Slack threads."}
OUT = {"category": "bug", "priority": "high", "product_area": "self_hosting", "needs_human": True,
       "summary": "Postgres migration fails on Ubuntu 22.04 with drizzle-orm 0.30.1."}
OUT2 = {"category": "bug", "priority": "medium", "product_area": "integrations", "needs_human": False,
        "summary": "Slack tool cannot post to threads."}
SEEDS = [{"issue_id": "sim-1", "output": OUT}, {"issue_id": "sim-2", "output": OUT2}]
ISSUES = {"sim-1": ISSUE, "sim-2": OTHER}


def run(op, out=OUT, issue=ISSUE, seed=0):
    return getattr(mutations, op)(dict(out), issue, random.Random(seed), SEEDS)


def changed_fields(a, b):
    return {k for k in set(a) | set(b) if a.get(k) != b.get(k)}


@pytest.mark.parametrize("op,field", [
    ("category_random", "category"), ("category_plausible", "category"),
    ("product_area_plausible", "product_area"), ("priority_off_by_one", "priority"),
    ("needs_human_flip", "needs_human"), ("summary_invented_number", "summary"),
    ("summary_invented_entity", "summary"), ("summary_swapped", "summary"),
    ("summary_negated", "summary"), ("enum_case", "category"),
])
def test_operator_changes_exactly_one_field(op, field):
    for seed in range(20):
        m = run(op, seed=seed)
        assert changed_fields(OUT, m) == {field}, (op, seed, m)


def test_category_plausible_stays_in_confusable_set():
    for seed in range(20):
        assert run("category_plausible", seed=seed)["category"] in ("question", "security")


def test_priority_off_by_one_is_one_level_and_in_range():
    for p in schema.PRIORITIES:
        for seed in range(10):
            m = run("priority_off_by_one", out={**OUT, "priority": p}, seed=seed)
            assert abs(schema.PRIORITIES.index(m["priority"]) - schema.PRIORITIES.index(p)) == 1


def test_invented_number_is_new_and_caught_by_number_gate():
    for seed in range(20):
        m = run("summary_invented_number", seed=seed)
        assert len(m["summary"]) <= schema.SUMMARY_MAX_CHARS
        assert gates.label_free(m, ISSUE).by_gate()["summary_numbers"].status == gates.FAIL


def test_invented_number_respects_length_limit_on_long_summary():
    long = {**OUT, "summary": ("Postgres migration fails on Ubuntu " * 10)[:158] + "."}
    m = run("summary_invented_number", out=long)
    assert len(m["summary"]) <= schema.SUMMARY_MAX_CHARS
    assert gates.label_free(m, ISSUE).by_gate()["summary_length"].status == gates.PASS


def test_invented_entity_replaces_a_sourced_name_with_an_unsourced_one():
    m = run("summary_invented_entity")
    new_words = set(m["summary"].split()) - set(OUT["summary"].split())
    assert len(new_words) == 1
    assert next(iter(new_words)).strip(".").lower() not in (ISSUE["title"] + ISSUE["body"]).lower()


def test_invented_entity_not_applicable_without_named_things():
    assert run("summary_invented_entity", out={**OUT, "summary": "migration fails on startup."}) is None


def test_negation_flips_verb():
    assert run("summary_negated")["summary"].startswith("Postgres migration works")
    assert run("summary_negated", out={**OUT, "summary": "all good here."}) is None


def test_swapped_summary_comes_from_another_issue():
    assert run("summary_swapped")["summary"] == OUT2["summary"]


def test_structural_mutants_fail_schema():
    for op in ("field_missing", "field_extra", "enum_case"):
        m = run(op)
        assert gates.label_free(m, ISSUE).by_gate()["schema"].status == gates.FAIL, op


def test_generate_is_deterministic_and_complete():
    a = mutations.generate(SEEDS, ISSUES)
    b = mutations.generate(SEEDS, ISSUES)
    assert a == b
    assert len(a) == len(SEEDS) * len(mutations.OPERATORS)
    assert {m["operator"] for m in a} == set(mutations.OPERATORS)
