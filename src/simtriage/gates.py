"""Deterministic gates. No model calls.

Label-free gates run on any output and are usable in production. Label-dependent
gates compare against hand labels and are regression-suite only. Every gate
returns pass, fail or skip; a gate that can't run on malformed input skips
rather than passing silently.
"""
import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from . import schema

PASS, FAIL, SKIP = "pass", "fail", "skip"

LABEL_FREE = ("schema", "consistency", "summary_length", "summary_numbers",
              "summary_urls", "summary_handles", "summary_entities")
LABEL_DEPENDENT = ("category_match", "priority_match", "product_area_match",
                   "needs_human_match")
LABEL_FIELDS = schema.FIELDS

# Capitalized words that may appear in a summary without appearing in the
# issue. Fixed before any model output was seen (see PROTOCOL.md section 3).
ENTITY_STOPLIST = frozenset({
    "Sim", "I", "API", "APIs", "UI", "URL", "URLs", "LLM", "LLMs", "SDK", "JSON",
    "HTTP", "HTTPS", "CLI", "ID", "IDs", "UUID", "OK", "User", "Users",
})

NUMBER = re.compile(r"(?<![\w.])v?\d+(?:[.,:]\d+)*(?![\w])", re.IGNORECASE)
URL = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)
DOMAIN = re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.(?:com|ai|io|dev|org|net|app|sh|co|so)\b",
                    re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
HANDLE = re.compile(r"(?<![\w@])@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
ISSUE_REF = re.compile(r"#\d+")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_.'][A-Za-z0-9]+)*")


@dataclass
class GateResult:
    gate: str
    status: str
    detail: str = ""


@dataclass
class Verdict:
    results: list = field(default_factory=list)

    def by_gate(self):
        return {r.gate: r for r in self.results}

    def failed(self, gates=None):
        return [r.gate for r in self.results
                if r.status == FAIL and (gates is None or r.gate in gates)]

    def passed_all(self, gates=None):
        return not self.failed(gates)


def parse(raw):
    """Return (dict or None, error). Accepts a dict or a JSON string."""
    if isinstance(raw, dict):
        return raw, ""
    if not isinstance(raw, str):
        return None, f"output is {type(raw).__name__}, not JSON object or string"
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e.msg}"
    if not isinstance(obj, dict):
        return None, f"JSON is {type(obj).__name__}, not an object"
    return obj, ""


def _norm_num(tok):
    return tok.lower().lstrip("v").replace(",", "")


def _missing(found, haystack):
    """Tokens from `found` that don't occur (case-insensitively) in `haystack`."""
    hay = haystack.lower()
    return sorted({t for t in found if t.lower() not in hay})


def gate_schema(obj, err, tax):
    if obj is None:
        return GateResult("schema", FAIL, err)
    try:
        tax.model.model_validate(obj)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, x['loc'])) or '(root)'}: {x['type']}"
                             for x in e.errors())
        return GateResult("schema", FAIL, problems)
    return GateResult("schema", PASS)


def gate_consistency(obj, tax):
    if not tax.usable(obj):
        return GateResult("consistency", SKIP, "fields missing or invalid")
    broken = tax.rule_violations(obj)
    return GateResult("consistency", FAIL if broken else PASS, ",".join(broken))


def _summary(obj):
    s = obj.get("summary") if obj is not None else None
    return s if isinstance(s, str) else None


def gate_summary_length(obj):
    s = _summary(obj)
    if s is None:
        return GateResult("summary_length", SKIP, "no summary string")
    if not s.strip():
        return GateResult("summary_length", FAIL, "empty")
    if "\n" in s or "\r" in s:
        return GateResult("summary_length", FAIL, "multi-line")
    if len(s) > schema.SUMMARY_MAX_CHARS:
        return GateResult("summary_length", FAIL, f"{len(s)} chars")
    return GateResult("summary_length", PASS)


def gate_summary_numbers(obj, source):
    s = _summary(obj)
    if s is None:
        return GateResult("summary_numbers", SKIP, "no summary string")
    source_nums = {_norm_num(t) for t in NUMBER.findall(source)}
    bad = sorted({t for t in NUMBER.findall(s)
                  if _norm_num(t) not in source_nums and t.lower() not in source.lower()})
    return GateResult("summary_numbers", FAIL if bad else PASS, ",".join(bad))


def gate_summary_urls(obj, source):
    s = _summary(obj)
    if s is None:
        return GateResult("summary_urls", SKIP, "no summary string")
    found = set(URL.findall(s)) | set(DOMAIN.findall(s))
    bad = _missing(found, source)
    return GateResult("summary_urls", FAIL if bad else PASS, ",".join(bad))


def gate_summary_handles(obj, source):
    s = _summary(obj)
    if s is None:
        return GateResult("summary_handles", SKIP, "no summary string")
    emails = set(EMAIL.findall(s))
    rest = EMAIL.sub(" ", s)
    bad = _missing(emails | set(HANDLE.findall(rest)), source)
    # "#1373" is supported if 1373 appears in the issue at all (often inside a URL).
    source_nums = {_norm_num(t) for t in NUMBER.findall(source)}
    bad += sorted({r for r in ISSUE_REF.findall(rest) if r[1:] not in source_nums})
    return GateResult("summary_handles", FAIL if bad else PASS, ",".join(bad))


def _non_initial_capitalized(text):
    out = []
    sentence_start = True
    for m in re.finditer(r"\S+", text):
        raw = m.group(0)
        w = WORD.search(raw)
        if w:
            word = w.group(0)
            if not sentence_start and word[0].isupper():
                out.append(word)
            sentence_start = False
        if raw.endswith((".", "!", "?", ":")):
            sentence_start = True
    return out


def _squash(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def entity_supported(token, source, match="v2"):
    """Is a capitalized summary word supported by the issue text?
    v1 (pre-registered): the exact token appears, case-insensitively.
    v2 (after reviewing 11 real false alarms, 2026-09-26): also accept the token
    with punctuation removed ("Next.js" ~ "nextjs", "UNAUTHORIZED_X" ~ "UNAUTHORIZED:_X"),
    a possessive stripped ("Manager's"), or every part of a hyphenated or
    underscored compound present ("Stripe-only", "ContainerOS-specific")."""
    low = source.lower()
    if token.lower() in low:
        return True
    if match == "v1":
        return False
    base = re.sub(r"['’]s$", "", token)
    if base.lower() in low:
        return True
    squashed = _squash(base)
    if len(squashed) >= 4 and squashed in _squash(source):
        return True
    parts = [p for p in re.split(r"[-_.:'’]", base) if p]
    return len(parts) > 1 and all(p.lower() in low for p in parts)


def gate_summary_entities(obj, source, match="v2"):
    s = _summary(obj)
    if s is None:
        return GateResult("summary_entities", SKIP, "no summary string")
    candidates = {w for w in _non_initial_capitalized(s) if w not in ENTITY_STOPLIST}
    bad = sorted(w for w in candidates if not entity_supported(w, source, match))
    return GateResult("summary_entities", FAIL if bad else PASS, ",".join(bad))


def label_free(raw, issue, tax):
    obj, err = parse(raw)
    source = f"{issue['title']}\n{issue['body']}"
    return Verdict([
        gate_schema(obj, err, tax),
        gate_consistency(obj, tax),
        gate_summary_length(obj),
        gate_summary_numbers(obj, source),
        gate_summary_urls(obj, source),
        gate_summary_handles(obj, source),
        gate_summary_entities(obj, source),
    ])


def matches(field, pred, gold, tax):
    """Does a predicted value agree with the answer key? `field` is the key's
    field. Gold may be one value or a list of acceptable values (e.g. a
    Kubernetes issue owned by two SIGs)."""
    if field == "category_coarse":
        pred = tax.grade_category(pred)
    return pred in gold if isinstance(gold, list) else pred == gold


def label_dependent(raw, gold, tax):
    """Only fields present in the answer key are graded."""
    obj, _ = parse(raw)
    results = []
    for f in LABEL_FIELDS:
        kf = schema.key_field(f, gold)
        if kf is None:
            continue
        gate = f"{f}_match"
        if obj is None or f not in obj:
            results.append(GateResult(gate, SKIP, "field missing"))
        elif matches(kf, obj[f], gold[kf], tax):
            results.append(GateResult(gate, PASS))
        else:
            results.append(GateResult(gate, FAIL, f"got {obj[f]!r}, key {kf}={gold[kf]!r}"))
    return Verdict(results)


def check(raw, issue, tax, gold=None):
    v = label_free(raw, issue, tax)
    if gold is not None:
        v.results += label_dependent(raw, gold, tax).results
    return v
