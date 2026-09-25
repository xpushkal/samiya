"""Helpers: reprojection to Web Mercator, colour ramps, image + JSON writers."""
import json

import numpy as np
from PIL import Image
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

from config import LAYERS, STATS


def to_webmerc(arr, src_transform, src_crs, resampling=Resampling.bilinear, nodata=np.nan):
    """Reproject a 2-D array to EPSG:3857; return (array, [[s, w], [n, e]] in WGS84)."""
    h, w = arr.shape
    dst_t, dw, dh = calculate_default_transform(src_crs, "EPSG:3857", w, h,
                                                *array_bounds(h, w, src_transform))
    dst = np.full((dh, dw), nodata, dtype=arr.dtype)
    reproject(arr, dst, src_transform=src_transform, src_crs=src_crs, dst_transform=dst_t,
              dst_crs="EPSG:3857", resampling=resampling, src_nodata=nodata, dst_nodata=nodata)
    west, south, east, north = transform_bounds("EPSG:3857", "EPSG:4326",
                                                *array_bounds(dh, dw, dst_t))
    return dst, [[round(south, 5), round(west, 5)], [round(north, 5), round(east, 5)]]


def ramp(stops):
    """Build a 256-entry RGB lookup from [(pos 0..1, '#rrggbb'), ...]."""
    pos = np.array([s[0] for s in stops])
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _, c in stops], float)
    x = np.linspace(0, 1, 256)
    return np.stack([np.interp(x, pos, rgb[:, k]) for k in range(3)], 1).astype(np.uint8)


NDWI_RAMP = ramp([(0, "#f7f4ea"), (0.45, "#cfe3f2"), (0.55, "#6fb1e4"), (0.75, "#1f6fd1"), (1, "#08306b")])
NDVI_RAMP = ramp([(0, "#8c2d04"), (0.3, "#d8a24a"), (0.5, "#f2e6a0"), (0.7, "#7bc86c"), (1, "#0b5d1e")])
DIFF_RAMP = ramp([(0, "#b2182b"), (0.4, "#f4a582"), (0.5, "#f7f7f7"), (0.6, "#92c5de"), (1, "#2166ac")])
ELEV_RAMP = ramp([(0, "#2d6a4f"), (0.12, "#74a860"), (0.25, "#d9c77a"), (0.45, "#b0763c"),
                  (0.65, "#8a5a44"), (0.82, "#c9c1bc"), (1, "#ffffff")])
SLOPE_RAMP = ramp([(0, "#fff7bc"), (0.33, "#fec44f"), (0.6, "#ec7014"), (1, "#7a0177")])


def colorize(arr, lut, vmin, vmax, alpha=255):
    """Continuous array -> RGBA uint8; NaN becomes transparent."""
    valid = np.isfinite(arr)
    idx = np.clip((np.nan_to_num(arr) - vmin) / (vmax - vmin), 0, 1) * 255
    rgba = np.zeros(arr.shape + (4,), np.uint8)
    rgba[..., :3] = lut[idx.astype(np.uint8)]
    rgba[..., 3] = np.where(valid, alpha, 0)
    return rgba


def categorical(arr, colors):
    """Integer class array -> RGBA using {class: (r, g, b, a)}; unknown classes transparent."""
    rgba = np.zeros(arr.shape + (4,), np.uint8)
    for k, c in colors.items():
        rgba[arr == k] = c
    return rgba


def save_png(rgba, name):
    Image.fromarray(rgba, "RGBA").save(LAYERS / name, optimize=True)
    return f"layers/{name}"


def save_webp(rgb, name, alpha=None, quality=80):
    """RGB (+ optional validity mask) -> lossy WebP with transparency for no-data."""
    rgba = np.dstack([rgb, np.where(alpha, 255, 0).astype(np.uint8) if alpha is not None
                      else np.full(rgb.shape[:2], 255, np.uint8)])
    Image.fromarray(rgba, "RGBA").save(LAYERS / name, "WEBP", quality=quality, method=6)
    return f"layers/{name}"


def stretch(band, lo=2, hi=98, valid=None):
    """Percentile stretch a reflectance band to 0..255 (for true-colour composites)."""
    v = band[valid] if valid is not None else band[np.isfinite(band)]
    a, b = np.percentile(v, [lo, hi]) if v.size else (0, 1)
    return (np.clip((band - a) / (b - a + 1e-9), 0, 1) ** 0.85 * 255).astype(np.uint8)


def write_json(obj, name):
    (STATS / name).write_text(json.dumps(obj, indent=1, default=_default))


def _default(o):
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(type(o))
