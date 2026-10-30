"""Deterministic, append-only paper broker for the lone-loser short signal."""
import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from glob import glob

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STRATEGY = "lone_loser_short"
SOURCE_BLOCK = "b5_short_green_tape"
EVENTS_FILE = "events.jsonl"
TRADES_FILE = "trades.csv"


def _event_id(trade_id, event, date):
    return hashlib.sha256(f"{trade_id}|{event}|{date}".encode("utf-8")).hexdigest()[:20]


def _date(value):
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else str(parsed.date())


def _number(value):
    return value is not None and not pd.isna(value)


def _normalized_bars(frame):
    """Normalize OHLCV and retain one deterministic row per session."""
    needed = {"date", "open", "high", "close"}
    if frame is None or frame.empty or not needed.issubset(frame.columns):
        return None
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result = result.dropna(subset=["date"]).sort_values("date")
    return result.drop_duplicates("date", keep="last").reset_index(drop=True)


def _unique_events(events):
    unique, seen = [], set()
    for event in events:
        if event["event_id"] not in seen:
            unique.append(event)
            seen.add(event["event_id"])
    return unique


def replay(states, bars):
    """Replay b5 candidates against daily bars without making broker calls."""
    events = []
    for state in states:
        signal_date = _date(state.get("meta", {}).get("data_date", state.get("data_date")))
        strategy = (state.get("incubation", {}).get("strategies", {}) or {}).get(SOURCE_BLOCK, {})
        if not signal_date or not strategy.get("gates_pass"):
            continue
        for candidate in strategy.get("candidates", []) or []:
            symbol = str(candidate.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            trade_id = f"{STRATEGY}:{signal_date}:{symbol}"

            def emit(event, date, **fields):
                day = _date(date) or str(date)
                events.append({"event_id": _event_id(trade_id, event, day), "trade_id": trade_id,
                               "event": event, "date": day, "symbol": symbol, **fields})

            # Intent is recorded even if data subsequently proves incomplete.
            emit("signal_intent", signal_date, signal_close=candidate.get("close"))
            frame = _normalized_bars(bars.get(symbol))
            if frame is None:
                emit("unresolved", signal_date, reason="missing bars")
                continue
            signal_rows = frame.loc[frame["date"] == signal_date]
            if signal_rows.empty:
                emit("unresolved", signal_date, reason="missing signal-day data")
                continue
            signal_high = signal_rows.iloc[-1]["high"]
            if not _number(signal_high):
                emit("unresolved", signal_date, reason="missing signal-day high")
                continue
            sessions = frame.loc[frame["date"] > signal_date].head(5)
            if len(sessions) < 5:
                emit("unresolved", signal_date, reason="fewer than five post-signal bars")
                continue
            entry_row = sessions.iloc[0]
            if not _number(entry_row["open"]):
                emit("unresolved", entry_row["date"], reason="missing D+1 open")
                continue
            entry_price = float(entry_row["open"])
            stop = min(float(signal_high), entry_price * 1.06)
            emit("d1_open_fill", entry_row["date"], price=entry_price, stop=stop)

            for _, row in sessions.iterrows():
                session = row["date"]
                if not _number(row["open"]):
                    emit("unresolved", session, reason="missing session open")
                    break
                # Conservative short fill: a gap receives the opening price;
                # an intraday touch fills at the stop.
                if float(row["open"]) >= stop:
                    emit("stop_fill", session, price=float(row["open"]), reason="stop_gap")
                    break
                if not _number(row["high"]):
                    emit("unresolved", session, reason="missing session high")
                    break
                if float(row["high"]) >= stop:
                    emit("stop_fill", session, price=stop, reason="stop")
                    break
                if not _number(row["close"]):
                    emit("unresolved", session, reason="missing session close")
                    break
                emit("daily_mtm", session, price=float(row["close"]))
            else:
                final_session = sessions.iloc[-1]
                emit("d5_time_exit", final_session["date"], price=float(final_session["close"]), reason="time_exit")
    return _unique_events(events)


def derive_trades(events, cost_bps=5.0):
    """Build completed summaries from the entire journal; events remain cost-free."""
    cost_bps = float(cost_bps)
    by_trade = {}
    for event in _unique_events(events):
        by_trade.setdefault(event["trade_id"], []).append(event)
    trades = []
    for trade_id in sorted(by_trade):
        rows = by_trade[trade_id]
        entry = next((row for row in rows if row["event"] == "d1_open_fill"), None)
        exit_ = next((row for row in rows if row["event"] in {"stop_fill", "d5_time_exit"}), None)
        if entry is None or exit_ is None:
            continue
        gross = (float(entry["price"]) - float(exit_["price"])) / float(entry["price"])
        trades.append({"trade_id": trade_id, "symbol": entry["symbol"],
                       "entry_date": entry["date"], "entry": float(entry["price"]),
                       "exit_date": exit_["date"], "exit": float(exit_["price"]),
                       "reason": exit_["reason"], "gross_return": gross,
                       "net_return": gross - (2 * cost_bps / 10000),
                       "cost_bps_per_side": cost_bps})
    return trades


def _read_journal(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_outputs(events, out_dir, cost_bps=5.0):
    """Append unseen events and rebuild the derived CSV from the full journal."""
    os.makedirs(out_dir, exist_ok=True)
    journal_path = os.path.join(out_dir, EVENTS_FILE)
    existing = _read_journal(journal_path)
    seen = {event["event_id"] for event in existing}
    additions = [event for event in _unique_events(events) if event["event_id"] not in seen]
    if additions:
        with open(journal_path, "a", encoding="utf-8") as handle:
            for event in additions:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
    journal = _unique_events(_read_journal(journal_path))
    trades = derive_trades(journal, cost_bps)
    fields = ["trade_id", "symbol", "entry_date", "entry", "exit_date", "exit", "reason", "gross_return", "net_return", "cost_bps_per_side"]
    with open(os.path.join(out_dir, TRADES_FILE), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(trades)
    return journal, trades


def load_states(states_dir):
    """Load dated state files only: latest.json is a duplicate convenience copy."""
    states = []
    for path in sorted(glob(os.path.join(states_dir, "????-??-??.json"))):
        with open(path, encoding="utf-8") as handle:
            states.append(json.load(handle))
    return states


def load_bars(bars_dir):
    return {os.path.splitext(os.path.basename(path))[0].upper(): pd.read_parquet(path)
            for path in glob(os.path.join(bars_dir, "*.parquet"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay lone-loser short paper signals from local data.")
    parser.add_argument("--states-dir", default=os.path.join(ROOT, "output", "state"))
    parser.add_argument("--bars-dir", default=os.path.join(ROOT, "data", "parquet", "daily"))
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "output", "paper_broker"))
    parser.add_argument("--cost-bps", type=float, default=5.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Read and report only (the default).")
    mode.add_argument("--write", action="store_true", help="Append events and rebuild trades.csv.")
    args = parser.parse_args(argv)
    states, bars = load_states(args.states_dir), load_bars(args.bars_dir)
    events = replay(states, bars)
    trades = derive_trades(events, args.cost_bps)
    status = {"states": len(states), "bars": len(bars), "events": len(events), "trades": len(trades),
              "event_counts": dict(sorted(Counter(event["event"] for event in events).items())),
              "mode": "write" if args.write else "dry-run"}
    if args.write:
        journal, journal_trades = write_outputs(events, args.out_dir, args.cost_bps)
        status.update({"journal_events": len(journal), "journal_trades": len(journal_trades)})
    print(json.dumps(status, sort_keys=True))
    return status


if __name__ == "__main__":
    main()
