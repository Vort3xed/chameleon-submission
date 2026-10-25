"""Design-rule metrics computed exactly from the JSON (no model involved).

Each metric is in [0, 1] (1 = follows the rule) and checks one principle a
VLM judge is bad at seeing reliably:

  alignment  blocks share edge or centre lines with each other or the canvas
             centre (the alignment measure from layout-generation research,
             Kikuchi et al. 2021 / Inoue et al. 2023)
  edge       no block crowds the canvas edge (within 2.5% of the short side)
  margins    the content's outer margins balance left/right and top/bottom
  spacing    no two neighbours that were comfortably apart are now crammed
             together (Gestalt proximity: spacing must still show what belongs together)

Every rule is relative to the source: the resize is penalised only where it
is worse than the designer's original (a full-bleed band may touch the edge
if it did before; a deliberately bottom-heavy poster may stay bottom-heavy).
  hierarchy  the source's headline is still the largest text, by its old margin
  hero       the product art keeps its share of the canvas
  logo       the logo keeps a legible share of the canvas (the brief: the logo survives intact)
  fill       the content uses the canvas about as much as the source did
  corners    corner badges / ribbons stay in their source corner

Blocks come from the engine's own scene analysis (a button's label and shape
are one block); extents are drawn ink, not boxes.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.chameleon_layout.geometry import Rect, bounding  # noqa: E402
from engine.chameleon_layout.scene import analyze  # noqa: E402

RULES = ("alignment", "edge", "margins", "spacing", "hierarchy", "hero", "logo", "fill", "corners")


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _opacity(e: dict) -> float:
    try:
        return 1.0 if e.get("opacity") is None else float(e["opacity"])
    except (TypeError, ValueError):
        return 1.0


def _scene(d: dict):
    """Scene analysis of what is actually drawn: elements at opacity 0 (how the
    engine hides dropped content, text included) are left out."""
    W, H = float(d["canvas"]["width"]), float(d["canvas"]["height"])
    drawn = [e for e in d["elements"] if isinstance(e, dict) and _opacity(e) > 0.01]
    sc = analyze(drawn, W, H)
    ink = {id(b): bounding([i.ink for i in b.items]) for b in sc.blocks + sc.ornaments}
    return W, H, sc, ink


def alignment(W, H, rects: List[Rect]) -> float:
    """Share of blocks that line up (an edge or centre within max(0.3%, 1.5 px)
    of the same line of another block, or the centre with the canvas centre),
    falling off linearly to 0 at 1.5%: a pixel never matters, a near-miss does.
    Distances are in units of the long side, as the canvas is seen scaled to it."""
    if len(rects) < 2:
        return 1.0
    L = max(W, H)
    ok = max(0.003, 1.5 / L)
    far = max(0.015, 3 * ok)
    total = 0.0
    for i, r in enumerate(rects):
        best = abs(r.cx - W / 2) / L
        for j, o in enumerate(rects):
            if i != j:
                best = min(best, *(abs(a - b) / L for a, b in zip((r.x, r.cx, r.x1, r.y, r.cy, r.y1),
                                                                   (o.x, o.cx, o.x1, o.y, o.cy, o.y1))))
        total += _clamp((far - best) / (far - ok)) if best > ok else 1.0
    return total / len(rects)


def crowded(W, H, rects: List[Rect]) -> int:
    """Blocks whose drawn content comes within 2.5% (of the short side) of the canvas edge."""
    lim = 0.025 * min(W, H)
    return sum(1 for r in rects if min(r.x, r.y, W - r.x1, H - r.y1) < lim)


def lopsided(W, H, rects: List[Rect]) -> Tuple[float, float]:
    """Left/right and top/bottom imbalance of the content's outer margins, as canvas fractions."""
    if not rects:
        return 0.0, 0.0
    c = bounding(rects)
    return abs(c.x - (W - c.x1)) / W, abs(c.y - (H - c.y1)) / H


def _facing(rects: List[Rect]) -> List[Tuple[int, int, float]]:
    """(i, j, gap) for neighbours that face each other vertically or horizontally with nothing in between."""
    out = []
    for i, a in enumerate(rects):
        for j, b in enumerate(rects):
            if i == j:
                continue
            if b.y >= a.y1 and min(a.x1, b.x1) > max(a.x, b.x):  # b below a
                if not any(k not in (i, j) and c.y >= a.y1 and c.y1 <= b.y and min(c.x1, a.x1, b.x1) > max(c.x, a.x, b.x)
                           for k, c in enumerate(rects)):
                    out.append((i, j, b.y - a.y1))
            if b.x >= a.x1 and min(a.y1, b.y1) > max(a.y, b.y):  # b right of a
                if not any(k not in (i, j) and c.x >= a.x1 and c.x1 <= b.x and min(c.y1, a.y1, b.y1) > max(c.y, a.y, b.y)
                           for k, c in enumerate(rects)):
                    out.append((i, j, b.x - a.x1))
    return out


def _clearance(a: Rect, b: Rect) -> float:
    """Gap between two rects along the axis that separates them (negative if they overlap)."""
    return max(b.x - a.x1, a.x - b.x1, b.y - a.y1, a.y - b.y1)


TIGHT = 0.012  # neighbours closer than this (fraction of the short side) read as crammed


def cramming(src_blocks, out_blocks, sW, sH, W, H) -> float:
    """Share of facing neighbour pairs that are not newly crammed: closer than
    1.2% of the short side now, although they were comfortably apart in the source.
    Blocks are matched across source and output by their element ids."""
    src = {frozenset(ids): r for ids, r in src_blocks}
    pairs = _facing([r for _, r in out_blocks])
    if not pairs:
        return 1.0
    crammed = 0
    for i, j, gap in pairs:
        if gap / min(W, H) >= TIGHT:
            continue
        a, b = src.get(frozenset(out_blocks[i][0])), src.get(frozenset(out_blocks[j][0]))
        if a is None or b is None or _clearance(a, b) / min(sW, sH) >= TIGHT:
            crammed += 1
    return _clamp(1 - 2 * crammed / len(pairs))


def _font_of(d: dict, el_id) -> float:
    for e in d["elements"]:
        if e.get("id") == el_id:
            return float(e.get("font_size") or 0)
    return 0.0


def hierarchy(src: dict, out: dict, src_scene) -> float:
    heads = [b for b in src_scene.blocks if b.role == "headline" and b.kind == "text"]
    if not heads:
        return 1.0
    hid = heads[0].items[0].el.get("id")
    others = [e for e in out["elements"] if e.get("type") == "text" and e.get("id") != hid and e.get("opacity", 1) > 0]
    src_others = [e for e in src["elements"] if e.get("type") == "text" and e.get("id") != hid]
    if not others or not src_others:
        return 1.0
    r_src = _font_of(src, hid) / max(1.0, max(float(e.get("font_size") or 0) for e in src_others))
    r_out = _font_of(out, hid) / max(1.0, max(float(e.get("font_size") or 0) for e in others))
    want = min(r_src, 1.25)
    return 1.0 if want <= 1.0 else _clamp((r_out - 1.0) / (want - 1.0))


def _role_frac(d: dict, scene, ink, role: str) -> float:
    """Share of the canvas drawn by blocks of `role` (product art, logo)."""
    W, H = float(d["canvas"]["width"]), float(d["canvas"]["height"])
    blocks = [b for b in scene.blocks + scene.ornaments if b.role == role and ink[id(b)] is not None]
    return sum(ink[id(b)].area for b in blocks) / (W * H)


def _ids_inks(sc, ink):
    return [(tuple(i.el.get("id") for i in b.items), ink[id(b)]) for b in sc.blocks if ink[id(b)] is not None]


def _not_bleeding(sc, ink) -> List[Rect]:
    """Flow blocks that are meant to sit inside the margins (panels and frames may bleed)."""
    return [ink[id(b)] for b in sc.blocks if ink[id(b)] is not None and b.kind != "panel"]


def evaluate(source: dict, output: dict) -> Dict[str, float]:
    """Each rule compares the resize with its own source: a designer's original
    scores 1 everywhere against itself, and only what got worse is penalised."""
    sW, sH, ssc, sink = _scene(source)
    W, H, sc, ink = _scene(output)
    sflow = [sink[id(b)] for b in ssc.blocks if sink[id(b)] is not None]
    flow = [ink[id(b)] for b in sc.blocks if ink[id(b)] is not None]
    sall = sflow + [sink[id(b)] for b in ssc.ornaments if sink[id(b)] is not None]
    allr = flow + [ink[id(b)] for b in sc.ornaments if ink[id(b)] is not None]
    m = {}
    m["alignment"] = _clamp(1 - max(0.0, alignment(sW, sH, sflow) - alignment(W, H, flow)) / 0.6)
    m["edge"] = _clamp(1 - max(0, crowded(W, H, _not_bleeding(sc, ink)) - crowded(sW, sH, _not_bleeding(ssc, sink))) / 2)
    (sx, sy), (ox, oy) = lopsided(sW, sH, sflow), lopsided(W, H, flow)  # corner ornaments excluded
    m["margins"] = _clamp(1 - max(0.0, ox - sx) / 0.08) * _clamp(1 - max(0.0, oy - sy) / 0.2) ** 0.5
    m["spacing"] = cramming(_ids_inks(ssc, sink), _ids_inks(sc, ink), sW, sH, W, H)
    m["hierarchy"] = hierarchy(source, output, ssc)
    hs, ho = _role_frac(source, ssc, sink, "hero"), _role_frac(output, sc, ink, "hero")
    m["hero"] = 1.0 if hs <= 0 else _clamp(ho / (0.85 * hs))
    ls, lo = _role_frac(source, ssc, sink, "logo"), _role_frac(output, sc, ink, "logo")
    m["logo"] = 1.0 if ls <= 0 else _clamp(math.sqrt(lo / ls) / 0.8)  # linear size, 20% grace
    src_fill = bounding(sall).area / (sW * sH) if sall else 0.0
    out_fill = bounding(allr).area / (W * H) if allr else 0.0
    m["fill"] = 1.0 if src_fill <= 0 else _clamp(out_fill / (0.8 * src_fill))
    m["corners"] = _corners(ssc, sc, sW, sH, W, H)
    return m


def _corners(ssc, sc, sW, sH, W, H) -> float:
    def near(r, w, h):
        return min(r.x, w - r.x1) < 0.15 * w and min(r.y, h - r.y1) < 0.15 * h

    src = {tuple(sorted(i.el.get("id") for i in b.items)): b.corner for b in ssc.ornaments if near(b.src, sW, sH)}
    if not src:
        return 1.0
    kept = 0
    for b in sc.blocks + sc.ornaments:
        key = tuple(sorted(i.el.get("id") for i in b.items))
        if key in src:
            r = b.src
            corner = ("t" if r.cy < H / 2 else "b") + ("l" if r.cx < W / 2 else "r")
            kept += corner == src[key] and near(r, W, H)
    return kept / len(src)


def score(m: Dict[str, float], weights: Dict[str, float] | None = None) -> float:
    w = weights or {k: 1.0 for k in RULES}
    return sum(m[k] * w.get(k, 0.0) for k in RULES) / max(1e-9, sum(w.values()))


def preference(source: dict, a: dict, b: dict, weights=None, temp: float = 0.02) -> Tuple[float, dict, dict]:
    ma, mb = evaluate(source, a), evaluate(source, b)
    return math.tanh((score(ma, weights) - score(mb, weights)) / temp), ma, mb
