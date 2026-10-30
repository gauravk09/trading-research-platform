"""Test-only fixture for canonical_runner; not a strategy or promotion claim."""


def run(spec):
    if spec.get("fixture_incomplete"):
        return {"metrics": {"return": 0.1}, "status": "completed"}
    return {"metrics": {"return": 0.1, "trades": 10}, "status": "completed", "verdict": "PASS",
            "artifacts": [], "checks": {"same_date_control": "passed",
                                         "era_results": {"A": 0.05, "B": 0.04},
                                         "cost_inclusion": "included",
                                         "portfolio_sizing_mode": "capital",
                                         "attribution": "passed",
                                         "success_bars": {"lift": "passed"}}}
