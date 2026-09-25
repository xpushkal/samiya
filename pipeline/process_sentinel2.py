"""Sentinel-2 L2A: NDWI, NDVI, water change and vegetation change at native 10 m.

* Reflectance = (DN + BOA_ADD_OFFSET) / 10000 (processing baseline >= 04.00).
* Clear-sky mask from the Scene Classification Layer (SCL): keep vegetation (4),
  not-vegetated (5), water (6), unclassified (7). Clouds, cirrus, shadows,
  snow, saturated and no-data pixels are excluded.
* All areas are pixel counts x 100 m^2 at 10 m; previews are aggregated to 100 m.
"""
import re

from scipy.ndimage import binary_dilation, grey_dilation

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window

from common import (DIFF_RAMP, NDVI_RAMP, NDWI_RAMP, categorical, colorize, save_png, save_webp,
                    to_webmerc, write_json)
from config import (CLOUD_BUFFER_M, COMPARISONS, NIR_WATER_MAX, NDVI_DECLINE, NDVI_VEG, NDWI_WATER, NEPAL_ADM0, OBSERVATIONS,
                    RASTERS)
from rasterio.warp import Resampling

STRIP = 1220          # rows per strip (10980 = 9 x 1220)
AGG = 10              # 10 m -> 100 m preview blocks
PIX_KM2 = 100 / 1e6
SCL_NAMES = {0: "No data", 1: "Saturated / defective", 2: "Topographic shadow", 3: "Cloud shadow",
             4: "Vegetation", 5: "Not vegetated", 6: "Water", 7: "Unclassified",
             8: "Cloud (medium prob.)", 9: "Cloud (high prob.)", 10: "Thin cirrus", 11: "Snow / ice"}
CLEAR = [4, 5, 6, 7]


def band_path(obs, band, res):
    return next(obs["safe"].glob(f"GRANULE/*/IMG_DATA/R{res}m/*_{band}_{res}m.jp2"))


def boa_offset(obs):
    txt = (obs["safe"] / "MTD_MSIL2A.xml").read_text()
    m = re.search(r"<BOA_ADD_OFFSET[^>]*>(-?\d+)", txt)
    return int(m.group(1)) if m else 0


def block_mean(a, valid):
    h, w = a.shape
    s = np.where(valid, a, 0).reshape(h // AGG, AGG, w // AGG, AGG).sum((1, 3))
    n = valid.reshape(h // AGG, AGG, w // AGG, AGG).sum((1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > AGG * AGG * 0.25, s / n, np.nan).astype(np.float32)


def block_max(a):
    h, w = a.shape
    return a.reshape(h // AGG, AGG, w // AGG, AGG).max((1, 3))


def nd(a, b):
    with np.errstate(invalid="ignore", divide="ignore"):
        return (a - b) / (a + b)


def main():
    s2 = [o for o in OBSERVATIONS if o["platform"] == "sentinel2"]
    ref = rasterio.open(band_path(s2[0], "B03", 10))
    H, W, T, CRS = ref.height, ref.width, ref.transform, ref.crs
    nepal = gpd.read_file(NEPAL_ADM0).to_crs(CRS).geometry

    per = {o["id"]: dict(valid=0, valid_np=0, water=0, water_np=0, veg=0, veg_np=0,
                         scl_water=0, scl_water_hit=0, ndwi_water_in_scl=0,
                         ndvi_sum=0.0, ndwi_sum=0.0, footprint=0, scl=np.zeros(12, np.int64),
                         prev_ndwi=[], prev_ndvi=[], prev_scl=[]) for o in s2}
    cmp = {f"{a}__{b}": dict(common=0, common_np=0, persist=0, new=0, lost=0, new_np=0, lost_np=0,
                             persist_np=0, veg_before=0, veg_after=0, veg_decline=0, veg_gain=0,
                             veg_decline_np=0, dndvi_sum=0.0, bare_before=0, bare_after=0,
                             water_before=0, water_after=0, prev_cls=[], prev_dndvi=[],
                             cls_full=np.zeros((H, W), np.uint8))
           for a, b in COMPARISONS}
    offs = {o["id"]: boa_offset(o) for o in s2}
    srcs = {o["id"]: {b: rasterio.open(band_path(o, b, 10)) for b in ("B03", "B04", "B08")} |
            {"SCL": rasterio.open(band_path(o, "SCL", 20))} for o in s2}

    for r0 in range(0, H, STRIP):
        win = Window(0, r0, W, STRIP)
        wt = rasterio.windows.transform(win, T)
        in_np = ~geometry_mask(nepal, (STRIP, W), wt)
        strip = {}
        for o in s2:
            s = srcs[o["id"]]
            off = offs[o["id"]]
            g, r, n = (s[b].read(1, window=win).astype(np.float32) for b in ("B03", "B04", "B08"))
            dn_ok = (g > 0) & (n > 0)
            g, r, n = ((x + off) / 10000.0 for x in (g, r, n))
            # read SCL with a halo so the cloud buffer is seamless across strips
            halo = CLOUD_BUFFER_M // 20
            a0 = max(r0 // 2 - halo, 0); a1 = min((r0 + STRIP) // 2 + halo, H // 2)
            scl_h = s["SCL"].read(1, window=Window(0, a0, W // 2, a1 - a0))
            cloudy = binary_dilation(np.isin(scl_h, [3, 8, 9, 10]), iterations=halo)
            k0 = r0 // 2 - a0
            scl, cloudy = (np.repeat(np.repeat(x[k0:k0 + STRIP // 2], 2, 0), 2, 1) for x in (scl_h, cloudy))
            valid = np.isin(scl, CLEAR) & dn_ok & ~cloudy
            ndwi, ndvi = nd(g, n), nd(n, r)
            valid &= np.isfinite(ndwi) & np.isfinite(ndvi)
            water = valid & (ndwi > NDWI_WATER) & (n < NIR_WATER_MAX)
            veg = valid & (ndvi > NDVI_VEG) & ~water
            p = per[o["id"]]
            p["footprint"] += int((scl > 0).sum())
            p["scl"] += np.bincount(scl.ravel(), minlength=12)[:12]
            p["valid"] += int(valid.sum()); p["valid_np"] += int((valid & in_np).sum())
            p["water"] += int(water.sum()); p["water_np"] += int((water & in_np).sum())
            p["veg"] += int(veg.sum()); p["veg_np"] += int((veg & in_np).sum())
            p["ndvi_sum"] += float(ndvi[valid].sum()); p["ndwi_sum"] += float(ndwi[valid].sum())
            sw = scl == 6
            p["scl_water"] += int(sw.sum()); p["scl_water_hit"] += int((sw & water).sum())
            p["ndwi_water_in_scl"] += int((water & sw).sum())
            p["prev_ndwi"].append(block_mean(ndwi, valid))
            p["prev_ndvi"].append(block_mean(ndvi, valid))
            # preview mask: 0 no data, 1 clear, 2 cloud/cirrus, 3 shadow, 4 snow
            m = np.zeros(scl.shape, np.uint8)
            m[valid] = 1; m[np.isin(scl, [8, 9, 10])] = 2; m[np.isin(scl, [2, 3])] = 3; m[scl == 11] = 4
            p["prev_scl"].append(m[AGG // 2::AGG, AGG // 2::AGG])
            strip[o["id"]] = dict(valid=valid, water=water, veg=veg, ndvi=ndvi)

        for a, b in COMPARISONS:
            c = cmp[f"{a}__{b}"]
            A, B = strip[a], strip[b]
            common = A["valid"] & B["valid"]
            persist = common & A["water"] & B["water"]
            new = common & ~A["water"] & B["water"]
            lost = common & A["water"] & ~B["water"]
            dndvi = np.where(common, B["ndvi"] - A["ndvi"], np.nan)
            vb = common & A["veg"]
            c["common"] += int(common.sum()); c["common_np"] += int((common & in_np).sum())
            c["persist"] += int(persist.sum()); c["new"] += int(new.sum()); c["lost"] += int(lost.sum())
            c["persist_np"] += int((persist & in_np).sum())
            c["new_np"] += int((new & in_np).sum()); c["lost_np"] += int((lost & in_np).sum())
            c["water_before"] += int((common & A["water"]).sum()); c["water_after"] += int((common & B["water"]).sum())
            c["veg_before"] += int(vb.sum()); c["veg_after"] += int((common & B["veg"]).sum())
            c["bare_before"] += int((common & ~A["water"] & ~A["veg"]).sum())
            c["bare_after"] += int((common & ~B["water"] & ~B["veg"]).sum())
            dec = vb & (dndvi < NDVI_DECLINE)
            c["veg_decline"] += int(dec.sum()); c["veg_decline_np"] += int((dec & in_np).sum())
            c["veg_gain"] += int((common & B["veg"] & ~A["veg"] & (dndvi > -NDVI_DECLINE)).sum())
            c["dndvi_sum"] += float(np.nansum(dndvi))
            cls = np.zeros(common.shape, np.uint8)
            cls[common] = 1; cls[persist] = 2; cls[lost] = 3; cls[new] = 4
            c["cls_full"][r0:r0 + STRIP] = cls
            c["prev_cls"].append(block_max(cls))
            c["prev_dndvi"].append(block_mean(np.nan_to_num(dndvi), common))
        print(f"strip {r0 // STRIP + 1}/{H // STRIP} done", flush=True)

    pt = rasterio.Affine(T.a * AGG, 0, T.c, 0, T.e * AGG, T.f)
    obs_out = {}
    for o in s2:
        p = per[o["id"]]
        ndwi = np.vstack(p["prev_ndwi"]); ndvi = np.vstack(p["prev_ndvi"]); m = np.vstack(p["prev_scl"])
        layers = {}
        w, bounds = to_webmerc(ndwi, pt, CRS)
        layers["ndwi"] = save_png(colorize(w, NDWI_RAMP, -0.6, 0.6), f"{o['id']}_ndwi.png")
        w, _ = to_webmerc(ndvi, pt, CRS)
        layers["ndvi"] = save_png(colorize(w, NDVI_RAMP, -0.1, 0.8), f"{o['id']}_ndvi.png")
        w, _ = to_webmerc(m, pt, CRS, Resampling.nearest, nodata=0)
        layers["mask"] = save_png(categorical(w, {2: (235, 235, 245, 200), 3: (40, 40, 60, 170),
                                                  4: (160, 220, 255, 200)}), f"{o['id']}_mask.png")
        with rasterio.open(band_path(o, "TCI", 20)) as tci:
            rgb = tci.read(out_shape=(3, H // AGG, W // AGG), resampling=Resampling.average)
        chans = [to_webmerc(rgb[i].astype(np.float32), pt, CRS, nodata=0.0)[0] for i in range(3)]
        tc = np.clip(np.stack(chans, -1), 0, 255).astype(np.uint8)
        layers["truecolor"] = save_webp(tc, f"{o['id']}_truecolor.webp", alpha=chans[0] > 0)
        _write_tif(ndwi, pt, CRS, RASTERS / f"{o['id']}_ndwi_100m.tif")
        _write_tif(ndvi, pt, CRS, RASTERS / f"{o['id']}_ndvi_100m.tif")
        fp = p["footprint"]
        obs_out[o["id"]] = dict(
            bounds=bounds, layers=layers, pixel_size_m=10,
            footprint_km2=fp * PIX_KM2,
            clear_km2=p["valid"] * PIX_KM2, clear_pct=100 * p["valid"] / fp,
            clear_nepal_km2=p["valid_np"] * PIX_KM2,
            water_km2=p["water"] * PIX_KM2, water_nepal_km2=p["water_np"] * PIX_KM2,
            veg_km2=p["veg"] * PIX_KM2, veg_nepal_km2=p["veg_np"] * PIX_KM2,
            mean_ndvi=p["ndvi_sum"] / max(p["valid"], 1), mean_ndwi=p["ndwi_sum"] / max(p["valid"], 1),
            ndwi_vs_scl_water_recall=100 * p["scl_water_hit"] / max(p["scl_water"], 1),
            ndwi_water_confirmed_by_scl=100 * p["ndwi_water_in_scl"] / max(p["water"], 1),
            scl_classes=[dict(code=k, name=SCL_NAMES[k], km2=int(v) * PIX_KM2,
                              pct=100 * int(v) / int(p["scl"].sum())) for k, v in enumerate(p["scl"])],
        )

    cmp_out = {}
    for a, b in COMPARISONS:
        key = f"{a}__{b}"; c = cmp[key]
        cls = np.vstack(c["prev_cls"]); d = np.vstack(c["prev_dndvi"])
        # display only: widen change pixels to 3x3 so narrow channels stay visible at
        # overview zoom (class order = priority: new > lost > persistent > land)
        cls_view = grey_dilation(cls, size=3)
        w, bounds = to_webmerc(cls_view, pt, CRS, Resampling.nearest, nodata=0)
        change = save_png(categorical(w, {2: (40, 110, 220, 230), 3: (245, 160, 40, 240),
                                          4: (0, 220, 255, 255)}), f"{key}_water_change.png")
        w, _ = to_webmerc(d, pt, CRS)
        dpng = save_png(colorize(w, DIFF_RAMP, -0.4, 0.4), f"{key}_dndvi.png")
        with rasterio.open(RASTERS / f"{key}_water_change_10m.tif", "w", driver="GTiff", height=H,
                           width=W, count=1, dtype="uint8", crs=CRS, transform=T, nodata=0,
                           compress="deflate", tiled=True) as dst:
            dst.write(c["cls_full"], 1)
            dst.write_colormap(1, {1: (200, 200, 200), 2: (40, 110, 220), 3: (245, 160, 40), 4: (0, 220, 255)})
        _write_tif(d, pt, CRS, RASTERS / f"{key}_dndvi_100m.tif")
        k = lambda v: v * PIX_KM2
        cmp_out[key] = dict(
            before=a, after=b, bounds=bounds, layers=dict(water_change=change, dndvi=dpng),
            common_clear_km2=k(c["common"]), common_clear_nepal_km2=k(c["common_np"]),
            water_before_km2=k(c["water_before"]), water_after_km2=k(c["water_after"]),
            persistent_water_km2=k(c["persist"]), new_water_km2=k(c["new"]), lost_water_km2=k(c["lost"]),
            persistent_water_nepal_km2=k(c["persist_np"]), new_water_nepal_km2=k(c["new_np"]),
            lost_water_nepal_km2=k(c["lost_np"]),
            veg_before_km2=k(c["veg_before"]), veg_after_km2=k(c["veg_after"]),
            bare_before_km2=k(c["bare_before"]), bare_after_km2=k(c["bare_after"]),
            veg_decline_km2=k(c["veg_decline"]), veg_decline_nepal_km2=k(c["veg_decline_np"]),
            veg_gain_km2=k(c["veg_gain"]), mean_dndvi=c["dndvi_sum"] / max(c["common"], 1),
        )
    write_json(dict(observations=obs_out, comparisons=cmp_out,
                    thresholds=dict(ndwi_water=NDWI_WATER, nir_water_max=NIR_WATER_MAX, cloud_buffer_m=CLOUD_BUFFER_M, ndvi_veg=NDVI_VEG, ndvi_decline=NDVI_DECLINE),
                    boa_offset=offs), "sentinel2.json")


def _write_tif(a, t, crs, path):
    with rasterio.open(path, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=1,
                       dtype="float32", crs=crs, transform=t, nodata=np.nan, compress="deflate") as dst:
        dst.write(a, 1)


if __name__ == "__main__":
    main()
