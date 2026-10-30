"""Stage B run: K1 k-NN historical analogs, "long" window (2000-2024 test
years). Launched as a background script; progress heartbeats print every
30s to stdout — redirect to a file under $REGIME_OUT when launching.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from research.regime import runner
from research.regime.models.k1_knn import K1HistoricalAnalogs

STOP = threading.Event()


def _heartbeat():
    t0 = time.time()
    while not STOP.is_set():
        STOP.wait(30)
        if not STOP.is_set():
            print(f"[heartbeat] K1 still running, {time.time() - t0:.0f}s elapsed", flush=True)


def main():
    print("[K1] starting run_experiment, window_config=long", flush=True)
    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    t0 = time.time()
    try:
        row = runner.run_experiment(
            lambda knobs: K1HistoricalAnalogs(knobs),
            knobs={"k_mult": 1.0},
            feature_config={},
            tag="stage-b-k1-long",
            run_perturbations=True,
            window_config="long",
        )
    finally:
        STOP.set()
    dt = time.time() - t0
    print(f"[K1] done in {dt:.1f}s, exp_id={row['exp_id']}, gates_all_pass={row['gates_all_pass']}", flush=True)


if __name__ == "__main__":
    main()
