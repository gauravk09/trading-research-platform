"""Inventory-only artifact retention report. This module has no deletion/apply path."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = ROOT / "artifact_retention_policy.json"
DEFAULT_REPORT_DIR = ROOT / "output" / "retention"


def git_tracked_paths(root=ROOT):
    """Return repository-relative tracked paths, failing closed on git errors."""
    try:
        raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        return {Path(item.decode("utf-8")) for item in raw.split(b"\0") if item}
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("cannot verify git-tracked files; refusing to propose cleanup candidates") from exc


def _files(area_root, pattern):
    if not area_root.exists():
        return []
    if area_root.is_file():
        return [area_root]
    return sorted((path for path in area_root.glob(pattern) if path.is_file()), key=lambda path: str(path))


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def scan(policy, root=ROOT, tracked_paths=None, now=None):
    """Return a deterministic inventory; tracked files are never cleanup candidates."""
    root = Path(root).resolve()
    tracked = git_tracked_paths(root) if tracked_paths is None else {Path(path) for path in tracked_paths}
    now = now or datetime.now(timezone.utc).timestamp()
    areas, candidates = [], []
    for rule in policy["areas"]:
        relative = Path(rule["path"])
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise ValueError(f"policy path escapes root: {rule['path']}")
        rows, total, tracked_count, oldest, newest, reclaim = [], 0, 0, None, None, 0
        for path in _files(target, rule.get("glob", "**/*")):
            stat = path.stat()
            rel = path.relative_to(root)
            age_days = max(0, int((now - stat.st_mtime) // 86400))
            is_tracked = rel in tracked
            total += stat.st_size
            tracked_count += int(is_tracked)
            oldest = stat.st_mtime if oldest is None else min(oldest, stat.st_mtime)
            newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)
            eligible = (rule["action"] != "keep" and not is_tracked and age_days >= rule.get("min_age_days", 0))
            if eligible:
                reclaim += stat.st_size
                candidates.append({"path": str(rel), "bytes": stat.st_size, "age_days": age_days,
                                   "action": rule["action"], "category": rule["category"],
                                   "reason": rule["reason"]})
            rows.append((path, stat.st_size))
        areas.append({"path": str(relative), "category": rule["category"], "action": rule["action"],
                      "reason": rule["reason"], "files": len(rows), "bytes": total,
                      "tracked_files": tracked_count, "oldest": _iso(oldest) if oldest else None,
                      "newest": _iso(newest) if newest else None, "potential_reclaim_bytes": reclaim,
                      "min_age_days": rule.get("min_age_days", 0)})
    candidates.sort(key=lambda item: (-item["bytes"], item["path"]))
    return {"policy": policy["policy"], "generated_at": _iso(now), "areas": areas,
            "top_candidates": candidates[:20], "potential_reclaim_bytes": sum(item["bytes"] for item in candidates),
            "note": "Inventory evidence only. No file has been moved, compressed, or deleted."}


def load_policy(path=DEFAULT_POLICY):
    with open(path, encoding="utf-8") as handle:
        policy = json.load(handle)
    if policy.get("policy") != "inventory_only_no_deletion" or not isinstance(policy.get("areas"), list):
        raise ValueError("invalid retention policy")
    return policy


def write_report(report, report_dir=DEFAULT_REPORT_DIR):
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "retention_report.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dry-run artifact retention inventory (no deletion support).")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--dry-run", action="store_true", help="Inventory only (the default).")
    parser.add_argument("--write-report", action="store_true", help="Write JSON inventory under output/retention.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    args = parser.parse_args(argv)
    report = scan(load_policy(args.policy), args.root)
    if args.write_report:
        report["report_path"] = str(write_report(report, args.report_dir))
    print(json.dumps(report, sort_keys=True, indent=2))
    return report


if __name__ == "__main__":
    main()
