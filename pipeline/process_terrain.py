"""Interim DEM + slope from AWS Terrain Tiles (Terrarium encoding, SRTM-derived).

The PRD's planned DEM (SRTM 1 Arc-Second) is still pending, so this module pulls
the public, no-login AWS Open Data terrain tiles. Tiles are already in Web
Mercator, so no reprojection is required. Replace DEM_SOURCE with the SRTM
GeoTIFF once it is downloaded; the outputs and dashboard stay the same.

* Nepal-wide shaded-relief basemap at zoom 8 (~540 m)
* Corridor elevation + slope at zoom 11 (~67 m)
"""
import io
import math
import urllib.request

import geopandas as gpd
import numpy as np
from PIL import Image
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds

from common import ELEV_RAMP, SLOPE_RAMP, colorize, save_png, save_webp, write_json
from config import CORRIDOR_BBOX, NEPAL_ADM0, ROOT

CACHE = ROOT / "data/dem/terrarium"
CACHE.mkdir(parents=True, exist_ok=True)
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
NEPAL_BBOX = (80.0, 26.3, 88.3, 30.5)
BASEMAP_BBOX = (77.8, 25.0, 90.4, 31.8)   # generous margin so the map never shows an edge
R = 6378137.0


def tile_xy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int(x), int(y)


def tile_lonlat(x, y, z):
    n = 2 ** z
    return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))


def fetch(z, x, y):
    f = CACHE / f"{z}_{x}_{y}.png"
    if not f.exists():
        f.write_bytes(urllib.request.urlopen(URL.format(z=z, x=x, y=y), timeout=60).read())
    rgb = np.asarray(Image.open(io.BytesIO(f.read_bytes())).convert("RGB")).astype(np.float64)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def mosaic(bbox, z):
    x0, y0 = tile_xy(bbox[0], bbox[3], z)
    x1, y1 = tile_xy(bbox[2], bbox[1], z)
    rows = [np.hstack([fetch(z, x, y) for x in range(x0, x1 + 1)]) for y in range(y0, y1 + 1)]
    dem = np.clip(np.vstack(rows).astype(np.float32), 0, None)  # clamp tile voids
    w, n = tile_lonlat(x0, y0, z)
    e, s = tile_lonlat(x1 + 1, y1 + 1, z)
    return dem, (w, s, e, n)


def merc(lon, lat):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def slope_hillshade(dem, bounds):
    """Slope (deg) and hillshade using true ground spacing (Mercator scale corrected)."""
    h, w = dem.shape
    (mx0, my0), (mx1, my1) = merc(bounds[0], bounds[1]), merc(bounds[2], bounds[3])
    lat_c = (bounds[1] + bounds[3]) / 2
    px = (mx1 - mx0) / w * math.cos(math.radians(lat_c))
    py = (my1 - my0) / h * math.cos(math.radians(lat_c))
    dzdy, dzdx = np.gradient(dem, py, px)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    az, alt = math.radians(315), math.radians(45)
    aspect = np.arctan2(-dzdx, dzdy)
    hs = (np.sin(alt) * np.cos(np.radians(slope)) +
          np.cos(alt) * np.sin(np.radians(slope)) * np.cos(az - aspect))
    return slope.astype(np.float32), np.clip(hs, 0, 1).astype(np.float32), px


def shaded(dem, hs, vmax=7500):
    rgba = colorize(dem, ELEV_RAMP, 0, vmax)
    shade = (0.35 + 0.75 * hs)[..., None]
    return np.clip(rgba[..., :3] * shade, 0, 255).astype(np.uint8)


def to_leaflet(b):
    return [[round(b[1], 5), round(b[0], 5)], [round(b[3], 5), round(b[2], 5)]]


def main():
    nepal = gpd.read_file(NEPAL_ADM0).to_crs(3857).geometry

    # ---- Nepal basemap (z8) ----
    dem, b = mosaic(BASEMAP_BBOX, 8)
    _, hs, base_px = slope_hillshade(dem, b)
    t = from_bounds(*merc(b[0], b[1]), *merc(b[2], b[3]), dem.shape[1], dem.shape[0])
    inside = ~geometry_mask(nepal, dem.shape, t)
    rgb = shaded(dem, hs)
    # dim terrain outside Nepal so the country reads as the subject
    rgb = np.where(inside[..., None], rgb, (rgb * 0.32 + 10).astype(np.uint8))
    base = save_webp(rgb, "basemap_nepal_relief.webp", quality=72)
    elev_np = dem[inside]
    # Himalayan skyline: highest point inside Nepal for each basemap column
    cols = np.where(inside.any(0))[0]
    peak = np.where(inside, dem, 0).max(0)
    lon_of = lambda c: b[0] + (c + 0.5) / dem.shape[1] * (b[2] - b[0])
    skyline = [[round(lon_of(c), 3), int(peak[c])] for c in cols[::3]]
    hist, edges = np.histogram(elev_np, bins=np.arange(0, 9000, 500))

    # ---- Corridor detail (z11) ----
    cdem, cb = mosaic(CORRIDOR_BBOX, 11)
    slope, chs, px = slope_hillshade(cdem, cb)
    ct = from_bounds(*merc(cb[0], cb[1]), *merc(cb[2], cb[3]), cdem.shape[1], cdem.shape[0])
    cin = ~geometry_mask(nepal, cdem.shape, ct)
    elev_png = save_webp(shaded(cdem, chs), "corridor_elevation.webp", quality=78)
    sl = np.where(cin, slope, np.nan)
    slope_png = save_png(colorize(sl, SLOPE_RAMP, 0, 60, alpha=215), "corridor_slope.png")
    cell_km2 = (px ** 2) / 1e6
    classes = [(0, 15, "Gentle (0–15°)"), (15, 30, "Moderate (15–30°)"),
               (30, 45, "Steep (30–45°)"), (45, 90, "Very steep (>45°)")]
    s_in = slope[cin]
    slope_classes = [dict(label=l, km2=float(((s_in >= a) & (s_in < z)).sum() * cell_km2),
                          pct=float(100 * ((s_in >= a) & (s_in < z)).mean())) for a, z, l in classes]
    np.save(CACHE.parent / "corridor_dem.npy", cdem); np.save(CACHE.parent / "corridor_slope.npy", slope)
    write_json(dict(
        source="AWS Open Data Terrain Tiles (Terrarium; SRTM/GMTED-derived) — interim until SRTM 1″",
        basemap=dict(layer=base, bounds=to_leaflet(b), zoom=8), skyline=skyline,
        nepal=dict(cell_km2=round(base_px ** 2 / 1e6, 4), min_m=float(elev_np.min()), max_m=float(elev_np.max()), mean_m=float(elev_np.mean()),
                   hist=dict(edges=edges.tolist(), counts=hist.tolist())),
        corridor=dict(bounds=to_leaflet(cb), zoom=11, pixel_m=round(px, 1),
                      layers=dict(elevation=elev_png, slope=slope_png),
                      min_m=float(cdem[cin].min()), max_m=float(cdem[cin].max()),
                      mean_slope=float(np.nanmean(s_in)), slope_classes=slope_classes,
                      grid=dict(bounds=cb, shape=list(cdem.shape))),
    ), "terrain.json")
    print("terrain ok", dem.shape, cdem.shape, round(px, 1))


if __name__ == "__main__":
    main()
