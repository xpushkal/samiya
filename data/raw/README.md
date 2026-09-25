# Raw input data

These files are **not in the repository** (3.7 GB total). The dashboard in `public/` and the
processed results in `outputs/` do not need them. You only need them to re-run the
satellite and rainfall steps of the pipeline.

Download each dataset into the folder shown, keeping the file names.

## Sentinel-2 L2A (Copernicus Data Space)

Source: <https://dataspace.copernicus.eu/>. Unzip each `.SAFE` product and put its
contents into a folder named after the acquisition date.

| Folder | Product |
|---|---|
| `sentinel2/2026-08-25/` | `S2C_MSIL2A_20260825T050651_N0512_R019_T44RQT_20260825T100415` |
| `sentinel2/2026-09-04/` | `S2C_MSIL2A_20260904T050651_N0512_R019_T44RQT_20260904T100557` |

Each folder must contain `MTD_MSIL2A.xml` and `GRANULE/*/IMG_DATA/R10m|R20m/`.

> Tile T44RQT does not cover the Rasuwa – Trishuli corridor. The corridor is covered by
> tiles **T45RUM**, **T45RUL** and **T45RTL**. Add those scenes to improve the flood analysis.

## Landsat 9 Collection 2 Level-2 (USGS EarthExplorer)

Source: <https://earthexplorer.usgs.gov/>. Scene `LC09_L2SP_141040_20260826_20260827_02_T1`.
Put these files in `landsat9/`:

```
LC09_L2SP_141040_20260826_20260827_02_T1_SR_B2.TIF
LC09_L2SP_141040_20260826_20260827_02_T1_SR_B3.TIF
LC09_L2SP_141040_20260826_20260827_02_T1_SR_B4.TIF
LC09_L2SP_141040_20260826_20260827_02_T1_SR_B5.TIF
LC09_L2SP_141040_20260826_20260827_02_T1_SR_B6.TIF
LC09_L2SP_141040_20260826_20260827_02_T1_SR_B7.TIF
LC09_L2SP_141040_20260826_20260827_02_T1_QA_PIXEL.TIF
```

## GPM IMERG Final daily, V07B (NASA GES DISC)

Source: <https://disc.gsfc.nasa.gov/> (collection `GPM_3IMERGDF`, version 07). 62 daily
files, 1 July – 31 August 2025, into `imerg/`:

```
3B-DAY.MS.MRG.3IMERG.20250701-S000000-E235959.V07B.nc4
...
3B-DAY.MS.MRG.3IMERG.20250831-S000000-E235959.V07B.nc4
```

## Not needed from here

- **DEM**: `pipeline/process_terrain.py` downloads public AWS Terrain Tiles into `data/dem/`
  automatically.
- **Landslides and boundaries**: already in the repository under `data/landslides/` and
  `data/boundaries/`.
