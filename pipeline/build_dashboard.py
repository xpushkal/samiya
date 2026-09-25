"""Assemble the observation registry and the self-contained dashboard.

Reads outputs/stats/*.json + outputs/layers/*, writes:
  outputs/registry.json      – machine-readable registry (file paths)
  public/index.html          – single-file dashboard (data + images inlined), deployable as-is

Only processed outputs are needed here, so the dashboard can be rebuilt without the raw data.
    python pipeline/build_dashboard.py                    # -> public/index.html
    python pipeline/build_dashboard.py --fragment out.html # body-only variant (no <html>/<head>)
"""
import base64
import io
import json
import sys
from datetime import date

import geopandas as gpd
from PIL import Image

from config import (CORRIDOR_BBOX, CORRIDOR_DISTRICTS, NEPAL_ADM0, NEPAL_PROVINCES, OBSERVATIONS,
                    OUT, ROOT, STATS)

DASH = ROOT / "dashboard"
SITE = ROOT / "public"
LOSSLESS = ("_water.png", "_water_change.png", "_mask.png")


def load(name):
    return json.loads((STATS / name).read_text())


def encode(rel):
    """Layer file -> WebP data URI (lossless for class maps, lossy for continuous ramps)."""
    im = Image.open(OUT / rel).convert("RGBA")
    buf = io.BytesIO()
    if rel.endswith(LOSSLESS):
        im.save(buf, "WEBP", lossless=True, method=6)
    else:
        im.save(buf, "WEBP", quality=80, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def geo(path, tol, props=()):
    g = gpd.read_file(path)
    g["geometry"] = g.geometry.simplify(tol, preserve_topology=True)
    g = g[[*props, "geometry"]]
    gj = json.loads(g.to_json(drop_id=True))

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 4), round(c[1], 4)]
    for f in gj["features"]:
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    return gj


def main():
    s2, l9 = load("sentinel2.json"), load("landsat9.json")
    terrain, rain, slides = load("terrain.json"), load("rainfall.json"), load("landslides.json")

    observations = []
    for o in OBSERVATIONS:
        rec = {k: v for k, v in o.items() if k not in ("safe", "prefix")}
        if o["platform"] == "sentinel2":
            st = s2["observations"][o["id"]]
            rec |= dict(pixel_m=10, extents={"tile": dict(bounds=st["bounds"], layers=st["layers"])},
                        default_extent="tile", covers_corridor=False,
                        stats={k: v for k, v in st.items() if k not in ("bounds", "layers")})
        else:
            rec |= dict(pixel_m=30, default_extent="corridor", covers_corridor=True,
                        extents={k: dict(bounds=l9[k]["bounds"], layers=l9[k]["layers"])
                                 for k in ("corridor", "scene")},
                        stats={k: l9[k]["stats"] for k in ("corridor", "scene")})
        observations.append(rec)
    comparisons = [dict(id=k, **v) for k, v in s2["comparisons"].items()]

    registry = dict(generated=date.today().isoformat(), observations=observations,
                    comparisons=comparisons, thresholds=s2["thresholds"])
    (OUT / "registry.json").write_text(json.dumps(registry, indent=1))

    # collect every referenced layer and inline it
    paths = set()
    for o in observations:
        for e in o["extents"].values():
            paths |= set(e["layers"].values())
    for c in comparisons:
        paths |= set(c["layers"].values())
    paths |= {terrain["basemap"]["layer"], *terrain["corridor"]["layers"].values()}
    images = {p: encode(p) for p in sorted(paths)}

    data = dict(
        registry=registry, landsat=l9, terrain=terrain, rainfall=rain, landslides=slides,
        corridor=dict(bbox=CORRIDOR_BBOX, districts=CORRIDOR_DISTRICTS),
        boundaries=dict(nepal=geo(NEPAL_ADM0, 0.01), provinces=geo(NEPAL_PROVINCES, 0.01, ("province",))),
        images=images,
    )
    tpl = (DASH / "template.html").read_text()
    css = (DASH / "vendor/leaflet.css").read_text()
    html = (tpl.replace("/*__LEAFLET_CSS__*/", css)
               .replace("/*__DATA__*/", "window.DATA = " + json.dumps(data, separators=(",", ":")) + ";"))
    if "--fragment" in sys.argv:
        out = ROOT / sys.argv[sys.argv.index("--fragment") + 1]
    else:
        SITE.mkdir(exist_ok=True)
        out = SITE / "index.html"
        html = f'<!doctype html>\n<html lang="en">\n<head>\n{html}\n</body>\n</html>\n'
        html = html.replace("</style>\n\n<div class=\"app\">", "</style>\n</head>\n<body>\n<div class=\"app\">", 1)
    out.write_text(html)
    mb = len(html.encode()) / 1e6
    print(f"{out.relative_to(ROOT)}  {mb:.1f} MB  ({len(images)} layers)")


if __name__ == "__main__":
    main()
