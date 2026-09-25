"""Label space and consistency rules. Single source of truth.

The labeling tool, the deterministic gates and the mutation engine all import
from here, so the allowed values can't drift between them.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CATEGORIES = ("bug", "feature_request", "integration_request", "question",
              "docs", "security", "invalid")
PRIORITIES = ("low", "medium", "high", "urgent")  # ordered
PRODUCT_AREAS = ("self_hosting", "dev_setup", "workflow_editor", "execution_engine",
                 "agents_models", "copilot", "integrations", "mcp", "api_deployment",
                 "auth_accounts", "logs_observability", "other")
SUMMARY_MAX_CHARS = 160

Category = Literal[CATEGORIES]
Priority = Literal[PRIORITIES]
ProductArea = Literal[PRODUCT_AREAS]


class Triage(BaseModel):
    """What the workflow must return, and what a label records (minus summary)."""
    model_config = ConfigDict(extra="forbid", strict=True)

    category: Category
    priority: Priority
    product_area: ProductArea
    needs_human: bool
    summary: str = Field(min_length=1, max_length=SUMMARY_MAX_CHARS)


def priority_rank(p: str) -> int:
    return PRIORITIES.index(p)


# Each rule: (id, description, predicate(record) -> True if the record VIOLATES it).
# `record` is any mapping with category/priority/product_area/needs_human.
RULES = (
    ("R1", "needs_human implies priority is not low",
     lambda r: r["needs_human"] and r["priority"] == "low"),
    ("R2", "security implies needs_human and priority high or urgent",
     lambda r: r["category"] == "security"
     and (not r["needs_human"] or priority_rank(r["priority"]) < priority_rank("high"))),
    ("R3", "invalid implies priority low, not needs_human, product_area other",
     lambda r: r["category"] == "invalid"
     and (r["priority"] != "low" or r["needs_human"] or r["product_area"] != "other")),
    ("R4", "urgent implies needs_human",
     lambda r: r["priority"] == "urgent" and not r["needs_human"]),
    ("R5", "integration_request implies product_area integrations, mcp or agents_models",
     lambda r: r["category"] == "integration_request"
     and r["product_area"] not in ("integrations", "mcp", "agents_models")),
    ("R6", "docs implies priority low or medium",
     lambda r: r["category"] == "docs" and priority_rank(r["priority"]) > priority_rank("medium")),
    ("R7", "question implies priority is not urgent",
     lambda r: r["category"] == "question" and r["priority"] == "urgent"),
)


def rule_violations(record) -> list[str]:
    return [rid for rid, _, violated in RULES if violated(record)]
