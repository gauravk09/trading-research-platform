"""H1: Gaussian HMM, 3 states, full covariance, Baum-Welch EM in log-space
(spec Section 3.1, H1; Docs/regime_system_design.md).

Fixed design (pre-declared, not tuned on results):
- observation = [ret_20, rvol_20] from the T1 features, standardized with the
  TRAIN fold's mean/std only (fit() never sees test rows).
- 3 states, full covariance, a 1e-6*I covariance floor for stability.
- 10 random restarts with fixed seeds (0..9); keep the restart with the best
  TRAIN log-likelihood. max_iter=200, tol=1e-6 on the log-likelihood.
- Training E-step: standard forward-backward, done in log-space. The hot
  T-length recursions (forward-backward for training, the causal filter for
  prediction) are JIT-compiled with numba (`_forward_backward_numba`,
  `_filter_causal_numba`) -- pure-python/numpy versions of the same math are
  kept as `_forward_backward` / `_filter_causal` and used ONLY as a
  reference in tests/test_hmm_gaussian.py, which asserts the numba and
  reference outputs agree to 1e-9 on synthetic data. Both exist purely to
  stop the alpha/beta recursion from underflowing over a few thousand rows
  by working in log-space.
- Prediction is FILTERED (causal) only: the forward recursion is run from
  the first available row of history through t, using only rows <= t. The
  smoothed/backward pass exists solely for the EM E-step; predict() never
  calls it and never uses backward messages. A model that used Viterbi or
  smoothed gamma over the full series for its "predictions" would be
  reading the future through t's neighbours' emissions -- see
  tests/test_hmm_gaussian.py::test_filtered_state_is_causal.
- After every fit, states are relabeled by sorting on the fitted state's
  MEAN ret_20 (original, unstandardized scale): highest -> Up, lowest ->
  Down, middle -> Choppy. This fixes label switching across folds/restarts.
  It is a real risk with this model: an HMM on [ret_20, rvol_20] is just as
  likely to separate on volatility as on drift (see README's state-meaning
  table for this run's actual per-state means) -- sorting on ret_20 is a
  deliberate choice consistent with the spec's "Up/Choppy/Down" framing, not
  a claim that the fitted states are secretly trend states.
- n_fitted_knobs = 0: n_states and n_restarts are fixed by the spec, not
  knobs the harness's perturbation suite is meant to shake -- so `knobs` is
  accepted (for the model_factory interface) but not used to configure
  anything. is_stochastic = True because of the restart seeds, but they are
  fixed internally, not exposed as a perturbable knob.
"""
from __future__ import annotations

import math

import numba
import numpy as np
import pandas as pd
from scipy.special import logsumexp

from .base import RegimeModel, StateToOdds, HORIZONS

OBS_COLS = ["ret_20", "rvol_20"]
STATE_COLS = ["regime_p_down", "regime_p_chop", "regime_p_up"]
N_STATES = 3
COV_FLOOR = 1e-6 * np.eye(2)
RESTART_SEEDS = tuple(range(10))
MAX_ITER = 200
TOL = 1e-6


def _log_gaussian(x: np.ndarray, mean: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """x: (T,D). Returns (T,) log density of a single full-covariance Gaussian."""
    d = x.shape[1]
    diff = x - mean
    prec = np.linalg.inv(cov)
    sign, logdet = np.linalg.slogdet(cov)
    maha = np.einsum("ti,ij,tj->t", diff, prec, diff)
    return -0.5 * (d * np.log(2 * np.pi) + logdet + maha)


def _log_emissions(x: np.ndarray, means: np.ndarray, covs: np.ndarray) -> np.ndarray:
    """means: (K,D), covs: (K,D,D). Returns (T,K) log emission likelihoods."""
    return np.column_stack([_log_gaussian(x, means[k], covs[k]) for k in range(means.shape[0])])


def _resets_from_valid(valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """valid: (T,) bool. Returns (valid_idx, resets) where valid_idx are the
    original row positions of the valid rows (ascending) and resets[i] is
    True where the causal chain must restart from log_start -- the first
    valid row, or any valid row that isn't immediately preceded (in the
    ORIGINAL index) by the previous valid row (a data gap).
    """
    valid_idx = np.flatnonzero(valid)
    resets = np.zeros(len(valid_idx), dtype=np.bool_)
    if len(valid_idx):
        resets[0] = True
        resets[1:] = np.diff(valid_idx) != 1
    return valid_idx, resets


# ---------------------------------------------------------------------------
# Reference implementations (pure python/numpy). Used directly by fit() for
# the E-step (called ~10 restarts x <=200 iterations x 25 folds, so it still
# matters that this isn't naive per-step numpy allocation -- see _lse), and
# used ONLY as a correctness oracle for the numba versions below in tests.
# ---------------------------------------------------------------------------

def _lse(vals) -> float:
    """logsumexp of a short python sequence, in plain math (no numpy call
    overhead) -- K is always 3 here, so this beats numpy's small-array
    allocation cost by a wide margin when called T times per EM iteration.
    """
    m = max(vals)
    if m == -math.inf:
        return -math.inf
    return m + math.log(sum(math.exp(v - m) for v in vals))


def _forward_backward(log_emit: np.ndarray, log_start: np.ndarray, log_trans: np.ndarray):
    """Reference log-space forward-backward (pure python inner loop).
    log_trans[i, j] = log P(s_t=j | s_{t-1}=i). Assumes log_emit has no
    gaps (a single contiguous block from t=0). Returns log_gamma (T,K),
    log_xi (T-1,K,K), loglik (scalar).
    """
    T, K = log_emit.shape
    emit = log_emit.tolist()
    start = log_start.tolist()
    trans = log_trans.tolist()

    log_alpha = [[start[k] + emit[0][k] for k in range(K)]]
    for t in range(1, T):
        prev = log_alpha[-1]
        log_alpha.append([_lse([prev[i] + trans[i][j] for i in range(K)]) + emit[t][j] for j in range(K)])

    log_beta = [[0.0] * K for _ in range(T)]
    for t in range(T - 2, -1, -1):
        nb, ne = log_beta[t + 1], emit[t + 1]
        log_beta[t] = [_lse([trans[i][j] + ne[j] + nb[j] for j in range(K)]) for i in range(K)]

    log_alpha = np.array(log_alpha)
    log_beta = np.array(log_beta)
    loglik = logsumexp(log_alpha[-1])
    log_gamma = log_alpha + log_beta - loglik

    log_xi = np.empty((T - 1, K, K))
    for t in range(T - 1):
        log_xi[t] = (log_alpha[t][:, None] + log_trans + log_emit[t + 1][None, :]
                     + log_beta[t + 1][None, :] - loglik)
    return log_gamma, log_xi, loglik


def _filter_causal(log_emit: np.ndarray, log_start: np.ndarray, log_trans: np.ndarray,
                    resets: np.ndarray | None = None) -> np.ndarray:
    """Reference filtered (forward-only) state probabilities (pure python
    inner loop) for a precomputed (T,K) emission log-likelihood matrix,
    where T only counts VALID (non-NaN) rows. `resets[t]` (default: only
    t=0) restarts the recursion from log_start -- used to represent a data
    gap in the original series. Returns (T,K).
    """
    T, K = log_emit.shape
    if resets is None:
        resets = np.zeros(T, dtype=bool)
        if T:
            resets[0] = True
    emit = log_emit.tolist()
    start = log_start.tolist()
    trans = log_trans.tolist()

    log_alpha_rows = []
    prev = None
    for t in range(T):
        if resets[t] or prev is None:
            row = [start[k] + emit[t][k] for k in range(K)]
        else:
            row = [_lse([prev[i] + trans[i][j] for i in range(K)]) + emit[t][j] for j in range(K)]
        log_alpha_rows.append(row)
        prev = row

    out = np.array(log_alpha_rows)
    m = logsumexp(out, axis=1, keepdims=True)
    return np.exp(out - m)


def _filter_forward(x: np.ndarray, means, covs, start, trans) -> np.ndarray:
    """Filtered (causal, forward-only) state probabilities for a fully-valid
    (no NaN) standardized observation matrix, via the numba filter. Returns
    (T,K). Used inside fit() to get the train fold's own state probs for
    StateToOdds.
    """
    log_emit = _log_emissions(x, means, covs)
    log_start = np.log(np.clip(start, 1e-300, None))
    log_trans = np.log(np.clip(trans, 1e-300, None))
    T = log_emit.shape[0]
    resets = np.zeros(T, dtype=np.bool_)
    if T:
        resets[0] = True
    return _filter_causal_numba(log_emit, log_start, log_trans, resets)


def _kmeans_pp_init(x: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    T = x.shape[0]
    centers = [x[rng.integers(T)]]
    for _ in range(1, k):
        d2 = np.min([np.sum((x - c) ** 2, axis=1) for c in centers], axis=0)
        total = d2.sum()
        probs = d2 / total if total > 0 else np.ones(T) / T
        centers.append(x[rng.choice(T, p=probs)])
    return np.array(centers)


# ---------------------------------------------------------------------------
# numba versions of the same two recursions, semantics IDENTICAL to
# _forward_backward / _filter_causal above (see
# tests/test_hmm_gaussian.py::test_numba_matches_reference_*). These are
# what fit()/predict() actually call -- the pure-python T-loop, while much
# faster than naive per-step numpy, is still too slow for the "long" window
# config's later folds (thousands of rows x 10 restarts x up to 200 EM
# iterations x 25 folds).
# ---------------------------------------------------------------------------

@numba.njit(cache=True)
def _forward_backward_numba(log_emit, log_start, log_trans):
    T, K = log_emit.shape
    log_alpha = np.empty((T, K))
    for k in range(K):
        log_alpha[0, k] = log_start[k] + log_emit[0, k]
    for t in range(1, T):
        for j in range(K):
            m = -np.inf
            for i in range(K):
                v = log_alpha[t - 1, i] + log_trans[i, j]
                if v > m:
                    m = v
            s = 0.0
            for i in range(K):
                s += np.exp(log_alpha[t - 1, i] + log_trans[i, j] - m)
            log_alpha[t, j] = m + np.log(s) + log_emit[t, j]

    log_beta = np.zeros((T, K))
    for t in range(T - 2, -1, -1):
        for i in range(K):
            m = -np.inf
            for j in range(K):
                v = log_trans[i, j] + log_emit[t + 1, j] + log_beta[t + 1, j]
                if v > m:
                    m = v
            s = 0.0
            for j in range(K):
                s += np.exp(log_trans[i, j] + log_emit[t + 1, j] + log_beta[t + 1, j] - m)
            log_beta[t, i] = m + np.log(s)

    m = -np.inf
    for k in range(K):
        if log_alpha[T - 1, k] > m:
            m = log_alpha[T - 1, k]
    s = 0.0
    for k in range(K):
        s += np.exp(log_alpha[T - 1, k] - m)
    loglik = m + np.log(s)

    log_gamma = log_alpha + log_beta - loglik
    log_xi = np.empty((T - 1, K, K))
    for t in range(T - 1):
        for i in range(K):
            for j in range(K):
                log_xi[t, i, j] = log_alpha[t, i] + log_trans[i, j] + log_emit[t + 1, j] + log_beta[t + 1, j] - loglik
    return log_gamma, log_xi, loglik


@numba.njit(cache=True)
def _filter_causal_numba(log_emit, log_start, log_trans, resets):
    T, K = log_emit.shape
    out = np.empty((T, K))
    prev = np.empty(K)
    for t in range(T):
        if resets[t] or t == 0:
            for k in range(K):
                prev[k] = log_start[k] + log_emit[t, k]
        else:
            new_row = np.empty(K)
            for j in range(K):
                m = -np.inf
                for i in range(K):
                    v = prev[i] + log_trans[i, j]
                    if v > m:
                        m = v
                s = 0.0
                for i in range(K):
                    s += np.exp(prev[i] + log_trans[i, j] - m)
                new_row[j] = m + np.log(s) + log_emit[t, j]
            prev = new_row
        m2 = -np.inf
        for k in range(K):
            if prev[k] > m2:
                m2 = prev[k]
        s2 = 0.0
        for k in range(K):
            s2 += np.exp(prev[k] - m2)
        logz = m2 + np.log(s2)
        for k in range(K):
            out[t, k] = np.exp(prev[k] - logz)
    return out


class GaussianHMM3State(RegimeModel):
    name = "H1_gaussian_hmm"
    is_stochastic = True

    def __init__(self, knobs: dict | None = None):
        super().__init__(knobs=knobs)
        # Not a spec knob (n_fitted_knobs stays 0): an optional offset applied
        # to the 10 fixed restart seeds, used only by the refit-seed
        # stability check (spec Section 4.3) to get a second fixed-but-
        # different set of restarts without touching the real run's knobs={}.
        self.restart_seed_offset = int(self.knobs.get("restart_seed_offset", 0))
        self.feature_mean_: np.ndarray | None = None
        self.feature_std_: np.ndarray | None = None
        self.means_: np.ndarray | None = None
        self.covs_: np.ndarray | None = None
        self.start_: np.ndarray | None = None
        self.trans_: np.ndarray | None = None
        self.state_order_: dict[int, str] | None = None
        self.s2o_ = StateToOdds()
        self.loglik_history_: list[float] = []
        self.info: dict = {}

    @property
    def n_fitted_knobs(self) -> int:
        return 0

    def _init_params(self, x: np.ndarray, seed: int):
        rng = np.random.default_rng(seed)
        means = _kmeans_pp_init(x, N_STATES, rng)
        var = x.var(axis=0)
        cov0 = np.diag(np.where(var > 0, var, 1.0)) + COV_FLOOR
        covs = np.array([cov0.copy() for _ in range(N_STATES)])
        start = np.full(N_STATES, 1.0 / N_STATES)
        trans = np.full((N_STATES, N_STATES), 0.05)
        np.fill_diagonal(trans, 0.9)
        trans = trans / trans.sum(axis=1, keepdims=True)
        return means, covs, start, trans

    def _em(self, x: np.ndarray, params):
        means, covs, start, trans = params
        ll_hist: list[float] = []
        for _ in range(MAX_ITER):
            log_emit = _log_emissions(x, means, covs)
            log_start = np.log(np.clip(start, 1e-300, None))
            log_trans = np.log(np.clip(trans, 1e-300, None))
            log_gamma, log_xi, loglik = _forward_backward_numba(log_emit, log_start, log_trans)
            ll_hist.append(float(loglik))
            if len(ll_hist) >= 2 and abs(ll_hist[-1] - ll_hist[-2]) < TOL:
                break

            gamma = np.exp(log_gamma)
            xi = np.exp(log_xi)

            start = gamma[0] / gamma[0].sum()
            denom = gamma[:-1].sum(axis=0)
            denom = np.where(denom > 0, denom, 1.0)
            trans = xi.sum(axis=0) / denom[:, None]
            trans = trans / trans.sum(axis=1, keepdims=True)

            Nk = gamma.sum(axis=0)
            Nk_safe = np.where(Nk > 0, Nk, 1.0)
            means = (gamma.T @ x) / Nk_safe[:, None]
            covs_new = np.empty_like(covs)
            for k in range(N_STATES):
                diff = x - means[k]
                cov_k = (gamma[:, k][:, None] * diff).T @ diff / Nk_safe[k]
                covs_new[k] = cov_k + COV_FLOOR
            covs = covs_new
        return (means, covs, start, trans), ll_hist

    def fit(self, X_train: pd.DataFrame, Y_train: pd.DataFrame) -> "GaussianHMM3State":
        obs_raw = X_train[OBS_COLS]
        valid = obs_raw.notna().all(axis=1)
        obs_valid = obs_raw[valid].to_numpy()
        if len(obs_valid) < N_STATES * 5:
            raise ValueError("not enough valid rows in X_train to fit a 3-state HMM")

        mean = obs_valid.mean(axis=0)
        std = obs_valid.std(axis=0)
        std = np.where(std > 0, std, 1.0)
        self.feature_mean_, self.feature_std_ = mean, std
        x = (obs_valid - mean) / std

        best_params, best_ll_hist = None, None
        for seed in (s + self.restart_seed_offset for s in RESTART_SEEDS):
            init = self._init_params(x, seed)
            params, ll_hist = self._em(x, init)
            if best_ll_hist is None or ll_hist[-1] > best_ll_hist[-1]:
                best_params, best_ll_hist = params, ll_hist
        self.means_, self.covs_, self.start_, self.trans_ = best_params
        self.loglik_history_ = best_ll_hist

        orig_means = self.means_ * std + mean
        order = np.argsort(orig_means[:, 0])
        down_i, chop_i, up_i = int(order[0]), int(order[1]), int(order[2])
        self.state_order_ = {down_i: "regime_p_down", chop_i: "regime_p_chop", up_i: "regime_p_up"}

        self.info["state_mean_ret20"] = {self.state_order_[k]: float(orig_means[k, 0]) for k in range(N_STATES)}
        self.info["state_mean_rvol20"] = {self.state_order_[k]: float(orig_means[k, 1]) for k in range(N_STATES)}
        n_mean = N_STATES * 2
        n_cov = N_STATES * 2 * 3 // 2
        n_trans = N_STATES * (N_STATES - 1)
        n_start = N_STATES - 1
        self.info["n_estimated_params"] = n_mean + n_cov + n_trans + n_start
        self.info["final_train_loglik"] = self.loglik_history_[-1]

        filt = _filter_forward(x, self.means_, self.covs_, self.start_, self.trans_)
        idx_train = obs_raw.index[valid]
        probs_df = pd.DataFrame(0.0, index=idx_train, columns=STATE_COLS)
        for k in range(N_STATES):
            probs_df[self.state_order_[k]] = filt[:, k]

        levels = {f"band_{h}": [0, 1, 2] for h in HORIZONS}
        levels.update({f"dd_{h}": [0, 1] for h in HORIZONS})
        levels["vol_tercile_20"] = [0, 1, 2]
        self.s2o_.fit(probs_df, Y_train.loc[idx_train], levels)
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        out = self._empty_predictions(X.index)
        obs_raw = X[OBS_COLS]
        valid = obs_raw.notna().all(axis=1).to_numpy()
        x_std = (obs_raw.to_numpy() - self.feature_mean_) / self.feature_std_

        log_start = np.log(np.clip(self.start_, 1e-300, None))
        log_trans = np.log(np.clip(self.trans_, 1e-300, None))
        T = len(X)
        valid_idx, resets = _resets_from_valid(valid)

        filt = np.full((T, N_STATES), np.nan)
        if len(valid_idx):
            # Emission log-likelihoods computed ONCE for every valid row in a
            # single vectorized batch; the T-loop inside the numba filter
            # only does the cheap causal recursion.
            log_emit_valid = _log_emissions(x_std[valid_idx], self.means_, self.covs_)
            filt_valid = _filter_causal_numba(log_emit_valid, log_start, log_trans, resets)
            filt[valid_idx] = filt_valid

        probs_df = pd.DataFrame(0.0, index=X.index, columns=STATE_COLS)
        for k in range(N_STATES):
            probs_df[self.state_order_[k]] = filt[:, k]
        for col in STATE_COLS:
            out[col] = probs_df[col]

        for h in HORIZONS:
            odds = self.s2o_.predict(probs_df, f"band_{h}")
            out[f"p_down_{h}"] = odds[0]
            out[f"p_flat_{h}"] = odds[1]
            out[f"p_up_{h}"] = odds[2]
            odds_dd = self.s2o_.predict(probs_df, f"dd_{h}")
            out[f"p_dd_{h}"] = odds_dd[1]
        odds_vol = self.s2o_.predict(probs_df, "vol_tercile_20")
        out["p_vol_low_20"] = odds_vol[0]
        out["p_vol_mid_20"] = odds_vol[1]
        out["p_vol_high_20"] = odds_vol[2]
        return out
