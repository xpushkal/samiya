"""Standardise the three landslide sources.

* N-LID 2016–2020 (polygons, EPSG:4326)      -> centroid points + area
* ICIMOD Koshi 2024 (polygons, EPSG:32645)   -> centroid points + elevation/slope/aspect
* BIPAD 2020–2026 (incident CSV, no coords)  -> tabular aggregates only; mapped to
  provinces/districts by name, never drawn as points (PRD §12).
The three sources cover different periods/types and cannot be de-duplicated
spatially (BIPAD has no coordinates), so they are always shown separately.
"""
import geopandas as gpd
import numpy as np
import pandas as pd

from common import write_json
from config import CORRIDOR_BBOX, CORRIDOR_DISTRICTS, LANDSLIDE_DIR, NEPAL_PROVINCES

LS = LANDSLIDE_DIR
EQ_AREA = 32645  # UTM 45N is adequate for area over Nepal


def in_bbox(g, b=CORRIDOR_BBOX):
    return (g.x >= b[0]) & (g.x <= b[2]) & (g.y >= b[1]) & (g.y <= b[3])


def province_join(pts, prov):
    j = gpd.sjoin(pts[["geometry"]], prov[["province", "geometry"]], how="left", predicate="within")
    return j[~j.index.duplicated()]["province"].reindex(pts.index)


def main():
    prov = gpd.read_file(NEPAL_PROVINCES)

    # ---- N-LID ----
    nl = gpd.read_file(LS / "nepal_landslides_2016_2020.gpkg")
    nl["area_m2"] = nl.to_crs(EQ_AREA).area
    c = nl.to_crs(EQ_AREA).centroid.to_crs(4326)
    nl_pts = gpd.GeoDataFrame(nl.drop(columns="geometry"), geometry=c, crs=4326)
    nl_pts["province"] = province_join(nl_pts, prov)
    nlid = dict(
        count=len(nl), total_area_km2=float(nl.area_m2.sum() / 1e6),
        median_area_m2=float(nl.area_m2.median()),
        by_year=nl.groupby("year").size().to_dict(),
        by_province=nl_pts.province.value_counts().to_dict(),
        in_corridor=int(in_bbox(nl_pts.geometry).sum()),
        points=[[round(g.x, 4), round(g.y, 4), int(y), round(a)] for g, y, a in
                zip(nl_pts.geometry, nl_pts.year, nl_pts.area_m2)],
    )

    # ---- ICIMOD Koshi 2024 ----
    ko = gpd.read_file(LS / "landslides_koshi_2024.gpkg")
    ko["area_m2"] = ko.area
    kc = ko.centroid.to_crs(4326)
    ko_pts = gpd.GeoDataFrame(ko.drop(columns="geometry"), geometry=kc, crs=4326)
    ko_pts["province"] = province_join(ko_pts, prov)
    eb = np.arange(0, 7001, 500); sb = np.arange(0, 71, 5)
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    asp = ((ko.Aspect.clip(lower=0) + 22.5) // 45 % 8).astype(int)
    koshi = dict(
        count=len(ko), total_area_km2=float(ko.area_m2.sum() / 1e6),
        median_area_m2=float(ko.area_m2.median()),
        mean_slope=float(ko.Slope.mean()), median_elev=float(ko.Elevation.median()),
        elev_hist=dict(edges=eb.tolist(), counts=np.histogram(ko.Elevation, eb)[0].tolist()),
        slope_hist=dict(edges=sb.tolist(), counts=np.histogram(ko.Slope, sb)[0].tolist()),
        aspect=[dict(dir=d, n=int((asp == i).sum())) for i, d in enumerate(dirs)],
        by_province=ko_pts.province.value_counts().to_dict(),
        in_corridor=int(in_bbox(ko_pts.geometry).sum()),
        points=[[round(g.x, 4), round(g.y, 4), int(e), int(s), round(a)] for g, e, s, a in
                zip(ko_pts.geometry, ko.Elevation, ko.Slope, ko.area_m2)],
    )

    # ---- BIPAD ----
    b = pd.read_csv(LS / "bipad_landslides_2020-2026.csv")
    b["date"] = pd.to_datetime(b["Incident on"])
    cols = {"Total - People Death": "deaths", "Total - People Missing": "missing",
            "Total - People Injured": "injured", "House destroyed": "houses_destroyed",
            "House affected": "houses_affected", "Total estimated loss (NPR)": "loss_npr"}
    b = b.rename(columns=cols)
    agg = lambda g: g.agg(incidents=("Title", "size"), deaths=("deaths", "sum"), missing=("missing", "sum"),
                          injured=("injured", "sum"), houses_destroyed=("houses_destroyed", "sum"),
                          loss_npr=("loss_npr", "sum"))
    yearly = agg(b.groupby(b.date.dt.year)).reset_index(names="year")
    monthly = b.groupby([b.date.dt.year.rename("y"), b.date.dt.month.rename("m")]).size().unstack(fill_value=0)
    by_district = agg(b.groupby("District")).reset_index().sort_values("incidents", ascending=False)
    ev = b[(b.date >= "2026-08-20") & (b.date <= "2026-09-13")]
    event_daily = ev.groupby(ev.date.dt.strftime("%Y-%m-%d")).size().to_dict()
    corr = b[b.District.isin(CORRIDOR_DISTRICTS)]
    corr_2026 = corr[corr.date.dt.year == 2026]
    bipad = dict(
        count=len(b), period=[b.date.min().strftime("%Y-%m-%d"), b.date.max().strftime("%Y-%m-%d")],
        totals={k: float(b[k].sum()) for k in cols.values()},
        yearly=yearly.to_dict("records"),
        monthly={int(y): monthly.loc[y].reindex(range(1, 13), fill_value=0).tolist() for y in monthly.index},
        by_province=b.Province.value_counts().to_dict(),
        by_district=by_district.head(20).to_dict("records"),
        event_window=dict(start="2026-08-20", end="2026-09-13", incidents=len(ev),
                          deaths=int(ev.deaths.sum()), missing=int(ev.missing.sum()), daily=event_daily,
                          top_districts=ev.District.value_counts().head(10).to_dict()),
        corridor=dict(districts=CORRIDOR_DISTRICTS, incidents_all=len(corr), incidents_2026=len(corr_2026),
                      deaths_all=int(corr.deaths.sum()),
                      by_district=corr.groupby("District").size().to_dict(),
                      recent=corr[corr.date >= "2026-08-15"].sort_values("date", ascending=False)
                      [["date", "Title", "District", "deaths", "missing", "injured"]]
                      .assign(date=lambda d: d.date.dt.strftime("%Y-%m-%d")).to_dict("records")),
    )
    write_json(dict(nlid=nlid, koshi=koshi, bipad=bipad), "landslides.json")
    print("N-LID", nlid["count"], "corridor", nlid["in_corridor"], "| Koshi", koshi["count"],
          "corridor", koshi["in_corridor"], "| BIPAD", bipad["count"])
    print(bipad["event_window"]); print(bipad["corridor"]["by_district"], len(bipad["corridor"]["recent"]))


if __name__ == "__main__":
    main()
