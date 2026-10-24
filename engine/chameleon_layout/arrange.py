"""Candidate layouts for a set of blocks inside a region.

  preserve  keep the source composition: uniform scale, every block keeps its
            relative position (best for nearby aspect ratios)
  stack     one column in reading order (tall / square regions)
  split     hero visual in one column, everything else stacked beside it
  row       banner: logo | visual | text columns | call to action

Arrangements work on a `Scope` (blocks + their source frame + target region),
so the canvas and the inside of a panel (card, scrim) are handled the same
way: a panel's children get their own best arrangement for the panel's new
shape.  Each arrangement searches the largest text scale that fits.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import blocks as B
from .blocks import INF, Ctx, Placement, fit_block, keep_lines, measure, place, stack_measure, stack_place
from .geometry import Rect
from .scene import Block, Scene


@dataclass
class Scope:
    blocks: List[Block]
    src: Rect  # where these blocks lived in the source
    region: Rect  # where they must go now


@dataclass
class Layout:
    name: str
    ctx: Ctx
    out: Dict[int, Placement] = field(default_factory=dict)
    placed: List[Tuple[Block, Rect]] = field(default_factory=list)
    hidden: List[Block] = field(default_factory=list)


def margin(W: float, H: float) -> float:
    return max(2.0, 0.045 * min(W, H))


def bisect(fits: Callable[[float], bool], lo: float, hi: float, steps: int = 14) -> Optional[float]:
    """Largest value in [lo, hi] for which `fits` holds (assumed monotone)."""
    if fits(hi):
        return hi
    if not fits(lo):
        return None
    for _ in range(steps):
        mid = math.sqrt(lo * hi)
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo


def scale_bounds(scope: Scope) -> Tuple[float, float]:
    sx, sy = scope.region.w / scope.src.w, scope.region.h / scope.src.h
    m, M = min(sx, sy), max(sx, sy)
    return 0.02, max(m, math.sqrt(m * M)) * 1.15


def _fit_scale(build):
    """Search the text scale for each floor-relaxation level until one fits."""
    for relax in (1.0, 0.8, 0.6, 0.0):
        lay = build(relax)
        if lay is not None:
            return lay
    return None


def _base(ctx0: Ctx, relax: float) -> Ctx:
    return Ctx(ctx0.W, ctx0.H, ctx0.src_W, ctx0.src_H, floor_relax=relax)


# ---------------------------------------------------------------------------
# arrangements


def preserve(scope: Scope, ctx0: Ctx, boost: float, items) -> Optional[Layout]:
    src, reg = scope.src, scope.region
    s = min(reg.w / src.w, reg.h / src.h) * boost
    ctx = ctx0.with_scale(s, s)
    ctx.floor_relax = 0.0
    lay = Layout(f"preserve{boost:.2f}", ctx)
    for b in scope.blocks:
        r = b.src
        w, h = r.w * s, r.h * s
        if w > reg.w + 0.5 or h > reg.h + 0.5:
            return None
        x = min(max(reg.x, reg.x + (r.cx - src.x) / src.w * reg.w - w / 2), reg.x1 - w)
        y = min(max(reg.y, reg.y + (r.cy - src.y) / src.h * reg.h - h / 2), reg.y1 - h)
        scale_block(b, s, x, y, lay.out)
        lay.placed.append((b, Rect(x, y, w, h)))
    from .objective import new_overlap

    if new_overlap(lay.out, scope.blocks, items) > 0.05:
        return None  # elements that were apart (or barely touching) now collide
    return lay


def scale_block(b: Block, s: float, x: float, y: float, out: Dict[int, Placement]):
    """Scale a block's elements uniformly about its source corner."""
    src = b.src
    for it in b.items:
        p = Placement(x + (it.box.x - src.x) * s, y + (it.box.y - src.y) * s, it.box.w * s, it.box.h * s)
        if it.type == "text":
            p.font = keep_lines(it, it.font * s, p.w)
        out[it.idx] = p


def stack(scope: Scope, ctx0: Ctx, k: float) -> Optional[Layout]:
    blocks, reg = scope.blocks, scope.region
    if not blocks:
        return None
    lo, hi = scale_bounds(scope)

    def build(relax):
        base = _base(ctx0, relax)

        def fits(ts):
            w, h, _, _ = stack_measure(blocks, base.with_scale(ts, ts * k), reg.w, reg.h)
            return h <= reg.h and w <= reg.w + 0.5

        ts = bisect(fits, lo, hi)
        if ts is None:
            return None
        lay = Layout(f"stack k={k}", base.with_scale(ts, ts * k))
        lay.placed = stack_place(blocks, lay.ctx, reg, lay.out)
        return lay

    return _fit_scale(build)


def visual_block(blocks: List[Block]) -> Optional[Block]:
    cands = [b for b in blocks if b.role in ("hero", "image")
             or (b.kind == "row" and all(c.role == "image" for c in b.children))]
    return max(cands, key=lambda b: b.src.area) if cands else None


def split(scope: Scope, ctx0: Ctx, side: str, frac: float, k: float) -> Optional[Layout]:
    vis = visual_block(scope.blocks)
    rest = [b for b in scope.blocks if b is not vis]
    if vis is None or not rest:
        return None
    reg = scope.region
    gutter = margin(reg.w, reg.h)
    vw = (reg.w - gutter) * frac
    vcol = Rect(reg.x if side == "left" else reg.x1 - vw, reg.y, vw, reg.h)
    tcol = Rect(reg.x + vw + gutter if side == "left" else reg.x, reg.y, reg.w - vw - gutter, reg.h)
    lo, hi = scale_bounds(scope)

    def build(relax):
        base = _base(ctx0, relax)

        def fits(ts):
            w, h, _, _ = stack_measure(rest, base.with_scale(ts, ts * k), tcol.w, tcol.h)
            return h <= tcol.h and w <= tcol.w + 0.5

        ts = bisect(fits, lo, hi)
        if ts is None:
            return None
        lay = Layout(f"split {side} {frac} k={k}", base.with_scale(ts, ts * k))
        big = fit_block(vis, lay.ctx, vcol.w, vcol.h * 0.92)
        w, h = measure(vis, big, vcol.w)
        r = place(vis, big, vcol.x + (vcol.w - w) / 2, vcol.y + (vcol.h - h) / 2, vcol.w, INF, lay.out)
        lay.placed = [(vis, r)] + stack_place(rest, lay.ctx, tcol, lay.out, valign="center")
        return lay

    return _fit_scale(build)


def _partitions(items: List[Block], max_parts: int):
    n = len(items)
    for parts in range(1, min(max_parts, n) + 1):
        for cuts in itertools.combinations(range(1, n), parts - 1):
            bounds = (0,) + cuts + (n,)
            yield [items[a:b] for a, b in zip(bounds, bounds[1:])]


def _text_weight(blocks: List[Block]) -> float:
    return sum(sum(len(t.content) * t.font for t in b.texts) or b.src.w for b in blocks) or 1.0


def row(scope: Scope, ctx0: Ctx) -> List[Layout]:
    reg, blocks = scope.region, scope.blocks
    logo = [b for b in blocks if b.role == "logo"][:1]
    vis = visual_block([b for b in blocks if b not in logo])
    cta = [b for b in blocks if b.role == "cta" and b not in logo][-1:]
    middle = [b for b in blocks if b not in logo + cta and b is not vis]
    lead = logo + ([vis] if vis is not None else [])
    gap = max(4.0, 0.6 * margin(reg.w, reg.h))
    lo, hi = scale_bounds(scope)
    layouts = []
    for parts in (_partitions(middle, 3) if middle else [[]]):
        def columns(ts, relax):
            c = Ctx(ctx0.W, ctx0.H, ctx0.src_W, ctx0.src_H, ts, ts, relax)
            fixed = [(b, _slot_size(b, c, reg)) for b in lead]
            tail = [(b, _slot_size(b, c, reg)) for b in cta]
            used = sum(w for _, (w, _) in fixed + tail) + gap * (len(fixed) + len(tail) + len(parts) - 1)
            weights = [_text_weight(p) for p in parts]
            widths = [(reg.w - used) * w / sum(weights) for w in weights] if parts else []
            return c, fixed, tail, widths

        def fits(ts, relax):
            c, fixed, tail, widths = columns(ts, relax)
            if any(w <= 4 for w in widths) or any(h > reg.h for _, (_, h) in fixed + tail):
                return False
            for p, w in zip(parts, widths):
                cw, ch, _, _ = stack_measure(p, c, w, reg.h)
                if ch > reg.h or cw > w + 0.5:
                    return False
            return True

        ts = relax = None
        for relax in (1.0, 0.8, 0.6):
            ts = bisect(lambda t: fits(t, relax), lo, hi, steps=10)
            if ts is not None:
                break
        if ts is None:
            continue
        c, fixed, tail, widths = columns(ts, relax)
        lay = Layout(f"row {len(parts)}col", c)
        seq = [(b, wh[0]) for b, wh in fixed] + [(p, w) for p, w in zip(parts, widths)] + [(b, wh[0]) for b, wh in tail]
        extra = max(0.0, reg.w - sum(w for _, w in seq) - gap * (len(seq) - 1)) / max(1, len(seq) - 1)
        x = reg.x
        for obj, w in seq:
            if isinstance(obj, Block):
                bc = _slot_ctx(obj, c, reg)
                bw, bh = measure(obj, bc, reg.w / 3)
                lay.placed.append((obj, place(obj, bc, x, reg.y + (reg.h - bh) / 2, reg.w / 3, INF, lay.out)))
            else:
                lay.placed += stack_place(obj, c, Rect(x, reg.y, w, reg.h), lay.out, valign="center")
            x += w + gap + extra
        layouts.append(lay)
    return layouts


def _slot_ctx(b: Block, c: Ctx, reg: Rect) -> Ctx:
    """Banner items: images fill the height (logo a bit less), chips follow the text scale."""
    if b.role in ("logo", "hero", "image") or b.kind == "image":
        return fit_block(b, c, reg.w / 3, reg.h * (0.75 if b.role == "logo" else 1.0))
    w, h = measure(b, c, reg.w / 3)
    return c if h <= reg.h else fit_block(b, c, reg.w / 3, reg.h)


def _slot_size(b: Block, c: Ctx, reg: Rect) -> Tuple[float, float]:
    return measure(b, _slot_ctx(b, c, reg), reg.w / 3)


def arrangements(scope: Scope, ctx0: Ctx, items, allow_preserve: bool = True) -> List[Layout]:
    out: List[Layout] = []
    reg = scope.region
    if allow_preserve:
        for boost in (1.3, 1.2, 1.1, 1.0):
            lay = preserve(scope, ctx0, boost, items)
            if lay is not None:
                out.append(lay)
                break
    for k in (0.7, 1.0, 1.4, 2.0):
        lay = stack(scope, ctx0, k)
        if lay:
            out.append(lay)
    aspect = reg.w / max(reg.h, 1e-6)
    if aspect > 0.9:
        vis = visual_block(scope.blocks)
        side = "left" if vis is None or vis.src.cx <= scope.src.cx else "right"
        for frac in (0.38, 0.5):
            for k in (1.0, 1.5):
                lay = split(scope, ctx0, side, frac, k)
                if lay:
                    out.append(lay)
    if aspect > 1.8:
        out += row(scope, ctx0)
    return out


def best_layout(scope: Scope, ctx0: Ctx, items, allow_preserve: bool = True) -> Optional[Layout]:
    from .objective import evaluate

    lays = arrangements(scope, ctx0, items, allow_preserve)
    if not lays:
        return None
    return max(lays, key=lambda lay: evaluate(lay, scope, items)["total"])


def _panel_inner(children: List[Block], src: Rect, region: Rect, ctx: Ctx, items) -> Dict[int, Placement]:
    """Lay out a panel's children inside its new box (hooked into blocks.py)."""
    lay = best_layout(Scope(children, src, region), ctx, items)
    return lay.out if lay else {}


# ---------------------------------------------------------------------------
# shared finishing: backgrounds, decor, hidden items, ornaments


def _proportional(it, scene: Scene, W: float, H: float, scale: float) -> Placement:
    w, h = it.box.w * scale, it.box.h * scale
    fit = min(1.0, W / max(w, 1e-6), H / max(h, 1e-6))
    w, h = w * fit, h * fit
    b = Rect(0, 0, w, h).rotated_bounds(it.rotation)
    cx = min(max(it.box.cx / scene.W * W, b.w / 2), W - b.w / 2)
    cy = min(max(it.box.cy / scene.H * H, b.h / 2), H - b.h / 2)
    font = max(1, int(round(it.font * scale * fit))) if it.type == "text" else None
    return Placement(cx - w / 2, cy - h / 2, w, h, font)


def _corner_positions(corner: str, W, H, w, h, m, steps=6):
    """Corner first, then sliding along both edges away from it, then other corners."""
    for c in [corner] + [c for c in ("tr", "tl", "br", "bl") if c != corner]:
        x0 = m if c[1] == "l" else W - m - w
        y0 = m if c[0] == "t" else H - m - h
        yield x0, y0
        for i in range(1, steps + 1):
            dx, dy = (W - 2 * m - w) * i / steps, (H - 2 * m - h) * i / steps
            yield (x0 + dx if c[1] == "l" else x0 - dx), y0
            yield x0, (y0 + dy if c[0] == "t" else y0 - dy)


def place_ornaments(ornaments: List[Block], lay: Layout):
    ctx = lay.ctx
    W, H = ctx.W, ctx.H
    m = margin(W, H) * 0.6
    taken = [r for _, r in lay.placed]
    for b in ornaments:
        best = None
        for shrink in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3):
            c = ctx.with_scale(ctx.ts * shrink, ctx.img * shrink)
            w, h = measure(b, c, W - 2 * m, H - 2 * m)
            for x, y in _corner_positions(b.corner, W, H, w, h, m):
                r = Rect(x, y, w, h)
                hit = sum(r.intersection(t) for t in taken)
                if best is None or hit < best[0] - 1e-6:
                    best = (hit, c, r)
                if hit <= 0:
                    break
            if best[0] <= 0:
                break
        _, c, r = best
        place(b, c, r.x, r.y, r.w + 0.01, r.h + 0.01, lay.out)
        lay.placed.append((b, r))
        taken.append(r)


def finish(scene: Scene, lay: Layout, ornaments: List[Block]) -> Layout:
    W, H = lay.ctx.W, lay.ctx.H
    m = min(W / scene.W, H / scene.H)
    place_ornaments(ornaments, lay)
    for it in scene.backgrounds:
        lay.out[it.idx] = Placement(0.0, 0.0, W, H)
    canvas_src = Rect(0, 0, scene.W, scene.H)
    for it in scene.decor:
        visible = it.bounds.intersection(canvas_src) / max(1e-6, it.bounds.area)
        lay.out[it.idx] = _proportional(it, scene, W, H, m * math.sqrt(max(0.2, visible)))
    for it in scene.hidden:
        p = _proportional(it, scene, W, H, m)
        p.hidden = it.missing  # graceful skip of a missing asset
        lay.out[it.idx] = p
    for b in lay.hidden:
        for it in b.items:
            p = _proportional(it, scene, W, H, m)
            p.hidden = True
            lay.out[it.idx] = p
    return lay


DROP_STEPS = (0.25, 0.36, 0.45, 0.55, 0.65, 0.8, 0.9)  # the last step may drop the logo


def drop_levels(scene: Scene) -> List[List[Block]]:
    """Progressively larger sets of low-importance blocks that may be hidden
    when the canvas is too small to show everything legibly.  Headline, CTA
    and logo are never dropped; text only when it can really be hidden."""
    def droppable(b):
        return b.importance < 0.9 and b.role not in ("headline", "cta") and b.kind != "panel" \
            and (scene.hide_z is not None or not b.texts)

    levels, seen = [[]], set()
    for thr in DROP_STEPS:
        drop = [b for b in scene.blocks + scene.ornaments if b.importance < thr and droppable(b)]
        key = frozenset(map(id, drop))
        if drop and key not in seen and len(drop) < len(scene.blocks) + len(scene.ornaments):
            seen.add(key)
            levels.append(drop)
    return levels


def candidates(scene: Scene, ctx0: Ctx) -> Tuple[Scope, List[Layout]]:
    """All candidate layouts, plus the scope they should be judged in."""
    from .objective import evaluate

    W, H = ctx0.W, ctx0.H
    m = margin(W, H)
    src = Rect(0, 0, scene.W, scene.H)
    region = Rect(m, m, W - 2 * m, H - 2 * m)
    judge = Scope(scene.blocks + scene.ornaments, src, region)
    B.panel_layout_hook = lambda kids, s, r, c: _panel_inner(kids, s, r, c, scene.items)
    out = []
    if abs(math.log((W / H) / (scene.W / scene.H))) < 0.45:
        for boost in (1.3, 1.2, 1.1, 1.0):
            lay = preserve(Scope(scene.blocks + scene.ornaments, src, Rect(0, 0, W, H)), ctx0, boost, scene.items)
            if lay is not None:  # preserve positions the ornaments itself
                out.append(finish(scene, lay, []))
                break
    for drop in drop_levels(scene):
        flow = [b for b in scene.blocks if b not in drop]
        if not flow:
            continue
        lays = arrangements(Scope(flow, src, region), ctx0, scene.items, allow_preserve=False)
        for lay in lays:
            lay.hidden += drop
            finish(scene, lay, [b for b in scene.ornaments if b not in drop])
        out += lays
        if any(evaluate(lay, judge, scene.items)["legibility"] >= 0.97 for lay in lays):
            break  # everything left is legible: no need to drop more
    return judge, out
