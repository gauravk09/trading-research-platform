import json

from research.regime import scoreboard


def _row(exp_id, model, ts, skill=0.05, lo=0.01, hi=0.09, gates_pass=True, knobs=None):
    return {
        "exp_id": exp_id, "model": model, "timestamp": ts, "tag": "",
        "knobs": knobs or {}, "n_fitted_knobs": 0,
        "metrics": {"rps_skill_20": skill, "rps_skill_20_ci_lo": lo, "rps_skill_20_ci_hi": hi},
        "gates": {"g1": gates_pass}, "gates_all_pass": gates_pass,
        "plot_paths": ["/tmp/plot.png"],
    }


def test_read_experiments_roundtrip(tmp_path):
    log_path = tmp_path / "log.jsonl"
    rows = [_row("e1", "B0", "2026-01-01T00:00:00"), _row("e2", "B0", "2026-01-02T00:00:00")]
    with open(log_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    loaded = scoreboard.read_experiments(log_path)
    assert len(loaded) == 2
    assert loaded[0]["exp_id"] == "e1"


def test_read_experiments_missing_file_returns_empty(tmp_path):
    assert scoreboard.read_experiments(tmp_path / "missing.jsonl") == []


def test_latest_per_variant_keeps_most_recent():
    rows = [
        _row("e1", "B0", "2026-01-01T00:00:00", skill=0.01),
        _row("e2", "B0", "2026-01-03T00:00:00", skill=0.05),  # same model+knobs, later
        _row("e3", "L1", "2026-01-02T00:00:00", skill=0.02),
    ]
    latest = scoreboard._latest_per_variant(rows)
    b0_rows = [r for r in latest if r["model"] == "B0"]
    assert len(b0_rows) == 1
    assert b0_rows[0]["exp_id"] == "e2"


def test_build_scoreboard_writes_markdown(tmp_path):
    log_path = tmp_path / "log.jsonl"
    out_path = tmp_path / "SCOREBOARD.md"
    rows = [_row("e1", "B0_climatology", "2026-01-01T00:00:00")]
    with open(log_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    text = scoreboard.build_scoreboard(log_path, out_path)
    assert out_path.exists()
    assert "B0_climatology" in text
    assert "Total experiments logged" in text
    assert "1" in text
