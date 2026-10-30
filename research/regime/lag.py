"""Detection lag (spec Section 4.4): how many trading days after a hindsight
truth-regime change does the model's own label first agree with the new truth?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CAP = 120


def truth_change_points(truth: pd.Series, min_persist: int = 20) -> pd.DataFrame:
    """Dates where truth_regime changes to a new value that then persists for
    at least `min_persist` rows (a "real" regime change, not one noisy day).
    """
    t = truth.dropna()
    vals = t.to_numpy()
    dates = t.index.to_numpy()
    n = len(vals)
    changes = []
    i = 1
    while i < n:
        if vals[i] != vals[i - 1]:
            run_val = vals[i]
            j = i
            while j < n and vals[j] == run_val:
                j += 1
            run_len = j - i
            if run_len >= min_persist:
                changes.append({"date": dates[i], "new_regime": run_val, "run_len": run_len})
            i = j
        else:
            i += 1
    return pd.DataFrame(changes)


def detection_lag(model_labels: pd.Series, truth: pd.Series, min_persist: int = 20, cap: int = CAP) -> pd.DataFrame:
    """For each qualifying truth change point, rows-until model_labels first
    equals the new truth regime (searching forward from the change date,
    capped at `cap` rows; censored if not found within the cap).
    """
    cps = truth_change_points(truth, min_persist=min_persist)
    idx = model_labels.index
    rows = []
    for _, cp in cps.iterrows():
        change_date = cp["date"]
        if change_date not in idx:
            continue
        pos = idx.get_loc(change_date)
        window = model_labels.iloc[pos : pos + cap + 1]
        match = window[window == cp["new_regime"]]
        if len(match) > 0:
            lag = idx.get_loc(match.index[0]) - pos
            censored = False
        else:
            lag = cap
            censored = True
        rows.append({
            "date": change_date, "new_regime": cp["new_regime"],
            "lag": lag, "censored": censored,
        })
    return pd.DataFrame(rows)


def median_lag_by_direction(lag_df: pd.DataFrame, up_value, down_value) -> dict:
    if len(lag_df) == 0:
        return {"median_lag_into_up": np.nan, "median_lag_into_down": np.nan,
                "n_censored": 0, "n_events": 0}
    up = lag_df[lag_df["new_regime"] == up_value]["lag"]
    down = lag_df[lag_df["new_regime"] == down_value]["lag"]
    return {
        "median_lag_into_up": float(up.median()) if len(up) else np.nan,
        "median_lag_into_down": float(down.median()) if len(down) else np.nan,
        "n_censored": int(lag_df["censored"].sum()),
        "n_events": int(len(lag_df)),
    }
