"""Locate brand-kit assets and read the few facts the layout needs from them.

The engine never modifies pixels; it only asks whether an asset exists and
where its visible (non-transparent) content sits, so spacing can be judged by
what a viewer actually sees.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

try:
    from PIL import Image, ImageStat  # type: ignore
except Exception:  # pragma: no cover
    Image = None


@lru_cache(maxsize=1)
def assets_dir() -> Optional[Path]:
    here = Path(__file__).resolve()
    candidates = []
    if os.environ.get("CHAMELEON_ASSETS_DIR"):
        candidates.append(Path(os.environ["CHAMELEON_ASSETS_DIR"]))
    for up in (2, 3, 1):
        try:
            candidates.append(here.parents[up] / "brand_kit" / "assets")
        except IndexError:
            pass
    candidates += [Path.cwd() / "brand_kit" / "assets", Path("/app/brand_kit/assets")]
    for c in candidates:
        try:
            if c.is_dir() and any(c.iterdir()):
                return c
        except Exception:
            continue
    return None


def is_missing(asset_id) -> bool:
    """True when the renderer would draw its 'missing asset' placeholder.
    Unknown (no assets folder found) counts as present."""
    if not asset_id:
        return True
    d = assets_dir()
    if d is None:
        return False
    try:
        return not (d / str(asset_id)).is_file()
    except Exception:
        return False


@lru_cache(maxsize=128)
def content_bounds(asset_id) -> Tuple[float, float, float, float]:
    """Normalised (x0, y0, x1, y1) of the asset's opaque pixels; full frame if unknown."""
    d = assets_dir()
    if d is None or Image is None or not asset_id:
        return (0.0, 0.0, 1.0, 1.0)
    try:
        with Image.open(d / str(asset_id)) as im:
            im = im.convert("RGBA")
            box = im.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
            if not box:
                return (0.0, 0.0, 1.0, 1.0)
            return (box[0] / im.width, box[1] / im.height, box[2] / im.width, box[3] / im.height)
    except Exception:
        return (0.0, 0.0, 1.0, 1.0)


@lru_cache(maxsize=128)
def is_opaque(asset_id) -> bool:
    """True if every pixel of the asset is (nearly) fully opaque."""
    d = assets_dir()
    if d is None or Image is None or not asset_id:
        return False
    try:
        with Image.open(d / str(asset_id)) as im:
            if "A" not in im.getbands() and im.mode != "P":
                return True
            return im.convert("RGBA").getchannel("A").getextrema()[0] >= 250
    except Exception:
        return False


@lru_cache(maxsize=128)
def mean_luminance(asset_id) -> Optional[float]:
    """Average relative luminance (0 black - 1 white) of the asset, None if it cannot be read."""
    d = assets_dir()
    if d is None or Image is None or not asset_id:
        return None
    try:
        with Image.open(d / str(asset_id)) as im:
            r, g, b = ImageStat.Stat(im.convert("RGB").resize((32, 32))).mean
    except Exception:
        return None
    return relative_luminance(r, g, b)


def relative_luminance(r: float, g: float, b: float) -> float:
    """WCAG relative luminance of an 8-bit RGB colour."""
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


@lru_cache(maxsize=128)
def pixel_size(asset_id) -> Optional[Tuple[int, int]]:
    d = assets_dir()
    if d is None or Image is None or not asset_id:
        return None
    try:
        with Image.open(d / str(asset_id)) as im:
            return im.size
    except Exception:
        return None
