"""Landsat 9 C2 L2 event-day scene: scaling, QA masking, NDWI / MNDWI / NDVI.

SR = DN * 0.0000275 - 0.2. QA_PIXEL bits used: 0 fill, 1 dilated cloud, 2 cirrus,
3 cloud, 4 cloud shadow, 5 snow, 7 water. Stats are computed at native 30 m for
the full scene and for the Rasuwa–Bhote Koshi–Trishuli corridor.
"""
import geopandas as gpd
import numpy as np
from scipy.ndimage import binary_dilation
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import Resampling, transform_bounds
from rasterio.windows import from_bounds

from common import (NDVI_RAMP, NDWI_RAMP, categorical, colorize, save_png, save_webp, stretch,
                    to_webmerc, write_json)
from config import CLOUD_BUFFER_M, NIR_WATER_MAX, CORRIDOR_BBOX, NDVI_VEG, NDWI_WATER, NEPAL_ADM0, OBSERVATIONS, RASTERS

PIX_KM2 = 900 / 1e6


def nd(a, b):
    with np.errstate(invalid="ignore", divide="ignore"):
        return (a - b) / (a + b)


def agg(a, f, how="mean"):
    h, w = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    b = a[:h, :w].reshape(h // f, f, w // f, f)
    with np.errstate(invalid="ignore"):
        return np.nanmean(b, (1, 3)) if how == "mean" else b[:, f // 2, :, f // 2]


def analyse(obs, window, label, f, nepal):
    pre = str(obs["prefix"])
    rd = lambda b: rasterio.open(f"{pre}_{b}.TIF")
    with rd("QA_PIXEL") as q:
        qa = q.read(1, window=window); T = q.window_transform(window); crs = q.crs
    fill = (qa & 1) > 0
    cloud = (qa & (1 << 1 | 1 << 2 | 1 << 3)) > 0
    shadow = (qa & (1 << 4)) > 0
    snow = (qa & (1 << 5)) > 0
    qa_water = (qa & (1 << 7)) > 0
    buf = binary_dilation(cloud | shadow, iterations=CLOUD_BUFFER_M // 30)
    valid = ~fill & ~buf & ~snow
    sr = {}
    for b in ("SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6"):
        with rd(b) as s:
            dn = s.read(1, window=window).astype(np.float32)
        sr[b] = np.where(dn > 0, dn * 0.0000275 - 0.2, np.nan)
    ndwi = nd(sr["SR_B3"], sr["SR_B5"])
    mndwi = nd(sr["SR_B3"], sr["SR_B6"])
    ndvi = nd(sr["SR_B5"], sr["SR_B4"])
    valid &= np.isfinite(ndwi) & np.isfinite(ndvi)
    dark = sr["SR_B5"] < NIR_WATER_MAX
    water = valid & (ndwi > NDWI_WATER) & dark
    mwater = valid & (mndwi > NDWI_WATER) & dark
    veg = valid & (ndvi > NDVI_VEG) & ~water
    in_np = ~geometry_mask(nepal.to_crs(crs).geometry, qa.shape, T)
    scene = ~fill
    k = lambda m: float(m.sum() * PIX_KM2)
    stats = dict(
        scene_km2=k(scene), clear_km2=k(valid), clear_pct=100 * valid.sum() / max(scene.sum(), 1),
        cloud_pct=100 * (cloud & scene).sum() / max(scene.sum(), 1),
        shadow_pct=100 * (shadow & scene & ~cloud).sum() / max(scene.sum(), 1),
        snow_pct=100 * (snow & scene & ~cloud).sum() / max(scene.sum(), 1),
        nepal_km2=k(scene & in_np), clear_nepal_km2=k(valid & in_np),
        water_ndwi_km2=k(water), water_mndwi_km2=k(mwater), water_nepal_km2=k(water & in_np),
        veg_km2=k(veg), veg_nepal_km2=k(veg & in_np),
        qa_water_km2=k(qa_water & valid),
        ndwi_vs_qa_water_recall=100 * (water & qa_water).sum() / max((qa_water & valid).sum(), 1),
        mean_ndvi=float(np.nanmean(ndvi[valid])) if valid.any() else None,
        ndvi_hist=np.histogram(ndvi[valid], bins=20, range=(-0.2, 0.8))[0].tolist() if valid.any() else [],
    )

    # ---- previews (aggregated) ----
    ndwi_v = np.where(valid, ndwi, np.nan); ndvi_v = np.where(valid, ndvi, np.nan)
    pt = T * rasterio.Affine.scale(f)
    layers = {}
    w, bounds = to_webmerc(agg(ndwi_v, f).astype(np.float32), pt, crs)
    layers["ndwi"] = save_png(colorize(w, NDWI_RAMP, -0.6, 0.6), f"{obs['id']}_{label}_ndwi.png")
    w, _ = to_webmerc(agg(ndvi_v, f).astype(np.float32), pt, crs)
    layers["ndvi"] = save_png(colorize(w, NDVI_RAMP, -0.1, 0.8), f"{obs['id']}_{label}_ndvi.png")
    wm = agg(water.astype(np.float32), f)
    w, _ = to_webmerc(np.where(wm > 0, 1, np.nan).astype(np.float32), pt, crs)
    layers["water"] = save_png(categorical(np.nan_to_num(w).round().astype(np.uint8), {1: (0, 200, 255, 255)}),
                               f"{obs['id']}_{label}_water.png")
    m = np.zeros(qa.shape, np.uint8); m[valid] = 1; m[cloud] = 2; m[shadow & ~cloud] = 3; m[snow & ~cloud] = 4; m[fill] = 0
    w, _ = to_webmerc(agg(m, f, "sample"), pt, crs, Resampling.nearest, nodata=0)
    layers["mask"] = save_png(categorical(w, {2: (235, 235, 245, 200), 3: (40, 40, 60, 170),
                                              4: (160, 220, 255, 200)}), f"{obs['id']}_{label}_mask.png")
    vis = ~fill & np.isfinite(sr["SR_B4"])
    rgb = []
    for b in ("SR_B4", "SR_B3", "SR_B2"):
        a = agg(np.where(vis, sr[b], np.nan), f).astype(np.float32)
        wv, _ = to_webmerc(a, pt, crs)
        rgb.append(wv)
    tc = np.stack([stretch(np.nan_to_num(c), 1, 97, np.isfinite(c) & (c < 0.3)) for c in rgb], -1)
    layers["truecolor"] = save_webp(tc, f"{obs['id']}_{label}_truecolor.webp", alpha=np.isfinite(rgb[0]))
    if label == "corridor":
        with rasterio.open(RASTERS / f"{obs['id']}_corridor_ndwi_30m.tif", "w", driver="GTiff",
                           height=ndwi.shape[0], width=ndwi.shape[1], count=2, dtype="float32",
                           crs=crs, transform=T, nodata=np.nan, compress="deflate") as dst:
            dst.write(ndwi_v.astype(np.float32), 1); dst.write(ndvi_v.astype(np.float32), 2)
            dst.set_band_description(1, "NDWI"); dst.set_band_description(2, "NDVI")
    return dict(stats=stats, layers=layers, bounds=bounds, preview_m=30 * f)


def main():
    obs = next(o for o in OBSERVATIONS if o["platform"] == "landsat")
    nepal = gpd.read_file(NEPAL_ADM0)
    with rasterio.open(f"{obs['prefix']}_QA_PIXEL.TIF") as q:
        full = rasterio.windows.Window(0, 0, q.width, q.height)
        cb = transform_bounds("EPSG:4326", q.crs, *CORRIDOR_BBOX)
        cw = from_bounds(*cb, transform=q.transform).round_offsets().round_lengths()
        cw = cw.intersection(full)
        foot = transform_bounds(q.crs, "EPSG:4326", *q.bounds)
    out = dict(scene=analyse(obs, full, "scene", 5, nepal),
               corridor=analyse(obs, cw, "corridor", 2, nepal),
               corridor_bbox=CORRIDOR_BBOX, footprint_bbox=foot)
    write_json(out, "landsat9.json")
    print({k: out[k]["stats"]["clear_pct"] for k in ("scene", "corridor")})


if __name__ == "__main__":
    main()
