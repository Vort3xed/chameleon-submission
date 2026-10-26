"""Automated scorer approximating the CHAMELEON rubric.

Two parts, mirroring RULES.md:
  1. A hard structural gate (same ids, required fields, schema-valid, nothing
     off-canvas, images in proportion, content/fonts/assets unchanged, finite
     numbers, renderable).  Failing the gate scores 0.
  2. Soft quality metrics computed from real font metrics and actual renders:
     unwanted collisions, cut-off, text fitting its box, readability,
     contrast, hierarchy, prominence of key elements, group integrity, shape
     distortion, margins, space use, balance, alignment, completeness,
     reading order, background coverage and visible missing-asset boxes.

Element roles for weighting come from the semantic ids the test generator
emits (ground truth the engine never sees), with a heuristic fallback for
unknown ids.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.chameleon_layout import text_metrics as tm  # noqa: E402

ASSETS = ROOT / "brand_kit" / "assets"
SCHEMA_PATH = ROOT / "chameleon_design_schema_v0.9.json"

WEIGHTS = {
    "overlap": 0.16,
    "cutoff": 0.07,
    "text_fit": 0.05,
    "readability": 0.11,
    "contrast": 0.10,
    "hierarchy": 0.08,
    "prominence": 0.06,
    "groups": 0.07,
    "distortion": 0.03,
    "margins": 0.04,
    "space": 0.05,
    "balance": 0.03,
    "alignment": 0.04,
    "completeness": 0.05,
    "reading_order": 0.01,
    "bg_coverage": 0.03,
    "missing_visible": 0.02,
}

IMPORTANCE = {"headline": 1.0, "cta": 0.8, "logo": 0.8, "hero": 0.7, "text": 0.5, "body": 0.35, "badge": 0.3,
              "ribbon": 0.3, "legal": 0.2, "divider": 0.1, "container": 0.4, "decor": 0.05, "missing": 0.0,
              "background": 0.0, "other": 0.3}

ROLE_PATTERNS = [
    (r"^bg(_\d+)?$", "background"),
    (r"^(deco_circle|dot|speck|frame|bleed_bar|hidden_layer|zero_shape|deco)", "decor"),
    (r"^(overlay)", "decor"),
    (r"^(card|panel|scrim)", "container"),
    (r"^(logo|wordmark)", "logo"),
    (r"^(product)", "hero"),
    (r"^(headline|big_offer)", "headline"),
    (r"^(cta)", "cta"),
    (r"^(badge)", "badge"),
    (r"^(ribbon)", "ribbon"),
    (r"^(legal)", "legal"),
    (r"^(divider)", "divider"),
    (r"^(body)", "body"),
    (r"^(watermark|qr_code|missing_img|holiday_watermark)", "missing"),
    (r"^(subhead|kicker|date_line|location|details|price|name|swipe|sticker|weird_text|tag_)", "text"),
    (r"^item", "hero"),
]


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------

Rect = Tuple[float, float, float, float]  # x0, y0, x1, y1


def area(r: Rect) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def inter(a: Rect, b: Rect) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def union_rect(rs: List[Rect]) -> Optional[Rect]:
    rs = [r for r in rs if area(r) > 0]
    if not rs:
        return None
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))


def rotate_rect(r: Rect, cx: float, cy: float, deg: float) -> Rect:
    if not deg:
        return r
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    pts = [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]
    xs, ys = [], []
    for x, y in pts:
        dx, dy = x - cx, y - cy
        xs.append(cx + dx * c - dy * s)
        ys.append(cy + dx * s + dy * c)
    return (min(xs), min(ys), max(xs), max(ys))


def num(v, default=0.0) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except Exception:
        return default


_RGBA = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")


def parse_color(v) -> Tuple[float, float, float, float]:
    m = _RGBA.match(str(v or "").strip())
    if not m:
        s = str(v or "").strip().lstrip("#")
        if len(s) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in s):
            if len(s) == 3:
                s = "".join(c * 2 for c in s)
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 1.0)
        return (0, 0, 0, 1.0)
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)), a)


def rel_lum(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def contrast_ratio(l1, l2):
    hi, lo = np.maximum(l1, l2), np.minimum(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


@lru_cache(maxsize=64)
def asset_info(asset_id: str):
    """(width, height, normalized opaque bbox, mean opaque rgb) or None if missing."""
    p = ASSETS / str(asset_id)
    if not asset_id or not p.is_file():
        return None
    im = Image.open(p).convert("RGBA")
    a = np.asarray(im)
    alpha = a[..., 3]
    ys, xs = np.where(alpha > 16)
    if len(xs) == 0:
        bbox = (0.0, 0.0, 1.0, 1.0)
        mean = (128.0, 128.0, 128.0)
    else:
        bbox = (xs.min() / im.width, ys.min() / im.height, (xs.max() + 1) / im.width, (ys.max() + 1) / im.height)
        mean = tuple(a[..., :3][alpha > 16].mean(0).tolist())
    return im.width, im.height, bbox, mean


# ---------------------------------------------------------------------------
# per-element visual extents
# ---------------------------------------------------------------------------

@dataclass
class Vis:
    id: str
    type: str
    role: str
    box: Rect  # element box (unrotated)
    ink: Rect  # visible extent (rotated AABB)
    visible: bool
    opacity: float
    group: Optional[str]
    z: float
    order: int
    el: dict = field(repr=False, default_factory=dict)
    lines: int = 0
    font_px: int = 0
    text_overflow: float = 0.0  # fraction of ink outside own box
    missing: bool = False


def element_role(el: dict, all_els: List[dict], canvas) -> str:
    eid = str(el.get("id", ""))
    for pat, role in ROLE_PATTERNS:
        if re.match(pat, eid):
            if role == "missing" and el.get("type") == "image" and asset_info(el.get("asset_id")) is not None:
                return "other"
            return role
    # heuristic fallback
    W, H = canvas
    t = el.get("type")
    x, y, w, h = (num(el.get(k)) for k in ("x", "y", "width", "height"))
    if t in ("image", "shape") and w * h >= 0.85 * W * H:
        return "background"
    if t == "image":
        if asset_info(el.get("asset_id")) is None:
            return "missing"
        if "logo" in str(el.get("asset_id", "")).lower():
            return "logo"
        return "hero"
    if t == "text":
        faint = lambda e: parse_color(e.get("color"))[3] < 0.3  # noqa: E731
        if faint(el):
            return "decor"  # faint type is texture behind the content, not copy
        sizes = [num(e.get("font_size"), 0) for e in all_els if e.get("type") == "text" and not faint(e)]
        fs = num(el.get("font_size"), 0)
        if sizes and fs >= max(sizes):
            return "headline"
        if el.get("group_id"):
            return "cta"
        if sizes and fs <= min(sizes) and len(str(el.get("content", ""))) > 40:
            return "legal"
        return "text"
    if t == "shape":
        if num(el.get("opacity"), 1.0) < 0.5:
            return "decor"
        if el.get("group_id"):
            return "cta"
        return "decor"
    return "other"


def text_ink(el: dict) -> Tuple[Rect, Rect, int, int, float]:
    x, y, w, h = (num(el.get(k)) for k in ("x", "y", "width", "height"))
    lay = tm.layout_text(el.get("content", ""), el.get("font_family", ""), el.get("font_weight"), el.get("font_style"),
                         num(el.get("font_size"), 1), w, num(el.get("line_height"), 1.2) or 1.2,
                         num(el.get("letter_spacing"), 0.0))
    align = el.get("text_align", "left")
    xs0, xs1 = [], []
    for lw in lay.line_widths:
        if lw <= 0:
            continue
        off = 0.0 if align == "left" else ((w - lw) / 2 if align == "center" else w - lw)
        xs0.append(x + off)
        xs1.append(x + off + lw)
    if not xs0:
        ink = (x, y, x, y)
    else:
        ink = (min(xs0), y + lay.ink_top, max(xs1), y + lay.ink_bottom)
    box = (x, y, x + w, y + h)
    a = area(ink)
    over = 0.0
    if a > 0:
        over = 1.0 - inter(ink, box) / a
    return box, ink, lay.n_lines, lay.font_size, over


def image_ink(el: dict) -> Tuple[Rect, bool]:
    x, y, w, h = (num(el.get(k)) for k in ("x", "y", "width", "height"))
    info = asset_info(el.get("asset_id"))
    if info is None or w <= 0 or h <= 0:
        return (x, y, x + w, y + h), info is None
    iw, ih, bb, _ = info
    fit = el.get("fit", "contain")
    if fit == "contain":
        s = min(w / iw, h / ih)
        dw, dh = iw * s, ih * s
        ox, oy = x + (w - dw) / 2, y + (h - dh) / 2
        return (ox + bb[0] * dw, oy + bb[1] * dh, ox + bb[2] * dw, oy + bb[3] * dh), False
    if fit == "cover":
        s = max(w / iw, h / ih)
        dw, dh = iw * s, ih * s
        ox, oy = x + (w - dw) / 2, y + (h - dh) / 2
        r = (ox + bb[0] * dw, oy + bb[1] * dh, ox + bb[2] * dw, oy + bb[3] * dh)
        return (max(r[0], x), max(r[1], y), min(r[2], x + w), min(r[3], y + h)), False
    return (x + bb[0] * w, y + bb[1] * h, x + bb[2] * w, y + bb[3] * h), False


def visuals(design: dict) -> List[Vis]:
    W, H = num(design["canvas"]["width"], 1), num(design["canvas"]["height"], 1)
    els = design["elements"]
    out = []
    for i, el in enumerate(els):
        t = el.get("type")
        x, y, w, h = (num(el.get(k)) for k in ("x", "y", "width", "height"))
        rot = num(el.get("rotation"), 0.0)
        op = max(0.0, min(1.0, num(el.get("opacity"), 1.0)))
        role = element_role(el, els, (W, H))
        missing = False
        lines = fpx = 0
        over = 0.0
        if t == "text":
            box, ink, lines, fpx, over = text_ink(el)
            op_eff = parse_color(el.get("color"))[3]
            vis = op_eff > 0.05 and len(str(el.get("content", "")).strip()) > 0 and fpx >= 1
        elif t == "image":
            box = (x, y, x + w, y + h)
            ink, missing = image_ink(el)
            vis = op > 0.05
        else:
            box = (x, y, x + w, y + h)
            ink = box
            if el.get("shape_type") == "line":
                sw = max(1.0, num(el.get("stroke_width"), 1.0))
                ink = (x, y + h / 2 - sw / 2, x + w, y + h / 2 + sw / 2)
            vis = op * parse_color(el.get("fill_color"))[3] > 0.03
        if rot:
            cx, cy = x + w / 2, y + h / 2
            ink = rotate_rect(ink, cx, cy, rot)
        vis = vis and area(ink) >= 4
        out.append(Vis(str(el.get("id")), t, role, box, ink, vis, op, el.get("group_id"), num(el.get("z_index"), 0), i,
                       el, lines, fpx, over, missing))
    _apply_occlusion(out)
    return out


def _opaque(v: Vis) -> bool:
    el = v.el
    if num(el.get("rotation"), 0) or v.opacity < 0.99:
        return False
    if v.type == "shape":
        return el.get("shape_type", "rectangle") == "rectangle" and parse_color(el.get("fill_color"))[3] >= 0.99
    if v.type == "image":
        info = asset_info(el.get("asset_id"))
        return info is not None and el.get("fit", "contain") in ("cover", "fill") and _asset_opaque(el.get("asset_id"))
    return False


@lru_cache(maxsize=64)
def _asset_opaque(asset_id) -> bool:
    im = Image.open(ASSETS / str(asset_id))
    return "A" not in im.getbands() or im.convert("RGBA").getchannel("A").getextrema()[0] >= 250


def _apply_occlusion(vs: List[Vis]):
    """Elements fully covered by an opaque element painted above them are invisible
    (the converter paints in stable z_index order)."""
    order = sorted(vs, key=lambda v: v.z)  # stable: ties keep list order
    rank = {id(v): k for k, v in enumerate(order)}
    covers = [v for v in vs if v.visible and _opaque(v)]
    for v in vs:
        if not v.visible or not covers:
            continue
        canvas = union_rect([c.box for c in covers])
        ink = (max(v.ink[0], canvas[0]), max(v.ink[1], canvas[1]), min(v.ink[2], canvas[2]), min(v.ink[3], canvas[3]))
        if area(ink) <= 0 or any(rank[id(c)] > rank[id(v)] and any(_contained(ink, core, 0.999) for core in _cores(c))
                                 for c in covers):
            v.visible = False


def _cores(c: Vis) -> List[Rect]:
    """The parts of an opaque rectangle that are opaque edge to edge: the whole box, or, with rounded
    corners, the box without the corner radius on either axis."""
    r = min(num(c.el.get("corner_radius"), 0), (c.box[2] - c.box[0]) / 2, (c.box[3] - c.box[1]) / 2)
    if r <= 0:
        return [c.box]
    x0, y0, x1, y1 = c.box
    return [(x0 + r, y0, x1 - r, y1), (x0, y0 + r, x1, y1 - r)]


# ---------------------------------------------------------------------------
# hard gate
# ---------------------------------------------------------------------------

_validator = None


def _schema_validator():
    global _validator
    if _validator is None:
        try:
            import jsonschema  # type: ignore

            schema = json.loads(SCHEMA_PATH.read_text())
            _validator = jsonschema.Draft202012Validator(schema)
        except Exception:
            _validator = False
    return _validator


FROZEN = ["type", "content", "font_family", "asset_id", "shape_type", "color", "fill_color", "stroke_color",
          "font_weight", "font_style", "style_runs"]


def gate(source: dict, target: dict, output) -> List[str]:
    errs = []
    if not isinstance(output, dict):
        return ["output is not an object"]
    extra = set(output) - {"canvas", "elements"}
    if extra:
        errs.append(f"extra top-level keys {sorted(extra)}")
    if "canvas" not in output or "elements" not in output or not isinstance(output.get("elements"), list):
        return errs + ["missing canvas/elements"]
    try:
        cw, ch = int(output["canvas"]["width"]), int(output["canvas"]["height"])
    except Exception:
        return errs + ["bad canvas"]
    if (cw, ch) != (int(target["width"]), int(target["height"])):
        errs.append(f"canvas {cw}x{ch} != target")
    v = _schema_validator()
    if v:
        for e in list(v.iter_errors(output))[:3]:
            errs.append("schema: " + e.message[:120])
    src_ids = [e.get("id") for e in source["elements"]]
    out_ids = [e.get("id") for e in output["elements"]]
    if sorted(map(str, src_ids)) != sorted(map(str, out_ids)):
        errs.append("id multiset mismatch")
    src_by = {e.get("id"): e for e in source["elements"]}
    for el in output["elements"]:
        if not isinstance(el, dict):
            errs.append("non-object element")
            continue
        s = src_by.get(el.get("id"))
        for k in ("x", "y", "width", "height", "font_size", "rotation", "opacity"):
            if k in el:
                try:
                    f = float(el[k])
                    if not math.isfinite(f):
                        errs.append(f"{el.get('id')}: non-finite {k}")
                except Exception:
                    errs.append(f"{el.get('id')}: non-numeric {k}")
        if s is None:
            continue
        for k in FROZEN:
            if s.get(k) != el.get(k):
                errs.append(f"{el.get('id')}: changed {k}")
        x, y, w, h = (num(el.get(k)) for k in ("x", "y", "width", "height"))
        if el.get("type") == "text" and (w <= 0 or h <= 0):
            errs.append(f"{el.get('id')}: text box w/h must be > 0 (renderer crashes)")
        if x < -0.5 or y < -0.5 or x + w > cw + 0.5 or y + h > ch + 0.5:
            errs.append(f"{el.get('id')}: off-canvas")
        if el.get("type") == "image" and el.get("fit", "contain") != "cover":
            sw, sh = num(s.get("width")), num(s.get("height"))
            full = w >= cw - 1 and h >= ch - 1
            if sw > 0 and sh > 0 and w > 0 and h > 0 and not full:
                if abs((w / h) / (sw / sh) - 1) > 0.05:
                    errs.append(f"{el.get('id')}: image aspect changed")
    return errs


# ---------------------------------------------------------------------------
# soft metrics
# ---------------------------------------------------------------------------

CONTENT_EXCLUDE = {"background", "decor"}


def _pairs_overlap(vs: List[Vis]) -> Dict[Tuple[str, str], float]:
    d = {}
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            a, b = vs[i], vs[j]
            ia = inter(a.ink, b.ink)
            if ia <= 0:
                continue
            d[(a.id, b.id)] = ia / max(1.0, min(area(a.ink), area(b.ink)))
    return d


def _norm_in(box: Rect, frame: Rect) -> Tuple[float, float, float, float]:
    """`box` expressed in [0,1] coordinates of `frame`."""
    fw, fh = max(1e-6, frame[2] - frame[0]), max(1e-6, frame[3] - frame[1])
    return ((box[0] - frame[0]) / fw, (box[1] - frame[1]) / fh, (box[2] - frame[0]) / fw, (box[3] - frame[1]) / fh)


def _box_shift(s_box: Rect, s_frame: Rect, o_box: Rect, o_frame: Rect) -> float:
    """Mean change of a member's normalized position inside its group frame."""
    return sum(abs(p - q) for p, q in zip(_norm_in(s_box, s_frame), _norm_in(o_box, o_frame))) / 4


def _contained(child: Rect, parent: Rect, thr=0.9) -> bool:
    a = area(child)
    return a > 0 and inter(child, parent) / a >= thr


def render_layers(design: dict, scale_max: int = 1024):
    """Full render + background-only render (texts removed), plus scale."""
    from eval.render import render

    W = design["canvas"]["width"]
    full, warns = render(design, max_size=scale_max)
    bg_design = {"canvas": design["canvas"], "elements": [e for e in design["elements"] if e.get("type") != "text"]}
    if not bg_design["elements"]:
        bg = Image.new("RGBA", full.size, (255, 255, 255, 255))
    else:
        bg, _ = render(bg_design, max_size=scale_max)
    s = full.width / float(W)
    return full, bg, s, warns


def text_contrast(v: Vis, bg: np.ndarray, s: float) -> Optional[float]:
    x0, y0, x1, y1 = v.ink
    h, w = bg.shape[:2]
    X0, Y0 = int(max(0, math.floor(x0 * s))), int(max(0, math.floor(y0 * s)))
    X1, Y1 = int(min(w, math.ceil(x1 * s))), int(min(h, math.ceil(y1 * s)))
    if X1 - X0 < 1 or Y1 - Y0 < 1:
        return None
    region = bg[Y0:Y1, X0:X1, :3].astype(np.float64)
    r, g, b, a = parse_color(v.el.get("color"))
    tc = np.array([r, g, b], dtype=np.float64)
    blended = a * tc + (1 - a) * region
    ratio = contrast_ratio(rel_lum(blended), rel_lum(region))
    return float(np.percentile(ratio, 20))


def image_contrast(v: Vis, bg_wo: np.ndarray, s: float) -> Optional[float]:
    info = asset_info(v.el.get("asset_id"))
    if info is None:
        return None
    x0, y0, x1, y1 = v.ink
    h, w = bg_wo.shape[:2]
    X0, Y0 = int(max(0, x0 * s)), int(max(0, y0 * s))
    X1, Y1 = int(min(w, x1 * s)), int(min(h, y1 * s))
    if X1 - X0 < 1 or Y1 - Y0 < 1:
        return None
    region = bg_wo[Y0:Y1, X0:X1, :3].astype(np.float64).reshape(-1, 3).mean(0)
    mean = np.array(info[3])
    return float(contrast_ratio(rel_lum(mean[None])[0], rel_lum(region[None])[0]))


def contrast_score(ratio: Optional[float]) -> Optional[float]:
    if ratio is None:
        return None
    return float(min(1.0, max(0.0, (ratio - 1.4) / (4.5 - 1.4))))


@dataclass
class Prep:
    vis: List[Vis]
    by_id: Dict[str, Vis]
    W: float
    H: float
    full: Optional[np.ndarray] = None
    bg: Optional[np.ndarray] = None
    s: float = 1.0
    contrasts: Dict[str, Optional[float]] = field(default_factory=dict)


def prepare(design: dict, do_render: bool = True) -> Prep:
    vs = visuals(design)
    p = Prep(vs, {v.id: v for v in vs}, num(design["canvas"]["width"], 1), num(design["canvas"]["height"], 1))
    if do_render:
        full, bg, s, _ = render_layers(design)
        p.full, p.bg, p.s = np.asarray(full), np.asarray(bg), s
        for v in vs:
            if v.visible and v.type == "text":
                p.contrasts[v.id] = text_contrast(v, p.bg, s)
        # logo / image visibility against what is beneath it
        imgs = [v for v in vs if v.visible and v.type == "image" and v.role in ("logo",)]
        for v in imgs:
            from eval.render import render

            under = {"canvas": design["canvas"], "elements": [e for e in design["elements"]
                                                               if num(e.get("z_index"), 0) < v.z and e.get("type") != "text"]}
            if under["elements"]:
                im, _ = render(under, max_size=1024)
                p.contrasts[v.id] = image_contrast(v, np.asarray(im), s)
            else:
                p.contrasts[v.id] = image_contrast(v, np.full_like(p.bg, 255), s)
    return p


def kendall_concordance(a: List[float], b: List[float], min_ratio=1.12) -> Optional[float]:
    conc = tot = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            if a[i] <= 0 or a[j] <= 0:
                continue
            r = a[i] / a[j]
            if 1 / min_ratio < r < min_ratio:
                continue
            tot += 1
            if (a[i] - a[j]) * (b[i] - b[j]) > 0:
                conc += 1
    return conc / tot if tot else None


def reading_seq(vs: List[Vis]) -> List[str]:
    items = sorted(vs, key=lambda v: (v.ink[1] + v.ink[3]) / 2)
    rows: List[List[Vis]] = []
    for v in items:
        cy = (v.ink[1] + v.ink[3]) / 2
        placed = False
        for row in rows:
            r0, r1 = min(x.ink[1] for x in row), max(x.ink[3] for x in row)
            if r0 <= cy <= r1:
                row.append(v)
                placed = True
                break
        if not placed:
            rows.append([v])
    seq = []
    for row in rows:
        seq += [v.id for v in sorted(row, key=lambda v: v.ink[0])]
    return seq


def wavg(pairs) -> Optional[float]:
    pairs = [(s, w) for s, w in pairs if s is not None and w > 0]
    if not pairs:
        return None
    return sum(s * w for s, w in pairs) / sum(w for _, w in pairs)


def score_task(source: dict, target: dict, output, src_prep: Optional[Prep] = None, do_render: bool = True) -> dict:
    errs = gate(source, target, output)
    if errs:
        return {"score": 0.0, "gate": errs, "metrics": {}, "issues": errs[:5]}
    try:
        out_prep = prepare(output, do_render)
    except Exception as e:  # render crash = unusable output
        return {"score": 0.0, "gate": [f"render failed: {e!r}"], "metrics": {}, "issues": [f"render failed: {e!r}"]}
    if src_prep is None:
        src_prep = prepare(source, do_render)
    S, O = src_prep, out_prep
    W, H = O.W, O.H
    issues: List[str] = []
    m: Dict[str, float] = {}

    imp = {v.id: IMPORTANCE.get(v.role, 0.3) for v in S.vis}

    # groups and containment in the source
    groups: Dict[str, List[str]] = {}
    for v in S.vis:
        if v.group:
            groups.setdefault(v.group, []).append(v.id)
    same_group = {(a, b) for g in groups.values() for a in g for b in g if a != b}
    containers = []
    for p in S.vis:
        eff_alpha = p.opacity * parse_color(p.el.get("fill_color"))[3]
        if p.type != "shape" or not p.visible or p.role in ("background", "decor") or eff_alpha < 0.3:
            continue
        for c in S.vis:
            if c.id != p.id and c.visible and c.z >= p.z and c.role != "background" and _contained(c.ink, p.box, 0.9) \
                    and area(p.box) > area(c.ink) * 1.05:
                containers.append((p.id, c.id))
    cont_set = {(a, b) for a, b in containers} | {(b, a) for a, b in containers}

    # ---- overlap ---------------------------------------------------------
    s_over = _pairs_overlap([v for v in S.vis if v.visible])
    o_content = [v for v in O.vis if v.visible and v.role not in CONTENT_EXCLUDE and S.by_id.get(v.id) is not None
                 and S.by_id[v.id].role not in CONTENT_EXCLUDE]
    o_over = _pairs_overlap(o_content)
    pen = 0.0
    for (a, b), io in o_over.items():
        if (a, b) in same_group or (a, b) in cont_set:
            continue
        src_io = s_over.get((a, b), s_over.get((b, a), 0.0))
        excess = io - src_io
        if excess <= 0.02:
            continue
        ta, tb = O.by_id[a].type, O.by_id[b].type
        if ta == "text" and tb == "text":
            w = 1.0
        elif "text" in (ta, tb):
            w = 0.8
        elif ta == "image" and tb == "image":
            w = 0.5
        else:
            w = 0.35
        pen += excess * w
        if excess * w > 0.1:
            issues.append(f"overlap {a}~{b} {excess:.2f}")
    m["overlap"] = math.exp(-2.5 * pen)

    # ---- cutoff (ink outside canvas) --------------------------------------
    canvas = (0.0, 0.0, W, H)
    cut = []
    for v in O.vis:
        if not v.visible or v.role in CONTENT_EXCLUDE:
            continue
        a = area(v.ink)
        if a <= 0:
            continue
        frac = 1 - inter(v.ink, canvas) / a
        w = imp.get(v.id, 0.3) * (3 if v.type == "text" else 1)
        cut.append((1 - min(1.0, frac * 4), w))
        if frac > 0.02:
            issues.append(f"cutoff {v.id} {frac:.2f}")
    m["cutoff"] = wavg(cut) if cut else 1.0

    # ---- text fit ---------------------------------------------------------
    fit = []
    for v in O.vis:
        if v.visible and v.type == "text":
            sv = S.by_id.get(v.id)
            base = sv.text_overflow if sv else 0.0
            ex = max(0.0, v.text_overflow - base - 0.03)
            fit.append((1 - min(1.0, ex * 3), imp.get(v.id, 0.3) + 0.1))
            if ex > 0.1:
                issues.append(f"text overflows box {v.id} {ex:.2f}")
    m["text_fit"] = wavg(fit) if fit else 1.0

    # ---- readability -------------------------------------------------------
    view = min(1.0, 1024.0 / max(W, H))
    rd = []
    for v in O.vis:
        if not (v.visible and v.type == "text"):
            continue
        sv = S.by_id.get(v.id)
        if sv is None:
            continue
        e = v.font_px * view
        small_role = sv.role in ("legal", "badge", "ribbon", "decor")
        lo, hi = (5.0, 9.0) if small_role else (7.0, 12.0)
        sc = min(1.0, max(0.0, (e - lo) / (hi - lo)))
        # if the source itself was tiny, do not demand more than it had
        se = sv.font_px * min(1.0, 1024.0 / max(S.W, S.H))
        if se < hi:
            sc = max(sc, min(1.0, e / max(se, 1e-6)))
        rd.append((sc, imp.get(v.id, 0.3) + 0.05))
        if sc < 0.5:
            issues.append(f"small text {v.id} {v.font_px}px")
    m["readability"] = wavg(rd) if rd else 1.0

    # ---- contrast ---------------------------------------------------------
    cs = []
    if O.contrasts:
        for vid, ratio in O.contrasts.items():
            if ratio is None:
                continue
            so = contrast_score(ratio)
            ss = contrast_score(S.contrasts.get(vid)) if vid in S.contrasts else None
            ref = max(ss if ss is not None else 1.0, 0.25)
            sc = min(1.0, so / ref)
            w = imp.get(vid, 0.3) + 0.05
            if O.by_id[vid].type == "image":
                w *= 0.7
            cs.append((sc, w))
            if sc < 0.6:
                issues.append(f"low contrast {vid} {ratio:.1f}")
    m["contrast"] = wavg(cs) if cs else 1.0

    # ---- hierarchy -------------------------------------------------------------
    texts = [v for v in O.vis if v.visible and v.type == "text" and v.id in S.by_id and S.by_id[v.id].visible]
    hs = []
    if len(texts) >= 2:
        a = [float(num(S.by_id[v.id].el.get("font_size"), 0)) for v in texts]
        b = [float(v.font_px) for v in texts]
        kc = kendall_concordance(a, b)
        if kc is not None:
            hs.append((kc, 1.0))
        heads = [v for v in texts if S.by_id[v.id].role == "headline"]
        if heads:
            hmax = max(h.font_px for h in heads)
            others = [v.font_px for v in texts if S.by_id[v.id].role not in ("headline",)]
            if others:
                hs.append((1.0 if hmax >= max(others) else max(0.0, 1 - (max(others) / hmax - 1) * 2), 1.0))
    m["hierarchy"] = wavg(hs) if hs else 1.0

    # ---- prominence of key elements (relative share of canvas) --------------
    pr = []
    for v in O.vis:
        sv = S.by_id.get(v.id)
        if sv is None or not sv.visible or sv.role not in ("headline", "hero", "logo", "cta"):
            continue
        if not v.visible:
            continue
        s_share = area(sv.ink) / (S.W * S.H)
        o_share = area(v.ink) / (W * H)
        if s_share <= 0:
            continue
        r = o_share / s_share
        sc = 1.0 if r >= 0.35 else max(0.0, r / 0.35)
        if r > 8:  # grossly oversized relative to the original
            sc = max(0.5, 1 - (r / 8 - 1) * 0.2)
        pr.append((sc, imp.get(v.id, 0.3)))
        if sc < 0.5:
            issues.append(f"{v.id} shrunk (share x{r:.2f})")
    m["prominence"] = wavg(pr) if pr else 1.0

    # ---- groups / containment --------------------------------------------------
    gs = []
    for g, ids in groups.items():
        vis_ids = [i for i in ids if O.by_id.get(i) and O.by_id[i].visible and S.by_id[i].visible]
        if len(vis_ids) < 2:
            continue
        # compare what is visible (a label's box may tighten around its words)
        sb = union_rect([S.by_id[i].ink for i in vis_ids])
        ob = union_rect([O.by_id[i].ink for i in vis_ids])
        if not sb or not ob:
            continue
        diffs = [_box_shift(S.by_id[i].ink, sb, O.by_id[i].ink, ob) for i in vis_ids]
        d = sum(diffs) / len(diffs)
        sc = max(0.0, 1 - d * 4)
        gs.append((sc, 1.0))
        if sc < 0.6:
            issues.append(f"group {g} rearranged {d:.2f}")
    for pid, cid in containers:
        po, co = O.by_id.get(pid), O.by_id.get(cid)
        if not po or not co or not po.visible or not co.visible:
            continue
        ok = _contained(co.ink, po.box, 0.85)
        gs.append((1.0 if ok else 0.0, imp.get(cid, 0.3)))  # a dot leaving a card matters less than a headline
        if not ok:
            issues.append(f"{cid} left container {pid}")
    m["groups"] = wavg(gs) if gs else 1.0

    # ---- distortion (circles/pills stretched) -----------------------------------
    ds = []
    for v in O.vis:
        sv = S.by_id.get(v.id)
        if not sv or v.type != "shape" or not v.visible:
            continue
        el = sv.el
        round_ish = el.get("shape_type") == "ellipse" or num(el.get("corner_radius"), 0) > 0
        if not round_ish:
            continue
        sw, sh = sv.box[2] - sv.box[0], sv.box[3] - sv.box[1]
        ow, oh = v.box[2] - v.box[0], v.box[3] - v.box[1]
        if min(sw, sh, ow, oh) <= 1:
            continue
        lr = abs(math.log((ow / oh) / (sw / sh)))
        tol = 0.05 if el.get("shape_type") == "ellipse" else 0.6
        sc = max(0.0, 1 - max(0.0, lr - tol) * 2)
        ds.append((sc, 1.0 if sv.role != "decor" else 0.5))
        if sc < 0.6:
            issues.append(f"distorted {v.id}")
    m["distortion"] = wavg(ds) if ds else 1.0

    # ---- margins ----------------------------------------------------------------
    mg = []
    mmin = max(2.0, 0.02 * min(W, H))
    for v in O.vis:
        sv = S.by_id.get(v.id)
        if not v.visible or not sv or sv.role in CONTENT_EXCLUDE or sv.role == "container":
            continue
        smin = max(2.0, 0.02 * min(S.W, S.H))
        s_edges = (sv.ink[0], sv.ink[1], S.W - sv.ink[2], S.H - sv.ink[3])
        o_edges = (v.ink[0], v.ink[1], W - v.ink[2], H - v.ink[3])
        bad = 0
        for se, oe in zip(s_edges, o_edges):
            if oe < mmin and se >= smin * 0.8:
                bad += 1
        mg.append((1.0 - min(1.0, bad * 0.5), imp.get(v.id, 0.3) + 0.05))
        if bad:
            issues.append(f"tight margin {v.id}")
    m["margins"] = wavg(mg) if mg else 1.0

    # ---- space use + balance ----------------------------------------------------
    def content_boxes(P: Prep, ids):
        return [P.by_id[i].ink for i in ids if P.by_id.get(i) and P.by_id[i].visible]

    content_ids = [v.id for v in S.vis if v.visible and v.role not in CONTENT_EXCLUDE]
    sb = union_rect(content_boxes(S, content_ids))
    ob = union_rect(content_boxes(O, content_ids))
    if sb and ob:
        s_cov = area(sb) / (S.W * S.H)
        o_cov = area(ob) / (W * H)
        r = o_cov / max(1e-6, s_cov)
        m["space"] = 1.0 if r >= 0.65 else max(0.0, r / 0.65)
        if r < 0.5:
            issues.append(f"content uses x{r:.2f} of source coverage")

        def centroid(P: Prep, w_, h_):
            tot = cx = cy = 0.0
            for i in content_ids:
                v = P.by_id.get(i)
                if not v or not v.visible:
                    continue
                a = area(v.ink)
                tot += a
                cx += a * (v.ink[0] + v.ink[2]) / 2
                cy += a * (v.ink[1] + v.ink[3]) / 2
            if tot <= 0:
                return 0.0
            return math.hypot(cx / tot / w_ - 0.5, cy / tot / h_ - 0.5)

        dev = centroid(O, W, H) - centroid(S, S.W, S.H)
        m["balance"] = max(0.0, 1 - max(0.0, dev - 0.05) * 4)
        if dev > 0.15:
            issues.append(f"unbalanced (+{dev:.2f})")
    else:
        m["space"] = 1.0
        m["balance"] = 1.0

    # ---- alignment ---------------------------------------------------------------
    def align_frac(P: Prep, ids, w_, h_):
        vs_ = [P.by_id[i] for i in ids if P.by_id.get(i) and P.by_id[i].visible]
        if len(vs_) < 2:
            return None
        tol = 0.012 * max(w_, h_) + 1
        ok = 0
        for a in vs_:
            ax = (a.ink[0], (a.ink[0] + a.ink[2]) / 2, a.ink[2])
            ay = (a.ink[1], (a.ink[1] + a.ink[3]) / 2, a.ink[3])
            hit = False
            for b in vs_:
                if b is a:
                    continue
                bx = (b.ink[0], (b.ink[0] + b.ink[2]) / 2, b.ink[2])
                by = (b.ink[1], (b.ink[1] + b.ink[3]) / 2, b.ink[3])
                if any(abs(p - q) < tol for p, q in zip(ax, bx)) or any(abs(p - q) < tol for p, q in zip(ay, by)):
                    hit = True
                    break
            ok += hit
        return ok / len(vs_)

    ids_al = [v.id for v in S.vis if v.visible and v.role not in CONTENT_EXCLUDE and v.role != "container"]
    sa, oa = align_frac(S, ids_al, S.W, S.H), align_frac(O, ids_al, W, H)
    if sa is not None and oa is not None:
        m["alignment"] = min(1.0, oa / max(0.5, sa))
    else:
        m["alignment"] = 1.0

    # ---- completeness -------------------------------------------------------------
    cp = []
    for v in S.vis:
        if not v.visible or v.id not in O.by_id:
            continue
        w = imp.get(v.id, 0.3)
        if w <= 0:
            continue
        cp.append((1.0 if O.by_id[v.id].visible else 0.0, w))
        if not O.by_id[v.id].visible and w >= 0.3:
            issues.append(f"hidden {v.id}")
    m["completeness"] = wavg(cp) if cp else 1.0

    # ---- reading order ----------------------------------------------------------------
    ro_ids = [v.id for v in S.vis if v.visible and v.role in ("headline", "text", "cta", "body", "logo")]
    s_seq = [i for i in reading_seq([S.by_id[i] for i in ro_ids]) if O.by_id.get(i) and O.by_id[i].visible]
    o_seq = [i for i in reading_seq([O.by_id[i] for i in ro_ids if O.by_id[i].visible])]
    if len(s_seq) >= 3:
        pos = {i: k for k, i in enumerate(o_seq)}
        kc = kendall_concordance([float(-k) for k in range(len(s_seq))], [float(-pos.get(i, 0)) for i in s_seq], 1.0001)
        m["reading_order"] = kc if kc is not None else 1.0
    else:
        m["reading_order"] = 1.0

    # ---- background coverage -------------------------------------------------------------
    bgs = [v for v in S.vis if v.role == "background" and v.visible]
    if bgs:
        cov = 0.0
        for v in bgs:
            o = O.by_id.get(v.id)
            if o and o.visible:
                cov = max(cov, inter(o.box, canvas) / (W * H))
        m["bg_coverage"] = cov ** 2
        if cov < 0.98:
            issues.append(f"background covers {cov:.2f}")
    else:
        m["bg_coverage"] = 1.0

    # ---- visible missing-asset placeholders -----------------------------------------------
    miss_area = sum(area(v.ink) for v in O.vis if v.visible and v.missing)
    m["missing_visible"] = 1 - min(1.0, miss_area / (0.02 * W * H))

    total = sum(WEIGHTS[k] * m.get(k, 1.0) for k in WEIGHTS) / sum(WEIGHTS.values())
    return {"score": round(100 * total, 3), "gate": [], "metrics": {k: round(v, 4) for k, v in m.items()},
            "issues": issues[:12]}
