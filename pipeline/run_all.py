"""Run the full pipeline, then rebuild the dashboard.

    python pipeline/run_all.py            # everything
    python pipeline/run_all.py --skip s2  # skip slow steps by name
"""
import sys
import time

import build_dashboard
import process_landsat
import process_landslides
import process_rainfall
import process_sentinel2
import process_terrain

STEPS = [("s2", process_sentinel2), ("landsat", process_landsat), ("terrain", process_terrain),
         ("rainfall", process_rainfall), ("landslides", process_landslides), ("build", build_dashboard)]

if __name__ == "__main__":
    skip = set(sys.argv[sys.argv.index("--skip") + 1].split(",")) if "--skip" in sys.argv else set()
    for name, mod in STEPS:
        if name in skip:
            continue
        t = time.time()
        print(f"== {name}", flush=True)
        mod.main()
        print(f"   {time.time() - t:.0f}s", flush=True)
