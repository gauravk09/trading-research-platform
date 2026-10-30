"""Reads experiments.jsonl and writes SCOREBOARD.md: one row per experiment
(latest per model+knobs), the gate pass/fail matrix, the primary metric (20d
RPS skill + CI), the paired skill difference vs a named reference experiment,
n_fitted_knobs, and a multiple-testing disclosure (total experiments logged).
"""
from __future__ import annotations

import json
from pathlib import Path

from .runner import EXPERIMENTS_LOG, PKG_DIR

SCOREBOARD_PATH = PKG_DIR / "SCOREBOARD.md"
REFERENCE_MODEL = "Naive-200"  # not yet built in Stage A; column stays empty until it exists


def read_experiments(log_path: Path = EXPERIMENTS_LOG) -> list[dict]:
    if not log_path.exists():
        return []
    rows = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _latest_per_variant(rows: list[dict]) -> list[dict]:
    """One row per (model, knobs) — the latest by timestamp."""
    best: dict[tuple, dict] = {}
    for row in rows:
        key = (row["model"], json.dumps(row.get("knobs", {}), sort_keys=True))
        prev = best.get(key)
        if prev is None or row["timestamp"] > prev["timestamp"]:
            best[key] = row
    return sorted(best.values(), key=lambda r: r["timestamp"])


def _fmt(v, nd=3):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "PASS" if v else "FAIL"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def build_scoreboard(log_path: Path = EXPERIMENTS_LOG, out_path: Path = SCOREBOARD_PATH,
                      reference_model: str = REFERENCE_MODEL) -> str:
    rows = read_experiments(log_path)
    latest = _latest_per_variant(rows)

    ref_row = None
    for r in reversed(rows):
        if r["model"] == reference_model:
            ref_row = r
            break

    lines = []
    lines.append("# Regime Harness Scoreboard")
    lines.append("")
    lines.append(f"Total experiments logged (multiple-testing disclosure): **{len(rows)}**")
    lines.append(f"Distinct model/knob variants shown below: **{len(latest)}**")
    lines.append("")
    lines.append(
        "| model | tag | n_fitted_knobs | RPS skill 20d | CI | skill vs " + reference_model +
        " | gates | exp_id |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in latest:
        m = row.get("metrics", {})
        skill = m.get("rps_skill_20")
        lo = m.get("rps_skill_20_ci_lo")
        hi = m.get("rps_skill_20_ci_hi")
        ci_str = f"[{_fmt(lo)}, {_fmt(hi)}]" if lo is not None else "n/a"
        gates_summary = "PASS" if row.get("gates_all_pass") else "FAIL/NA"
        diff_str = "n/a (reference not yet logged)" if ref_row is None or row is ref_row else "n/a"
        lines.append(
            f"| {row['model']} | {row.get('tag','')} | {row.get('n_fitted_knobs')} | "
            f"{_fmt(skill)} | {ci_str} | {diff_str} | {gates_summary} | `{row['exp_id']}` |"
        )
    lines.append("")

    lines.append("## Gate detail (latest per variant)")
    lines.append("")
    for row in latest:
        lines.append(f"### {row['model']} — `{row['exp_id']}`")
        lines.append("")
        for gate_name, result in row.get("gates", {}).items():
            status = "n/a" if result is None else ("PASS" if result else "FAIL")
            lines.append(f"- {gate_name}: {status}")
        lines.append("")

    lines.append("## Calibration plots")
    lines.append("")
    for row in latest:
        for p in row.get("plot_paths", []):
            lines.append(f"- {row['model']} (`{row['exp_id']}`): {p}")
    lines.append("")

    text = "\n".join(lines) + "\n"
    out_path.write_text(text)
    return text
