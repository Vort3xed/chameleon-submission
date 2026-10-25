"""Candidate layouts for a set of blocks inside a region.

  preserve  keep the source composition: uniform scale; blocks that overlap
            along an axis move together and only the space between them
            stretches (best for nearby aspect ratios)
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
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Tuple

from . import blocks as B
from .blocks import INF, Ctx, Placement, fit_block, keep_lines, measure, place, stack_measure, stack_place
from .geometry import Rect, bounding
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
    return min(max(2.0, 0.045 * min(W, H)), 0.25 * min(W, H))  # tiny canvases keep a positive region


def outer_margins(W: float, H: float) -> Tuple[float, float]:
    """(x, y) margins of the content region: the usual margin, growing at the
    ends of a strip (a 320x50 banner needs ~8 px there, not 2) up to ~15% of
    its short side."""
    m = margin(W, H)
    grow = lambda r: min(3.3, max(1.0, r / 1.5))  # noqa: E731
    return min(m * grow(W / H), 0.25 * W), min(m * grow(H / W), 0.25 * H)


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
    # a sparse design (little drawn on its canvas) may grow up to 2x more into the new space
    drawn = sum(b.visible.area for b in scope.blocks) / max(1.0, scope.src.area)
    sparse = min(2.0, max(1.0, math.sqrt(0.3 / max(drawn, 1e-6))))
    return 0.02, m ** 0.3 * M ** 0.7 * 1.15 * sparse  # leans to the long side: banners keep short text large


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


def _band_starts(spans: List[Tuple[float, float]], lo: float, hi: float, s: float, out_lo: float,
                 out_len: float, edge: float = 0.0, s0: float = 1.0) -> List[float]:
    """New start of each source span [a, b] (inside [lo, hi]) along one axis.

    Spans whose drawn content overlaps form a band and keep their relative
    layout, scaled by s.  The gaps between bands (and the outer margins)
    scale by s too, and any space left over is shared equally among them:
    tight pairs stay tighter than loose ones while spacing evens out."""
    if not spans:
        return []
    order = sorted(range(len(spans)), key=lambda i: spans[i][0])
    bands: List[List[float]] = []  # [start, end, members...]
    for i in order:
        a, b = max(lo, spans[i][0]), min(hi, spans[i][1])
        if bands and a < bands[-1][1]:
            bands[-1][1] = max(bands[-1][1], b)
            bands[-1].append(i)
        else:
            bands.append([a, max(a, b), i])
    gaps = [bands[0][0] - lo] + [n[0] - p[1] for p, n in zip(bands, bands[1:])] + [hi - bands[-1][1]]
    # the outer margins never shrink below `edge` (or their own scaled distance, if smaller)
    floor = [min(edge, max(0.0, gaps[0]) * s0)] + [0.0] * (len(gaps) - 2) + [min(edge, max(0.0, gaps[-1]) * s0)]
    gaps = [max(0.0, g) * s for g in gaps]
    slack = out_len - s * sum(b[1] - b[0] for b in bands) - sum(gaps)
    if slack >= 0:
        gaps = [g + slack / len(gaps) for g in gaps]
    else:  # tighter than the source: what can give way shrinks in proportion
        give = sum(max(0.0, g - f) for g, f in zip(gaps, floor))
        k = max(0.0, 1 + slack / give) if give > 0 else 0.0
        gaps = [min(g, f) + max(0.0, g - f) * k for g, f in zip(gaps, floor)]
    pos = out_lo + gaps[0]
    starts = [0.0] * len(spans)
    for band, gap in zip(bands, gaps[1:]):
        for i in band[2:]:
            starts[i] = pos + (spans[i][0] - band[0]) * s
        pos += (band[1] - band[0]) * s + gap
    return starts


def _drawn(b: Block) -> Rect:
    return bounding([i.ink for i in b.items])


def _tight_text(b: Block, ink: Rect, s: float) -> Optional[Tuple[Rect, int]]:
    """(source-space frame, font) for a lone text box tightened around its
    lines at scale s, or None.  The font is the one that keeps the source's
    lines in the full scaled box; the tight width is verified to wrap the same."""
    if b.kind != "text" or b.rotated:
        return None
    it, r = b.items[0], b.src
    font = keep_lines(it, it.font * s, r.w * s)
    lay = it.text_layout(font, r.w * s)
    w = lay.max_line_width + 0.1 * font + 6
    if w >= r.w * s or it.text_layout(font, w).lines != lay.lines:
        return None
    w /= s
    x = {"center": ink.cx - w / 2, "right": ink.x1 - w}.get(it.el.get("text_align", "left"), ink.x)
    return Rect(x, r.y, w, r.h), font


ROOM_KEPT = 0.6  # an enlarged element keeps at least this share of its scaled breathing room (up to 2 margins)


def preserve(scope: Scope, ctx0: Ctx, boost: float, items) -> Optional[Layout]:
    """Keep the composition, scaled by `boost`.  Lone text boxes are first
    tightened around their lines (a full-width box around short lines must
    not cap the growth); a boost is refused if it eats more than 40% of any
    element's breathing room (capped at two margins, so sparse designs grow)."""
    src, reg = scope.src, scope.region
    s = min(reg.w / src.w, reg.h / src.h) * boost
    ctx = ctx0.with_scale(s, s)
    ctx.floor_relax = 0.0
    lay = Layout(f"preserve{boost:.2f}", ctx)
    m, s0 = margin(reg.w, reg.h), s / boost
    inks = [_drawn(b) for b in scope.blocks]
    flow = [k for k, b in enumerate(scope.blocks) if not b.ornament]  # corner pieces do not shape the bands
    xs = _band_starts([(inks[k].x, inks[k].x1) for k in flow], src.x, src.x1, s, reg.x, reg.w, m, s0)
    ys = _band_starts([(inks[k].y, inks[k].y1) for k in flow], src.y, src.y1, s, reg.y, reg.h)
    starts = {k: (x, y) for k, x, y in zip(flow, xs, ys)}
    for k, (b, ink) in enumerate(zip(scope.blocks, inks)):
        snug = _tight_text(b, ink, s)
        r = snug[0] if snug else b.src
        if k in starts:  # band positions are of the drawn content
            x0, y0 = starts[k][0] - (ink.x - r.x) * s, starts[k][1] - (ink.y - r.y) * s
        else:  # an ornament keeps its relative place, i.e. stays by its corner
            x0 = reg.x + (r.cx - src.x) / src.w * reg.w - r.w * s / 2
            y0 = reg.y + (r.cy - src.y) / src.h * reg.h - r.h * s / 2
        w, h = r.w * s, r.h * s
        if w > reg.w + 0.5 or h > reg.h + 0.5:
            return None
        # what is drawn keeps the usual margin from each edge (or its own scaled distance if it sat
        # closer); the box only has to stay on the canvas - a wide box around short text may not push it
        l, t, rt, bt = (min(m, max(0.0, d) * s0) for d in (ink.x - src.x, ink.y - src.y, src.x1 - ink.x1, src.y1 - ink.y1))
        il, it_, ir, ib = (ink.x - r.x) * s, (ink.y - r.y) * s, (r.x1 - ink.x1) * s, (r.y1 - ink.y1) * s
        x = max(reg.x, reg.x + l - il, min(x0, reg.x1 - w, reg.x1 - rt - w + ir))
        y = max(reg.y, reg.y + t - it_, min(y0, reg.y1 - h, reg.y1 - bt - h + ib))
        if snug:
            lay.out[b.items[0].idx] = Placement(x, y, w, h, snug[1])
        else:
            scale_block(b, s, x, y, lay.out)
        drawn = Rect(x + (ink.x - r.x) * s, y + (ink.y - r.y) * s, ink.w * s, ink.h * s)
        for got, d in ((drawn.x - reg.x, ink.x - src.x), (drawn.y - reg.y, ink.y - src.y),
                       (reg.x1 - drawn.x1, src.x1 - ink.x1), (reg.y1 - drawn.y1, src.y1 - ink.y1)):
            if got < min(ROOM_KEPT * max(0.0, d) * s0, 2 * m) - 0.5:
                return None  # this boost eats the element's breathing room
        lay.placed.append((b, Rect(x, y, w, h)))
    if any(it.rotation and (p.x < -0.5 or p.y < -0.5 or p.x + p.w > ctx0.W + 0.5 or p.y + p.h > ctx0.H + 0.5)
           for it, p in ((items[i], p) for i, p in lay.out.items())):
        return None  # a rotated element whose box only fits off-canvas would be dragged across the design
    from .objective import new_overlap, visible_inks

    g = 0.2 * m  # half the breathing room each side: elements that were apart must not touch
    vis = [(b, it, o.inset(-g), si.inset(-g / s0)) for b, it, o, si in visible_inks(lay.out, scope.blocks)]
    if new_overlap(vis) > 0.05:
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


def stack(scope: Scope, ctx0: Ctx, k: float, shrink: float = 1.0) -> Optional[Layout]:
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
        ts *= shrink
        lay = Layout(f"stack k={k} s={shrink}", base.with_scale(ts, ts * k))
        lay.placed = stack_place(blocks, lay.ctx, reg, lay.out)
        return lay

    return _fit_scale(build)


def visual_block(blocks: List[Block]) -> Optional[Block]:
    cands = [b for b in blocks if b.role in ("hero", "image") or b.hero
             or (b.kind == "row" and all(c.role in ("hero", "image") for c in b.children))]
    return max(cands, key=lambda b: b.src.area) if cands else None


def split(scope: Scope, ctx0: Ctx, side: str, frac: float, k: float, shrink: float = 1.0) -> Optional[Layout]:
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
        ts *= shrink
        lay = Layout(f"split {side} {frac} k={k} s={shrink}", base.with_scale(ts, ts * k))
        big = fit_block(vis, lay.ctx, vcol.w, vcol.h * 0.92)
        w, h = measure(vis, big, vcol.w)
        r = place(vis, big, vcol.x + (vcol.w - w) / 2, vcol.y + (vcol.h - h) / 2, vcol.w, INF, lay.out)
        lay.placed = [(vis, r)] + stack_place(rest, lay.ctx, tcol, lay.out, valign="center")
        _centre_columns(lay, [[vis], rest], reg.cy)
        _center_ink(lay, scope.blocks, reg, gutter)  # equal outer margins as drawn
        return lay

    return _fit_scale(build)


def _centre_columns(lay: Layout, columns: List[List[Block]], cy: float):
    """Side-by-side columns share one centre line as drawn: boxes include line
    spacing and transparent padding, so centring them leaves the visible
    centres a few pixels apart - a near-miss reads as a mistake."""
    H = lay.ctx.H
    for col in columns:
        items = [it for b in col for it in b.items if it.idx in lay.out and not lay.out[it.idx].hidden]
        ink = bounding([it.ink_at(lay.out[it.idx].rect, lay.out[it.idx].font) for it in items])
        if ink is None:
            continue
        boxes = [lay.out[it.idx] for b in col for it in b.items if it.idx in lay.out]
        dy = max(-min(q.y for q in boxes), min(cy - ink.cy, H - max(q.y + q.h for q in boxes)))
        for b in col:
            for it in b.items:
                if it.idx in lay.out:
                    lay.out[it.idx] = replace(lay.out[it.idx], y=lay.out[it.idx].y + dy)
        ids = {id(b) for b in col}
        lay.placed = [(b, r.moved(0, dy) if id(b) in ids else r) for b, r in lay.placed]


def _partitions(items: List[Block], max_parts: int):
    """Contiguous splits of `items` into 1..max_parts columns.  Cuts are taken
    near equal shares of text weight (plus neighbours), so the count stays
    small however many blocks there are."""
    n = len(items)
    cum = list(itertools.accumulate(_text_weight([b]) for b in items))
    seen = set()
    for parts in range(1, min(max_parts, n) + 1):
        ideal = [min(range(1, n), key=lambda i: abs(cum[i - 1] - cum[-1] * k / parts)) for k in range(1, parts)]
        options = [sorted({max(1, min(n - 1, c + d)) for d in (-1, 0, 1)}) for c in ideal]
        for cuts in itertools.product(*options):
            if list(cuts) != sorted(set(cuts)) or cuts in seen:
                continue
            seen.add(cuts)
            bounds = (0,) + cuts + (n,)
            yield [items[a:b] for a, b in zip(bounds, bounds[1:])]


def _text_weight(blocks: List[Block]) -> float:
    return sum(sum(len(t.content) * t.font for t in b.texts) or b.src.w for b in blocks) or 1.0


TEXT_SHARE = 0.25  # a banner row gives its copy at least this share of the width


def row(scope: Scope, ctx0: Ctx, shrink: float = 1.0) -> List[Layout]:
    reg, blocks = scope.region, scope.blocks
    logo = [b for b in blocks if b.role == "logo"][:1]
    vis = visual_block([b for b in blocks if b not in logo])
    cta = [b for b in blocks if b.role == "cta" and b not in logo][-1:]
    middle = [b for b in blocks if b not in logo + cta and b is not vis]
    lead = logo + ([vis] if vis is not None else [])
    gap = max(4.0, 0.6 * margin(reg.w, reg.h))
    lo, hi0 = scale_bounds(scope)
    heads = [i.font for b in blocks if b.role == "headline" for i in b.texts]
    # the text may grow until a headline fills two lines of the row's height; logo and button keep the usual cap
    hi = max(hi0, reg.h / 2.6 / max(heads)) if heads else hi0
    layouts = []
    for parts in (_partitions(middle, 3) if middle else [[]]):
        def columns(ts, relax, even):
            c = Ctx(ctx0.W, ctx0.H, ctx0.src_W, ctx0.src_H, ts, ts, relax)
            cf = Ctx(ctx0.W, ctx0.H, ctx0.src_W, ctx0.src_H, min(ts, hi0), min(ts, hi0), relax)
            fixed = [(b, _slot_size(b, cf, reg)) for b in lead]
            tail = [(b, _slot_size(b, cf, reg)) for b in cta]
            inset = (_edge_inset(fixed[0], 0, reg.x) if fixed else 0.0,
                     _edge_inset(tail[-1], 2, c.W - reg.x1) if tail else 0.0)
            if even:  # a padded end sets the drawn margin on both ends
                inset = (max(inset),) * 2
            used = sum(inset) + sum(w for _, (w, _) in fixed + tail) + gap * (len(fixed) + len(tail) + len(parts) - 1)
            weights = [_text_weight(p) for p in parts]
            widths = [(reg.w - used) * w / sum(weights) for w in weights] if parts else []
            return c, fixed, tail, widths, inset

        def fits(ts, relax, even):
            c, fixed, tail, widths, _ = columns(ts, relax, even)
            if any(w <= 4 for w in widths) or any(h > reg.h for _, (_, h) in fixed + tail):
                return False
            if parts and sum(widths) < TEXT_SHARE * reg.w:
                return False  # the copy is squeezed into a sliver: drop something or use another layout
            for p, w in zip(parts, widths):
                cw, ch, _, _ = stack_measure(p, c, w, reg.h)
                if ch > reg.h or cw > w + 0.5:
                    return False
            return True

        made = []  # (scale, layout) for the row as fitted, then with even ends
        for even in (False, True):
            ts = relax = None
            for relax in (1.0, 0.8, 0.6):
                ts = bisect(lambda t: fits(t, relax, even), lo, hi, steps=10)
                if ts is not None:
                    break
            if ts is None:
                break
            c, fixed, tail, widths, inset = columns(ts * shrink, relax, even)
            made.append((ts, _row_layout(c, fixed, tail, parts, widths, inset, reg, gap, cta, blocks, hi0,
                                         f"row {len(parts)}col s={shrink}")))
            if inset[0] == inset[1]:
                break  # the ends are already even
        if len(made) == 2 and made[1][0] >= EVEN_COST * made[0][0] and _lines(made[1][1]) == _lines(made[0][1]):
            made.pop(0)
        layouts += [lay for _, lay in made[:1]]
    return layouts


EVEN_COST = 0.9  # even end margins may cost a banner's type up to 10%, never a line break


def _lines(lay: Layout) -> Dict[int, int]:
    """Line count of every visible text in a layout."""
    return {it.idx: it.text_layout(p.font, p.w).n_lines for b, _ in lay.placed for it in b.texts
            if (p := lay.out.get(it.idx)) is not None and not p.hidden and p.font}


def _row_layout(c: Ctx, fixed, tail, parts, widths, inset, reg: Rect, gap: float, cta, blocks, hi0: float,
                name: str) -> Layout:
    cf = c.with_scale(min(c.ts, hi0), min(c.ts, hi0))
    lay = Layout(name, c)
    seq = [(b, wh[0]) for b, wh in fixed] + [(p, w) for p, w in zip(parts, widths)] + [(b, wh[0]) for b, wh in tail]
    free = reg.w - sum(inset) - sum(w for _, w in seq) - gap * (len(seq) - 1)
    extra = max(0.0, free) / max(1, len(seq) - 1)
    x = reg.x + inset[0]
    for obj, w in seq:
        if isinstance(obj, Block):
            bc = _slot_ctx(obj, cf, reg)
            bw, bh = measure(obj, bc, reg.w / 3)
            lay.placed.append((obj, place(obj, bc, x, reg.y + (reg.h - bh) / 2, reg.w / 3, INF, lay.out)))
        else:
            lay.placed += stack_place(obj, c, Rect(x, reg.y, w, reg.h), lay.out, valign="center")
        x += w + gap + extra
    if cta:
        _cta_below_headline(lay, cta[0], cf, reg)
    _centre_columns(lay, [obj if isinstance(obj, list) else [obj] for obj, _ in seq], reg.cy)
    _center_ink(lay, blocks, reg, gap)
    return lay


def _font_lead(b: Block, out: Dict[int, Placement]) -> Tuple[float, float]:
    """(largest placed font, its source font) among b's text items."""
    best = max(((out[i.idx].font or 0.0, i.font) for i in b.texts if i.idx in out and not out[i.idx].hidden),
               default=(0.0, 0.0))
    return best


def _cta_below_headline(lay: Layout, cta: Block, c: Ctx, reg: Rect):
    """A banner's button must not outshine its headline: its label stays under
    85% of the headline's size (or under their source ratio, if smaller).
    The button shrinks about its right edge, so its end margin is kept."""
    heads = [b for b, _ in lay.placed if b is not cta and b.role == "headline"]
    if not heads or not cta.texts:
        return
    head, head_src = _font_lead(heads[0], lay.out)
    label, label_src = _font_lead(cta, lay.out)
    if not head or not label or not head_src:
        return
    cap = head * min(0.85, label_src / head_src)
    if label <= cap + 0.5:
        return
    old = next(r for b, r in lay.placed if b is cta)
    bc = _slot_ctx(cta, c, reg).scaled(cap / label)
    bw, bh = measure(cta, bc, reg.w / 3)
    r = place(cta, bc, old.x1 - bw, reg.y + (reg.h - bh) / 2, reg.w / 3, INF, lay.out)
    lay.placed = [(b, r if b is cta else q) for b, q in lay.placed]


def _center_ink(lay: Layout, blocks: List[Block], reg: Rect, gap: float):
    """Make the row's outer margins match as drawn.  Transparent padding in a
    logo or product art must not make one side look wider: the whole row
    shifts as far as the boxes allow, then whatever is left over is taken
    from the padding-side gap (everything after the padded end slides in)."""
    from .objective import visible_inks

    order = sorted(lay.placed, key=lambda br: br[1].x)
    ink_of = {it.idx: o for _, it, o, _ in visible_inks(lay.out, blocks)}
    inks = [bounding([ink_of[it.idx] for it in b.items if it.idx in ink_of]) for b, _ in order]
    if not order or any(r is None for r in inks):
        return

    def shift(bs, dx):
        for b in bs:
            for it in b.items:
                if it.idx in lay.out:
                    lay.out[it.idx] = replace(lay.out[it.idx], x=lay.out[it.idx].x + dx)
        moved = {id(b) for b in bs}
        lay.placed = [(b, r.moved(dx, 0) if id(b) in moved else r) for b, r in lay.placed]

    def room(bs, dx):
        """dx clipped so that every box of bs stays on the canvas."""
        ps = [lay.out[it.idx] for b in bs for it in b.items if it.idx in lay.out]
        return max(-min(p.x for p in ps), min(dx, lay.ctx.W - max(p.x + p.w for p in ps)))

    blocks_in_order = [b for b, _ in order]
    left, right = inks[0].x - reg.x, reg.x1 - max(r.x1 for r in inks)
    dx = room(blocks_in_order, (right - left) / 2)
    shift(blocks_in_order, dx)
    left, right = left + dx, right - dx
    if len(order) > 1 and abs(left - right) > 1.0:
        if left > right:  # the first block's padding held the row back: the rest slides toward it
            free = min(r.x for r in inks[1:]) + dx - (inks[0].x + dx) - (inks[0].w) - gap
            shift(blocks_in_order[1:], room(blocks_in_order[1:], -max(0.0, min((left - right) / 2, free))))
        else:
            free = (inks[-1].x + dx) - max(r.x1 for r in inks[:-1]) - dx - gap
            shift(blocks_in_order[:-1], room(blocks_in_order[:-1], max(0.0, min((right - left) / 2, free))))


def _slot_ctx(b: Block, c: Ctx, reg: Rect) -> Ctx:
    """Banner items: images fill the height as far as their padded box stays on
    the canvas (the logo at most half of it, and not outgrowing the text by
    more than 1.5x its source proportion); chips follow the text scale."""
    if b.role in ("logo", "hero", "image") or b.kind == "image":
        _, top, _, bottom = B.image_pads(b)
        h = min(reg.h, reg.cy / (0.5 + top), (c.H - reg.cy) / (0.5 + bottom))
        if b.role == "logo":
            h = min(h, 0.5 * reg.h, 1.5 * measure(b, c, INF)[1])
        return fit_block(b, c, reg.w / 3, h)
    w, h = measure(b, c, reg.w / 3)
    return c if h <= reg.h else fit_block(b, c, reg.w / 3, reg.h)


def _slot_size(b: Block, c: Ctx, reg: Rect) -> Tuple[float, float]:
    return measure(b, _slot_ctx(b, c, reg), reg.w / 3)


def _edge_inset(slot, side: int, room: float) -> float:
    """How far a banner's end item moves inwards so its padded box stays on the canvas."""
    b, (w, _) = slot
    return max(0.0, B.image_pads(b)[side] * w - room)


def arrangements(scope: Scope, ctx0: Ctx, items, allow_preserve: bool = True) -> List[Layout]:
    out: List[Layout] = []
    reg = scope.region
    if allow_preserve:
        for boost in (2.0, 1.75, 1.5, 1.4, 1.3, 1.2, 1.1, 1.0):
            lay = preserve(scope, ctx0, boost, items)
            if lay is not None:
                out.append(lay)
                break
    aspect = reg.w / max(reg.h, 1e-6)
    vis = visual_block(scope.blocks)
    side = "left" if vis is None or vis.src.cx <= scope.src.cx else "right"
    for shrink in SHRINKS:  # the largest text that fits, and a calmer variant
        out += [lay for k in (0.7, 1.0, 1.4, 2.0) if (lay := stack(scope, ctx0, k, shrink))]
        if aspect > 0.9:
            out += [lay for frac in (0.38, 0.5, 0.62) for k in (1.0, 1.5)
                    if (lay := split(scope, ctx0, side, frac, k, shrink))]
        if aspect > 1.8:
            out += row(scope, ctx0, shrink)
    return out


SHRINKS = (1.0, 0.82)


def best_layout(scope: Scope, ctx0: Ctx, items, allow_preserve: bool = True) -> Optional[Layout]:
    from .objective import evaluate

    lays = arrangements(scope, ctx0, items, allow_preserve)
    if not lays:
        return None
    return max(lays, key=lambda lay: evaluate(lay, scope, items)["total"])


def _panel_inner(children: List[Block], src: Rect, region: Rect, ctx: Ctx, items) -> Dict[int, Placement]:
    """Lay out a panel's children inside its new box (hooked into blocks.py).
    Panels nested deeper simply stack, which keeps the search linear in depth."""
    hook, B.panel_layout_hook = B.panel_layout_hook, None
    try:
        lay = best_layout(Scope(children, src, region), ctx, items)
    finally:
        B.panel_layout_hook = hook
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


def _is_frame(it, scene: Scene) -> bool:
    """A large unrotated rectangle (inset border, tint) spanning most of the canvas."""
    return it.type == "shape" and not it.rotation and it.el.get("shape_type", "rectangle") == "rectangle" \
        and it.box.w >= 0.5 * scene.W and it.box.h >= 0.5 * scene.H


def _anchored(it, scene: Scene, W: float, H: float, scale: float) -> Placement:
    """Each edge keeps its scaled distance to the matching canvas edge."""
    b = it.box
    x0, y0 = max(0.0, b.x) * scale, max(0.0, b.y) * scale
    x1, y1 = W - max(0.0, scene.W - b.x1) * scale, H - max(0.0, scene.H - b.y1) * scale
    return Placement(x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0))


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


CORNER_SHRINKS = (1.0, 0.85, 0.7)  # an ornament shrinks this far to stay in its own corner before it moves


def _spot(c: Ctx, x: float, y: float, foot: Rect, w: float, h: float, taken):
    """(overlap with placed content, ctx, footprint rect, w, h) with the footprint's corner at (x, y);
    the unrotated box must stay on the canvas too, so its centre is clamped."""
    cx = min(max(x + foot.w / 2, w / 2), c.W - w / 2)
    cy = min(max(y + foot.h / 2, h / 2), c.H - h / 2)
    r = Rect(cx - foot.w / 2, cy - foot.h / 2, foot.w, foot.h)
    return sum(r.intersection(t) for t in taken), c, r, w, h


def _measure_ornament(b: Block, c: Ctx, rot: float, m: float):
    w, h = measure(b, c, c.W - 2 * m, c.H - 2 * m)
    foot = Rect(0, 0, w, h).rotated_bounds(rot)
    fit = min(1.0, (c.W - 2 * m) / max(foot.w, 1e-6), (c.H - 2 * m) / max(foot.h, 1e-6), c.W / max(w, 1e-6),
              c.H / max(h, 1e-6))
    return w, h, foot, fit


def _in_corner(b: Block, ctx: Ctx, rot: float, m: float, taken):
    """The ornament in its own corner, shrunk a little if that is what it takes to stay clear."""
    for shrink in CORNER_SHRINKS:
        c = ctx.with_scale(ctx.ts * shrink, ctx.img * shrink)
        w, h, foot, fit = _measure_ornament(b, c, rot, m)
        if fit < 1.0:
            continue
        x, y = next(_corner_positions(b.corner, c.W, c.H, foot.w, foot.h, m))
        spot = _spot(c, x, y, foot, w, h, taken)
        if spot[0] <= 0:
            return spot
    return None


def _anywhere(b: Block, ctx: Ctx, rot: float, m: float, taken):
    """Slide along the edges and try the other corners, shrinking further; least overlap wins."""
    best, fit = None, 1.0
    for shrink in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, None):
        if shrink is None:  # nothing fitted: scale exactly to fit, legibility floors off
            if best is not None:
                break
            c = Ctx(ctx.W, ctx.H, ctx.src_W, ctx.src_H, ctx.ts * 0.3 * fit, ctx.img * 0.3 * fit, 0.0)
        else:
            c = ctx.with_scale(ctx.ts * shrink, ctx.img * shrink)
        w, h, foot, fit = _measure_ornament(b, c, rot, m)
        if fit < 1.0 and shrink is not None:
            continue  # the rotated footprint (or the box itself) does not fit the canvas yet
        for x, y in _corner_positions(b.corner, c.W, c.H, foot.w, foot.h, m):
            spot = _spot(c, x, y, foot, w, h, taken)
            if best is None or spot[0] < best[0] - 1e-6:
                best = spot
            if spot[0] <= 0:
                return best
    return best


GIVE_WAY = (0.95, 0.9, 0.85)  # how far product art may shrink to leave a corner badge its corner


def _make_way(b: Block, lay: Layout, rot: float, m: float) -> bool:
    """If only image art (a product, a photo) sits in the ornament's corner,
    shrink that art about its far corner until the corner is free."""
    ctx = lay.ctx
    c = ctx.with_scale(ctx.ts * CORNER_SHRINKS[-1], ctx.img * CORNER_SHRINKS[-1])
    w, h, foot, fit = _measure_ornament(b, c, rot, m)
    if fit < 1.0:
        return False
    x, y = next(_corner_positions(b.corner, c.W, c.H, foot.w, foot.h, m))
    spot = Rect(x, y, foot.w, foot.h).inset(-0.3 * m)
    blockers = [(k, o, r) for k, (o, r) in enumerate(lay.placed) if r.intersection(spot) > 0]
    if not blockers or any(o.kind not in ("image", "rigid") or o.texts for _, o, _ in blockers):
        return False  # text is never pushed aside for a badge
    def anchor(r: Rect) -> Tuple[float, float]:  # the art's corner away from the badge stays put
        return (r.x1 if b.corner[1] == "l" else r.x), (r.y1 if b.corner[0] == "t" else r.y)

    def shrunk(r: Rect, f: float) -> Rect:
        ax, ay = anchor(r)
        return Rect(ax + (r.x - ax) * f, ay + (r.y - ay) * f, r.w * f, r.h * f)

    for f in GIVE_WAY:
        if all(shrunk(r, f).intersection(spot) <= 0 for _, _, r in blockers):
            for k, o, r in blockers:
                ax, ay = anchor(r)
                for it in o.items:
                    p = lay.out.get(it.idx)
                    if p is not None:
                        lay.out[it.idx] = replace(p, x=ax + (p.x - ax) * f, y=ay + (p.y - ay) * f, w=p.w * f, h=p.h * f,
                                                  font=None if p.font is None else max(1, int(round(p.font * f))))
                lay.placed[k] = (o, shrunk(r, f))
            return True
    return False


def place_ornaments(ornaments: List[Block], lay: Layout):
    ctx = lay.ctx
    m = margin(ctx.W, ctx.H) * 0.6
    for b in ornaments:
        taken = [r for _, r in lay.placed]
        # a single rotated element measures unrotated; groups already measure rotated bounds
        rot = b.items[0].rotation if b.kind in ("text", "image", "shape") else 0.0
        spot = _in_corner(b, ctx, rot, m, taken)
        if spot is None and _make_way(b, lay, rot, m):
            taken = [r for _, r in lay.placed]
            spot = _in_corner(b, ctx, rot, m, taken)
        _, c, r, w, h = spot or _anywhere(b, ctx, rot, m, taken)
        place(b, c, r.cx - w / 2, r.cy - h / 2, w + 0.01, h + 0.01, lay.out)
        lay.placed.append((b, r))


def _panels(blocks: List[Block]) -> List[Block]:
    out = []
    for b in blocks:
        if b.kind == "panel":
            out += [b] + _panels(b.children)
    return out


def _on_frame(it, frame, p: Placement) -> Placement:
    """Keep an item where it sat on its card: same relative centre, scaled with the card."""
    f = frame.box
    k = min(p.w / max(f.w, 1e-6), p.h / max(f.h, 1e-6))
    cx, cy = p.x + (it.box.cx - f.x) / max(f.w, 1e-6) * p.w, p.y + (it.box.cy - f.y) / max(f.h, 1e-6) * p.h
    w, h = it.box.w * k, it.box.h * k
    return Placement(cx - w / 2, cy - h / 2, w, h)


def finish(scene: Scene, lay: Layout, ornaments: List[Block]) -> Layout:
    W, H = lay.ctx.W, lay.ctx.H
    m = min(W / scene.W, H / scene.H)
    place_ornaments(ornaments, lay)
    for it in scene.backgrounds:
        lay.out[it.idx] = Placement(0.0, 0.0, W, H)
    canvas_src = Rect(0, 0, scene.W, scene.H)
    frames = [b.frame for b in _panels(scene.blocks) if b.frame is not None and b.frame.idx in lay.out
              and not lay.out[b.frame.idx].hidden]
    for it in scene.decor:
        visible = it.bounds.intersection(canvas_src) / max(1e-6, it.bounds.area)
        c = it.bounds
        card = next((f for f in frames if f.box.x <= c.cx <= f.box.x1 and f.box.y <= c.cy <= f.box.y1
                     and c.area < 0.5 * f.box.area), None)
        if card is not None:  # decoration on a card moves with the card
            lay.out[it.idx] = _on_frame(it, card, lay.out[card.idx])
        else:
            lay.out[it.idx] = _anchored(it, scene, W, H, m) if _is_frame(it, scene) else \
                _proportional(it, scene, W, H, m * math.sqrt(max(0.2, visible)))
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


def _overlap(a: Rect, b: Rect) -> float:
    return a.intersection(b) / max(1.0, min(a.area, b.area))


def settle_decor(scene: Scene, lay: Layout) -> None:
    """Move decorative shapes to the nearest spot clear of content they did not
    cover in the source (a dot landing on a button reads as a collision);
    tiny ones with no clear spot are hidden.  Run on the chosen layout only."""
    W, H = lay.ctx.W, lay.ctx.H
    skip = {it.idx for it in scene.backgrounds + scene.decor + scene.hidden}
    content = [(scene.items[i], scene.items[i].ink_at(p.rect, p.font)) for i, p in lay.out.items()
               if i not in skip and not p.hidden]
    steps = [i / 8 for i in range(9)]
    for d in scene.decor:
        p = lay.out.get(d.idx)
        if p is None or p.hidden or _is_frame(d, scene):
            continue

        def cost(r: Rect) -> float:
            return sum(max(0.0, _overlap(r, ink) - _overlap(d.bounds, it.ink) - 0.02) for it, ink in content)

        here = p.rect
        if cost(here) <= 0:
            continue
        spots = [Rect(fx * (W - p.w), fy * (H - p.h), p.w, p.h) for fx in steps for fy in steps]
        best = min(spots, key=lambda r: (cost(r), math.hypot(r.cx - here.cx, r.cy - here.cy)))
        if cost(best) <= 0:
            p.x, p.y = best.x, best.y
        elif p.w * p.h < 0.005 * W * H:
            p.hidden = True


SNAP = 0.015  # a block this close (fraction of the canvas) to a shared line is moved onto it


def snap_alignment(scene: Scene, lay: Layout) -> None:
    """Final beautification: a block whose edge or centre sits within 1.5% of
    the same line of a sibling (or, for its centre, of the centre of what holds
    it: the canvas, or its card) is moved onto that line exactly - near-misses
    read as mistakes, exact alignment as intent - unless that creates an
    overlap, crams a neighbour, unbalances the margins or leaves its frame.
    Cards are done the same way inside.  Run on the chosen layout only."""
    from .objective import new_overlap, visible_inks

    W, H = lay.ctx.W, lay.ctx.H
    every = [b for b, _ in lay.placed]

    def ink(b: Block) -> Optional[Rect]:
        return bounding([scene.items[it.idx].ink_at(lay.out[it.idx].rect, lay.out[it.idx].font)
                         for it in b.items if it.idx in lay.out and not lay.out[it.idx].hidden])

    def moved(b: Block, dx: float, dy: float) -> Dict[int, Placement]:
        return {it.idx: replace(lay.out[it.idx], x=lay.out[it.idx].x + dx, y=lay.out[it.idx].y + dy)
                for it in b.items if it.idx in lay.out}

    def overlap() -> float:
        return new_overlap(visible_inks(lay.out, every))

    def snap(group: List[Block], frame: Rect):
        def clearance(b: Block) -> float:
            """Distance from b to its nearest sibling along the axis that separates them."""
            r = ink(b)
            gaps = [max(o.x - r.x1, r.x - o.x1, o.y - r.y1, r.y - o.y1)
                    for o in (ink(o) for o in group if o is not b) if o is not None]
            return min(gaps, default=INF)

        def lopsided() -> float:
            c = bounding([r for r in (ink(o) for o in group) if r is not None])
            return abs((c.x - frame.x) - (frame.x1 - c.x1))

        room = 0.6 * margin(frame.w, frame.h)  # a gap this wide is comfortable whatever happens to it
        for b in sorted(group, key=lambda b: -b.importance):
            r = ink(b)
            if r is None:
                continue
            others = [o for o in (ink(o) for o in group if o is not b) if o is not None]
            for axis, size in (("x", W), ("y", H)):
                lines = (lambda q: (q.x, q.cx, q.x1)) if axis == "x" else (lambda q: (q.y, q.cy, q.y1))
                offers = [ref - mine for o in others for mine, ref in zip(lines(r), lines(o))]
                if axis == "x":
                    offers.append(frame.cx - r.cx)
                offers = [d for d in offers if 0.5 < abs(d) < SNAP * size]
                if not offers:
                    continue
                d = min(offers, key=abs)
                new = moved(b, d if axis == "x" else 0.0, d if axis == "y" else 0.0)
                if any(p.x < frame.x - 0.5 or p.y < frame.y - 0.5 or p.x + p.w > frame.x1 + 0.5 or
                       p.y + p.h > frame.y1 + 0.5 for p in new.values()):
                    continue
                before, gap, side, old = overlap(), clearance(b), lopsided(), {i: lay.out[i] for i in new}
                lay.out.update(new)
                if overlap() > before + 1e-6 or clearance(b) < min(0.75 * gap, room) or \
                        lopsided() > side + 0.005 * frame.w:
                    lay.out.update(old)  # no new collision, no crammed neighbour, no lopsided margins
                else:
                    r = ink(b)
        for b in group:  # inside each card, its children against the card
            if b.kind == "panel" and b.frame is not None and b.frame.idx in lay.out:
                snap(b.children, lay.out[b.frame.idx].rect)

    snap([b for b in every if b not in scene.ornaments], Rect(0, 0, W, H))


DROP_STEPS = (0.25, 0.36, 0.45, 0.55, 0.65, 0.8, 0.9)


def _never_dropped(b: Block) -> bool:
    return b.importance >= DROP_STEPS[-1] or b.role in ("headline", "cta", "logo") or b.kind == "panel"


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
                out.append(finish(scene, lay, []))
                break
        if out and stretch < SAME_SHAPE and evaluate(out[0], judge, scene.items)["legibility"] >= 0.9:
            return judge, out  # the same shape keeps the designer's composition
    for drop in drop_levels(scene):
        flow = [prune(b, drop) for b in scene.blocks if b not in drop]
        if not flow:
            continue
        lays = arrangements(Scope(flow, src, region), ctx0, scene.items, allow_preserve=False)
        for lay in lays:
            lay.hidden += drop
            finish(scene, lay, [b for b in scene.ornaments if b not in drop])
        out += lays
        if any(evaluate(lay, judge, scene.items)["legibility"] >= 0.97 for lay in lays):
            break  # everything left is legible: no need to drop more
        if len(out) > MAX_LAYOUTS:
            break
    if not out:
        out.append(finish(scene, letterbox(scene, ctx0), []))
    return judge, out
