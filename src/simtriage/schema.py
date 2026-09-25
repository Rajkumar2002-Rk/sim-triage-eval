"""Per-customer label spaces and consistency rules. Single source of truth.

Each customer (dataset) is a Taxonomy: its own categories, ordered priorities,
product areas and rules. Gates, mutations, the report and the response schema
all read from here, so the allowed values can't drift between them.
"""
from dataclasses import dataclass, field
from functools import cached_property
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

SUMMARY_MAX_CHARS = 160
FIELDS = ("category", "priority", "product_area", "needs_human")


@dataclass(frozen=True)
class Taxonomy:
    name: str
    categories: tuple
    priorities: tuple                      # ordered, lowest first
    areas: tuple
    rules: tuple                           # (id, description, violated(record) -> bool)
    category_confusable: dict              # category -> plausible wrong categories
    area_neighbors: dict                   # area -> plausible wrong areas
    # How a predicted category is compared with the answer key, when the key is
    # coarser than the model's label space (Sim reporters only choose bug/feature).
    category_grade_map: dict = field(default_factory=dict)
    # Real, plausible names for the invented-entity mutation (used only when
    # absent from the issue), so the injected detail is subtle, not absurd.
    entity_pool: tuple = ()

    def rank(self, priority):
        return self.priorities.index(priority)

    @cached_property
    def model(self):
        return create_model(
            f"Triage_{self.name}",
            __config__=ConfigDict(extra="forbid", strict=True),
            category=(Literal[self.categories], ...),
            priority=(Literal[self.priorities], ...),
            product_area=(Literal[self.areas], ...),
            needs_human=(bool, ...),
            summary=(str, Field(min_length=1, max_length=SUMMARY_MAX_CHARS)),
        )

    def usable(self, obj):
        """All four label fields present with allowed values (rules can be evaluated)."""
        return (isinstance(obj, dict)
                and obj.get("category") in self.categories
                and obj.get("priority") in self.priorities
                and obj.get("product_area") in self.areas
                and isinstance(obj.get("needs_human"), bool))

    def rule_violations(self, record):
        return [rid for rid, _, violated in self.rules if violated(record)]

    def grade_category(self, pred):
        """Map a predicted category into a coarse answer key's vocabulary."""
        return self.category_grade_map.get(pred, "other")


def key_field(field, gold):
    """Which answer-key field grades a prediction field. A coarse category key
    (Sim reporters' bug/feature template choice) is stored as category_coarse so
    it can't be confused with the fine-grained category of the same name."""
    if field == "category" and "category_coarse" in gold:
        return "category_coarse"
    return field if field in gold else None


def _at_least(tax_priorities, p, floor):
    return tax_priorities.index(p) >= tax_priorities.index(floor)


# ---------------------------------------------------------------- Sim
_SIM_P = ("low", "medium", "high", "urgent")
SIM = Taxonomy(
    name="sim",
    categories=("bug", "feature_request", "integration_request", "question",
                "docs", "security", "invalid"),
    priorities=_SIM_P,
    areas=("self_hosting", "dev_setup", "workflow_editor", "execution_engine",
           "agents_models", "copilot", "integrations", "mcp", "api_deployment",
           "auth_accounts", "logs_observability", "other"),
    rules=(
        ("R1", "needs_human implies priority is not low",
         lambda r: r["needs_human"] and r["priority"] == "low"),
        ("R2", "security implies needs_human and priority high or urgent",
         lambda r: r["category"] == "security"
         and (not r["needs_human"] or not _at_least(_SIM_P, r["priority"], "high"))),
        ("R3", "invalid implies priority low, not needs_human, product_area other",
         lambda r: r["category"] == "invalid"
         and (r["priority"] != "low" or r["needs_human"] or r["product_area"] != "other")),
        ("R4", "urgent implies needs_human",
         lambda r: r["priority"] == "urgent" and not r["needs_human"]),
        ("R5", "integration_request implies product_area integrations, mcp or agents_models",
         lambda r: r["category"] == "integration_request"
         and r["product_area"] not in ("integrations", "mcp", "agents_models")),
        ("R6", "docs implies priority low or medium",
         lambda r: r["category"] == "docs" and _at_least(_SIM_P, r["priority"], "high")),
        ("R7", "question implies priority is not urgent",
         lambda r: r["category"] == "question" and r["priority"] == "urgent"),
    ),
    category_confusable={
        "bug": ("question", "security"), "question": ("bug", "docs"),
        "security": ("bug",), "feature_request": ("integration_request",),
        "integration_request": ("feature_request",), "docs": ("question",),
        "invalid": ("question",),
    },
    area_neighbors={},   # filled below
    # Sim reporters pick the "Bug report" or "Feature request" template; that
    # choice is the answer key. Anything else counts as "other" (never matches).
    category_grade_map={"bug": "bug", "security": "bug",
                        "feature_request": "feature", "integration_request": "feature",
                        "question": "other", "docs": "other", "invalid": "other"},
    entity_pool=("Notion", "Airtable", "HubSpot", "Supabase", "Stripe", "Linear", "Jira",
                 "Zendesk", "Salesforce", "Pinecone", "Twilio", "Discord"),
)
for a, b in (("self_hosting", "dev_setup"), ("execution_engine", "workflow_editor"),
             ("integrations", "api_deployment"), ("agents_models", "integrations"),
             ("copilot", "agents_models"), ("mcp", "integrations"),
             ("auth_accounts", "self_hosting"), ("logs_observability", "execution_engine")):
    SIM.area_neighbors.setdefault(a, []).append(b)
    SIM.area_neighbors.setdefault(b, []).append(a)

# ---------------------------------------------------------------- Kubernetes
# Label vocabulary from kubernetes/kubernetes (kind/*, priority/*, sig/*).
# Priority definitions: kubernetes/community contributors/guide/issue-triage.md.
_K8S_P = ("backlog", "important-longterm", "important-soon", "critical-urgent")
K8S = Taxonomy(
    name="k8s",
    categories=("bug", "regression", "failing_test", "flake", "feature", "cleanup",
                "documentation", "support"),
    priorities=_K8S_P,
    areas=("api-machinery", "apps", "architecture", "auth", "autoscaling", "cli",
           "cloud-provider", "cluster-lifecycle", "contributor-experience", "docs", "etcd",
           "instrumentation", "k8s-infra", "multicluster", "network", "node", "release",
           "scalability", "scheduling", "security", "storage", "testing", "ui", "windows"),
    # Each rule was checked against the 229 triager-set priorities before any
    # model output existed (see PROTOCOL.md); none is broken by a real triager.
    rules=(
        ("K1", "critical-urgent implies needs_human",
         lambda r: r["priority"] == "critical-urgent" and not r["needs_human"]),
        ("K2", "needs_human implies priority is not backlog",
         lambda r: r["needs_human"] and r["priority"] == "backlog"),
        ("K3", "regression implies priority important-soon or critical-urgent",
         lambda r: r["category"] == "regression" and not _at_least(_K8S_P, r["priority"], "important-soon")),
        ("K4", "feature, cleanup or documentation implies priority is not critical-urgent",
         lambda r: r["category"] in ("feature", "cleanup", "documentation")
         and r["priority"] == "critical-urgent"),
    ),
    category_confusable={
        "bug": ("regression", "failing_test"), "regression": ("bug",),
        "failing_test": ("flake", "bug"), "flake": ("failing_test",),
        "feature": ("cleanup",), "cleanup": ("feature",),
        "documentation": ("cleanup",), "support": ("bug",),
    },
    area_neighbors={},
    entity_pool=("Calico", "Cilium", "Istio", "Helm", "Prometheus", "CoreDNS", "Flannel",
                 "Longhorn", "Karpenter", "Kyverno", "Envoy", "Rancher"),
)
for a, b in (("node", "windows"), ("node", "storage"), ("node", "scheduling"), ("node", "network"),
             ("node", "instrumentation"), ("api-machinery", "apps"), ("api-machinery", "cli"),
             ("apps", "scheduling"), ("testing", "release"), ("testing", "k8s-infra"),
             ("auth", "security"), ("scheduling", "autoscaling"), ("cluster-lifecycle", "cloud-provider"),
             ("network", "cloud-provider"), ("storage", "apps")):
    K8S.area_neighbors.setdefault(a, []).append(b)
    K8S.area_neighbors.setdefault(b, []).append(a)

REGISTRY = {"sim": SIM, "k8s": K8S}


def get(name):
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown dataset {name!r}; known: {sorted(REGISTRY)}") from None
