"""All candidate layouts for a scene: the arrangement families (families.py)
at progressively stronger drop levels, with header / footer bands kept at
their edges where that reads, each finished (finishing.py); the same shape
keeps the designer's composition.  `candidates` is the entry point.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from . import blocks as B
from .blocks import Ctx, Placement, place
from .families import Layout, Scope, _base, _panel_inner, arrangements, outer_margins, preserve, scale_block
from .finishing import _anchored, _is_frame, finish, opaque_covers
from .geometry import Rect
from .scene import Block, Scene, backdrop, luminance

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
    covered = opaque_covers(scene)
    levels, seen = [[]], set()
    for thr in DROP_STEPS:
        drop = [b for b in pool if b.importance < thr and not _never_dropped(b)
                and (scene.hide_z is not None or not b.texts or id(b) in covered)]
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


def _flowing(scene: Scene, ctx0: Ctx, src: Rect, region: Rect, judge: Scope, bands, stripes,
             mx: float, my: float) -> List[Layout]:
    """The arrangement families at each drop level, with the given bands kept at their edges
    (the content of a stripe - a bar that cannot hold it - flows with the rest)."""
    from .objective import evaluate

    out: List[Layout] = []
    for drop in drop_levels(scene):
        flow = [prune(b, drop) for b in scene.blocks if b not in drop and id(b) not in bands]
        flow += [prune(c, drop) for k in stripes for c in bands[k][0].children if c not in drop]
        if flow:
            lays = arrangements(Scope(flow, src, region), ctx0, scene.items, allow_preserve=False)
        elif bands:  # nothing but bars: they are the layout
            lays = [Layout("bands", _base(ctx0, 1.0))]
        else:
            continue
        for lay in lays:
            lay.hidden += drop
            lay.region = region
            _place_bands(lay, bands, stripes, scene, mx, my)
            finish(scene, lay, [b for b in scene.ornaments if b not in drop])
        lays = [lay for lay in lays if all(it.idx in lay.out for k in bands for it in bands[k][0].items)]
        out += lays  # (a bar whose content fits no arrangement inside it cannot be kept in that layout)
        if any(evaluate(lay, judge, scene.items)["legibility"] >= 0.97 for lay in lays):
            break  # everything left is legible: no need to drop more
        if len(out) > MAX_LAYOUTS:
            break
    return out


def _between(region: Rect, bands, scene: Scene, mx: float, my: float) -> Rect:
    """The content region left between the kept bands.  Where the source let
    content run under a bar (product art beneath a photo scrim), it may again,
    as deep into the bar as it went."""
    if not bands:
        return region

    def under(b: Block) -> float:
        f, flow = b.frame.box, [o.src for o in scene.blocks if o is not b and not o.band]
        depth = [min(r.y1, f.y1) - f.y if b.band == "bottom" else f.y1 - max(r.y, f.y)
                 for r in flow if min(r.x1, f.x1) > max(r.x, f.x)]
        return max(0.0, min(0.6, max(depth, default=0.0) / f.h))

    def kept(edge):
        return [(b, r) for b, r in bands.values() if b.band == edge]

    tops = [r.y1 - under(b) * r.h if under(b) else r.y1 + my for b, r in kept("top")]
    bottoms = [r.y + under(b) * r.h if under(b) else r.y - my for b, r in kept("bottom")]
    y0, y1 = max([region.y] + tops), min([region.y1] + bottoms)
    x0 = max([region.x] + [r.x1 + mx for _, r in kept("left")])
    x1 = min([region.x1] + [r.x - mx for _, r in kept("right")])
    return Rect(x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0))


BAND_MIN = 24.0  # px: a band thinner than this cannot hold its content; it stays a stripe on its edge


def _bands(scene: Scene, W: float, H: float) -> Dict[int, Tuple[Block, Rect]]:
    """Bars on an edge (header, footer, photo scrim, side panel) keep that edge,
    their full length and their share of the canvas across it.  A side panel
    does so only on a canvas relatively as wide as the source or wider, and
    only wide enough to hold its content."""
    def rect(b: Block) -> Rect:
        f = b.frame.box
        if b.band in ("top", "bottom"):
            h = f.h * H / scene.H
            return Rect(0.0, 0.0 if b.band == "top" else H - h, W, h)
        w = f.w * W / scene.W
        return Rect(0.0 if b.band == "left" else W - w, 0.0, w, H)

    wider = W / H >= scene.W / scene.H  # a side panel keeps its edge only with room beside it, and room
    side = lambda b: (wider or len(b.items) == 1) and rect(b).w >= BAND_MIN  # noqa: E731  # inside it (an empty
    # one always: flowing, it would only float as a box); else it flows
    return {id(b): (b, rect(b)) for b in scene.blocks if b.band in ("top", "bottom") or b.band and side(b)}


KEY_ROLES = ("headline", "cta", "hero", "price")


def _holds_key(b: Block) -> bool:
    """The block is, or holds, part of the message (headline, button, product...)."""
    return b.role in KEY_ROLES or b.hero or any(map(_holds_key, b.children))


def _kept(b: Block, r: Rect, bg: Optional[float], H: float) -> Optional[Rect]:
    """Where a band is kept, if at all.  One thick enough holds its content; a bar too thin for it never
    floats as a box: empty, or with peripheral content (a logo, small print) that stays legible off it, it
    becomes a stripe; else it grows to hold that content (up to a quarter of the canvas); a thin bar holding
    the message is not kept - it flows as a card behind it."""
    if min(r.w, r.h) >= BAND_MIN or len(b.items) == 1 or _stripe(b, bg):
        return r
    if not _holds_key(b) and BAND_MIN <= 0.25 * H:
        return Rect(r.x, 0.0 if b.band == "top" else H - BAND_MIN, r.w, BAND_MIN)
    return None


def _stripe(b: Block, bg: Optional[float]) -> bool:
    """A thin bar may become a stripe, its content lifted onto the canvas: only peripheral content, and only
    off a bar close in tone to the background (contrast under 2:1), so what it held stays legible."""
    lum = luminance(b.frame.el.get("fill_color"))
    return not _holds_key(b) and lum is not None and bg is not None and (max(lum, bg) + 0.05) / (min(lum, bg) + 0.05) < 2


def _place_bands(lay: Layout, bands: Dict[int, Tuple[Block, Rect]], stripes, scene: Scene, mx: float, my: float):
    """Each band's bar at its edge, its content laid out inside it - free along the bar, in proportion across
    it - unless the bar is a stripe, whose content flows with the rest."""
    for k, (b, r) in bands.items():
        lay.placed.append((b, r))
        if k in stripes:
            lay.out[b.frame.idx] = Placement(r.x, r.y, r.w, r.h)
            continue
        f, inner = b.frame.box, b.inner or b.frame.box
        if b.band in ("top", "bottom"):
            s = r.h / f.h
            box = Rect(r.x + mx, r.y + (inner.y - f.y) * s, r.w - 2 * mx, inner.h * s)
        else:
            s = r.w / f.w
            box = Rect(r.x + (inner.x - f.x) * s, r.y + my, inner.w * s, r.h - 2 * my)
        if b.kind == "rigid":  # a lone picture on the bar: scaled as one to fit, centred where it was
            fit = min(box.w / inner.w, box.h / inner.h)
            scale_block(b, fit, box.cx - (inner.cx - b.src.x) * fit, box.cy - (inner.cy - b.src.y) * fit, lay.out)
        else:
            lay.out.update(_panel_inner(b.children, inner, box, lay.ctx, scene.items))
        lay.out[b.frame.idx] = Placement(r.x, r.y, r.w, r.h)


def _bleed_bands(lay: Layout, scene: Scene, W: float, H: float):
    """Keep-the-composition scales a band in place: its bar grows back to its edge and its full length."""
    for b in scene.blocks:
        if b.band and b.frame.idx in lay.out:
            p = lay.out[b.frame.idx]
            lay.out[b.frame.idx] = {"top": replace(p, x=0.0, w=W, y=0.0, h=p.y + p.h),
                                    "bottom": replace(p, x=0.0, w=W, h=H - p.y),
                                    "left": replace(p, x=0.0, w=p.x + p.w, y=0.0, h=H),
                                    "right": replace(p, w=W - p.x, y=0.0, h=H)}[b.band]


def _with_bands(scene: Scene, ctx0: Ctx, src: Rect, region: Rect, judge: Scope, mx: float, my: float) -> List[Layout]:
    """The flowing layouts with the bands kept at their edges whenever that reads - or reads no worse
    than flowing them as cards behind their content.  Stripes keep their edges either way."""
    from .objective import evaluate

    def flow(bands, stripes):  # the flow sits between the bands, in proportion to where it sat in the source
        free = _between(src, {k: (b, b.frame.box) for k, (b, _) in bands.items()}, scene, 0.0, 0.0)
        return _flowing(scene, ctx0, free, _between(region, bands, scene, mx, my), judge, bands, stripes, mx, my)

    def legibility(lays):
        return max((evaluate(lay, judge, scene.items)["legibility"] for lay in lays), default=0.0)

    bg = backdrop(scene)
    bands = {k: (b, kr) for k, (b, r) in _bands(scene, ctx0.W, ctx0.H).items() if (kr := _kept(b, r, bg, ctx0.H)) is not None}
    thin = {k: v for k, v in bands.items() if min(v[1].w, v[1].h) < BAND_MIN}
    kept = flow(bands, list(thin)) if bands else []  # (lists, not sets: the flow keeps the source's order)
    if legibility(kept) >= 0.9:
        return kept
    cards = flow(thin, list(thin))
    return cards if not kept or legibility(cards) > legibility(kept) + 0.02 else kept


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
    out += _with_bands(scene, ctx0, src, region, judge, mx, my)
    if not out:
        out.append(finish(scene, letterbox(scene, ctx0), []))
    return judge, out
