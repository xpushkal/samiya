"""Shared paths and the observation registry.

The dashboard is data-driven: every satellite observation is one record in
OBSERVATIONS. To add a new date, download the scene, add a record here and
re-run `python pipeline/run_all.py` — no dashboard code changes are needed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
LAYERS = OUT / "layers"      # web-ready PNG/JPG overlays (EPSG:3857)
RASTERS = OUT / "rasters"    # analysis GeoTIFFs
STATS = OUT / "stats"        # JSON results consumed by the dashboard
for d in (OUT, LAYERS, RASTERS, STATS):
    d.mkdir(parents=True, exist_ok=True)

NEPAL_ADM0 = ROOT / "data/boundaries/npl_ADM0.geojson"
# Provinces: geoBoundaries gbHumanitarian ADM1 (OCHA COD), renamed to current province names
NEPAL_PROVINCES = ROOT / "data/boundaries/npl_provinces.geojson"

# Rasuwa – Bhote Koshi – Trishuli corridor (event focus area, WGS84)
CORRIDOR_BBOX = (84.70, 27.70, 85.60, 28.45)  # minlon, minlat, maxlon, maxlat
CORRIDOR_DISTRICTS = ["Rasuwa", "Nuwakot", "Dhading", "Gorkha", "Chitwan", "Tanahun"]

# Water / vegetation thresholds. NDWI > 0 is the McFeeters (1996) default; the
# pipeline reports agreement with the sensor's own water class so it can be
# validated rather than assumed.
NDWI_WATER = 0.0
NIR_WATER_MAX = 0.15   # water must also be dark in NIR (rejects haze / cloud / snow)
CLOUD_BUFFER_M = 60    # Sentinel-2: clouds + shadows dilated before analysis (SCL has no edge buffer)
L9_CLOUD_BUFFER_M = 0  # Landsat 9: QA_PIXEL bit 1 ("dilated cloud") already buffers cloud edges
NDVI_VEG = 0.3
NDVI_DECLINE = -0.2

# Large raw inputs live in data/raw/ (gitignored; see data/raw/README.md for sources)
RAW = ROOT / "data/raw"
S2_DIR = RAW / "sentinel2"
L9_DIR = RAW / "landsat9"
IMERG_DIR = RAW / "imerg"
LANDSLIDE_DIR = ROOT / "data/landslides"

OBSERVATIONS = [
    {
        "id": "s2-2026-08-25",
        "date": "2026-08-25",
        "sensor": "Sentinel-2C MSI L2A",
        "platform": "sentinel2",
        "tile": "T44RQT",
        "role": "Pre-flood baseline",
        "safe": S2_DIR / "2026-08-25",
    },
    {
        "id": "l9-2026-08-26",
        "date": "2026-08-26",
        "sensor": "Landsat 9 OLI-2 C2 L2",
        "platform": "landsat",
        "tile": "Path 141 / Row 040",
        "role": "Event-day observation",
        "prefix": L9_DIR / "LC09_L2SP_141040_20260826_20260827_02_T1",
    },
    {
        "id": "s2-2026-09-04",
        "date": "2026-09-04",
        "sensor": "Sentinel-2C MSI L2A",
        "platform": "sentinel2",
        "tile": "T44RQT",
        "role": "Post-flood observation",
        "safe": S2_DIR / "2026-09-04",
    },
]

# Pairs that can be compared pixel-for-pixel (same sensor + same footprint).
COMPARISONS = [("s2-2026-08-25", "s2-2026-09-04")]
