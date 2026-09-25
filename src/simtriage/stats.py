"""Small, dependency-free statistics used by the report."""
import math
from collections import Counter


def wilson(k, n, z=1.96):
    """Proportion with a 95% Wilson score interval. None when n == 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {"k": k, "n": n, "p": round(p, 4),
            "lo": round(max(0.0, centre - half), 4), "hi": round(min(1.0, centre + half), 4)}


def cohen_kappa(a, b):
    """Cohen's kappa for two equal-length label lists. None if undefined."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe == 1:
        return None
    return round((po - pe) / (1 - pe), 4)


def macro_f1(gold, pred, classes):
    """Macro-F1 over classes that appear in gold (absent classes are not averaged)."""
    scores = []
    for c in classes:
        tp = sum(g == c and p == c for g, p in zip(gold, pred))
        fp = sum(g != c and p == c for g, p in zip(gold, pred))
        fn = sum(g == c and p != c for g, p in zip(gold, pred))
        if tp + fn == 0:
            continue
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn)
        scores.append(0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec))
    return round(sum(scores) / len(scores), 4) if scores else None


def percentile(values, q):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    idx = (len(vals) - 1) * q
    lo, hi = math.floor(idx), math.ceil(idx)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (idx - lo), 1)
