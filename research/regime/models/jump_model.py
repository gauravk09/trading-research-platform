"""J1: statistical jump model, a.k.a. sticky HMM without the probabilistic
transition matrix (Nystrup, Madsen & Lindstrom 2020; Shu, Yu & Mulvey 2024).
spec Section 3.1, J1.

Fixed design (pre-declared, not tuned on results):
- observation = [ret_20, rvol_20], standardized with the TRAIN fold's
  mean/std only.
- 3 states. Fit by coordinate descent on the TRAIN fold:
    (a) state-sequence assignment by dynamic programming, minimizing
        sum_t ||x_t - mu_{s_t}||^2 + lambda * sum_t 1[s_t != s_{t-1}]
    (b) centroid update mu_k = mean of the points currently assigned to k
  alternating until the assignment stops changing (or max_iter=50).
- 10 k-means++-style initializations with fixed seeds (0..9); keep the
  lowest final objective.
- lambda (jump penalty) is PRE-DECLARED at 50.0 for standardized 2-D
  features -- not tuned here. It is the model's one numeric knob
  (n_fitted_knobs=1), so the harness's perturbation suite (+-10%/+-25%)
  exercises it automatically via `knobs={"lambda_penalty": 50.0}`.
- Prediction is ONLINE (causal), not the batch DP used for fitting:
    s_t = argmin_k ||x_t - mu_k||^2 + lambda * 1[k != s_{t-1}]
  run forward from the first available row of history. This never looks at
  x_{t+1}, ..., unlike the training-time DP, which is allowed to see the
  whole train fold because train/test dates never overlap (see
  tests/test_jump_model.py::test_predict_state_is_causal).
- Regime probabilities are one-hot on s_t: 1.0 for the assigned state, 0.0
  for the other two. States are relabeled by sorting fitted centroids on
  their ret_20 coordinate (highest -> Up, lowest -> Down, middle -> Choppy),
  same convention as H1, for the same reason (this model can separate on
  volatility just as easily as trend -- check the state-meaning table before
  trusting the labels).
- The DP and online-assignment T-loops are JIT-compiled with numba
  (`_dp_assign_numba`, `_online_assign_numba`) -- pure-python reference
  versions of the same math (`_dp_assign_core`, `_online_assign_core`) are
  kept and used ONLY in tests/test_jump_model.py, which asserts the numba
  and reference outputs agree exactly (integer state paths) on synthetic
  data.
"""
from __future__ import annotations

import numba
import numpy as np
import pandas as pd

from .base import RegimeModel, StateToOdds, HORIZONS
from .hmm_gaussian import OBS_COLS, STATE_COLS, _kmeans_pp_init, _resets_from_valid

N_STATES = 3
RESTART_SEEDS = tuple(range(10))
MAX_ITER = 50
DEFAULT_LAMBDA = 50.0


def _sq_cost(x: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """x: (T,D), centroids: (K,D). Returns (T,K) squared distances -- one
    vectorized batch computation, shared by both fit (DP) and predict
    (online) so the T-loops themselves never call numpy per row.
    """
    K = centroids.shape[0]
    return np.array([np.sum((x - centroids[k]) ** 2, axis=1) for k in range(K)]).T


# ---------------------------------------------------------------------------
# Reference implementations (pure python). Used as the correctness oracle
# for the numba versions below in tests only; fit()/predict() call numba.
# ---------------------------------------------------------------------------

def _dp_assign_core(sq_cost: np.ndarray, lam: float):
    """Optimal state sequence for FIXED centroids (given their precomputed
    (T,K) squared-distance costs): minimizes
    sum_t ||x_t - mu_{s_t}||^2 + lam * sum_t 1[s_t != s_{t-1}] by dynamic
    programming (batch -- sees the whole sequence; only ever used on a
    single fold's train rows). Returns (states (T,) int, objective float).
    """
    T, K = sq_cost.shape
    sq = sq_cost.tolist()

    dp = [sq[0]]
    back = [[-1] * K]
    for t in range(1, T):
        prev = dp[-1]
        min_idx = min(range(K), key=lambda i: prev[i])
        min_val = prev[min_idx]
        second_idx = min((i for i in range(K) if i != min_idx), key=lambda i: prev[i])
        second_val = prev[second_idx]
        row_dp, row_back = [0.0] * K, [0] * K
        for k in range(K):
            cost_stay = prev[k]
            if k != min_idx:
                cost_switch, switch_src = min_val + lam, min_idx
            else:
                cost_switch, switch_src = second_val + lam, second_idx
            if cost_stay <= cost_switch:
                row_dp[k] = cost_stay + sq[t][k]
                row_back[k] = k
            else:
                row_dp[k] = cost_switch + sq[t][k]
                row_back[k] = switch_src
        dp.append(row_dp)
        back.append(row_back)

    states = [0] * T
    states[-1] = int(np.argmin(dp[-1]))
    obj = float(dp[-1][states[-1]])
    for t in range(T - 2, -1, -1):
        states[t] = back[t + 1][states[t + 1]]
    return np.array(states), obj


def _online_assign_core(sq: np.ndarray, lam: float, resets: np.ndarray) -> np.ndarray:
    """Causal, greedy state assignment on a precomputed (T,K) squared-
    distance matrix for VALID rows only: s_t = argmin_k sq[t,k] +
    lam*1[k != s_{t-1}], run forward. `resets[t]` restarts with no penalty
    term at all (represents a data gap or the very first row).
    """
    T, K = sq.shape
    states = np.empty(T, dtype=int)
    prev = None
    for t in range(T):
        if resets[t]:
            prev = None
        row = sq[t]
        if prev is None:
            k = min(range(K), key=lambda i: row[i])
        else:
            k = min(range(K), key=lambda i: row[i] + (lam if i != prev else 0.0))
        states[t] = k
        prev = k
    return states


# ---------------------------------------------------------------------------
# numba versions, semantics IDENTICAL to the _core functions above (see
# tests/test_jump_model.py::test_numba_matches_reference_*).
# ---------------------------------------------------------------------------

@numba.njit(cache=True)
def _dp_assign_numba(sq_cost, lam):
    T, K = sq_cost.shape
    dp = np.empty((T, K))
    back = np.empty((T, K), dtype=np.int64)
    for k in range(K):
        dp[0, k] = sq_cost[0, k]
        back[0, k] = -1
    for t in range(1, T):
        min_idx = 0
        min_val = dp[t - 1, 0]
        for k in range(1, K):
            if dp[t - 1, k] < min_val:
                min_val = dp[t - 1, k]
                min_idx = k
        second_idx = -1
        second_val = np.inf
        for k in range(K):
            if k != min_idx and dp[t - 1, k] < second_val:
                second_val = dp[t - 1, k]
                second_idx = k
        for k in range(K):
            cost_stay = dp[t - 1, k]
            if k != min_idx:
                cost_switch, switch_src = min_val + lam, min_idx
            else:
                cost_switch, switch_src = second_val + lam, second_idx
            if cost_stay <= cost_switch:
                dp[t, k] = cost_stay + sq_cost[t, k]
                back[t, k] = k
            else:
                dp[t, k] = cost_switch + sq_cost[t, k]
                back[t, k] = switch_src

    states = np.empty(T, dtype=np.int64)
    best_k = 0
    best_val = dp[T - 1, 0]
    for k in range(1, K):
        if dp[T - 1, k] < best_val:
            best_val = dp[T - 1, k]
            best_k = k
    states[T - 1] = best_k
    obj = dp[T - 1, best_k]
    for t in range(T - 2, -1, -1):
        states[t] = back[t + 1, states[t + 1]]
    return states, obj


@numba.njit(cache=True)
def _online_assign_numba(sq, lam, resets):
    T, K = sq.shape
    states = np.empty(T, dtype=np.int64)
    prev = -1
    for t in range(T):
        if resets[t]:
            prev = -1
        if prev == -1:
            best_k = 0
            best_val = sq[t, 0]
            for k in range(1, K):
                if sq[t, k] < best_val:
                    best_val = sq[t, k]
                    best_k = k
        else:
            best_k = 0
            best_val = sq[t, 0] + (lam if prev != 0 else 0.0)
            for k in range(1, K):
                val = sq[t, k] + (lam if prev != k else 0.0)
                if val < best_val:
                    best_val = val
                    best_k = k
        states[t] = best_k
        prev = best_k
    return states


class JumpModel3State(RegimeModel):
    name = "J1_jump_model"
    is_stochastic = True

    def __init__(self, knobs: dict | None = None):
        knobs = dict(knobs or {})
        knobs.setdefault("lambda_penalty", DEFAULT_LAMBDA)
        super().__init__(knobs=knobs)
        self.lam = float(self.knobs["lambda_penalty"])
        # Not a spec knob (n_fitted_knobs stays 1, lambda_penalty only): an
        # optional offset applied to the 10 fixed restart seeds, used only by
        # the refit-seed stability check (spec Section 4.3).
        self.restart_seed_offset = int(self.knobs.get("restart_seed_offset", 0))
        self.feature_mean_: np.ndarray | None = None
        self.feature_std_: np.ndarray | None = None
        self.centroids_: np.ndarray | None = None
        self.state_order_: dict[int, str] | None = None
        self.s2o_ = StateToOdds()
        self.obj_history_: list[float] = []
        self.info: dict = {}

    @property
    def n_fitted_knobs(self) -> int:
        return 1

    def _fit_one_init(self, x: np.ndarray, seed: int):
        rng = np.random.default_rng(seed)
        centroids = _kmeans_pp_init(x, N_STATES, rng)
        obj_hist = []
        states = None
        for _ in range(MAX_ITER):
            sq_cost = _sq_cost(x, centroids)
            states, obj = _dp_assign_numba(sq_cost, self.lam)
            obj_hist.append(float(obj))
            new_centroids = centroids.copy()
            for k in range(N_STATES):
                pts = x[states == k]
                if len(pts) > 0:
                    new_centroids[k] = pts.mean(axis=0)
            if np.allclose(new_centroids, centroids):
                centroids = new_centroids
                break
            centroids = new_centroids
        return centroids, states, obj_hist

    def fit(self, X_train: pd.DataFrame, Y_train: pd.DataFrame) -> "JumpModel3State":
        obs_raw = X_train[OBS_COLS]
        valid = obs_raw.notna().all(axis=1)
        obs_valid = obs_raw[valid].to_numpy()
        if len(obs_valid) < N_STATES * 5:
            raise ValueError("not enough valid rows in X_train to fit a 3-state jump model")

        mean = obs_valid.mean(axis=0)
        std = obs_valid.std(axis=0)
        std = np.where(std > 0, std, 1.0)
        self.feature_mean_, self.feature_std_ = mean, std
        x = (obs_valid - mean) / std

        best = None
        for seed in (s + self.restart_seed_offset for s in RESTART_SEEDS):
            centroids, states, obj_hist = self._fit_one_init(x, seed)
            if best is None or obj_hist[-1] < best[2][-1]:
                best = (centroids, states, obj_hist)
        self.centroids_, train_states, self.obj_history_ = best

        orig_centroids = self.centroids_ * std + mean
        order = np.argsort(orig_centroids[:, 0])
        down_i, chop_i, up_i = int(order[0]), int(order[1]), int(order[2])
        self.state_order_ = {down_i: "regime_p_down", chop_i: "regime_p_chop", up_i: "regime_p_up"}

        self.info["state_mean_ret20"] = {self.state_order_[k]: float(orig_centroids[k, 0]) for k in range(N_STATES)}
        self.info["state_mean_rvol20"] = {self.state_order_[k]: float(orig_centroids[k, 1]) for k in range(N_STATES)}
        self.info["n_estimated_params"] = N_STATES * 2 + 1  # 3 centroids in 2D + lambda
        self.info["final_train_objective"] = self.obj_history_[-1]

        idx_train = obs_raw.index[valid]
        probs_df = pd.DataFrame(0.0, index=idx_train, columns=STATE_COLS)
        for k in range(N_STATES):
            probs_df.loc[train_states == k, self.state_order_[k]] = 1.0

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

        T = len(X)
        valid_idx, resets = _resets_from_valid(valid)
        states = np.full(T, -1, dtype=np.int64)
        if len(valid_idx):
            sq_valid = _sq_cost(x_std[valid_idx], self.centroids_)
            states[valid_idx] = _online_assign_numba(sq_valid, self.lam, resets)

        probs_df = pd.DataFrame(0.0, index=X.index, columns=STATE_COLS)
        for k in range(N_STATES):
            probs_df.loc[states == k, self.state_order_[k]] = 1.0
        probs_df.loc[states == -1, :] = np.nan
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
