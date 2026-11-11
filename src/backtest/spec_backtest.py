"""spec_backtest.py — backtest one generated strategy file over every stock, write an Excel report.

    PYTHONPATH=src python -m backtest.spec_backtest strategies/dan_zanger_breakout/strategy.py
    PYTHONPATH=src python -m backtest.spec_backtest strategies/_spec/examples/dan_zanger_breakout.json   # compiles first

Data: the repo's per-stock parquet files (data/parquet/daily/<SYMBOL>.parquet,
long format date|symbol|open|high|low|close|volume), read with DuckDB in
batches of stocks so memory stays small. Adapted from multi_stock_backtest.py.

Each entry clock listed in the strategy (ENTRY_CLOCKS) is run separately. Before
any trade is simulated, the signals of the first batch are recomputed on
truncated history; if a past signal changes, the strategy reads the future and
the run stops.

Output: output/spec_backtests/<id>/<timestamp>/report.xlsx (see spec_report.py).
"""

import argparse
import importlib.util
import os
import subprocess
import time
from datetime import date, datetime

import duckdb
import numpy as np
import pandas as pd

from backtest import spec_functions as F
from backtest.spec_report import write_report
from backtest.spec_simulator import simulate_stock
from data_collection.paths import ROOT_DIR

DEFAULT_DATA = os.path.join(ROOT_DIR, "data", "parquet", "daily", "*.parquet")
DEFAULT_FEATURES = os.path.join(ROOT_DIR, "data", "processed", "features")
DEFAULT_MARKET = os.path.join(ROOT_DIR, "data", "processed", "mm_history.parquet")
DEFAULT_OUT = os.path.join(ROOT_DIR, "output", "spec_backtests")
STRONG_CLOSE = 0.75        # FACTORY lever 1: signal-day close in the top quarter of the range


class LookAheadError(RuntimeError):
    pass


# ── data ──────────────────────────────────────────────────────────────────────

def connect():
    con = duckdb.connect()
    con.execute("SET memory_limit='4GB'")
    # Stored dates are midnight IST. Without this, a machine on UTC casts every
    # date to the previous day.
    con.execute("SET TimeZone='Asia/Kolkata'")
    return con


def reader(path):
    path = path.replace("'", "''")
    return f"read_csv_auto('{path}')" if path.lower().endswith(".csv") else f"read_parquet('{path}', union_by_name=true)"


def list_symbols(con, src, start, end, min_rows):
    q = f"""SELECT symbol FROM {src}
            WHERE CAST(date AS DATE) BETWEEN '{start}' AND '{end}'
            GROUP BY symbol HAVING count(*) >= {min_rows} ORDER BY symbol"""
    return [r[0] for r in con.execute(q).fetchall()]


def load_batch(con, src, symbols, start, end, features_dir, market):
    sym_list = ",".join("'" + s.replace("'", "''") + "'" for s in symbols)
    q = f"""SELECT CAST(date AS DATE) AS date, symbol,
                   CAST(open AS DOUBLE) AS open, CAST(high AS DOUBLE) AS high, CAST(low AS DOUBLE) AS low,
                   CAST(close AS DOUBLE) AS close, CAST(volume AS DOUBLE) AS volume
            FROM {src}
            WHERE symbol IN ({sym_list}) AND CAST(date AS DATE) BETWEEN '{start}' AND '{end}'"""
    df = con.execute(q).df()
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(["date", "symbol"], keep="last")
    d = {k: df.pivot(index="date", columns="symbol", values=k).sort_index()
         for k in ("open", "high", "low", "close", "volume")}
    d["features_dir"] = features_dir
    d["market"] = market
    return d


def market_index(con, src, start, end):
    """Equal-weight index of every stock in the data (the market leg of the report)."""
    q = f"""WITH px AS (SELECT CAST(date AS DATE) AS d, symbol, CAST(close AS DOUBLE) AS c
                        FROM {src} WHERE CAST(date AS DATE) BETWEEN '{start}' AND '{end}'),
                 r AS (SELECT d, c / lag(c) OVER (PARTITION BY symbol ORDER BY d) - 1 AS r FROM px)
            SELECT d, avg(r) AS r FROM r WHERE r IS NOT NULL AND abs(r) < 0.5 GROUP BY d ORDER BY d"""
    daily = con.execute(q).df()
    return pd.Series((1 + daily["r"]).cumprod().values, index=pd.to_datetime(daily["d"]))


def load_market(path):
    return pd.read_parquet(path) if os.path.exists(path) else None


# ── strategy ──────────────────────────────────────────────────────────────────

def load_strategy(path):
    """Import a strategy file; compile it first when given a spec JSON."""
    if path.endswith(".json"):
        from backtest.spec_compiler import write_strategy
        path = write_strategy(path)
    spec = importlib.util.spec_from_file_location("generated_strategy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SOURCE_PATH = path
    return module


def signal_frame(module, d):
    """(signal, per-condition frames): the signal is the AND of every entry condition."""
    conditions = {k: v.fillna(False).astype(bool) for k, v in module.entry_conditions(d).items()}
    signal = None
    for frame in conditions.values():
        signal = frame if signal is None else signal & frame
    return signal, conditions


def check_lookahead(module, d, cuts=(0.5, 0.75, 0.9)):
    """Recompute every condition on truncated history; past values must not change."""
    _, full = signal_frame(module, d)
    n = len(d["close"])
    leaks = set()
    for share in cuts:
        cut = int(n * share)
        if cut < 2:
            continue
        short = dict(d)
        for k in ("open", "high", "low", "close", "volume"):
            short[k] = d[k].iloc[:cut]
        _, truncated = signal_frame(module, short)
        for cid, frame in truncated.items():
            if not frame.equals(full[cid].iloc[:cut]):
                leaks.add(cid)
    if leaks:
        raise LookAheadError(f"conditions change when future bars are removed: {sorted(leaks)}")
    return f"passed ({len(cuts)} truncation points, {d['close'].shape[1]} stocks)"


def run_batch(module, d, clock):
    signal, conditions = signal_frame(module, d)
    if clock == "signal_close_strong":
        signal = signal & (F.range_pos(d) >= STRONG_CLOSE)
    # Fill price frame, aligned to the SIGNAL bar. For next_open this is
    # tomorrow's open: used only to set stop/target levels at fill time,
    # never inside a signal.
    fill = d["close"] if clock in ("signal_close", "signal_close_strong") else d["open"].shift(-1)
    stop = module.stop_price(d, fill)
    rules = module.exit_rules(d, fill)

    dates = d["close"].index
    trades, skipped = [], 0
    for symbol in d["close"].columns:
        bars = {k: d[k][symbol].to_numpy(dtype=float) for k in ("open", "high", "low", "close")}
        stock_rules = [_rule_for(r, symbol) for r in rules]
        stock_stop = stop[symbol].to_numpy(dtype=float) if stop is not None else None
        t, sk = simulate_stock(symbol, dates, bars, signal[symbol].to_numpy(), stock_stop, stock_rules,
                               clock, module.DIRECTION, module.COSTS_PCT_PER_SIDE, module.DEDUP_BARS)
        trades += t
        skipped += sk
    counts = {cid: int(frame.values.sum()) for cid, frame in conditions.items()}
    counts["(all conditions)"] = int(signal.values.sum())
    return trades, skipped, counts


def _rule_for(rule, symbol):
    out = dict(rule)
    for key in ("live", "level", "when"):
        if key in out:
            out[key] = out[key][symbol].to_numpy()
    return out


# ── reporting helpers ────────────────────────────────────────────────────────

def add_market_leg(trades, index):
    """mkt_ret = equal-weight universe return entry->exit; pnl = trade's excess over it, side-signed."""
    if trades.empty:
        return trades
    entry_level = index.reindex(trades["entry"]).values
    exit_level = index.reindex(trades["exit"]).values
    trades["mkt_ret"] = exit_level / entry_level - 1
    long = trades["side"] == "LONG"
    trades["pnl"] = np.where(long, trades["raw_ret"] - trades["mkt_ret"], trades["raw_ret"] + trades["mkt_ret"])
    return trades


def add_era(trades, eras):
    def era_of(day):
        for name, span in eras.items():
            start, end = span.split("/")
            if pd.Timestamp(start) <= day <= pd.Timestamp(end):
                return name
        return "outside_eras"
    if not trades.empty:
        trades["era"] = trades["entry"].map(era_of)
    return trades


def git_sha():
    try:
        return subprocess.check_output(["git", "-C", ROOT_DIR, "rev-parse", "--short", "HEAD"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


# ── main ─────────────────────────────────────────────────────────────────────

def run(strategy_path, data=DEFAULT_DATA, features_dir=DEFAULT_FEATURES, market_path=DEFAULT_MARKET,
        start="2015-01-01", end=None, batch=300, min_rows=250, limit=0, out_root=DEFAULT_OUT, clocks=None):
    end = end or date.today().isoformat()
    module = load_strategy(strategy_path)
    clocks = clocks or list(module.ENTRY_CLOCKS)
    notes = list(module.NOT_APPLIED)
    if module.NEXT_OPEN_ONLY:
        dropped = [c for c in clocks if c != "next_open"]
        clocks = [c for c in clocks if c == "next_open"]
        if dropped:
            notes.append(f"clocks {dropped} skipped: a condition is only known at the next open")
    if not clocks:
        raise SystemExit("no runnable entry clock")

    con = connect()
    src = reader(data)
    symbols = list_symbols(con, src, start, end, min_rows)
    if limit:
        symbols = symbols[:limit]
    if not symbols:
        raise SystemExit(f"no symbols with >= {min_rows} rows in {data} between {start} and {end}")
    market = load_market(market_path)
    print(f"{module.SPEC_ID}: {len(symbols)} stocks, batches of {batch}, clocks {clocks}")

    all_trades, skipped, counts, lookahead, t0 = [], {c: 0 for c in clocks}, {}, None, time.time()
    for i in range(0, len(symbols), batch):
        d = load_batch(con, src, symbols[i:i + batch], start, end, features_dir, market)
        if lookahead is None:
            lookahead = check_lookahead(module, d)
        for clock in clocks:
            trades, sk, batch_counts = run_batch(module, d, clock)
            all_trades += trades
            skipped[clock] += sk
            for cid, k in batch_counts.items():
                counts[(clock, cid)] = counts.get((clock, cid), 0) + k
        print(f"  {min(i + batch, len(symbols))}/{len(symbols)} stocks  ({time.time() - t0:.0f}s)")

    trades = pd.DataFrame(all_trades)
    trades = add_era(add_market_leg(trades, market_index(con, src, start, end)), module.ERAS)

    run_info = {
        "strategy": module.SPEC_ID,
        "name": module.NAME,
        "author": module.AUTHOR,
        "direction": module.DIRECTION,
        "strategy_file": os.path.relpath(module.SOURCE_PATH, ROOT_DIR),
        "data": data,
        "period": f"{start} to {end}",
        "stocks_tested": len(symbols),
        "entry_clocks": ", ".join(clocks),
        "costs_pct_per_side": module.COSTS_PCT_PER_SIDE,
        "dedup_bars": module.DEDUP_BARS,
        "lookahead_check": lookahead,
        "git_sha": git_sha(),
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    spec_json = os.path.join(os.path.dirname(module.SOURCE_PATH), "spec.json")
    out_dir = os.path.join(out_root, module.SPEC_ID, datetime.now().strftime("%Y%m%d-%H%M%S"))
    path = write_report(os.path.join(out_dir, "report.xlsx"), trades, run_info, notes, counts, skipped,
                        module.ERAS, spec_json if os.path.exists(spec_json) else None)
    print(f"{len(trades)} trades -> {path}")
    return path, trades


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backtest a generated strategy file (or a spec JSON) over all stocks")
    ap.add_argument("strategy", help="strategies/<id>/strategy.py, or a spec .json (compiled first)")
    ap.add_argument("--data", default=DEFAULT_DATA, help="parquet/CSV file or glob, long format")
    ap.add_argument("--features-dir", default=DEFAULT_FEATURES)
    ap.add_argument("--market", default=DEFAULT_MARKET, help="mm_history.parquet, for market.* conditions")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=None, help="default: today")
    ap.add_argument("--batch", type=int, default=300, help="stocks per batch (lower if RAM is tight)")
    ap.add_argument("--min-rows", type=int, default=250, help="skip stocks with less history (days)")
    ap.add_argument("--limit", type=int, default=0, help="test only the first N stocks (quick runs)")
    ap.add_argument("--clock", action="append", help="run only this entry clock (repeatable)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    run(a.strategy, a.data, a.features_dir, a.market, a.start, a.end, a.batch, a.min_rows, a.limit, a.out, a.clock)


if __name__ == "__main__":
    main()
