"""Proper scores, calibration, and block-bootstrap confidence intervals.

RPS definition used throughout (Epstein 1969, unnormalized): for K ordered
categories with predicted probabilities p and true category y,
  CDF_pred[k] = sum_{j<=k} p[j],  CDF_true[k] = 1{y <= k}
  RPS = sum_{k=0}^{K-2} (CDF_pred[k] - CDF_true[k])^2
(the k=K-1 term is always 0 since both CDFs sum to 1, so it's dropped).
Hand-computed examples are in tests/test_scoring.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Proper scores
# ---------------------------------------------------------------------------

def rps_per_day(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    """probs: (n, K) predicted probabilities, y: (n,) true category index in
    [0, K-1]. Returns per-row RPS. Rows with any NaN in probs or NaN y give NaN.
    """
    probs = np.asarray(probs, dtype=float)
    y = np.asarray(y, dtype=float)
    n, K = probs.shape
    valid = ~np.isnan(probs).any(axis=1) & ~np.isnan(y)
    out = np.full(n, np.nan)
    if valid.sum() == 0:
        return out
    p = probs[valid]
    yy = y[valid].astype(int)
    cdf_pred = np.cumsum(p, axis=1)
    true_onehot = np.zeros_like(p)
    true_onehot[np.arange(len(yy)), yy] = 1.0
    cdf_true = np.cumsum(true_onehot, axis=1)
    diffs = (cdf_pred[:, :-1] - cdf_true[:, :-1]) ** 2
    out[valid] = diffs.sum(axis=1)
    return out


def rps_skill(rps_model: np.ndarray, rps_clim: np.ndarray) -> float:
    rps_model = np.asarray(rps_model, dtype=float)
    rps_clim = np.asarray(rps_clim, dtype=float)
    valid = ~np.isnan(rps_model) & ~np.isnan(rps_clim)
    if valid.sum() == 0:
        return np.nan
    return 1.0 - np.nanmean(rps_model[valid]) / np.nanmean(rps_clim[valid])


def log_loss_multiclass(probs: np.ndarray, y: np.ndarray, eps: float = 1e-12) -> float:
    probs = np.asarray(probs, dtype=float)
    y = np.asarray(y, dtype=float)
    n = probs.shape[0]
    valid = ~np.isnan(probs).any(axis=1) & ~np.isnan(y)
    if valid.sum() == 0:
        return np.nan
    p = np.clip(probs[valid], eps, 1.0)
    yy = y[valid].astype(int)
    p_true = p[np.arange(len(yy)), yy]
    return float(-np.mean(np.log(p_true)))


def brier_binary(p: np.ndarray, y: np.ndarray) -> float:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    valid = ~np.isnan(p) & ~np.isnan(y)
    if valid.sum() == 0:
        return np.nan
    return float(np.mean((p[valid] - y[valid]) ** 2))


def brier_multiclass(probs: np.ndarray, y: np.ndarray) -> float:
    probs = np.asarray(probs, dtype=float)
    y = np.asarray(y, dtype=float)
    n, K = probs.shape
    valid = ~np.isnan(probs).any(axis=1) & ~np.isnan(y)
    if valid.sum() == 0:
        return np.nan
    p = probs[valid]
    yy = y[valid].astype(int)
    onehot = np.zeros_like(p)
    onehot[np.arange(len(yy)), yy] = 1.0
    return float(np.mean(np.sum((p - onehot) ** 2, axis=1)))


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def ece(p: np.ndarray, y_binary: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error, equal-width bins over [0, 1]."""
    p = np.asarray(p, dtype=float)
    y_binary = np.asarray(y_binary, dtype=float)
    valid = ~np.isnan(p) & ~np.isnan(y_binary)
    p, y_binary = p[valid], y_binary[valid]
    if len(p) == 0:
        return np.nan
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, bins, right=False) - 1, 0, n_bins - 1)
    total = len(p)
    e = 0.0
    for b in range(n_bins):
        mask = idx == b
        cnt = mask.sum()
        if cnt == 0:
            continue
        mean_pred = p[mask].mean()
        obs = y_binary[mask].mean()
        e += (cnt / total) * abs(mean_pred - obs)
    return float(e)


def _wilson_ci(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (np.nan, np.nan)
    phat = k / n
    denom = 1 + z ** 2 / n
    center = phat + z ** 2 / (2 * n)
    margin = z * np.sqrt(phat * (1 - phat) / n + z ** 2 / (4 * n ** 2))
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    return (max(0.0, lo), min(1.0, hi))


def reliability_diagram_data(p: np.ndarray, y_binary: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    p = np.asarray(p, dtype=float)
    y_binary = np.asarray(y_binary, dtype=float)
    valid = ~np.isnan(p) & ~np.isnan(y_binary)
    p, y_binary = p[valid], y_binary[valid]
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, bins, right=False) - 1, 0, n_bins - 1) if len(p) else np.array([])
    rows = []
    for b in range(n_bins):
        mask = idx == b
        cnt = int(mask.sum())
        if cnt == 0:
            rows.append({"bin": b, "mean_pred": np.nan, "obs_freq": np.nan,
                         "count": 0, "ci_lo": np.nan, "ci_hi": np.nan})
            continue
        k = int(y_binary[mask].sum())
        lo, hi = _wilson_ci(k, cnt)
        rows.append({
            "bin": b, "mean_pred": float(p[mask].mean()), "obs_freq": k / cnt,
            "count": cnt, "ci_lo": lo, "ci_hi": hi,
        })
    return pd.DataFrame(rows)


def _logit(p: np.ndarray) -> np.ndarray:
    return np.log(p / (1.0 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z))


def _fit_logistic_calibration(logit_p: np.ndarray, y: np.ndarray, max_iter: int = 100,
                               tol: float = 1e-8, ridge: float = 1e-6):
    """IRLS fit of logit(P(y=1)) = a + b*logit_p (2-parameter logistic
    regression, with a tiny ridge penalty for numerical stability -- see
    below). Returns (a, b), or None if logit_p has ~zero variance (e.g. a
    constant-probability forecaster like Climatology) -- the slope is
    undefined when there's nothing to regress against.

    The ridge term guards against separation blow-up: when a forecaster's
    clipped probabilities pile up near 0.01/0.99 (common for an
    overconfident/miscalibrated forecaster after clipping), those extreme
    points can be perfectly separated by y, which sends the unpenalized MLE
    to +/-infinity and its Newton steps to numerical overflow. A negligible
    ridge (1e-6) keeps every fit finite without materially biasing a
    well-behaved fit -- this is standard practice for logistic MLE near
    separation, not a design choice invented for this test.
    """
    if np.std(logit_p) < 1e-8:
        return None
    X = np.column_stack([np.ones_like(logit_p), logit_p])
    ridge_matrix = ridge * np.eye(2)
    beta = np.array([0.0, 1.0])
    for _ in range(max_iter):
        eta = X @ beta
        mu = _sigmoid(eta)
        w = np.clip(mu * (1.0 - mu), 1e-10, None)
        z = eta + (y - mu) / w
        xtw = X.T * w
        try:
            beta_new = np.linalg.solve(xtw @ X + ridge_matrix, xtw @ z)
        except np.linalg.LinAlgError:
            return None
        if not np.all(np.isfinite(beta_new)):
            return None
        beta_new = np.clip(beta_new, -25.0, 25.0)  # bound against separation blow-up
        if np.max(np.abs(beta_new - beta)) < tol:
            beta = beta_new
            break
        beta = beta_new
    if not np.all(np.isfinite(beta)):
        return None
    return float(beta[0]), float(beta[1])


def _fit_logistic_calibration_batch(logit_p_matrix: np.ndarray, y_matrix: np.ndarray,
                                     max_iter: int = 100, tol: float = 1e-8, ridge: float = 1e-6):
    """Vectorized batch IRLS: fits R independent copies of
    _fit_logistic_calibration's 2-parameter regression at once, one per row
    of logit_p_matrix/y_matrix (shape (R, n) each -- e.g. R bootstrap reps).

    Returns (a, b, ok), each shape (R,): ok[r] is False exactly where the
    scalar call `_fit_logistic_calibration(logit_p_matrix[r], y_matrix[r],
    max_iter, tol, ridge)` would return None (near-zero variance in that
    row, a singular/non-finite Newton step, or a non-finite final beta);
    a[r]/b[r] are NaN wherever ok[r] is False.

    For a 2-parameter model each IRLS step only needs 5 weighted sums per
    row (Sw, Swx, Swx2, Swz, Swxz), so the 2x2 weighted-least-squares system
    X'WX beta = X'Wz can be solved in closed form (Cramer's rule) instead of
    np.linalg.solve -- that's what makes it vectorizable across rows with
    plain array ops. Each row stops updating the moment ITS OWN step is
    below tol (a per-row mask), so a row's final beta is identical to what
    the scalar loop would have returned for that row in isolation -- rows
    don't interact.
    """
    logit_p_matrix = np.asarray(logit_p_matrix, dtype=float)
    y_matrix = np.asarray(y_matrix, dtype=float)
    R, n = logit_p_matrix.shape

    valid = np.std(logit_p_matrix, axis=1) >= 1e-8
    failed = ~valid
    converged = np.zeros(R, dtype=bool)
    beta = np.tile(np.array([0.0, 1.0]), (R, 1))

    for _ in range(max_iter):
        active = valid & ~converged & ~failed
        if not active.any():
            break

        eta = beta[:, 0:1] + beta[:, 1:2] * logit_p_matrix
        mu = _sigmoid(eta)
        w = np.clip(mu * (1.0 - mu), 1e-10, None)
        z = eta + (y_matrix - mu) / w

        Sw = w.sum(axis=1)
        Swx = (w * logit_p_matrix).sum(axis=1)
        Swx2 = (w * logit_p_matrix * logit_p_matrix).sum(axis=1)
        Swz = (w * z).sum(axis=1)
        Swxz = (w * logit_p_matrix * z).sum(axis=1)

        A11 = Sw + ridge
        A22 = Swx2 + ridge
        A12 = Swx
        det = A11 * A22 - A12 * A12

        with np.errstate(divide="ignore", invalid="ignore"):
            a_new = (Swz * A22 - A12 * Swxz) / det
            b_new = (A11 * Swxz - A12 * Swz) / det
        beta_new = np.column_stack([a_new, b_new])

        finite = np.isfinite(beta_new).all(axis=1)
        failed = failed | (active & ~finite)

        update = active & finite
        clipped = np.clip(beta_new, -25.0, 25.0)  # bound against separation blow-up
        step = np.max(np.abs(clipped - beta), axis=1)
        converged = converged | (update & (step < tol))

        beta = np.where(update[:, None], clipped, beta)

    ok = valid & ~failed & np.isfinite(beta).all(axis=1)
    a = np.where(ok, beta[:, 0], np.nan)
    b = np.where(ok, beta[:, 1], np.nan)
    return a, b, ok


def cox_calibration_test(p: np.ndarray, y_binary: np.ndarray, block: int = 20,
                          n_reps: int = 1000, seed: int = 0, ci: float = 0.95) -> dict:
    """Cox (1958) logistic calibration test, with a MOVING-BLOCK bootstrap
    instead of the independent-per-day resampling of consistency_resampling_ece.

    Fits logit(P(y=1)) = a + b*logit(p) (p clipped to [0.01, 0.99]). A
    perfectly calibrated forecaster has a=0, b=1. CIs for a and b come from
    resampling (p, y) PAIRS in contiguous blocks of `block` rows -- this
    respects the autocorrelation that overlapping horizon targets introduce
    (day t's 20-day target shares 19 days with day t+1's), which independent
    per-day resampling ignores and which made that narrower null reject even
    a synthetic Oracle that knows the true regime state (see CHANGELOG.md).

    When p has no variance (e.g. Climatology's fold-constant forecast), the
    slope is undefined -- only calibration-in-the-large is reported (mean p
    vs mean y, with its own block-bootstrap CI), and `slope_defined` is False.
    """
    p = np.asarray(p, dtype=float)
    y_binary = np.asarray(y_binary, dtype=float)
    valid = ~np.isnan(p) & ~np.isnan(y_binary)
    p, y_binary = p[valid], y_binary[valid]
    n = len(p)
    empty = {
        "n": 0, "slope_defined": False,
        "a": np.nan, "a_lo": np.nan, "a_hi": np.nan,
        "b": np.nan, "b_lo": np.nan, "b_hi": np.nan,
        "citl": np.nan, "citl_lo": np.nan, "citl_hi": np.nan,
    }
    if n == 0:
        return empty

    p_clipped = np.clip(p, 0.01, 0.99)
    logit_p = _logit(p_clipped)
    fit = _fit_logistic_calibration(logit_p, y_binary)
    slope_defined = fit is not None
    citl_point = float(np.mean(y_binary) - np.mean(p_clipped))

    alpha = (1 - ci) / 2 * 100
    # Same resampled index sets the old per-rep loop drew, in the same order
    # (same _block_bootstrap_index_reps call, same seed) -- just stacked into
    # one (R, n) matrix so the bootstrap reps can be fit in one batch call
    # instead of R scalar IRLS fits (see _fit_logistic_calibration_batch).
    idx_matrix = np.array(list(_block_bootstrap_index_reps(n, block, n_reps, seed)))
    pb_matrix = p_clipped[idx_matrix]
    yb_matrix = y_binary[idx_matrix]
    citl_boot = np.mean(yb_matrix, axis=1) - np.mean(pb_matrix, axis=1)

    a_boot, b_boot = [], []
    if slope_defined:
        a_arr, b_arr, ok = _fit_logistic_calibration_batch(_logit(pb_matrix), yb_matrix)
        a_boot = a_arr[ok].tolist()
        b_boot = b_arr[ok].tolist()

    citl_lo, citl_hi = np.percentile(citl_boot, [alpha, 100 - alpha])
    result = dict(empty)
    result.update({
        "n": int(n), "slope_defined": slope_defined,
        "citl": citl_point, "citl_lo": float(citl_lo), "citl_hi": float(citl_hi),
    })
    if slope_defined and len(a_boot) > 0:
        a_lo, a_hi = np.percentile(a_boot, [alpha, 100 - alpha])
        b_lo, b_hi = np.percentile(b_boot, [alpha, 100 - alpha])
        result.update({
            "a": fit[0], "a_lo": float(a_lo), "a_hi": float(a_hi),
            "b": fit[1], "b_lo": float(b_lo), "b_hi": float(b_hi),
        })
    return result


def consistency_resampling_ece(p: np.ndarray, y_binary: np.ndarray, n_bins: int = 10,
                                n_reps: int = 1000, seed: int = 0, percentile: float = 95.0) -> dict:
    """Broecker & Smith (2007) consistency resampling for ECE.

    DIAGNOSTIC ONLY, NOT A GATE (see CHANGELOG.md 2026-09-26): this draws
    y* ~ Bernoulli(p) independently per day, which ignores the
    autocorrelation that overlapping horizon targets introduce (day t's
    20-day target shares 19 days with day t+1's). That makes the null
    distribution too NARROW, not merely "conservative" -- it was found to
    reject even a synthetic Oracle that knows the true regime state. The
    pass/fail calibration gate now uses cox_calibration_test's moving-block
    bootstrap instead. This function is kept only to report raw ECE and its
    p-value against the (too-narrow) i.i.d. null as a reported diagnostic.
    """
    p = np.asarray(p, dtype=float)
    y_binary = np.asarray(y_binary, dtype=float)
    valid = ~np.isnan(p) & ~np.isnan(y_binary)
    p, y_binary = p[valid], y_binary[valid]
    if len(p) == 0:
        return {"observed_ece": np.nan, "null_ece_pct": np.nan, "p_value": np.nan, "n": 0}

    observed_ece = ece(p, y_binary, n_bins=n_bins)
    rng = np.random.default_rng(seed)
    n = len(p)
    null_ece = np.empty(n_reps)
    for r in range(n_reps):
        y_star = (rng.random(n) < p).astype(float)
        null_ece[r] = ece(p, y_star, n_bins=n_bins)
    null_pct = float(np.percentile(null_ece, percentile))
    p_value = float(np.mean(null_ece >= observed_ece))
    return {
        "observed_ece": float(observed_ece),
        "null_ece_pct": null_pct,
        "p_value": p_value,
        "n": int(n),
    }


# ---------------------------------------------------------------------------
# Moving-block bootstrap
# ---------------------------------------------------------------------------

def _block_bootstrap_index_reps(n: int, block: int, n_reps: int, seed: int):
    rng = np.random.default_rng(seed)
    block = max(1, min(block, n))
    n_blocks = int(np.ceil(n / block))
    max_start = n - block
    for _ in range(n_reps):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        yield idx


def rps_skill_ci(rps_model, rps_clim, block: int = 20, n_reps: int = 1000, seed: int = 0, ci: float = 0.95) -> dict:
    rps_model = np.asarray(rps_model, dtype=float)
    rps_clim = np.asarray(rps_clim, dtype=float)
    valid = ~np.isnan(rps_model) & ~np.isnan(rps_clim)
    rm, rc = rps_model[valid], rps_clim[valid]
    n = len(rm)
    if n == 0:
        return {"point": np.nan, "lo": np.nan, "hi": np.nan, "n": 0}
    stats = np.empty(n_reps)
    for r, idx in enumerate(_block_bootstrap_index_reps(n, block, n_reps, seed)):
        stats[r] = rps_skill(rm[idx], rc[idx])
    point = rps_skill(rm, rc)
    alpha = (1 - ci) / 2 * 100
    lo, hi = np.percentile(stats, [alpha, 100 - alpha])
    return {"point": float(point), "lo": float(lo), "hi": float(hi), "n": int(n)}


def paired_skill_diff_ci(rps_a_model, rps_a_clim, rps_b_model, rps_b_clim,
                          block: int = 20, n_reps: int = 1000, seed: int = 0, ci: float = 0.95) -> dict:
    """Skill difference (a - b) using the SAME resampled blocks for both, so
    the CI reflects paired (same-day) comparison rather than independent
    resampling of each experiment's predictions.
    """
    rps_a_model = np.asarray(rps_a_model, dtype=float)
    rps_a_clim = np.asarray(rps_a_clim, dtype=float)
    rps_b_model = np.asarray(rps_b_model, dtype=float)
    rps_b_clim = np.asarray(rps_b_clim, dtype=float)
    valid = (~np.isnan(rps_a_model) & ~np.isnan(rps_a_clim)
              & ~np.isnan(rps_b_model) & ~np.isnan(rps_b_clim))
    am, ac, bm, bc = rps_a_model[valid], rps_a_clim[valid], rps_b_model[valid], rps_b_clim[valid]
    n = len(am)
    if n == 0:
        return {"point": np.nan, "lo": np.nan, "hi": np.nan, "n": 0}
    stats = np.empty(n_reps)
    for r, idx in enumerate(_block_bootstrap_index_reps(n, block, n_reps, seed)):
        stats[r] = rps_skill(am[idx], ac[idx]) - rps_skill(bm[idx], bc[idx])
    point = rps_skill(am, ac) - rps_skill(bm, bc)
    alpha = (1 - ci) / 2 * 100
    lo, hi = np.percentile(stats, [alpha, 100 - alpha])
    return {"point": float(point), "lo": float(lo), "hi": float(hi), "n": int(n)}


def block_bootstrap_mean_ci(values, block: int = 20, n_reps: int = 1000, seed: int = 0, ci: float = 0.95) -> dict:
    values = np.asarray(values, dtype=float)
    valid = ~np.isnan(values)
    v = values[valid]
    n = len(v)
    if n == 0:
        return {"point": np.nan, "lo": np.nan, "hi": np.nan, "n": 0}
    stats = np.empty(n_reps)
    for r, idx in enumerate(_block_bootstrap_index_reps(n, block, n_reps, seed)):
        stats[r] = np.mean(v[idx])
    point = float(np.mean(v))
    alpha = (1 - ci) / 2 * 100
    lo, hi = np.percentile(stats, [alpha, 100 - alpha])
    return {"point": point, "lo": float(lo), "hi": float(hi), "n": int(n)}


# ---------------------------------------------------------------------------
# Separation
# ---------------------------------------------------------------------------

def separation_by_label(labels: pd.Series, value: pd.Series, block: int = 20, n_reps: int = 500, seed: int = 0) -> pd.DataFrame:
    """Mean of `value` grouped by `labels`, with block-bootstrap CIs."""
    rows = []
    for lab in sorted(labels.dropna().unique()):
        mask = (labels == lab) & value.notna()
        v = value[mask].to_numpy()
        if len(v) == 0:
            rows.append({"label": lab, "mean": np.nan, "lo": np.nan, "hi": np.nan, "n": 0})
            continue
        res = block_bootstrap_mean_ci(v, block=block, n_reps=n_reps, seed=seed)
        rows.append({"label": lab, "mean": res["point"], "lo": res["lo"], "hi": res["hi"], "n": len(v)})
    return pd.DataFrame(rows)
