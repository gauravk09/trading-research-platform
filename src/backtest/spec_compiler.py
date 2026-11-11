"""spec_compiler.py — turn a strategy JSON (strategies/_spec format) into a Python strategy file.

    PYTHONPATH=src python -m backtest.spec_compiler strategies/_spec/examples/dan_zanger_breakout.json

writes strategies/<id>/spec.json (a copy) and strategies/<id>/strategy.py, the
file spec_backtest.py runs. The generated file only calls backtest.spec_functions.

Rules the compiler enforces (it stops with SpecError rather than guess):
  - the JSON passes strategies/_spec/strategy.schema.json
  - every expr uses only the README vocabulary; no negative lags (no future bars)
  - deliv_x20 (published after the close) only in conditions marked known_at next_open
  - in stops and exits, any side of a comparison that mentions `entry` or a named
    level is FROZEN at entry (evaluated once on the signal bar); the other side is
    re-read every bar. So "close < pivot" means "below the breakout pivot", not
    below a pivot that keeps moving.
"""

import argparse
import ast
import json
import os
import pprint
import shutil

import jsonschema

from data_collection.paths import ROOT_DIR

SCHEMA_PATH = os.path.join(ROOT_DIR, "strategies", "_spec", "strategy.schema.json")
STRATEGIES_DIR = os.path.join(ROOT_DIR, "strategies")

BAR_FIELDS = {"open", "high", "low", "close", "volume"}
FEATURES = {"rs", "ti65", "ret7", "ret21", "ret30", "bounce_low21", "pct_52wh", "pct_52wl",
            "days_since_52wh", "eff_ratio", "adr20", "tightness", "rvol50", "volc5_50",
            "turn_decile", "dist_50dma", "trend_age", "consol_days", "days_since_burst",
            "burst_success", "sector_rs", "trend_template", "updown_vol50", "pocket_pivot",
            "rsline_pct52wh", "deliv_x20"}
NEXT_OPEN_FEATURES = {"deliv_x20"}
MARKET = {"pct40ma", "pct20ma", "net4", "ratio10", "net25q", "ti65_nifty50", "ti65_nifty500"}
CALENDAR = {"month", "dow", "dom"}
BAR_FUNCTIONS = {"range_pos", "gap_pct"}                       # no arguments
SERIES_FUNCTIONS = {"sma": "sma", "ema": "ema", "max": "rolling_max", "min": "rolling_min",
                    "avg": "rolling_mean", "ret": "ret"}       # (x, n)
WINDOW_FUNCTIONS = {"atr", "adr", "turnover_cr"}               # (n)
COMPARE_OPS = {ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<=", ast.Eq: "=="}
MATH_OPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
SUPPORTED_CLOCKS = {"next_open", "signal_close", "signal_close_strong"}


class SpecError(ValueError):
    pass


class _Translator:
    """Python-syntax expression -> pandas code string over spec_functions (alias F)."""

    def __init__(self, where, levels, allow_entry):
        self.where = where
        self.levels = levels
        self.allow_entry = allow_entry
        self.frozen = False          # mentions entry or a named level
        self.features = set()

    def run(self, expr):
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as exc:
            raise SpecError(f"{self.where}: cannot parse {expr!r} ({exc.msg})") from exc
        return self.node(tree.body)

    def fail(self, message):
        raise SpecError(f"{self.where}: {message}")

    def node(self, n):
        if isinstance(n, ast.BoolOp):
            joiner = " & " if isinstance(n.op, ast.And) else " | "
            return "(" + joiner.join(self.node(v) for v in n.values) + ")"
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            return f"(~{self.node(n.operand)})"
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return f"(-{self.node(n.operand)})"
        if isinstance(n, ast.BinOp) and type(n.op) in MATH_OPS:
            return f"({self.node(n.left)} {MATH_OPS[type(n.op)]} {self.node(n.right)})"
        if isinstance(n, ast.Compare):
            return self.compare(n)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return repr(n.value)
        if isinstance(n, ast.Name):
            return self.name(n.id)
        if isinstance(n, ast.Attribute):
            return self.attribute(n)
        if isinstance(n, ast.Call):
            return self.call(n)
        if isinstance(n, ast.Subscript):
            return self.lag(n)
        self.fail(f"unsupported syntax: {ast.unparse(n)!r}")

    def compare(self, n):
        parts, left = [], n.left
        for op, right in zip(n.ops, n.comparators):
            if type(op) not in COMPARE_OPS:
                self.fail(f"unsupported comparison in {ast.unparse(n)!r}")
            parts.append(f"({self.node(left)} {COMPARE_OPS[type(op)]} {self.node(right)})")
            left = right
        return parts[0] if len(parts) == 1 else "(" + " & ".join(parts) + ")"

    def name(self, name):
        if name in BAR_FIELDS:
            return f'd["{name}"]'
        if name in self.levels:
            self.frozen = True
            return f'lv["{name}"]'
        if name == "entry":
            if not self.allow_entry:
                self.fail("`entry` is only allowed in stops and exits")
            self.frozen = True
            return "entry"
        if name in FEATURES:
            self.features.add(name)
            return f'F.feature(d, "{name}")'
        if name in CALENDAR:
            return f'F.calendar(d, "{name}")'
        if name in BAR_FUNCTIONS:
            return f"F.{name}(d)"
        if name in ("market", "fin"):
            self.fail(f"use {name}.<column>, e.g. market.pct40ma")
        self.fail(f"unknown identifier {name!r} - not in the strategies/_spec vocabulary "
                  f"(declare it in good_to_have.new_features_needed and build it first)")

    def attribute(self, n):
        if not isinstance(n.value, ast.Name):
            self.fail(f"unsupported attribute {ast.unparse(n)!r}")
        if n.value.id == "market" and n.attr in MARKET:
            return f'F.market(d, "{n.attr}")'
        if n.value.id == "fin":
            self.fail(f"fin.{n.attr}: fundamentals are reserved; the point-in-time join is not built yet")
        self.fail(f"unknown identifier {ast.unparse(n)!r}")

    def call(self, n):
        if not isinstance(n.func, ast.Name) or n.keywords:
            self.fail(f"unsupported call {ast.unparse(n)!r}")
        name, args = n.func.id, n.args
        if name in SERIES_FUNCTIONS:
            if len(args) != 2:
                self.fail(f"{name}(x, n) takes 2 arguments: {ast.unparse(n)!r}")
            return f"F.{SERIES_FUNCTIONS[name]}({self.node(args[0])}, {self.window(args[1], n)})"
        if name in WINDOW_FUNCTIONS:
            if len(args) != 1:
                self.fail(f"{name}(n) takes 1 argument: {ast.unparse(n)!r}")
            return f"F.{name}(d, {self.window(args[0], n)})"
        if name in BAR_FUNCTIONS and not args:
            return f"F.{name}(d)"
        if name == "bars_since" and len(args) == 1:
            return f"F.bars_since({self.node(args[0])})"
        if name == "yoy":
            self.fail("yoy() is reserved; the fundamentals join is not built yet")
        self.fail(f"unknown function {name!r} in {ast.unparse(n)!r}")

    def window(self, arg, call):
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, int) and arg.value > 0):
            self.fail(f"window must be a positive whole number in {ast.unparse(call)!r}")
        return str(arg.value)

    def lag(self, n):
        index = n.slice
        if isinstance(index, ast.UnaryOp) and isinstance(index.op, ast.USub):
            self.fail(f"negative lag looks into the future: {ast.unparse(n)!r}")
        if not (isinstance(index, ast.Constant) and isinstance(index.value, int) and index.value >= 0):
            self.fail(f"lag must be a whole number >= 0: {ast.unparse(n)!r}")
        return f"F.lag({self.node(n.value)}, {index.value})"


def load_spec(path):
    with open(path) as f:
        spec = json.load(f)
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)
    problems = [f"{'/'.join(map(str, e.path)) or '(top)'}: {e.message}"
                for e in jsonschema.Draft202012Validator(schema).iter_errors(spec)]
    if problems:
        raise SpecError("spec does not match strategy.schema.json:\n  " + "\n  ".join(problems))
    return spec


def compile_spec(spec, spec_path):
    """Return the source code of the strategy module for a validated spec."""
    source, house = spec["must_have"]["from_source"], spec["must_have"]["from_house"]
    good = spec["good_to_have"]
    levels = source["entry"].get("levels", {})
    features, not_applied = set(), _not_applied(spec)

    level_lines = []
    for name, expr in levels.items():
        if name in BAR_FIELDS | FEATURES | CALENDAR | BAR_FUNCTIONS | {"entry", "market", "fin"}:
            raise SpecError(f"entry.levels: {name!r} clashes with a vocabulary name")
        t = _Translator(f"level {name}", set(levels) - {name}, allow_entry=False)
        level_lines.append(f'    lv["{name}"] = {t.run(expr)}')
        features |= t.features

    conditions = _universe_conditions(house["universe"])
    groups = [("setup", source["entry"]["setup_conditions"]), ("trigger", [source["entry"]["trigger"]]),
              ("selection", good.get("stock_selection", [])), ("market", good.get("market_filter", []))]
    next_open_only = False
    for group, items in groups:
        for c in items:
            t = _Translator(f"{group} condition {c['id']}", set(levels), allow_entry=False)
            conditions.append((f"{group}:{c['id']}", t.run(c["expr"])))
            features |= t.features
            if t.features & NEXT_OPEN_FEATURES:
                if c["known_at"] != "next_open":
                    raise SpecError(f"{group} condition {c['id']}: deliv_x20 is published after the "
                                    f"close; mark known_at next_open")
                next_open_only = True

    stop_code = _stop_code(source["stop_loss"], levels)
    rules = _exit_rules(source["exits"], good, levels)
    clocks = house["entry_clocks_tested"]
    unsupported = [c for c in clocks if c not in SUPPORTED_CLOCKS]
    if unsupported:
        not_applied.append(f"entry clocks {unsupported} need intraday bars; not run")

    meta = {
        "SPEC_ID": house["id"],
        "NAME": source["name"],
        "AUTHOR": source["author"],
        "DIRECTION": source["direction"],
        "ENTRY_CLOCKS": [c for c in clocks if c in SUPPORTED_CLOCKS],
        "COSTS_PCT_PER_SIDE": house["costs_pct_per_side"],
        "DEDUP_BARS": house["dedup_bars"],
        "ERAS": house["eras"],
        "NEXT_OPEN_ONLY": next_open_only,
        "FEATURES_USED": sorted(features),
        "NOT_APPLIED": not_applied,
    }
    return _render(spec_path, meta, level_lines, conditions, stop_code, rules)


def _universe_conditions(universe):
    out = []
    if universe["min_price"] > 0:
        out.append(("universe:min_price", f'(d["close"] >= {universe["min_price"]!r})'))
    if universe["min_turnover_cr"] > 0:
        out.append(("universe:min_turnover_cr", f'(F.turnover_cr(d, 20) >= {universe["min_turnover_cr"]!r})'))
    return out


def _stop_code(stop, levels):
    if stop["type"] == "none":
        return "None"
    t = _Translator("stop_loss", set(levels), allow_entry=True)
    return t.run(stop["expr"])


def _frozen_comparison(where, expr, levels):
    """Split `live <op> frozen` into its parts; return a rule dict fragment."""
    tree = ast.parse(expr, mode="eval").body
    if not (isinstance(tree, ast.Compare) and len(tree.ops) == 1 and type(tree.ops[0]) in COMPARE_OPS):
        raise SpecError(f"{where}: an exit that uses `entry` or a level must be ONE comparison, "
                        f"e.g. 'close < pivot' (got {expr!r})")
    sides = []
    for node in (tree.left, tree.comparators[0]):
        t = _Translator(where, set(levels), allow_entry=True)
        sides.append((t.run(ast.unparse(node)), t.frozen, ast.unparse(node)))
    (left, left_frozen, left_text), (right, right_frozen, right_text) = sides
    op = COMPARE_OPS[type(tree.ops[0])]
    if left_frozen == right_frozen:
        raise SpecError(f"{where}: exactly one side of {expr!r} must mention entry or a level")
    if left_frozen:
        flipped = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "==": "=="}
        left, right, left_text, op = right, left, right_text, flipped[op]
    touch = (left_text == "high" and op in (">", ">=")) or (left_text == "low" and op in ("<", "<="))
    return {"kind": "touch_level" if touch else "close_level", "live": left, "op": op, "level": right}


def _exit_rules(exits, good, levels):
    rules = []
    for i, e in enumerate(exits, start=1):
        where = f"exit {i} ({e['type']})"
        rule = {"id": f"exit_{i}:{e['type']}", "type": e["type"], "fraction": 1.0}
        if e["type"] in ("trail_pct", "target_pct", "target_r", "time"):
            if "value" not in e:
                raise SpecError(f"{where}: needs `value` (%, R or bars)")
            rule.update(kind=e["type"], value=e["value"])
        else:
            if "expr" not in e:
                raise SpecError(f"{where}: needs `expr`")
            probe = _Translator(where, set(levels), allow_entry=True)
            code = probe.run(e["expr"])
            if probe.frozen:
                rule.update(_frozen_comparison(where, e["expr"], levels))
            else:
                rule.update(kind="close_bool", when=code)
        rules.append(rule)

    for i, p in enumerate(good.get("partial_exits", []), start=1):
        where = f"partial exit {i}"
        rule = {"id": f"partial_{i}", "type": "partial", "fraction": p["fraction"]}
        rule.update(_frozen_comparison(where, p["at_expr"], levels))
        rules.append(rule)

    has_time_exit = any(r["type"] == "time" for r in rules)
    if "max_hold_bars" in good and not has_time_exit:
        rules.append({"id": "max_hold_bars", "type": "time", "kind": "time",
                      "value": good["max_hold_bars"]["value"], "fraction": 1.0})
    return rules


def _not_applied(spec):
    house, good = spec["must_have"]["from_house"], spec["good_to_have"]
    timing = spec["must_have"]["from_source"]["entry"]["timing"]
    notes = []
    if house["universe"]["base"] != "nse_eq_all":
        notes.append(f"universe base {house['universe']['base']!r} not applied; all symbols in --data are tested")
    if house["universe"].get("exclude_surveillance", True):
        notes.append("ASM/GSM exclusion not applied: there is no surveillance history")
    if timing not in house["entry_clocks_tested"]:
        notes.append(f"source entry timing {timing!r} is not one of the tested clocks")
    if "chase_limit_pct" in good:
        notes.append("chase_limit_pct not applied (no generic reference level)")
    if good.get("pyramiding"):
        notes.append("pyramiding not modelled")
    if good.get("variants"):
        notes.append("variants are not run: write each variant as its own spec file")
    notes.append(f"control: report uses an equal-weight universe market leg, not the "
                 f"{house['control_type']!r} control canonical_runner requires")
    notes.append("success bars are judged by a human against this report: " + json.dumps(house["success_bars"]))
    return notes


def _render(spec_path, meta, level_lines, conditions, stop_code, rules):
    rel_spec = os.path.relpath(spec_path, ROOT_DIR)
    lines = [
        f'"""GENERATED by backtest.spec_compiler from {rel_spec}.',
        "Do not edit by hand: change the JSON and regenerate.",
        "",
        f"{meta['NAME']} ({meta['AUTHOR']})",
        '"""',
        "",
        "from backtest import spec_functions as F",
        "",
    ]
    for key, value in meta.items():
        lines.append(f"{key} = {pprint.pformat(value, width=100, sort_dicts=False)}")
    lines += ["", "", "def levels(d):", '    """Named price levels, re-computed every bar."""', "    lv = {}"]
    lines += level_lines + ["    return lv", "", ""]
    lines += ["def entry_conditions(d):",
              '    """Each condition as a True/False frame on the signal bar; the signal is ALL of them."""',
              "    lv = levels(d)", "    return {"]
    lines += [f'        "{cid}": {code},' for cid, code in conditions]
    lines += ["    }", "", ""]
    lines += ["def stop_price(d, entry):",
              '    """Stop level, frozen at entry and aligned to the signal bar. `entry` = fill-price frame."""',
              "    lv = levels(d)", f"    return {stop_code}", "", ""]
    lines += ["def exit_rules(d, entry):",
              '    """Exits in priority order. Levels are frozen at entry; live values are read every bar."""',
              "    lv = levels(d)", "    return ["]
    for r in rules:
        parts = [f'"{k}": {v}' if k in ("live", "level", "when") else f'"{k}": {v!r}' for k, v in r.items()]
        lines.append("        {" + ", ".join(parts) + "},")
    lines += ["    ]", ""]
    return "\n".join(lines)


def write_strategy(spec_path, out_dir=None):
    """Validate + compile a spec; write <out_dir>/spec.json and strategy.py. Return the .py path."""
    spec = load_spec(spec_path)
    out_dir = out_dir or os.path.join(STRATEGIES_DIR, spec["must_have"]["from_house"]["id"])
    os.makedirs(out_dir, exist_ok=True)
    spec_copy = os.path.join(out_dir, "spec.json")
    if os.path.abspath(spec_path) != os.path.abspath(spec_copy):
        shutil.copyfile(spec_path, spec_copy)
    code = compile_spec(spec, spec_copy)
    compile(code, "strategy.py", "exec")          # fail here, not at backtest time
    py_path = os.path.join(out_dir, "strategy.py")
    with open(py_path, "w") as f:
        f.write(code)
    return py_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compile a strategy JSON into strategies/<id>/strategy.py")
    ap.add_argument("spec", help="path to the strategy JSON")
    ap.add_argument("--out-dir", help="default: strategies/<id>/")
    a = ap.parse_args(argv)
    try:
        print("wrote", write_strategy(a.spec, a.out_dir))
    except SpecError as exc:
        raise SystemExit(f"cannot compile: {exc}")


if __name__ == "__main__":
    main()
