"""Grade every spec JSON in a directory through the engine, at 5d and 20d,
long or short (per each spec's cohort.side). Writes each result to results/
and prints a compact table. Used by batch authoring agents to self-validate
and by the final uniform re-grade.

Usage:  python research/machine/run_batch.py specs/batch5
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import engine as E  # noqa: E402

HERE = os.path.dirname(__file__)


def grade(spec_dir):
    ev = E.load_events()
    paths = sorted(glob.glob(os.path.join(HERE, spec_dir, "*.json")))
    rows = []
    for p in paths:
        spec = json.load(open(p))
        try:
            r = E.run_spec(spec, ev)
        except Exception as exc:
            rows.append((spec.get("id", os.path.basename(p)), "ERROR", "-",
                         str(exc)[:60], "", "", ""))
            continue
        json.dump(r, open(os.path.join(E.RESULTS, f"{r['id']}.json"), "w"),
                  indent=1, default=float)
        eb = (r["effect_R"] or {}).get("B")
        eb20 = (r.get("effect_R_20") or {}).get("B")
        rows.append((r["id"], r["verdict"], r.get("verdict_20", "-"),
                     r.get("side", "long"), eb, eb20, r["n"]))
    return rows


if __name__ == "__main__":
    spec_dir = sys.argv[1] if len(sys.argv) > 1 else "specs/batch5"
    rows = grade(spec_dir)
    print(f"{'id':32s} {'5d':11s} {'20d':11s} {'side':6s} "
          f"{'effB5':>7s} {'effB20':>7s} {'n':>7s}")
    for rid, v5, v20, side, eb, eb20, n in rows:
        e5 = f"{eb:+.3f}" if isinstance(eb, (int, float)) else str(eb)
        e20 = f"{eb20:+.3f}" if isinstance(eb20, (int, float)) else ""
        print(f"{rid:32s} {v5:11s} {v20:11s} {side:6s} {e5:>7s} {e20:>7s} {str(n):>7s}")
