"""Last-resort layout with no dependencies beyond the standard library.

Used only if the main pipeline raises.  It letterboxes the whole source
design into the target (uniform scale, centred), stretches full-bleed
backgrounds to the new canvas and clamps everything on-canvas, so the output
is always structurally valid and recognisably the same design.
"""

from __future__ import annotations

import copy
import math


def _num(v, d=0.0):
    try:
        f = float(v)
        return f if math.isfinite(f) else d
    except Exception:
        return d


def letterbox(source, target_canvas) -> dict:
    source = source if isinstance(source, dict) else {}
    elements = source.get("elements") if isinstance(source.get("elements"), list) else []
    tc = target_canvas if isinstance(target_canvas, dict) else {}
    W = max(1, int(round(_num(tc.get("width"), 1080))))
    H = max(1, int(round(_num(tc.get("height"), 1080))))
    sc = source.get("canvas") if isinstance(source.get("canvas"), dict) else {}
    sW = _num(sc.get("width"), 0) or W
    sH = _num(sc.get("height"), 0) or H
    s = min(W / sW, H / sH)
    ox, oy = (W - sW * s) / 2, (H - sH * s) / 2
    out = []
    for el in elements:
        if not isinstance(el, dict):
            out.append(copy.deepcopy(el))
            continue
        e = {k: (0.0 if isinstance(v, float) and not math.isfinite(v) else v) for k, v in copy.deepcopy(el).items()}
        x, y, w, h = (_num(el.get(k)) for k in ("x", "y", "width", "height"))
        full = w * h >= 0.9 * sW * sH and el.get("type") in ("image", "shape")
        if full:
            x, y, w, h = 0.0, 0.0, float(W), float(H)
        else:
            x, y, w, h = ox + x * s, oy + y * s, max(0.0, w * s), max(0.0, h * s)
        if el.get("type") == "image":  # images shrink uniformly to fit, other boxes per side
            k = min(1.0, W / w if w else 1.0, H / h if h else 1.0)
            w, h = w * k, h * k
        w, h = min(w, W), min(h, H)
        if el.get("type") == "text":  # the renderer rejects empty text boxes
            w, h = max(1.0, w), max(1.0, h)
            e["font_size"] = max(1, int(round(_num(el.get("font_size"), 16) * s)))
        e["x"] = round(min(max(0.0, x), W - w), 2)
        e["y"] = round(min(max(0.0, y), H - h), 2)
        e["width"], e["height"] = round(w, 2), round(h, 2)
        out.append(e)
    return {"canvas": {"width": W, "height": H}, "elements": out}
