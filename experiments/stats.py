"""Statistical helpers for experiment summaries (bootstrap CI, paired tests).

Used by the sweep harness and ``experiments/paper_stats.py`` so the paper reports
confidence intervals and significance rather than bare mean +/- std over 24 runs.

Two things worth stating because they are easy to get wrong:

* Pairwise statistics must drop a sample from *both* vectors when either is missing.
  Cleaning each vector independently and then truncating silently re-pairs the data
  (``pearson_r`` did exactly that, and a single NaN turned an r of -1.00 into -0.99).
* The bootstrap is seeded, so every number in the paper is reproducible bit-for-bit.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

try:
    from scipy import stats as sp_stats
except ImportError:  # pragma: no cover - scipy is a hard requirement for the paper stats
    sp_stats = None


def _clean(vals) -> np.ndarray:
    v = np.asarray(vals, dtype=float)
    return v[np.isfinite(v)]


def _clean_pair(x, y) -> tuple[np.ndarray, np.ndarray]:
    """Drop index i from both vectors whenever either x[i] or y[i] is non-finite."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != y.shape:
        raise ValueError(f"paired vectors must have equal length, got {x.shape} and {y.shape}")
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def mean_std(vals) -> dict[str, float | int]:
    v = _clean(vals)
    if v.size == 0:
        return {"mean": float("nan"), "std": float("nan"), "n": 0}
    return {"mean": float(v.mean()),
            "std": float(v.std(ddof=1)) if v.size > 1 else 0.0,
            "n": int(v.size)}


def bootstrap_ci(vals, n_boot: int = 10000, alpha: float = 0.05, seed: int = 0) -> dict[str, float]:
    """Seeded percentile bootstrap CI for the mean."""
    v = _clean(vals)
    if v.size == 0:
        return {"ci_lo": float("nan"), "ci_hi": float("nan"), "level": 1.0 - alpha}
    if v.size == 1:
        m = float(v[0])
        return {"ci_lo": m, "ci_hi": m, "level": 1.0 - alpha}
    rng = np.random.default_rng(seed)
    boots = rng.choice(v, size=(n_boot, v.size), replace=True).mean(axis=1)
    lo, hi = np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {"ci_lo": float(lo), "ci_hi": float(hi), "level": 1.0 - alpha}


def paired_wilcoxon(baseline, steered) -> dict[str, float | int | None]:
    """Two-sided Wilcoxon signed-rank on paired (baseline, steered) samples."""
    b, s = _clean_pair(baseline, steered)
    d = s - b
    # The signed-rank test is undefined when every difference is zero. Older scipy
    # raised; current scipy warns and returns NaN. Neither is a p-value: say so.
    if b.size < 3 or sp_stats is None or not np.any(d != 0):
        return {"statistic": None, "p_value": None, "n": int(b.size), "test": "wilcoxon"}
    try:
        res = sp_stats.wilcoxon(d, alternative="two-sided", zero_method="wilcox")
    except ValueError:
        return {"statistic": None, "p_value": None, "n": int(b.size), "test": "wilcoxon"}
    if not np.isfinite(res.pvalue):
        return {"statistic": None, "p_value": None, "n": int(b.size), "test": "wilcoxon"}
    return {"statistic": float(res.statistic), "p_value": float(res.pvalue),
            "n": int(b.size), "test": "wilcoxon"}


def paired_sign_test_positive(vals) -> dict[str, float | int | None]:
    """Two-sided sign test on paired differences.

    Exact zeros are *ties*, not failures: on 6 of our 24 layouts the rApp moves no UE,
    so the gain is identically zero. The sign test discards ties and tests the remaining
    n_pos + n_neg differences against p=0.5 (Dixon & Mood). Counting ties as negatives
    -- as a naive ``sum(d > 0) / len(d)`` does -- deflates the statistic towards no
    effect. Both counts are returned so the reader can see how many ties there were.
    """
    d = _clean(vals)
    if d.size == 0:
        return {"frac_positive": float("nan"), "p_value": None, "n": 0,
                "n_positive": 0, "n_negative": 0, "n_tied": 0, "test": "sign"}
    n_pos, n_neg = int(np.sum(d > 0)), int(np.sum(d < 0))
    n_eff = n_pos + n_neg
    p = (float(sp_stats.binomtest(n_pos, n_eff, 0.5, alternative="two-sided").pvalue)
         if sp_stats is not None and n_eff > 0 else None)
    return {"frac_positive": float(n_pos / n_eff) if n_eff else float("nan"),
            "p_value": p, "n": int(n_eff), "n_positive": n_pos, "n_negative": n_neg,
            "n_tied": int(d.size - n_eff), "test": "sign"}


def summarize_gain(vals, seed: int = 0) -> dict[str, Any]:
    """Mean, std, bootstrap 95% CI, and sign test for a gain vector (%)."""
    v = _clean(vals)
    out = mean_std(v)
    out.update(bootstrap_ci(v, seed=seed))
    out.update({f"sign_{k}": val for k, val in paired_sign_test_positive(v).items()})
    return out


def pearson_r(x, y) -> dict[str, float | int | None]:
    """Pearson correlation over *paired* samples, dropping incomplete pairs."""
    x, y = _clean_pair(x, y)
    if x.size < 3 or np.std(x) == 0 or np.std(y) == 0:
        return {"r": None, "r2": None, "n": int(x.size)}
    r = float(np.corrcoef(x, y)[0, 1])
    return {"r": r, "r2": float(r * r), "n": int(x.size)}


def write_json(path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, allow_nan=False))
