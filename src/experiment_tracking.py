"""Small local MLflow index for research runs; FACTORY/LEDGER remains authority.

This tracks reproducibility metadata and pointers. It does not decide promotion,
copy result payloads, or start an MLflow server.
"""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "output" / "mlflow"
REQUIRED_PARAMETERS = {"costs", "entry_clock", "eras", "control_type"}
REQUIRED_FIELDS = {"run_name", "stage", "strategy", "code_entrypoint", "spec_path",
                   "dataset_paths", "parameters", "metrics", "status", "verdict"}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path, root=ROOT):
    """Stable, secret-free fingerprint for a selected local dataset/spec file."""
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = Path(root) / file_path
    file_path = file_path.resolve()
    if not file_path.is_file():
        raise ValueError(f"dataset/spec path does not exist or is not a file: {path}")
    stat = file_path.stat()
    try:
        display = str(file_path.relative_to(root))
    except ValueError:
        display = str(file_path)
    return {"path": display, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(file_path)}


def _git_state(root=ROOT):
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
        return {"git_sha": sha, "git_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"git_sha": "unavailable", "git_dirty": None}


def normalize_manifest(manifest, root=ROOT):
    """Validate and enrich a plain JSON manifest before any database is opened."""
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    missing = sorted(field for field in REQUIRED_FIELDS if manifest.get(field) in (None, "", [], {}))
    if missing:
        raise ValueError("missing required metadata: " + ", ".join(missing))
    if not isinstance(manifest["parameters"], dict) or not isinstance(manifest["metrics"], dict):
        raise ValueError("parameters and metrics must be JSON objects")
    missing_parameters = sorted(REQUIRED_PARAMETERS - set(manifest["parameters"]))
    if missing_parameters:
        raise ValueError("parameters missing reproducibility fields: " + ", ".join(missing_parameters))
    if not isinstance(manifest["dataset_paths"], list) or not all(isinstance(item, str) for item in manifest["dataset_paths"]):
        raise ValueError("dataset_paths must be a list of file paths")
    if not isinstance(manifest.get("artifact_paths", []), list) or not all(isinstance(item, str) for item in manifest.get("artifact_paths", [])):
        raise ValueError("artifact_paths must be a list of paths")
    for name, value in manifest["metrics"].items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"metric {name!r} must be numeric")
    spec = fingerprint(manifest["spec_path"], root)
    datasets = [fingerprint(path, root) for path in manifest["dataset_paths"]]
    artifacts = [{"path": path} for path in manifest.get("artifact_paths", [])]
    return {"run_name": str(manifest["run_name"]), "stage": str(manifest["stage"]),
            "strategy": str(manifest["strategy"]), "family": str(manifest.get("family", manifest["strategy"])),
            "code_entrypoint": str(manifest["code_entrypoint"]), "spec": spec,
            "datasets": datasets, "parameters": manifest["parameters"], "metrics": manifest["metrics"],
            "status": str(manifest["status"]), "verdict": str(manifest["verdict"]),
            "artifact_manifest": artifacts, "git": _git_state(root)}


def _tracking_uri(store_dir):
    return f"sqlite:///{(Path(store_dir).resolve() / 'mlflow.db')}"


def log_run(manifest, store_dir=DEFAULT_DIR, experiment_name="research"):
    """Log normalized metadata to local SQLite and only the small path manifest artifact."""
    normalized = normalize_manifest(manifest)
    store_dir = Path(store_dir).resolve()
    store_dir.mkdir(parents=True, exist_ok=True)
    import mlflow
    from mlflow.tracking import MlflowClient

    uri = _tracking_uri(store_dir)
    mlflow.set_tracking_uri(uri)
    client = MlflowClient(tracking_uri=uri)
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        experiment_id = client.create_experiment(experiment_name, artifact_location=(store_dir / "artifacts").as_uri())
    else:
        experiment_id = experiment.experiment_id
    tags = {"stage": normalized["stage"], "strategy": normalized["strategy"], "family": normalized["family"],
            "status": normalized["status"], "verdict": normalized["verdict"],
            "code_entrypoint": normalized["code_entrypoint"], "spec_sha256": normalized["spec"]["sha256"],
            "git_sha": normalized["git"]["git_sha"], "git_dirty": str(normalized["git"]["git_dirty"]),
            "dataset_fingerprints": json.dumps(normalized["datasets"], sort_keys=True),
            "artifact_manifest_note": "Paths only; source artifacts are not copied to MLflow."}
    params = {key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
              for key, value in normalized["parameters"].items()}
    with mlflow.start_run(experiment_id=experiment_id, run_name=normalized["run_name"], tags=tags) as run:
        mlflow.log_params(params)
        mlflow.log_metrics({key: float(value) for key, value in normalized["metrics"].items()})
        # This small manifest is the only MLflow artifact. Referenced results stay in place.
        mlflow.log_dict(normalized["artifact_manifest"], "artifact_manifest.json")
        return {"run_id": run.info.run_id, "tracking_uri": uri, "experiment_id": experiment_id,
                "normalized_manifest": normalized}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Log a research-run index entry to local MLflow SQLite.")
    parser.add_argument("manifest", help="JSON manifest path")
    parser.add_argument("--store-dir", default=str(DEFAULT_DIR))
    parser.add_argument("--experiment", default="research")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print only; creates no DB.")
    args = parser.parse_args(argv)
    with open(args.manifest, encoding="utf-8") as handle:
        manifest = json.load(handle)
    normalized = normalize_manifest(manifest)
    if args.dry_run:
        print(json.dumps(normalized, sort_keys=True, indent=2))
        return normalized
    result = log_run(manifest, args.store_dir, args.experiment)
    print(json.dumps({"run_id": result["run_id"], "tracking_uri": result["tracking_uri"],
                      "ui_command": f"mlflow ui --backend-store-uri {result['tracking_uri']}"}, indent=2))
    return result


if __name__ == "__main__":
    main()
