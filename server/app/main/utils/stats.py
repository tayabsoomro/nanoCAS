"""Small, dependency-free statistics used by the lab-results and cohort views.

Everything here is deliberately textbook so it can be cited in a methods
section: Wilson score interval for proportions, ordinary least squares with
Pearson r and a two-sided t-test p-value, Spearman rank correlation,
Cohen's kappa for agreement between two binary tests, and Poisson
detection probabilities used for limit-of-detection reasoning.
"""

from __future__ import annotations

import math
from typing import Sequence


# ---------------------------------------------------------------------------
# Special functions (regularised incomplete beta for the t distribution)
# ---------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    max_it, eps, fpmin = 200, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > fpmin else fpmin)
    h = d
    for m in range(1, max_it + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > fpmin else fpmin)
        c = 1.0 + aa / (c if abs(c) > fpmin else fpmin)
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > fpmin else fpmin)
        c = 1.0 + aa / (c if abs(c) > fpmin else fpmin)
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(ln_beta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1 - x) / b


def t_two_sided_p(t: float, df: int) -> float:
    """Two-sided p-value for Student's t with ``df`` degrees of freedom."""
    if df <= 0:
        return float('nan')
    x = df / (df + t * t)
    return betainc(df / 2.0, 0.5, x)


# ---------------------------------------------------------------------------
# Proportions
# ---------------------------------------------------------------------------

def wilson_interval(successes: int, n: int, z: float = 1.959964) -> tuple[float, float, float]:
    """Wilson score 95 % interval for a binomial proportion.
    Returns ``(estimate, lower, upper)`` as fractions; ``(nan, nan, nan)`` for n == 0."""
    if n <= 0:
        return float('nan'), float('nan'), float('nan')
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lower = 0.0 if successes == 0 else max(0.0, centre - half)
    upper = 1.0 if successes == n else min(1.0, centre + half)
    return p, lower, upper


def cohens_kappa(both_pos: int, a_only: int, b_only: int, both_neg: int) -> float | None:
    """Agreement between two binary tests from a 2x2 table."""
    n = both_pos + a_only + b_only + both_neg
    if n == 0:
        return None
    po = (both_pos + both_neg) / n
    pa = ((both_pos + a_only) / n) * ((both_pos + b_only) / n) + ((b_only + both_neg) / n) * ((a_only + both_neg) / n)
    if pa >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return (po - pa) / (1 - pa)


def sensitivity_specificity(both_pos: int, a_only: int, b_only: int, both_neg: int) -> dict:
    """Treat test B (e.g. qPCR) as the reference and A (nanopore) as the index
    test: sensitivity = TP/(TP+FN), specificity = TN/(TN+FP)."""
    tp, fp, fn, tn = both_pos, a_only, b_only, both_neg
    sens = wilson_interval(tp, tp + fn) if tp + fn else (None, None, None)
    spec = wilson_interval(tn, tn + fp) if tn + fp else (None, None, None)
    return {
        'sensitivity': sens[0], 'sensitivity_ci': [sens[1], sens[2]],
        'specificity': spec[0], 'specificity_ci': [spec[1], spec[2]],
        'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'kappa': cohens_kappa(both_pos, a_only, b_only, both_neg),
    }


# ---------------------------------------------------------------------------
# Correlation / regression
# ---------------------------------------------------------------------------

def linear_regression(xs: Sequence[float], ys: Sequence[float]) -> dict | None:
    """OLS y = slope * x + intercept with Pearson r, r², and a two-sided
    p-value for r != 0 (t-test, n - 2 df). Needs n >= 3 and non-constant x."""
    pairs = [(float(x), float(y)) for x, y in zip(xs, ys)
             if x is not None and y is not None and not (math.isnan(x) or math.isnan(y))]
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxx = sum((p[0] - mx) ** 2 for p in pairs)
    syy = sum((p[1] - my) ** 2 for p in pairs)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    if sxx == 0:
        return None
    slope = sxy / sxx
    intercept = my - slope * mx
    r = sxy / math.sqrt(sxx * syy) if syy > 0 else 0.0
    r = max(-1.0, min(1.0, r))
    if abs(r) < 1.0:
        t = r * math.sqrt((n - 2) / (1 - r * r))
        p = t_two_sided_p(t, n - 2)
    else:
        p = 0.0
    residuals = [p_[1] - (slope * p_[0] + intercept) for p_ in pairs]
    rmse = math.sqrt(sum(e * e for e in residuals) / n)
    return {'n': n, 'slope': slope, 'intercept': intercept, 'r': r, 'r2': r * r, 'p': p, 'rmse': rmse,
            'x_range': [min(p_[0] for p_ in pairs), max(p_[0] for p_ in pairs)]}


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    rx = _ranks([p[0] for p in pairs])
    ry = _ranks([p[1] for p in pairs])
    reg = linear_regression(rx, ry)
    return reg['r'] if reg else None


# ---------------------------------------------------------------------------
# Detection / limit of detection
# ---------------------------------------------------------------------------

def poisson_detection_probability(expected_reads: float, min_reads: int = 1) -> float:
    """P(observing >= min_reads | Poisson(expected_reads))."""
    if expected_reads <= 0:
        return 0.0
    cdf = 0.0
    term = math.exp(-expected_reads)
    for k in range(0, min_reads):
        cdf += term
        term *= expected_reads / (k + 1)
    return max(0.0, min(1.0, 1.0 - cdf))


def ct_for_expected_reads(reg: dict, target_log10_rpm: float) -> float | None:
    """Invert a log10(RPM) = slope * Ct + intercept fit."""
    if not reg or reg['slope'] == 0:
        return None
    return (target_log10_rpm - reg['intercept']) / reg['slope']


def log10_rpm(reads: int, total_reads: int) -> float | None:
    if not total_reads or reads is None:
        return None
    rpm = reads / total_reads * 1e6
    return math.log10(rpm) if rpm > 0 else None


def median(values: Sequence[float]) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return float(vals[mid]) if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0
