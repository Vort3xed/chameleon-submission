"""Rendering helpers for evaluation: official renderer -> PIL images, and
contact sheets for eyeballing many results at once."""

from __future__ import annotations

import io
import logging
import math
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ASSETS_DIR = ROOT / "brand_kit" / "assets"
FONTS_DIR = ROOT / "brand_kit" / "fonts"

logging.getLogger("cr_renderer").setLevel(logging.ERROR)
logging.getLogger("cr_renderer.fonts").setLevel(logging.ERROR)
logging.getLogger("cr_renderer.text_utils").setLevel(logging.ERROR)

_renderer = None


def _get():
    global _renderer
    if _renderer is None:
        from renderer.converter import convert  # noqa

        _renderer = convert
    return _renderer


def render(design: dict, max_size: int = 2048, canvas_color="white") -> Tuple[Image.Image, List[str]]:
    """Render a {canvas, elements} design exactly like engine/main.py does."""
    convert = _get()
    r = convert._get_renderer(str(FONTS_DIR))
    example, warnings = convert.convert_chameleon_to_crello(design, r.font_manager, str(ASSETS_DIR))
    import skia  # noqa

    kwargs = {}
    if canvas_color is None:
        kwargs["canvas_color"] = None
    data = r.render(example, max_size=max_size, format="png", **kwargs)
    return Image.open(io.BytesIO(data)).convert("RGBA"), warnings


def _font(size):
    for p in (FONTS_DIR / "SolsticeSans-Regular.ttf",):
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            pass
    return ImageFont.load_default()


def contact_sheet(items: Iterable[Tuple[Image.Image, str]], cell: int = 360, cols: int = 4, pad: int = 10,
                  label_h: int = 34, bg=(236, 232, 226)) -> Image.Image:
    items = list(items)
    rows = max(1, math.ceil(len(items) / cols))
    W = cols * (cell + pad) + pad
    H = rows * (cell + label_h + pad) + pad
    sheet = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(sheet)
    f = _font(13)
    for i, (img, label) in enumerate(items):
        r, c = divmod(i, cols)
        x0 = pad + c * (cell + pad)
        y0 = pad + r * (cell + label_h + pad)
        im = img.copy()
        im.thumbnail((cell, cell))
        ox = x0 + (cell - im.width) // 2
        oy = y0 + (cell - im.height) // 2
        draw.rectangle([ox - 1, oy - 1, ox + im.width, oy + im.height], outline=(150, 150, 150))
        sheet.paste(im.convert("RGB"), (ox, oy))
        for k, line in enumerate(str(label).split("\n")[:2]):
            draw.text((x0, y0 + cell + 2 + 15 * k), line[:58], fill=(30, 30, 30), font=f)
    return sheet


def side_by_side(src: Image.Image, out: Image.Image, h: int = 420, label: str = "") -> Image.Image:
    a, b = src.copy(), out.copy()
    a.thumbnail((h * 2, h))
    b.thumbnail((h * 3, h))
    W = a.width + b.width + 30
    img = Image.new("RGB", (W, h + 24), (236, 232, 226))
    img.paste(a.convert("RGB"), (5, 20))
    img.paste(b.convert("RGB"), (a.width + 20, 20))
    ImageDraw.Draw(img).text((5, 2), label, fill=(20, 20, 20), font=_font(14))
    return img


def vstack_images(images, bg=(236, 232, 226), pad=8) -> Image.Image:
    """Stack images vertically (each keeps its own size)."""
    W = max(im.width for im in images) + 2 * pad
    H = sum(im.height for im in images) + pad * (len(images) + 1)
    sheet = Image.new("RGB", (W, H), bg)
    y = pad
    for im in images:
        sheet.paste(im.convert("RGB"), (pad, y))
        y += im.height + pad
    return sheet
