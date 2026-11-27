"""spec_compiler.py — turn strategies/<id>/spec.json into strategies/<id>/strategy.py.

    PYTHONPATH=src python -m backtest.spec_compiler strategies/zanger

Deterministic: the same spec always produces the same file. The generated file
computes nothing of its own. Every name in a spec expression is read through
`col(name)`, which the engine supplies from the price cache (open/high/low/
close/volume) and the central feature store (backtest.features.FEATURE_NAMES).
A spec can use lags (`x[n]`), arithmetic and comparisons, but no functions:
a missing indicator is added to the feature store first.

The compiler stops with SpecError rather than guess:
  - the spec must pass strategies/_spec/schema.json, and its id must equal its folder
  - only bar fields, FEATURE_NAMES and entry.levels names; no negative lags
  - deliv_x20 (published after the close) only in conditions marked known_at next_open
  - exits must map onto the shared menu in backtest/exits.py:
      `close <op> <level>`        close exit at the next open (level frozen at entry)
      `high >= <level>` (long) /  `low <= <level>` (short)   resting touch
      any other True/False expr   signal exit at the next open
      time / target_pct / target_r by `value`
    In stops and exits, a side that mentions `entry` or a level is FROZEN: it is
    read once on the signal bar. So `close < pivot` means below the breakout pivot.
"""

import argparse
import ast
import json
import os
import pprint

import jsonschema

from backtest.features import FEATURE_NAMES, NEXT_OPEN_FEATURES
from data_collection.paths import ROOT_DIR

SCHEMA_PATH = os.path.join(ROOT_DIR, "strategies", "_spec", "schema.json")
BAR_FIELDS = ("open", "high", "low", "close", "volume")
COMPARE_OPS = {ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<=", ast.Eq: "=="}
MATH_OPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
SUPPORTED_CLOCKS = ("next_open", "signal_close", "signal_close_strong")


class SpecError(ValueError):
    pass


class _Translator:
    """Spec expression -> pandas code over col(name), lv[level] and entry."""

    def __init__(self, where, levels, allow_entry):
        self.where = where
        self.levels = levels
        self.allow_entry = allow_entry
        self.frozen = False          # mentions entry or a level
        self.columns = set()

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
        if isinstance(n, ast.Subscript):
            return self.lag(n)
        if isinstance(n, ast.Call):
            self.fail(f"functions are not allowed ({ast.unparse(n)!r}): add the indicator to the "
                      f"feature store (src/backtest/features.py, FEATURE_NAMES) and use its name")
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
        if name in self.levels:
            self.frozen = True
            return f'lv["{name}"]'
        if name == "entry":
            if not self.allow_entry:
                self.fail("`entry` is only allowed in stops and exits")
            self.frozen = True
            return "entry"
        if name in BAR_FIELDS or name in FEATURE_NAMES:
            self.columns.add(name)
            return f'col("{name}")'
        self.fail(f"unknown name {name!r}: not a bar field or a feature-store name "
                  f"(add it to FEATURE_NAMES in src/backtest/features.py first)")

    def lag(self, n):
        index = n.slice
        if isinstance(index, ast.UnaryOp) and isinstance(index.op, ast.USub):
            self.fail(f"negative lag looks into the future: {ast.unparse(n)!r}")
        if not (isinstance(index, ast.Constant) and isinstance(index.value, int) and index.value >= 0):
            self.fail(f"lag must be a whole number >= 0: {ast.unparse(n)!r}")
        return f"{self.node(n.value)}.shift({index.value})"


def load_spec(path):
    """Read and validate strategies/<id>/spec.json (a folder path is accepted)."""
    if os.path.isdir(path):
        path = os.path.join(path, "spec.json")
    with open(path) as f:
        spec = json.load(f)
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)
    problems = [f"{'/'.join(map(str, e.path)) or '(top)'}: {e.message}"
                for e in jsonschema.Draft202012Validator(schema).iter_errors(spec)]
    if problems:
        raise SpecError(f"{path} does not match schema.json:\n  " + "\n  ".join(problems))
    folder = os.path.basename(os.path.dirname(os.path.abspath(path)))
    spec_id = spec["must_have"]["from_house"]["id"]
    if spec_id != folder:
        raise SpecError(f"{path}: id {spec_id!r} must equal its folder name {folder!r}")
    return spec, path


def compile_spec(spec, spec_path):
    """Source code of the strategy module for a validated spec."""
    source, house, good = spec["must_have"]["from_source"], spec["must_have"]["from_house"], spec["good_to_have"]
    direction = source["direction"]
    levels = source["entry"].get("levels", {})
    columns = set()

    level_lines = []
    for name, expr in levels.items():
        if name in BAR_FIELDS or name in FEATURE_NAMES or name == "entry":
            raise SpecError(f"entry.levels: {name!r} clashes with a column name")
        t = _Translator(f"level {name}", set(levels) - {name}, allow_entry=False)
        level_lines.append(f'    lv["{name}"] = {t.run(expr)}')
        columns |= t.columns

    universe = _universe_conditions(house["universe"])
    columns |= {"close"} | ({"turnover20_cr"} if house["universe"]["min_turnover_cr"] > 0 else set())
    conditions, next_open_only = [], False
    groups = [("setup", source["entry"]["setup_conditions"]), ("trigger", [source["entry"]["trigger"]]),
              ("selection", good.get("stock_selection", [])), ("market", good.get("market_filter", []))]
    for group, items in groups:
        for c in items:
            t = _Translator(f"{group} condition {c['id']}", set(levels), allow_entry=False)
            conditions.append((f"{group}:{c['id']}", t.run(c["expr"])))
            columns |= t.columns
            if t.columns & NEXT_OPEN_FEATURES:
                if c["known_at"] != "next_open":
                    raise SpecError(f"{group} condition {c['id']}: {sorted(t.columns & NEXT_OPEN_FEATURES)} "
                                    f"are published after the close; mark known_at next_open")
                next_open_only = True

    stop_code, max_stop_pct, stop_columns = _stop(source["stop_loss"], levels)
    rules, exit_columns = _exit_rules(source["exits"], good, levels, direction)
    columns |= stop_columns | exit_columns
    clocks = [c for c in house["entry_clocks_tested"] if c in SUPPORTED_CLOCKS]
    if "signal_close_strong" in clocks:
        columns.add("range_pos")

    meta = {
        "SPEC_ID": house["id"],
        "SCHEMA_VERSION": spec["schema_version"],
        "NAME": source["name"],
        "DIRECTION": direction,
        "ENTRY_CLOCKS": clocks,
        "COSTS_PCT_PER_SIDE": house["costs_pct_per_side"],
        "DEDUP_BARS": house["dedup_bars"],
        "MAX_STOP_PCT": max_stop_pct,
        "NEXT_OPEN_ONLY": next_open_only,
        "COLUMNS": sorted(columns),
        "NOT_APPLIED": _not_applied(spec, clocks),
    }
    return _render(spec_path, meta, level_lines, universe, conditions, stop_code, rules)


def _universe_conditions(universe):
    out = []
    if universe["min_price"] > 0:
        out.append(("universe:min_price", f'(col("close") >= {universe["min_price"]!r})'))
    if universe["min_turnover_cr"] > 0:
        out.append(("universe:min_turnover_cr", f'(col("turnover20_cr") >= {universe["min_turnover_cr"]!r})'))
    return out


def _stop(stop, levels):
    if stop["type"] == "none":
        return "None", None, set()
    t = _Translator("stop_loss", set(levels), allow_entry=True)
    return t.run(stop["expr"]), stop.get("max_pct"), t.columns


def _frozen_rule(where, expr, levels, direction):
    """`live <op> frozen` -> a close exit or a touch on the shared menu."""
    tree = ast.parse(expr, mode="eval").body
    if not (isinstance(tree, ast.Compare) and len(tree.ops) == 1 and type(tree.ops[0]) in COMPARE_OPS):
        raise SpecError(f"{where}: an exit that uses `entry` or a level must be ONE comparison, "
                        f"e.g. 'close < pivot' (got {expr!r})")
    sides = []
    for node in (tree.left, tree.comparators[0]):
        t = _Translator(where, set(levels), allow_entry=True)
        sides.append((t.run(ast.unparse(node)), t.frozen, ast.unparse(node), t.columns))
    op = COMPARE_OPS[type(tree.ops[0])]
    if sides[0][1] == sides[1][1]:
        raise SpecError(f"{where}: exactly one side of {expr!r} must mention entry or a level")
    if sides[0][1]:                                   # frozen side first: flip to `live op frozen`
        sides.reverse()
        op = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "==": "=="}[op]
    (_, _, live_text, live_cols), (level_code, _, _, level_cols) = sides
    if live_text == "close" and op != "==":
        return {"kind": "close_exit", "op": op, "level": level_code}, live_cols | level_cols
    favourable = (live_text == "high" and op in (">", ">=")) if direction == "long" \
        else (live_text == "low" and op in ("<", "<="))
    if favourable:
        return {"kind": "touch", "level": level_code}, live_cols | level_cols
    raise SpecError(f"{where}: {expr!r} is not on the exit menu; use 'close <op> level', "
                    f"{'high >= level' if direction == 'long' else 'low <= level'} for a target, "
                    f"or stop_loss for a stop")


def _exit_rules(exits, good, levels, direction):
    rules, columns = [], set()
    for i, e in enumerate(exits, start=1):
        where = f"exit {i} ({e['type']})"
        rule = {"id": f"exit_{i}:{e['type']}"}
        if e["type"] in ("time", "target_pct", "target_r"):
            if "value" not in e:
                raise SpecError(f"{where}: needs `value` (bars, % or R)")
            rule.update(kind=e["type"], value=e["value"], fraction=1.0)
        elif e["type"] == "trail_pct":
            raise SpecError(f"{where}: trail_pct is not on the shared exit menu (backtest/exits.py) yet")
        else:
            if "expr" not in e:
                raise SpecError(f"{where}: needs `expr`")
            probe = _Translator(where, set(levels), allow_entry=True)
            code = probe.run(e["expr"])
            if probe.frozen:
                part, cols = _frozen_rule(where, e["expr"], levels, direction)
                rule.update(part, fraction=1.0)
                columns |= cols
            else:
                rule.update(kind="signal", when=code)
                columns |= probe.columns
        rules.append(rule)

    for i, p in enumerate(good.get("partial_exits", []), start=1):
        part, cols = _frozen_rule(f"partial exit {i}", p["at_expr"], levels, direction)
        if part["kind"] != "touch":
            raise SpecError(f"partial exit {i}: a partial must be a resting target "
                            f"({'high >= level' if direction == 'long' else 'low <= level'})")
        rules.append({"id": f"partial_{i}", **part, "fraction": p["fraction"]})
        columns |= cols

    if "max_hold_bars" in good and not any(r["kind"] == "time" for r in rules):
        rules.append({"id": "max_hold_bars", "kind": "time", "value": good["max_hold_bars"]["value"],
                      "fraction": 1.0})
    return rules, columns


def _not_applied(spec, clocks):
    house, good = spec["must_have"]["from_house"], spec["good_to_have"]
    timing = spec["must_have"]["from_source"]["entry"]["timing"]
    notes = []
    skipped = [c for c in house["entry_clocks_tested"] if c not in clocks]
    if skipped:
        notes.append(f"entry clocks {skipped} need intraday bars; not run")
    if house["universe"]["base"] != "nse_eq_all":
        notes.append(f"universe base {house['universe']['base']!r} not applied; every cached stock is eligible")
    if house["universe"].get("exclude_surveillance", True):
        notes.append("ASM/GSM exclusion not applied: there is no surveillance history")
    if timing not in house["entry_clocks_tested"]:
        notes.append(f"source entry timing {timing!r} is not one of the tested clocks")
    if "chase_limit_pct" in good:
        notes.append("chase_limit_pct not applied (no generic reference level)")
    if good.get("pyramiding"):
        notes.append("pyramiding not modelled")
    if good.get("variants"):
        notes.append("variants are not run: write each variant as its own spec")
    return notes


def _render(spec_path, meta, level_lines, universe, conditions, stop_code, rules):
    rel_spec = os.path.relpath(spec_path, ROOT_DIR)
    lines = [
        f'"""GENERATED by backtest.spec_compiler from {rel_spec}. Do not edit by hand:',
        "change the spec and recompile. `col(name)` returns a date x symbol frame from the",
        "price cache or the feature store; nothing is computed here.",
        '"""',
        "",
    ]
    lines += [f"{key} = {pprint.pformat(value, width=100, sort_dicts=False)}" for key, value in meta.items()]
    lines += ["", "", "def levels(col):", "    lv = {}"] + level_lines + ["    return lv", "", ""]
    lines += ["def universe_conditions(col):",
              '    """Who is eligible on a date (the control run draws from these too)."""', "    return {"]
    lines += [f'        "{cid}": {code},' for cid, code in universe] + ["    }", "", ""]
    lines += ["def entry_conditions(col):",
              '    """True/False on the signal bar; the signal is ALL of these plus the universe."""',
              "    lv = levels(col)", "    return {"]
    lines += [f'        "{cid}": {code},' for cid, code in conditions] + ["    }", "", ""]
    lines += ["def stop_level(col, entry):",
              '    """Stop price, read on the signal bar. `entry` = fill-price frame."""',
              "    lv = levels(col)", f"    return {stop_code}", "", ""]
    lines += ["def exit_rules(col, entry):",
              '    """Exits on the shared menu (backtest/exits.py), in priority order."""',
              "    lv = levels(col)", "    return ["]
    for r in rules:
        parts = [f'"{k}": {v}' if k in ("level", "when") else f'"{k}": {v!r}' for k, v in r.items()]
        lines.append("        {" + ", ".join(parts) + "},")
    lines += ["    ]", ""]
    return "\n".join(lines)


def write_strategy(path):
    """Validate + compile strategies/<id>/spec.json into strategy.py next to it."""
    spec, spec_path = load_spec(path)
    code = compile_spec(spec, spec_path)
    compile(code, "strategy.py", "exec")          # fail here, not at backtest time
    py_path = os.path.join(os.path.dirname(spec_path), "strategy.py")
    with open(py_path, "w") as f:
        f.write(code)
    return py_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compile strategies/<id>/spec.json into strategy.py")
    ap.add_argument("spec", help="strategies/<id> or strategies/<id>/spec.json")
    a = ap.parse_args(argv)
    try:
        print("wrote", write_strategy(a.spec))
    except SpecError as exc:
        raise SystemExit(f"cannot compile: {exc}")


if __name__ == "__main__":
    main()
