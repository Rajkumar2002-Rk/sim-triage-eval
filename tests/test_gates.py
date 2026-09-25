import json

import pytest

from simtriage import gates
from simtriage.gates import FAIL, PASS, SKIP

ISSUE = {
    "title": "[BUG] Docker Prod: Migration fails with drizzle-orm 0.30.1",
    "body": ("Running docker compose -f docker-compose.prod.yml up on Ubuntu 22.04. "
             "The migrations container exits with code 1. See https://github.com/simstudioai/sim/issues/1373 "
             "and ping @waleed. Postgres runs on port 5432."),
}
GOOD = {"category": "bug", "priority": "high", "product_area": "self_hosting",
        "needs_human": True,
        "summary": "Docker prod migrations container exits with code 1 on Ubuntu 22.04 due to drizzle-orm 0.30.1."}
LABEL = {"category": "bug", "priority": "high", "product_area": "self_hosting", "needs_human": True}


def status(raw, gate, issue=ISSUE):
    return gates.label_free(raw, issue).by_gate()[gate].status


def test_good_output_passes_every_gate():
    v = gates.check(GOOD, ISSUE, LABEL)
    assert v.failed() == [], [(r.gate, r.detail) for r in v.results]
    assert all(r.status == PASS for r in v.results)


def test_json_string_input_is_parsed():
    assert gates.label_free(json.dumps(GOOD), ISSUE).passed_all()


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", 42, None])
def test_unparseable_fails_schema_and_skips_the_rest(raw):
    v = gates.label_free(raw, ISSUE).by_gate()
    assert v["schema"].status == FAIL
    assert v["consistency"].status == SKIP
    assert v["summary_numbers"].status == SKIP


def test_schema_failure_still_runs_consistency_when_fields_usable():
    raw = {**GOOD, "confidence": 0.9}
    v = gates.label_free(raw, ISSUE).by_gate()
    assert v["schema"].status == FAIL and "confidence" in v["schema"].detail
    assert v["consistency"].status == PASS


def test_consistency_violation():
    assert status({**GOOD, "priority": "low"}, "consistency") == FAIL  # R1


@pytest.mark.parametrize("summary,expected", [
    ("", FAIL), ("two\nlines", FAIL), ("x" * 161, FAIL), ("x" * 160, PASS),
])
def test_summary_length(summary, expected):
    assert status({**GOOD, "summary": summary}, "summary_length") == expected


@pytest.mark.parametrize("summary,expected", [
    ("Migration fails with drizzle-orm 0.30.1", PASS),
    ("Migration fails with drizzle-orm v0.30.1", PASS),   # v-prefix normalized
    ("Postgres on port 5432 conflicts", PASS),
    ("Migration fails with drizzle-orm 0.31.0", FAIL),    # invented version
    ("Order 48213 failed", FAIL),                         # invented number
    ("Migration exits with code 1", PASS),
])
def test_summary_numbers(summary, expected):
    assert status({**GOOD, "summary": summary}, "summary_numbers") == expected


@pytest.mark.parametrize("summary,expected", [
    ("See github.com issue for details", PASS),
    ("Reported at https://github.com/simstudioai/sim/issues/1373", PASS),
    ("Workaround posted on stackoverflow.com", FAIL),
    ("Docs at https://docs.sim.ai/self-hosting are wrong", FAIL),
])
def test_summary_urls(summary, expected):
    assert status({**GOOD, "summary": summary}, "summary_urls") == expected


@pytest.mark.parametrize("summary,expected", [
    ("Reporter pinged @waleed about migrations", PASS),
    ("Reporter pinged @emir about migrations", FAIL),
    ("Contact [email] for details", PASS),
    ("Contact admin@acme.io for details", FAIL),
    ("Duplicate of #1373", PASS),     # appears inside the URL in the body
    ("Duplicate of #999", FAIL),
])
def test_summary_handles(summary, expected):
    assert status({**GOOD, "summary": summary}, "summary_handles") == expected


@pytest.mark.parametrize("summary,expected", [
    ("Docker prod migrations fail on Ubuntu", PASS),
    ("Migrations fail on Postgres with drizzle-orm", PASS),
    ("Migrations fail on Kubernetes", FAIL),              # entity not in issue
    ("Kubernetes migrations fail", PASS),                 # sentence-initial is exempt
    ("Migrations fail. Kubernetes is unaffected", PASS),  # after a period is exempt
    ("The API returns an error in the UI", PASS),         # stoplist
])
def test_summary_entities(summary, expected):
    assert status({**GOOD, "summary": summary}, "summary_entities") == expected


def test_label_dependent_gates():
    v = gates.check({**GOOD, "category": "question", "priority": "medium"}, ISSUE, LABEL)
    assert set(v.failed(gates.LABEL_DEPENDENT)) == {"category_match", "priority_match"}


def test_missing_field_skips_its_label_gate_but_fails_schema():
    raw = {k: v for k, v in GOOD.items() if k != "needs_human"}
    v = gates.check(raw, ISSUE, LABEL).by_gate()
    assert v["needs_human_match"].status == SKIP
    assert v["schema"].status == FAIL
