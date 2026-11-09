# indicators

Reusable calculations on price and volume series. **Pure functions only: no file or network access.**
Data comes in as pandas objects, a number or Series comes out. Callers load the data
(`data_collection.storage`, `preprocessing`) and pass it in.

| Module | Functions |
|---|---|
| `returns.py` | `n_day_return`, `month_return`, `rolling_return`, `cumulative_return` |
| `moving_averages.py` | `sma`, `ema`, `sma_series`, `ema_series`, `is_above_ma`, `is_surfing_ma`, `ma_slope` |
| `volatility.py` | `adr`, `adr_value`, `atr`, `atr_series`, `max_stop_distance` |
| `volume.py` | `avg_volume`, `volume_ratio`, `avg_turnover_cr`, `is_volume_surge` |
| `relative_strength.py` | `rs_rank`, `composite_rs_rank`, `residual_rs_rank` (needs a sector map passed in), `top_n_by_rs` |
| `trend_stage.py` | `trend_age`, `base_count`, `base_pivots`, `maturity_label` |
| `factor_model.py` | `absorption_ratio`, `absorption_series`, `n_significant_factors`, `marchenko_pastur_max`, `residual_momentum` |

Two traps to keep in mind when adding one: a value for day *t* must use only data up to the close of day *t*
(no look-ahead), and a series shorter than its window should return NaN, not a number.
