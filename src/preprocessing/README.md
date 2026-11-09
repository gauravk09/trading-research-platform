# preprocessing

Turns collected data (`data_collection/`) into the derived datasets that indicators, scans and the dashboard read.
Nothing here fetches from outside; it only reads `data/` and writes `data/processed/`.

| Module | Builds | Writes to |
|---|---|---|
| `precompute.py` | Per-stock summary table and the close/high/low/volume matrices | `data/processed/universe_summary.parquet`, `*_matrix.parquet` |
| `mm_history.py` | Full-history Market Monitor (breadth counts, ratios, index features) | `data/processed/mm_history.parquet` |
| `market_rhythm.py` | Leader-spread and winner-attribution series | `data/processed/market_rhythm.parquet` |
| `build_sector_map.py` | Symbol to industry map (run when the universe changes) | `data/processed/sector_map.csv` |
| `build_vol_curve.py` | Intraday cumulative-volume curve (needs Kite) | `data/processed/intraday_vol_curve.json` |
| `commodities/basis.py` | Converts a global USD price into an MCX-equivalent series | in memory |
| `commodities/research.py` | The commodity series to build strategies on | in memory |

Run as a module from the repo root, for example:

```bash
PYTHONPATH=src python -m preprocessing.precompute
```

`precompute` runs as step 5 of the nightly job (`data_collection/run_daily.py`).
