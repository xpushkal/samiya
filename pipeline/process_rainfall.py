"""GPM IMERG Final daily (V07B), 1 Jul – 31 Aug 2025: Nepal rainfall context.

This is historical 2025 monsoon context and is NOT event-day 2026 rainfall.
Outputs a per-day CSV, province season totals and a compact per-cell daily
grid (cells whose centres fall inside Nepal) for the dashboard's day slider.
"""
import re

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from rasterio.transform import from_origin

from common import write_json
from config import CORRIDOR_BBOX, IMERG_DIR, NEPAL_ADM0, NEPAL_PROVINCES, OUT

BOX = (80.0, 26.3, 88.3, 30.5)
SUB = 5  # supersampling for province area-weighting (0.02°)


def main():
    files = sorted(IMERG_DIR.glob("3B-DAY.MS.MRG.3IMERG.*.nc4"))
    with h5py.File(files[0]) as h:
        lon = h["lon"][:]; lat = h["lat"][:]
    i0, i1 = np.searchsorted(lon, BOX[0]), np.searchsorted(lon, BOX[2])
    j0, j1 = np.searchsorted(lat, BOX[1]), np.searchsorted(lat, BOX[3])
    lons, lats = lon[i0:i1], lat[j0:j1][::-1]             # north-up
    nx, ny = len(lons), len(lats)
    t = from_origin(lons[0] - 0.05, lats[0] + 0.05, 0.1, 0.1)
    nepal = gpd.read_file(NEPAL_ADM0).geometry
    inside = rasterize(((g, 1) for g in nepal), (ny, nx), transform=t).astype(bool)
    corridor = ((lons[None, :] >= CORRIDOR_BBOX[0]) & (lons[None, :] <= CORRIDOR_BBOX[2]) &
                (lats[:, None] >= CORRIDOR_BBOX[1]) & (lats[:, None] <= CORRIDOR_BBOX[3]))

    days, grids = [], []
    for f in files:
        d = re.search(r"\.(\d{8})-S", f.name).group(1)
        with h5py.File(f) as h:
            p = h["precipitation"][0, i0:i1, j0:j1].T[::-1].astype(np.float32)  # (lat, lon) north-up
        p[p < 0] = np.nan
        grids.append(p)
        v = p[inside]
        days.append(dict(date=pd.to_datetime(d).strftime("%Y-%m-%d"),
                         nepal_mean_mm=float(np.nanmean(v)), nepal_max_mm=float(np.nanmax(v)),
                         nepal_p95_mm=float(np.nanpercentile(v, 95)),
                         corridor_mean_mm=float(np.nanmean(p[corridor])),
                         cells_over_50mm=int((v > 50).sum()), cells_over_100mm=int((v > 100).sum()),
                         nepal_cells=int(inside.sum())))
    stack = np.stack(grids)
    total = stack.sum(0)
    df = pd.DataFrame(days)
    df.to_csv(OUT / "nepal_precipitation_data.csv", index=False)

    # province season totals, area-weighted on a 0.02° supersampled grid
    adm1 = gpd.read_file(NEPAL_PROVINCES)
    ts = from_origin(lons[0] - 0.05, lats[0] + 0.05, 0.1 / SUB, 0.1 / SUB)
    ids = rasterize(((g, i + 1) for i, g in enumerate(adm1.geometry)), (ny * SUB, nx * SUB), transform=ts)
    tot_hi = np.repeat(np.repeat(total, SUB, 0), SUB, 1)
    peak_hi = np.repeat(np.repeat(stack.max(0), SUB, 0), SUB, 1)
    provinces = {}
    for i, name in enumerate(adm1.province):
        m = ids == i + 1
        if m.any():
            provinces[name] = dict(total_mm=round(float(tot_hi[m].mean()), 1),
                                   peak_day_mm=round(float(peak_hi[m].max()), 1))

    iy, ix = np.nonzero(inside)
    peak = df.loc[df.nepal_mean_mm.idxmax()]
    write_json(dict(
        source="NASA GPM IMERG Final Run daily V07B (0.1°), precipitation variable",
        note="2025 monsoon context — not 2026 event-day rainfall",
        period=[df.date.iloc[0], df.date.iloc[-1]], daily=days,
        season=dict(nepal_mean_total_mm=float(total[inside].mean()),
                    nepal_max_total_mm=float(total[inside].max()),
                    corridor_mean_total_mm=float(total[corridor].mean()),
                    wettest_day=peak.date, wettest_day_mean_mm=float(peak.nepal_mean_mm),
                    days_any_cell_over_100mm=int((df.cells_over_100mm > 0).sum())),
        provinces=provinces,
        grid=dict(lon0=float(lons[0]), lat0=float(lats[0]), step=0.1, nx=nx, ny=ny,
                  cells=np.stack([iy, ix], 1).tolist(),
                  daily=[np.round(g[inside], 1).tolist() for g in grids],
                  total=np.round(total[inside], 0).tolist()),
    ), "rainfall.json")
    print(df.describe().T[["mean", "max"]])


if __name__ == "__main__":
    main()
