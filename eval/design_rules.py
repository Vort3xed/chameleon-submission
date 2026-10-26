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
  fill       the content's outer box spans the canvas about as much as the source's did
  presence   every block keeps about its share of the canvas (capped there: growing past
             it earns nothing, so an oversized button gains nothing); a resize that leaves
             small elements floating in a bigger canvas fails
  wrap       a one-line label (button, badge, price) stays one line, and a short phrase is
             not broken one word per line when the source kept its words together
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

RULES = ("alignment", "edge", "margins", "spacing", "hierarchy", "hero", "logo", "fill", "presence", "wrap",
         "corners", "bars")


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


def _aligned(r: Rect, others: List[Rect], centre: float, L: float) -> float:
    """1 if r shares an edge or centre line with another rect (or its centre with `centre`) within
    max(0.3%, 1.5 px) of the long side L, falling to 0 at 1.5%: a pixel never matters, a near-miss does."""
    best = abs(r.cx - centre) / L
    for o in others:
        best = min(best, *(abs(a - b) / L for a, b in zip((r.x, r.cx, r.x1, r.y, r.cy, r.y1),
                                                           (o.x, o.cx, o.x1, o.y, o.cy, o.y1))))
    ok = max(0.003, 1.5 / L)
    far = max(0.015, 3 * ok)
    return _clamp((far - best) / (far - ok)) if best > ok else 1.0


def alignment(W, H, groups) -> float:
    """Share of blocks that line up with a sibling or the centre of what holds
    them; `groups` are (rects, centre x) - the canvas's flow blocks, and each
    card's children.  Distances are in units of the long side, as the canvas
    is seen scaled to it."""
    L = max(W, H)
    scores = [_aligned(r, rects[:i] + rects[i + 1:], centre, L)
              for rects, centre in groups if len(rects) >= 2 for i, r in enumerate(rects)]
    return sum(scores) / len(scores) if scores else 1.0


def _groups(W: float, sc, ink) -> list:
    """(rects, centre x) to judge alignment in: the canvas, and the inside of every card."""
    out = [([ink[id(b)] for b in sc.blocks if ink[id(b)] is not None], W / 2)]

    def cards(blocks):
        for b in blocks:
            if b.kind == "panel" and b.frame is not None:
                kids = [r for r in (bounding([i.ink for i in k.items]) for k in b.children) if r is not None]
                out.append((kids, b.frame.box.cx))
                cards(b.children)
    cards(sc.blocks)
    return out


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


TIGHT = 0.012  # neighbours closer than this (fraction of the short side) read as crammed,
EM = 0.3  # and so do groups closer than 0.3 em of the larger text beside them (groups need more air than lines)


def cramming(src_blocks, out_blocks, sW, sH, W, H) -> float:
    """Share of facing neighbour pairs that are not newly crammed: closer than
    1.2% of the short side or 0.3 em now, although they were comfortably apart
    in the source.  Blocks are (ids, drawn extent, largest font), matched across
    source and output by their element ids."""
    src = {frozenset(ids): (r, f) for ids, r, f in src_blocks}
    pairs = _facing([r for _, r, _ in out_blocks])
    if not pairs:
        return 1.0
    crammed = 0
    for i, j, gap in pairs:
        (ia, _, fa), (ib, _, fb) = out_blocks[i], out_blocks[j]
        if gap >= max(TIGHT * min(W, H), EM * max(fa, fb)):
            continue
        a, b = src.get(frozenset(ia)), src.get(frozenset(ib))
        if a is None or b is None or _clearance(a[0], b[0]) >= max(TIGHT * min(sW, sH), EM * max(a[1], b[1])):
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


def _drawn_area(scene, pick) -> float:
    """Area drawn by the outermost blocks `pick` selects, nested ones included
    (product art inside a side panel, a logo on a header bar)."""
    area, todo = 0.0, list(scene.blocks + scene.ornaments)
    while todo:
        b = todo.pop()
        if not pick(b):
            todo += b.children
        elif (r := bounding([i.ink for i in b.items])) is not None:
            area += r.area
    return area


def _role_frac(d: dict, scene, role: str) -> float:
    """Share of the canvas drawn by blocks of `role` (product art, logo)."""
    W, H = float(d["canvas"]["width"]), float(d["canvas"]["height"])
    return _drawn_area(scene, lambda b: b.role == role) / (W * H)


def _ids_inks(sc, ink):
    """(element ids, drawn extent, largest font) of each flow block."""
    return [(tuple(i.el.get("id") for i in b.items), ink[id(b)], max((i.font for i in b.texts), default=0.0))
            for b in sc.blocks if ink[id(b)] is not None]


IMPORTANCE = {"headline": 1.0, "cta": 0.85, "logo": 0.85, "hero": 0.75, "subhead": 0.6, "price": 0.6}


def presence(src_blocks, out_blocks, ssc, src_area: float, out_area: float) -> float:
    """Importance-weighted share of blocks that keep at least 80% of their source share of
    the canvas (each capped at its share); a block that disappeared keeps nothing."""
    out = {frozenset(ids): r for ids, r, _ in out_blocks}
    role = {frozenset(i.el.get("id") for i in b.items): b.role for b in ssc.blocks}
    num = den = 0.0
    for ids, r, _ in src_blocks:
        key = frozenset(ids)
        w = IMPORTANCE.get(role.get(key, ""), 0.4)
        o = out.get(key)
        share = (o.area / out_area) / max(1e-9, r.area / src_area) if o is not None else 0.0
        num += w * _clamp(share / 0.8)
        den += w
    return num / den if den else 1.0


def _framed(sc, ink, W: float, H: float) -> List[Rect]:
    """Flow blocks whose outer margins matter: a panel touching the canvas edge is background-like."""
    out = []
    for b in sc.blocks:
        r = ink[id(b)]
        if r is not None and not (b.kind == "panel" and min(r.x, r.y, W - r.x1, H - r.y1) <= 1.0):
            out.append(r)
    return out


def _not_bleeding(sc, ink, bleeds=frozenset()) -> List[Rect]:
    """Flow blocks that are meant to sit inside the margins: everything except
    panels that already bled off the source's edge (`bleeds`: their element ids)."""
    return [ink[id(b)] for b in sc.blocks if ink[id(b)] is not None
            and not (b.kind == "panel" and frozenset(i.el.get("id") for i in b.items) & bleeds)]


def _bleeding_panels(sc, ink, W: float, H: float) -> frozenset:
    """Element ids of panels whose drawn extent touches the canvas edge (full-bleed bands, scrims)."""
    return frozenset(i.el.get("id") for b in sc.blocks if b.kind == "panel" and ink[id(b)] is not None
                     and min(ink[id(b)].x, ink[id(b)].y, W - ink[id(b)].x1, H - ink[id(b)].y1) <= 1.0 for i in b.items)


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
    m["alignment"] = _clamp(1 - max(0.0, alignment(sW, sH, _groups(sW, ssc, sink)) - alignment(W, H, _groups(W, sc, ink))) / 0.6)
    bleeds = _bleeding_panels(ssc, sink, sW, sH)
    m["edge"] = _clamp(1 - max(0, crowded(W, H, _not_bleeding(sc, ink, bleeds)) - crowded(sW, sH, _not_bleeding(ssc, sink, bleeds))) / 2)
    # corner ornaments, and panels bleeding off an edge (they act as background), are left out
    (sx, sy), (ox, oy) = lopsided(sW, sH, _framed(ssc, sink, sW, sH)), lopsided(W, H, _framed(sc, ink, W, H))
    m["margins"] = _clamp(1 - max(0.0, ox - sx) / 0.08) * _clamp(1 - max(0.0, oy - sy) / 0.2) ** 0.5
    m["spacing"] = cramming(_ids_inks(ssc, sink), _ids_inks(sc, ink), sW, sH, W, H)
    m["hierarchy"] = hierarchy(source, output, ssc)
    hs, ho = _role_frac(source, ssc, "hero"), _role_frac(output, sc, "hero")
    m["hero"] = 1.0 if hs <= 0 else _clamp(ho / (0.85 * hs))
    ls, lo = _role_frac(source, ssc, "logo"), _role_frac(output, sc, "logo")
    m["logo"] = 1.0 if ls <= 0 else _clamp(math.sqrt(lo / ls) / 0.8)  # linear size, 20% grace
    src_fill = bounding(sall).area / (sW * sH) if sall else 0.0
    out_fill = bounding(allr).area / (W * H) if allr else 0.0
    m["fill"] = 1.0 if src_fill <= 0 else _clamp(out_fill / (0.8 * src_fill))
    m["presence"] = presence(_ids_inks(ssc, sink), _ids_inks(sc, ink), ssc, sW * sH, W * H)
    m["wrap"] = wrapping(ssc, sc)
    m["corners"] = _corners(ssc, sc, sW, sH, W, H)
    m["bars"] = _bars(ssc, output, W, H)
    return m


def _lines(it, font, width):
    return it.text_layout(font, width).lines


def wrapping(ssc, sc) -> float:
    """Share of texts wrapped acceptably, judged with the renderer's exact wrap."""
    src = {i.el.get("id"): i for i in ssc.items if i.type == "text"}
    labels = {i.el.get("id") for b in ssc.blocks + ssc.ornaments if b.kind == "rigid" or b.role in ("cta", "badge", "price")
              for i in b.items if i.type == "text"}
    ok = n = 0
    for it in sc.items:
        s = src.get(it.el.get("id"))
        if it.type != "text" or s is None or not it.content.strip():
            continue
        out_lines, src_lines = _lines(it, it.font, it.box.w), _lines(s, s.font, s.box.w)
        words = len(it.content.split())
        n += 1
        if it.el.get("id") in labels and len(src_lines) == 1:
            ok += len(out_lines) == 1
        elif 2 <= words <= 5 and len(out_lines) >= words and len(src_lines) < words:
            ok += 0  # one word per line, though the source kept words together
        else:
            ok += 1
    return ok / n if n else 1.0


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


def _bars(ssc, output: dict, W: float, H: float) -> float:
    """Share of the source's header and footer bars that are still bars on their edge (full width, touching
    it), still cards behind all of their visible content, or hidden: a bar that floats loose from what it held
    reads as a stray box."""
    bars = [b for b in ssc.blocks if b.band in ("top", "bottom")]
    if not bars:
        return 1.0
    els = {e.get("id"): e for e in output["elements"] if isinstance(e, dict)}
    tol = 0.01 * max(W, H) + 1

    def box(e) -> Rect:
        return Rect(*(float(e.get(k) or 0) for k in ("x", "y", "width", "height")))

    def kept(b) -> bool:
        e = els.get(b.frame.el.get("id"))
        if e is None or _opacity(e) <= 0.01:
            return True
        r = box(e)
        if r.x <= tol and r.x1 >= W - tol and (r.y <= tol if b.band == "top" else r.y1 >= H - tol):
            return True
        held = [els[i.el.get("id")] for i in b.items if i is not b.frame and i.el.get("id") in els]
        held = [box(c) for c in held if _opacity(c) > 0.01]
        held = [c for c in held if min(c.w, c.h) >= 3]  # content shrunk to a speck is not held
        return bool(held) and all(r.contains(c, 0.95) for c in held)

    return sum(map(kept, bars)) / len(bars)


TASTE = ("headline", "product")


def taste(design: dict) -> Dict[str, float]:
    """What people reward beyond the source-relative rules (found in the human
    labels): a headline that is large for its canvas - full credit at 12% of the
    short side, the brief's own example is ~14% - and product art that fills it,
    full at 25% of the area.  Absolute, so an original does not score 1 here."""
    W, H, sc, _ = _scene(design)
    head = max((float(e.get("font_size") or 0) for e in design["elements"]
                if e.get("type") == "text" and _opacity(e) > 0.01), default=0.0)
    hero = _drawn_area(sc, lambda b: b.hero or b.role == "hero")
    return {"headline": _clamp(head / min(W, H) / 0.12), "product": _clamp(hero / (W * H) / 0.25)}


def score(m: Dict[str, float], weights: Dict[str, float] | None = None) -> float:
    w = weights or {k: 1.0 for k in RULES}
    return sum(m[k] * w.get(k, 0.0) for k in RULES) / max(1e-9, sum(w.values()))


def preference(source: dict, a: dict, b: dict, weights=None, temp: float = 0.02) -> Tuple[float, dict, dict]:
    ma, mb = evaluate(source, a), evaluate(source, b)
    return math.tanh((score(ma, weights) - score(mb, weights)) / temp), ma, mb
