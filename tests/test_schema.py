import pytest
from pydantic import ValidationError

from simtriage import schema

GOOD = dict(category="bug", priority="high", product_area="self_hosting",
            needs_human=True, summary="Docker compose migrations fail on startup")


def test_valid_output_parses():
    assert schema.Triage(**GOOD).category == "bug"


@pytest.mark.parametrize("field,value", [
    ("category", "Bug"), ("priority", "critical"), ("product_area", "docker"),
    ("needs_human", "true"), ("summary", ""), ("summary", "x" * 161),
])
def test_bad_values_rejected(field, value):
    with pytest.raises(ValidationError):
        schema.Triage(**{**GOOD, field: value})


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        schema.Triage(**GOOD, confidence=0.9)


def test_missing_field_rejected():
    with pytest.raises(ValidationError):
        schema.Triage(**{k: v for k, v in GOOD.items() if k != "priority"})


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
def test_rules(record, expected):
    assert schema.rule_violations(record) == expected
