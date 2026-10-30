"""Canonical promotion-grade runner for new S4+ research only.

Historical studies remain readable archives. New promotion claims must enter
through a JSON spec, an explicit module ``run(spec)`` call, complete evidence,
and the local experiment index. No shell command is accepted from a spec.
"""
import argparse
import hashlib
import importlib
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for import_path in (str(ROOT), str(ROOT / "src")):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from experiment_tracking import log_run

DEFAULT_OUTPUT = ROOT / "output" / "experiments"
REQUIRED = {"id", "stage", "strategy", "family", "module", "spec_path", "dataset_paths",
            "parameters", "success_bars"}
# The protocol header (Xia et al., arXiv:2605.19337: of 19 agentic-trading
# studies, 1 disclosed a cost model and 1 disclosed survivorship handling).
# Git SHA and dataset fingerprints are recorded by experiment_tracking.log_run.
REQUIRED_PARAMETERS = {"costs", "entry_clock", "eras", "control_type", "survivorship"}
REQUIRED_RESULT = {"metrics", "status", "verdict", "artifacts", "checks"}
# attribution = market/style/selection split (src/backtest/attribution.py);
# a PASS needs it passed, or an explicit "N/A (<why no cross-section>)".
REQUIRED_CHECKS = {"same_date_control", "era_results", "cost_inclusion",
                   "portfolio_sizing_mode", "success_bars", "attribution"}
PASS_VERDICTS = {"PASS", "PROMOTE", "PROMOTABLE"}
R2_REL_TOL = 1e-9


def _path(value):
    return Path(value) if Path(value).is_absolute() else ROOT / value


def validate_spec(spec):
    """Validate metadata and boundaries only: this deliberately imports nothing."""
    if not isinstance(spec, dict):
        raise ValueError("canonical spec must be a JSON object")
    missing = sorted(key for key in REQUIRED if spec.get(key) in (None, "", [], {}))
    if missing:
        raise ValueError("canonical spec missing: " + ", ".join(missing))
    if not str(spec["stage"]).upper().startswith("S") or int(str(spec["stage"])[1:]) < 4:
        raise ValueError("canonical runner is reserved for promotion-grade S4+ work")
    module = str(spec["module"])
    if not module.startswith("src.backtest.studies.") or module.count(".") < 3:
        raise ValueError("module must be a dotted module under src.backtest.studies")
    module_path = ROOT / (module.replace(".", os.sep) + ".py")
    try:
        module_path.relative_to(ROOT / "src" / "backtest" / "studies")
    except ValueError as exc:
        raise ValueError("module is outside src/backtest/studies") from exc
    if not module_path.is_file():
        raise ValueError(f"study module does not exist: {module}")
    if not _path(spec["spec_path"]).is_file():
        raise ValueError("spec_path does not exist")
    if not isinstance(spec["dataset_paths"], list) or not spec["dataset_paths"]:
        raise ValueError("dataset_paths must be a non-empty list")
    if any(not _path(path).is_file() for path in spec["dataset_paths"]):
        raise ValueError("every selected dataset path must exist and be a file")
    if not isinstance(spec["parameters"], dict):
        raise ValueError("parameters must be an object")
    missing_parameters = sorted(REQUIRED_PARAMETERS - set(spec["parameters"]))
    if missing_parameters:
        raise ValueError("parameters missing: " + ", ".join(missing_parameters))
    if not isinstance(spec["success_bars"], dict) or not spec["success_bars"]:
        raise ValueError("success_bars must be a non-empty object")
    if not isinstance(spec.get("artifact_paths", []), list):
        raise ValueError("artifact_paths must be a list when supplied")
    return spec


def _passed(value):
    return value is True or str(value).strip().lower() in {"pass", "passed", "included"}


def validate_result(result, spec=None):
    if not isinstance(result, dict):
        raise ValueError("study run(spec) must return an object")
    # A run may have no supplemental artifacts, but it must explicitly return
    # the list so the manifest is never ambiguous.
    missing = sorted(key for key in REQUIRED_RESULT
                     if key not in result or result.get(key) in (None, "", {}))
    if missing:
        raise ValueError("study result incomplete: " + ", ".join(missing))
    if not isinstance(result["metrics"], dict) or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                                                       for value in result["metrics"].values()):
        raise ValueError("study result metrics must be numeric")
    if not isinstance(result["artifacts"], list):
        raise ValueError("study result artifacts must be a list")
    if not isinstance(result["checks"], dict):
        raise ValueError("study result checks must be an object")
    missing_checks = sorted(key for key in REQUIRED_CHECKS if result["checks"].get(key) in (None, "", [], {}))
    if missing_checks:
        raise ValueError("study result checks incomplete: " + ", ".join(missing_checks))
    bars = result["checks"]["success_bars"]
    if not isinstance(bars, dict):
        raise ValueError("checks.success_bars must map every pre-registered bar to pass/fail")
    if spec is not None and set(bars) != set(spec["success_bars"]):
        raise ValueError("checks.success_bars must exactly match the pre-registered success bars")
    if str(result["verdict"]).upper() in PASS_VERDICTS:
        if not _passed(result["checks"]["same_date_control"]):
            raise ValueError("PASS verdict requires a passed same-date/matched control check")
        if not _passed(result["checks"]["cost_inclusion"]):
            raise ValueError("PASS verdict requires costs to be included")
        attribution = result["checks"]["attribution"]
        if not (_passed(attribution) or str(attribution).startswith("N/A")):
            raise ValueError("PASS verdict requires a passed attribution check "
                             "(selection alpha) or an explicit 'N/A (<reason>)'")
        failed_bars = [name for name, passed in bars.items() if not _passed(passed)]
        if failed_bars:
            raise ValueError("PASS verdict failed pre-registered bars: " + ", ".join(failed_bars))
    return result


def run_spec(spec, output_dir=DEFAULT_OUTPUT, mlflow_dir=None):
    """Explicitly import one whitelisted study, persist its small result, and index it."""
    spec = validate_spec(spec)
    module = importlib.import_module(spec["module"])
    runner = getattr(module, "run", None)
    if not callable(runner):
        raise ValueError(f"{spec['module']} must expose callable run(spec)")
    result = validate_result(runner(spec), spec)
    output_path = Path(output_dir) / str(spec["id"])
    output_path.mkdir(parents=True, exist_ok=True)
    payload = {"spec": spec, "result": result}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    result_path = output_path / f"{digest}.json"
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
    manifest = {"run_name": spec["id"], "stage": spec["stage"], "strategy": spec["strategy"],
                "family": spec["family"], "code_entrypoint": spec["module"], "spec_path": spec["spec_path"],
                "dataset_paths": spec["dataset_paths"], "parameters": spec["parameters"],
                "metrics": result["metrics"], "status": result["status"], "verdict": result["verdict"],
                "artifact_paths": [str(result_path)] + spec.get("artifact_paths", []) + result["artifacts"]}
    tracking = log_run(manifest, store_dir=mlflow_dir or ROOT / "output" / "mlflow")
    return {"result_path": str(result_path), "tracking": tracking, "result": result}


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=R2_REL_TOL, abs_tol=R2_REL_TOL)
    return a == b


def replay(result_path, output_dir=DEFAULT_OUTPUT, mlflow_dir=None):
    """R2 reproducibility: re-run a persisted result's spec from scratch and
    compare every metric and the verdict. A promotion claim that cannot be
    replayed in a fresh process is a number, not a finding."""
    payload = _load(result_path)
    fresh = run_spec(payload["spec"], output_dir, mlflow_dir)["result"]
    stored = payload["result"]
    diffs = {name: {"stored": value, "replay": fresh["metrics"].get(name)}
             for name, value in stored["metrics"].items()
             if not _same(value, fresh["metrics"].get(name))}
    if stored["verdict"] != fresh["verdict"]:
        diffs["verdict"] = {"stored": stored["verdict"], "replay": fresh["verdict"]}
    return {"r2": "FAIL" if diffs else "PASS", "diffs": diffs, "result_path": str(result_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Canonical promotion-grade research runner.")
    parser.add_argument("spec", help="canonical JSON spec (or a persisted result JSON with --replay)")
    parser.add_argument("--validate", action="store_true", help="validate only (default; imports/runs nothing)")
    parser.add_argument("--run", action="store_true", help="explicitly import and run the declared study")
    parser.add_argument("--replay", action="store_true",
                        help="R2 check: re-run a persisted result's spec and diff the metrics")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mlflow-dir", default=None)
    args = parser.parse_args(argv)
    if sum([args.validate, args.run, args.replay]) > 1:
        parser.error("choose at most one of --validate, --run and --replay")
    if args.replay:
        out = replay(args.spec, args.output_dir, args.mlflow_dir)
        print(json.dumps(out, indent=2, sort_keys=True))
        return out
    spec = validate_spec(_load(args.spec))
    if not args.run:
        print(json.dumps({"valid": True, "id": spec["id"], "mode": "validate"}, sort_keys=True))
        return spec
    result = run_spec(spec, args.output_dir, args.mlflow_dir)
    print(json.dumps({"result_path": result["result_path"], "run_id": result["tracking"]["run_id"]}, indent=2))
    return result


if __name__ == "__main__":
    main()
