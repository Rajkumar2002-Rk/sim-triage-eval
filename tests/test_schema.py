import pytest
from pydantic import ValidationError

from simtriage import schema
from simtriage.schema import SIM

GOOD = dict(category="bug", priority="high", product_area="self_hosting",
            needs_human=True, summary="Docker compose migrations fail on startup")


def test_valid_output_parses():
    assert SIM.model(**GOOD).category == "bug"


@pytest.mark.parametrize("field,value", [
    ("category", "Bug"), ("priority", "critical"), ("product_area", "docker"),
    ("needs_human", "true"), ("summary", ""), ("summary", "x" * 161),
])
def test_bad_values_rejected(field, value):
    with pytest.raises(ValidationError):
        SIM.model(**{**GOOD, field: value})


def test_extra_and_missing_fields_rejected():
    with pytest.raises(ValidationError):
        SIM.model(**GOOD, confidence=0.9)
    with pytest.raises(ValidationError):
        SIM.model(**{k: v for k, v in GOOD.items() if k != "priority"})


@pytest.mark.parametrize("record,expected", [
    (dict(category="bug", priority="low", product_area="other", needs_human=True), ["R1"]),
    (dict(category="security", priority="medium", product_area="other", needs_human=True), ["R2"]),
    (dict(category="invalid", priority="low", product_area="other", needs_human=False), []),
    (dict(category="invalid", priority="low", product_area="copilot", needs_human=False), ["R3"]),
    (dict(category="bug", priority="urgent", product_area="other", needs_human=False), ["R4"]),
    (dict(category="integration_request", priority="low", product_area="copilot", needs_human=False), ["R5"]),
    (dict(category="docs", priority="high", product_area="other", needs_human=True), ["R6"]),
    (dict(category="question", priority="urgent", product_area="other", needs_human=True), ["R7"]),
])
def test_sim_rules(record, expected):
    assert SIM.rule_violations(record) == expected


def test_every_taxonomy_is_internally_consistent():
    for tax in schema.REGISTRY.values():
        assert len(set(tax.categories)) == len(tax.categories)
        for c, alts in tax.category_confusable.items():
            assert c in tax.categories and all(a in tax.categories and a != c for a in alts)
        for a, ns in tax.area_neighbors.items():
            assert a in tax.areas and all(n in tax.areas for n in ns)
        for pred in tax.category_grade_map:
            assert pred in tax.categories


def test_unknown_dataset():
    with pytest.raises(KeyError):
        schema.get("nope")
