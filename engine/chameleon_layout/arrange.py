"""All candidate layouts for a scene: the arrangement families (families.py)
at progressively stronger drop levels, with header / footer bands kept at
their edges where that reads, each finished (finishing.py); the same shape
keeps the designer's composition.  `candidates` is the entry point.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Dict, List, Tuple

from . import blocks as B
from .blocks import Ctx, Placement, place
from .families import Layout, Scope, _base, _panel_inner, arrangements, outer_margins, preserve, scale_block
from .finishing import _anchored, _is_frame, finish
from .geometry import Rect
from .scene import Block, Scene

DROP_STEPS = (0.25, 0.36, 0.45, 0.55, 0.65, 0.8, 0.9)


def _never_dropped(b: Block) -> bool:
    """Headline, button and logo stay, and so does any panel holding one; a
    panel holding only small print (a footer bar with legal text) may go."""
    return b.importance >= DROP_STEPS[-1] or b.role in ("headline", "cta", "logo") or \
        b.kind == "panel" and (not b.children or any(_never_dropped(c) for c in b.children))


def _drop_pool(blocks: List[Block]) -> List[Block]:
    """Blocks that could be hidden: these, and the children of panels that
    keep at least one child for sure (so no panel is ever left empty)."""
    out = []
    for b in blocks:
        out.append(b)
        if b.kind == "panel" and any(_never_dropped(c) for c in b.children):
            out += _drop_pool(b.children)
    return out


def prune(b: Block, drop: List[Block]) -> Block:
    """`b` without the dropped blocks nested inside it (panels keep their frame)."""
    gone = {it.idx for d in drop for it in d.items}
    if b.kind != "panel" or not any(it.idx in gone for it in b.items):
        return b
    return replace(b, items=[it for it in b.items if it.idx not in gone],
                   children=[prune(c, drop) for c in b.children if c not in drop])


def drop_levels(scene: Scene) -> List[List[Block]]:
    """Progressively larger sets of low-importance blocks (also inside panels)
    that may be hidden when the canvas is too small to show everything
    legibly.  Headline, CTA and logo are never dropped; text only when it
    can really be hidden."""
    pool = _drop_pool(scene.blocks) + scene.ornaments
    levels, seen = [[]], set()
    for thr in DROP_STEPS:
        drop = [b for b in pool if b.importance < thr and not _never_dropped(b)
                and (scene.hide_z is not None or not b.texts)]
        key = frozenset(map(id, drop))
        if drop and key not in seen and len(drop) < len(pool):
            seen.add(key)
            levels.append(drop)
    return levels


def letterbox(scene: Scene, ctx0: Ctx) -> Layout:
    """Always-valid fallback: the source composition scaled uniformly and centred."""
    W, H = ctx0.W, ctx0.H
    s = min(W / scene.W, H / scene.H)
    ox, oy = (W - scene.W * s) / 2, (H - scene.H * s) / 2
    lay = Layout("letterbox", ctx0.with_scale(s, s))
    for b in scene.blocks + scene.ornaments:
        r = b.src
        x, y = ox + r.x * s, oy + r.y * s
        scale_block(b, s, x, y, lay.out)
        lay.placed.append((b, Rect(x, y, r.w * s, r.h * s)))
    return lay


SAME_SHAPE = 0.08  # aspect ratios this close (log ratio) count as the same shape
MAX_LAYOUTS = 400  # past this many candidates no further drop levels are explored (deterministic,
                   # unlike a time budget: the same input gives the same output on any machine)


def _flowing(scene: Scene, ctx0: Ctx, src: Rect, region: Rect, judge: Scope, bands, mx: float) -> List[Layout]:
    """The arrangement families at each drop level, with the given bands kept at their edges."""
    from .objective import evaluate

    out: List[Layout] = []
    for drop in drop_levels(scene):
        flow = [prune(b, drop) for b in scene.blocks if b not in drop and id(b) not in bands]
        if flow:
            lays = arrangements(Scope(flow, src, region), ctx0, scene.items, allow_preserve=False)
        elif bands:  # nothing but bars: they are the layout
            lays = [Layout("bands", _base(ctx0, 1.0))]
        else:
            continue
        for lay in lays:
            lay.hidden += drop
            _place_bands(lay, bands, scene, mx)
            finish(scene, lay, [b for b in scene.ornaments if b not in drop])
        out += lays
        if any(evaluate(lay, judge, scene.items)["legibility"] >= 0.97 for lay in lays):
            break  # everything left is legible: no need to drop more
        if len(out) > MAX_LAYOUTS:
            break
    return out


def _between(region: Rect, bands, scene: Scene, my: float) -> Rect:
    """The content region left between the kept bands.  Where the source let
    content run under a bar (product art beneath a photo scrim), it may again,
    as deep into the bar as it went."""
    def under(b: Block) -> float:
        f, flow = b.frame.box, [o.src for o in scene.blocks if o is not b and not o.band]
        depth = [min(r.y1, f.y1) - f.y if b.band == "bottom" else f.y1 - max(r.y, f.y)
                 for r in flow if min(r.x1, f.x1) > max(r.x, f.x)]
        return max(0.0, min(0.6, max(depth, default=0.0) / f.h))

    tops = [r.y1 - under(b) * r.h if under(b) else r.y1 + my for b, r in bands.values() if b.band == "top"]
    bottoms = [r.y + under(b) * r.h if under(b) else r.y - my for b, r in bands.values() if b.band == "bottom"]
    y0, y1 = max([region.y] + tops), min([region.y1] + bottoms)
    return Rect(region.x, y0, region.w, max(1.0, y1 - y0))


BAND_MIN = 24.0  # px: a band thinner than this cannot hold its content, so on such strips bands flow like any block


def _bands(scene: Scene, W: float, H: float) -> Dict[int, Tuple[Block, Rect]]:
    """Full-width bars (header, footer, photo scrim) keep their edge, the full
    width and their share of the canvas height - or none do."""
    s = H / scene.H
    out = {id(b): (b, Rect(0.0, 0.0 if b.band == "top" else H - b.frame.box.h * s, W, b.frame.box.h * s))
           for b in scene.blocks if b.band}
    return out if all(r.h >= BAND_MIN for _, r in out.values()) else {}


def _place_bands(lay: Layout, bands: Dict[int, Tuple[Block, Rect]], scene: Scene, mx: float):
    """Each band's bar at its edge, its content laid out inside it."""
    for b, r in bands.values():
        f, inner = b.frame.box, b.inner or b.frame.box
        s = r.h / f.h
        lay.out[b.frame.idx] = Placement(r.x, r.y, r.w, r.h)
        box = Rect(r.x + mx, r.y + (inner.y - f.y) * s, r.w - 2 * mx, inner.h * s)
        lay.out.update(_panel_inner(b.children, inner, box, lay.ctx, scene.items))
        lay.placed.append((b, r))


def _bleed_bands(lay: Layout, scene: Scene, W: float, H: float):
    """Keep-the-composition scales a band in place: its bar grows back to the edge and the full width."""
    for b in scene.blocks:
        if b.band and b.frame.idx in lay.out:
            p = lay.out[b.frame.idx]
            lay.out[b.frame.idx] = replace(p, x=0.0, w=W, y=0.0, h=p.y + p.h) if b.band == "top" else \
                replace(p, x=0.0, w=W, h=H - p.y)


def candidates(scene: Scene, ctx0: Ctx) -> Tuple[Scope, List[Layout]]:
    """All candidate layouts, plus the scope they should be judged in."""
    from .objective import evaluate

    W, H = ctx0.W, ctx0.H
    src, canvas = Rect(0, 0, scene.W, scene.H), Rect(0, 0, W, H)
    frame = max((it for it in scene.decor if _is_frame(it, scene)), key=lambda it: it.box.area, default=None)
    if frame is not None:  # an inset border frames the content: it is the canvas the content lives in
        src = Rect(max(0.0, frame.box.x), max(0.0, frame.box.y), 0, 0)
        src = Rect(src.x, src.y, min(scene.W, frame.box.x1) - src.x, min(scene.H, frame.box.y1) - src.y)
        canvas = _anchored(frame, scene, W, H, min(W / scene.W, H / scene.H)).rect
    mx, my = outer_margins(canvas.w, canvas.h)
    region = Rect(canvas.x + mx, canvas.y + my, canvas.w - 2 * mx, canvas.h - 2 * my)
    judge = Scope(scene.blocks + scene.ornaments, src, region)
    B.panel_layout_hook = lambda kids, s, r, c: _panel_inner(kids, s, r, c, scene.items)
    out = []
    stretch = abs(math.log((W / H) / (scene.W / scene.H)))
    if stretch < 0.45:
        for boost in (2.0, 1.75, 1.5, 1.4, 1.3, 1.2, 1.1, 1.0):
            lay = preserve(Scope(scene.blocks + scene.ornaments, src, canvas), ctx0, boost, scene.items)
            if lay is not None:  # preserve positions the ornaments itself
                _bleed_bands(lay, scene, W, H)
                out.append(finish(scene, lay, []))
                break
        if out and stretch < SAME_SHAPE and evaluate(out[0], judge, scene.items)["legibility"] >= 0.9:
            return judge, out  # the same shape keeps the designer's composition
    bands = _bands(scene, W, H)
    kept = _flowing(scene, ctx0, src, _between(region, bands, scene, my), judge, bands, mx) if bands else []
    if any(evaluate(lay, judge, scene.items)["legibility"] >= 0.9 for lay in kept):
        out += kept  # headers, footers and scrims stay at their edges whenever that reads
    else:
        out += _flowing(scene, ctx0, src, region, judge, {}, mx)
    if not out:
        out.append(finish(scene, letterbox(scene, ctx0), []))
    return judge, out
