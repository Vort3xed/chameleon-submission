"""Turn placements into the output design while enforcing every hard rule:
same elements in the same order, only geometry / font size / opacity
changed, finite rounded numbers, images in proportion, text boxes strictly
positive (the renderer crashes otherwise) and nothing outside the canvas."""

from __future__ import annotations

import copy
import math
from dataclasses import replace
from typing import Dict

from .blocks import Placement
from .geometry import Rect
from .scene import num


def _fit_inside(p: Placement, W: float, H: float, rotation: float, keep_aspect: bool, is_text: bool) -> Placement:
    w, h = max(0.0, p.w), max(0.0, p.h)
    if is_text:
        w, h = max(1.0, w), max(1.0, h)
    if w > W or h > H:  # too big for the canvas: shrink (uniformly when aspect matters)
        if keep_aspect:
            s = min(W / max(w, 1e-9), H / max(h, 1e-9))
            w, h = w * s, h * s
        else:
            w, h = min(w, W), min(h, H)
    # shift so the box - and, if possible, its rotated footprint - stays on canvas
    bx, by = Rect(0, 0, w, h).rotated_bounds(rotation).w, Rect(0, 0, w, h).rotated_bounds(rotation).h
    cx = p.x + p.w / 2 if p.w else p.x
    cy = p.y + p.h / 2 if p.h else p.y
    half_w, half_h = max(w, min(bx, W)) / 2, max(h, min(by, H)) / 2
    cx = min(max(cx, half_w), W - half_w)
    cy = min(max(cy, half_h), H - half_h)
    return replace(p, x=cx - w / 2, y=cy - h / 2, w=w, h=h)


_DEFAULTS = {"opacity": 1.0, "line_height": 1.2}
SPECK = 2.0  # px: an image whose short side would be smaller is kept at this size, in proportion, and hidden


def _finite(value, key=None):
    """Recursively replace NaN/inf (invalid JSON) with safe defaults."""
    if isinstance(value, float) and not math.isfinite(value):
        return _DEFAULTS.get(key, 0.0)
    if isinstance(value, dict):
        return {k: _finite(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v, key) for v in value]
    return value


def _r(v: float) -> float:
    v = round(float(v), 2)
    return 0.0 if v == 0 else v


def finalize(source: dict, W: int, H: int, placements: Dict[int, Placement], hide_z=None) -> dict:
    out = []
    for idx, el in enumerate(source.get("elements", [])):
        if not isinstance(el, dict):
            out.append(_finite(copy.deepcopy(el)))
            continue
        new = _finite(copy.deepcopy(el))
        p = placements.get(idx)
        if p is None:
            p = Placement(num(el.get("x")), num(el.get("y")), num(el.get("width")), num(el.get("height")))
        t = el.get("type")
        sw, sh = num(el.get("width")), num(el.get("height"))
        keep_aspect = t == "image" and sw > 0 and sh > 0
        if keep_aspect and el.get("fit") != "cover" and not (p.w >= W - 1 and p.h >= H - 1):
            # snap to the exact source aspect around the same centre
            cx, cy = p.x + p.w / 2, p.y + p.h / 2
            ar = sw / sh
            w = math.sqrt(max(p.w * p.h, 1e-6) * ar)
            h = w / ar
            p = replace(p, x=cx - w / 2, y=cy - h / 2, w=w, h=h)
        if keep_aspect and (p.w >= W - 1 and p.h >= H - 1):
            keep_aspect = False  # full-bleed backgrounds are exempt
        speck = keep_aspect and 0 < min(p.w, p.h) < SPECK
        if speck:  # squeezed to a speck: rounding would bend its proportions, and it cannot be seen anyway
            s = SPECK / min(p.w, p.h)
            p = replace(p, x=p.x + p.w / 2 * (1 - s), y=p.y + p.h / 2 * (1 - s), w=p.w * s, h=p.h * s, opacity=0.0)
        p = _fit_inside(p, W, H, num(el.get("rotation")), keep_aspect, t == "text")
        new["x"], new["y"] = _r(max(0.0, p.x)), _r(max(0.0, p.y))
        new["width"], new["height"] = _r(min(p.w, W)), _r(min(p.h, H))
        if t == "text":
            new["width"], new["height"] = max(1.0, new["width"]), max(1.0, new["height"])
            if p.font is not None:
                new["font_size"] = int(max(1, round(p.font)))
            elif "font_size" in new:
                new["font_size"] = int(max(1, round(num(new.get("font_size"), 16))))
        if t == "text" and p.align:
            new["text_align"] = p.align
        if p.opacity is not None:
            new["opacity"] = float(max(0.0, min(1.0, p.opacity)))
        if p.hidden:
            new["opacity"] = 0.0
            if t == "text" and hide_z is not None:
                new["z_index"] = int(hide_z)  # the renderer ignores text opacity
            elif t == "text" and p.under is not None:  # tucked beneath an opaque card instead
                cover = source["elements"][p.under]
                new["z_index"] = int(math.floor(num(cover.get("z_index") if isinstance(cover, dict) else 0))) - 1
        if t == "text" and p.font is not None and num(el.get("letter_spacing"), 0.0):
            new["letter_spacing"] = _r(num(el.get("letter_spacing")) * new["font_size"] / max(1.0, num(el.get("font_size"), 1.0)))
        out.append(new)
    return {"canvas": {"width": int(W), "height": int(H)}, "elements": out}
