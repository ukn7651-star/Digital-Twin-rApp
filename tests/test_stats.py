"""Unit tests for the experiment statistics helpers."""

from __future__ import annotations

import numpy as np
import pytest

from experiments.stats import (
    bootstrap_ci,
    mean_std,
    paired_sign_test_positive,
    paired_wilcoxon,
    pearson_r,
    summarize_gain,
)


def test_bootstrap_ci_contains_mean():
    v = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    ci = bootstrap_ci(v, n_boot=2000, seed=0)
    assert ci["ci_lo"] <= v.mean() <= ci["ci_hi"]


def test_bootstrap_ci_is_seeded():
    v = np.random.default_rng(7).normal(size=30)
    assert bootstrap_ci(v, n_boot=1000, seed=3) == bootstrap_ci(v, n_boot=1000, seed=3)


def test_bootstrap_ci_degenerate_cases():
    empty = bootstrap_ci([])
    assert np.isnan(empty["ci_lo"]) and np.isnan(empty["ci_hi"])
    one = bootstrap_ci([4.2])
    assert one["ci_lo"] == one["ci_hi"] == 4.2


def test_summarize_gain_positive_trend():
    s = summarize_gain([5.0, 8.0, 12.0, 3.0, 7.0, 9.0], seed=1)
    assert s["mean"] > 0 and s["n"] == 6
    assert s["sign_frac_positive"] == 1.0
    assert s["sign_n_tied"] == 0


def test_paired_wilcoxon_detects_shift():
    base = np.arange(10, dtype=float)
    res = paired_wilcoxon(base, base + 2.0)
    assert res["p_value"] is not None and res["p_value"] < 0.05


def test_paired_wilcoxon_all_zero_differences_is_not_a_crash():
    base = np.arange(10, dtype=float)
    res = paired_wilcoxon(base, base)
    assert res["p_value"] is None and res["n"] == 10


def test_sign_test_symmetric_sample_is_not_significant():
    res = paired_sign_test_positive([1.0, -1.0, 2.0, -2.0, 3.0, -3.0])
    assert res["frac_positive"] == 0.5
    assert res["p_value"] > 0.5


def test_sign_test_discards_ties_rather_than_counting_them_as_failures():
    """Dixon-Mood: exact zeros carry no sign information and are dropped.

    Our sweep has 6 layouts (of 24) where the rApp moves no UE, so the gain is
    identically zero. Counting those as non-positive would report 15/24 and p=0.31
    where the sign test says 15/18 and p<0.01.
    """
    vals = [1.0] * 15 + [-1.0] * 3 + [0.0] * 6
    res = paired_sign_test_positive(vals)
    assert res["n_positive"] == 15
    assert res["n_negative"] == 3
    assert res["n_tied"] == 6
    assert res["n"] == 18                       # ties excluded from the test
    assert res["frac_positive"] == pytest.approx(15 / 18)
    assert res["p_value"] < 0.01

    all_tied = paired_sign_test_positive([0.0, 0.0, 0.0])
    assert all_tied["n"] == 0 and all_tied["p_value"] is None


# --- pairing: the bug that made an r of -1.00 read as -0.99 -----------------
def test_pearson_r_drops_incomplete_pairs_from_both_vectors():
    """A NaN in x must remove the *same index* from y, not shift the pairing."""
    x = [1.0, np.nan, 3.0, 4.0, 5.0, 6.0]
    y = [6.0, 5.0, 4.0, 3.0, 2.0, 1.0]      # y = 7 - x, so the true r over valid pairs is -1
    assert pearson_r(x, y)["r"] == pytest.approx(-1.0)
    assert pearson_r(x, y)["n"] == 5


def test_paired_wilcoxon_drops_incomplete_pairs_from_both_vectors():
    base = [1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0]
    steer = [3.0, 4.0, 9.0, 6.0, 7.0, 8.0, 9.0]   # +2 on every complete pair
    res = paired_wilcoxon(base, steer)
    assert res["n"] == 6

def test_paired_vectors_of_unequal_length_are_rejected():
    with pytest.raises(ValueError, match="equal length"):
        pearson_r([1.0, 2.0, 3.0], [1.0, 2.0])


def test_mean_std_uses_sample_std():
    v = [1.0, 2.0, 3.0]
    assert mean_std(v)["std"] == pytest.approx(np.std(v, ddof=1))
    assert mean_std([5.0])["std"] == 0.0
