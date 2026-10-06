# Nepal Floods 2026

Interactive satellite-based analysis of the **26 August 2026 Rasuwa – Bhote Koshi – Trishuli flash
floods** in Nepal. A Python pipeline turns Sentinel-2, Landsat 9, rainfall, terrain and landslide
data into statistics and map layers. A single-page dashboard presents them.

Every number on the dashboard is computed from the raw data by the pipeline. None are typed in by hand.

## What the dashboard shows

| Page | Contents |
|---|---|
| Dashboard | KPIs, flood extent map (Before / After / Change), NDVI and NDWI pairs, summary charts |
| Study Area | Event corridor, data footprints, which datasets actually cover the corridor |
| Satellite Data | Observation registry, timeline, cloud / scene-classification breakdown |
| Flood Mapping | NDWI water extent, water change between dates, validation against sensor water flags |
| Vegetation Impact | NDVI, ΔNDVI, land-cover shift, corridor NDVI distribution |
| Terrain Analysis | Corridor elevation and slope, slope classes, landslide slope / elevation profiles |
| Landslide Analysis | N-LID and ICIMOD inventories, BIPAD reports by province, year and month |
| Rainfall 2025 | GPM IMERG daily rainfall map with day slider, province totals (2025 context) |
| Data Sources | Datasets, periods, resolution and event references |

## Key findings and caveats

- **The Sentinel-2 scenes (tile T44RQT) do not cover the event corridor.** They show Mustang and
  southern Tibet, ~130 km north-west. Tiles T45RUM, T45RUL and T45RTL are needed.
- **Landsat 9 on the event day is only 14 % cloud-free over the corridor** (69 % cloud, 11 % cloud edge, 5 % shadow).
- Sentinel-2 shows 10.5 km² of new water (25 Aug → 4 Sep), but haze in the 25 Aug scene inflates
  this figure. It is flagged as low confidence.
- BIPAD records 263 landslide reports across Nepal between 20 Aug and 13 Sep 2026. 2026 already has
  the most reports of any year (1,328).
- The DEM is interim (~67 m AWS Terrain Tiles) until SRTM 1″ is downloaded.
- No machine-learning results are shown. None have been trained or evaluated.

## Project structure

```
samiya/
├── public/                  Deployable site (built): index.html has all data and images inlined
├── dashboard/
│   ├── template.html        Dashboard source (HTML/CSS/JS, Leaflet + Chart.js from cdnjs)
│   └── vendor/leaflet.css   Inlined into the build
├── pipeline/
│   ├── config.py            Paths, thresholds and the observation registry
│   ├── common.py            Reprojection, colour ramps, image/JSON writers
│   ├── process_sentinel2.py NDWI / NDVI / change at 10 m with SCL cloud masking
│   ├── process_landsat.py   Landsat 9 scaling, QA masking, NDWI / MNDWI / NDVI
│   ├── process_terrain.py   Interim DEM, slope, relief basemap
│   ├── process_rainfall.py  GPM IMERG daily aggregation
│   ├── process_landslides.py N-LID, ICIMOD Koshi, BIPAD standardisation
│   ├── build_dashboard.py   Registry + builds public/index.html
│   └── run_all.py           Runs every step
├── outputs/
│   ├── stats/               JSON results the dashboard reads
│   ├── layers/              Web map overlays (Web Mercator)
│   ├── registry.json        Observation registry
│   └── nepal_precipitation_data.csv
├── data/
│   ├── landslides/          BIPAD CSV, N-LID and ICIMOD GeoPackages, QGIS projects
│   ├── boundaries/          Nepal outline and provinces (geoBoundaries)
│   └── raw/                 Satellite + rainfall inputs (not in git; see data/raw/README.md)
├── docs/                    PRD and the original design mock-up
├── requirements.txt
└── vercel.json
```

## Quick start

### View the dashboard

Open `public/index.html` in a browser. It needs an internet connection for fonts, Leaflet and Chart.js.

### Deploy on Vercel

1. Import this repository in Vercel.
2. Leave the framework preset as **Other**. `vercel.json` already sets the output directory to `public`.
3. Deploy. There is no build step; `public/index.html` is served as-is.

After changing the dashboard, rebuild `public/index.html` (below), commit and push. Vercel redeploys automatically.

### Edit the dashboard

The build only needs the committed `outputs/`, so the raw data is not required.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# edit dashboard/template.html, then:
python pipeline/build_dashboard.py      # writes public/index.html
```

### Re-run the full analysis

1. Download the raw data listed in [`data/raw/README.md`](data/raw/README.md).
2. Run:

```bash
python pipeline/run_all.py              # ~5 min; add --skip s2,landsat to skip steps
```

## Adding a new satellite date

The dashboard is data-driven:

1. Put the scene in `data/raw/sentinel2/<date>/` or `data/raw/landsat9/`.
2. Add a record to `OBSERVATIONS` in `pipeline/config.py`, and a pair to `COMPARISONS` if it
   should be compared pixel-for-pixel.
3. Run `python pipeline/run_all.py`.

The date selectors, maps, KPIs and registry table pick up the new record. No UI changes are needed.

## Method summary

- **Reflectance.** Sentinel-2: `(DN − 1000) / 10000` (baseline ≥ 04.00). Landsat 9: `DN × 0.0000275 − 0.2`.
- **Masking.** Clouds, cirrus, shadows and snow are removed using each scene's own quality layer.
  Sentinel-2 SCL clouds are buffered by 60 m. Landsat 9 uses the QA_PIXEL dilated-cloud flag as its
  buffer, with no extra dilation.
- **Water.** `NDWI = (Green − NIR) / (Green + NIR) > 0` and NIR < 0.15. The threshold is validated
  against each sensor's water class.
- **Vegetation.** `NDVI = (NIR − Red) / (NIR + Red) > 0.3`. Decline means ΔNDVI < −0.2.
- **Change.** Computed only on pixels that are clear in both scenes. Areas are pixel count × pixel area.

## Data sources

- Sentinel-2 L2A: Copernicus Data Space
- Landsat 9 C2 L2: USGS EarthExplorer
- GPM IMERG Final V07B: NASA GES DISC
- N-LID landslide inventory (2016–2020)
- ICIMOD Koshi Basin landslide inventory (2024)
- BIPAD Portal, Government of Nepal (incident reports, 2020–2026)
- AWS Open Data Terrain Tiles (interim DEM)
- geoBoundaries (country and provinces)

Event context: WHO Nepal situation reporting on the 2026 Rasuwa flash floods. WHO's preliminary
assessment of the flood mechanism is not a finding of this analysis.
