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
from .scene import Block


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
    region: Optional[Rect] = None  # where the family laid the flow out, if not the whole content region (beside bands)


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
    drawn = sum(sum(c.visible.area for c in b.children) if b.kind == "table" else b.visible.area
                for b in scope.blocks) / max(1.0, scope.src.area)  # a table draws its cells, not its gaps
    sparse = min(2.0, max(1.0, math.sqrt(0.3 / max(drawn, 1e-6))))
    return 0.02, m ** 0.3 * M ** 0.7 * 1.15 * sparse  # leans to the long side: banners keep short text large


def _fit_scale(build):
    """Search the text scale for each floor-relaxation level until one fits - and until the headline still
    leads, if some level down to 0.6 allows it: a group scaled up to keep its small labels legible must not
    outgrow the headline.  Floors are dropped entirely only to fit at all."""
    first = None
    for relax in (1.0, 0.8, 0.6, 0.0):
        if first is not None and relax == 0.0:
            break
        lay = build(relax)
        if lay is not None and _headline_leads(lay):
            return lay
        first = first or lay
    return first


def _leaves(b: Block) -> List[Block]:
    return [leaf for c in b.children for leaf in _leaves(c)] if b.kind in ("panel", "row", "table") else [b]


def _headline_leads(lay: Layout) -> bool:
    """No visible text that was at most the headline's size in the source has outgrown it."""
    heads, others = [], []
    for b, _ in lay.placed:
        for leaf in _leaves(b):
            for it in leaf.texts:
                p = lay.out.get(it.idx)
                if p is not None and not p.hidden and p.font:
                    (heads if leaf.role == "headline" else others).append((it.font, p.font))
    if not heads:
        return True
    src, out = max(heads)
    return all(o <= out for s, o in others if s <= src)


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
    blocks = [c for b in scope.blocks for c in (b.children if b.kind == "table" else [b])]  # a table's columns
    inks = [_drawn(b) for b in blocks]  # are bands of their own, so the gaps between them can tighten
    flow = [k for k, b in enumerate(blocks) if not b.ornament]  # corner pieces do not shape the bands
    xs = _band_starts([(inks[k].x, inks[k].x1) for k in flow], src.x, src.x1, s, reg.x, reg.w, m, s0)
    ys = _band_starts([(inks[k].y, inks[k].y1) for k in flow], src.y, src.y1, s, reg.y, reg.h)
    starts = {k: (x, y) for k, x, y in zip(flow, xs, ys)}
    for k, (b, ink) in enumerate(zip(blocks, inks)):
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


LOGO_COST = 0.8  # a logo that headed the copy keeps heading it in a banner row if that costs the type under 20%
STRIP = 5.0  # rows this much wider than tall are strips: too low for a logo above the copy


def _heads_copy(logo: Block, blocks: List[Block]) -> bool:
    """The logo sat just above the headline, overlapping it across: it heads the copy."""
    head = next((b for b in blocks if b.role == "headline"), None)
    return head is not None and logo.src.y1 <= head.src.y and min(logo.src.x1, head.src.x1) > max(logo.src.x, head.src.x)


def row(scope: Scope, ctx0: Ctx, shrink: float = 1.0) -> List[Layout]:
    """Banner rows with the logo leading - or, beside product art on a banner (not a strip), still heading
    the copy it headed if that costs the type little: a logo set apart by the product reads as a stray."""
    logo = next((b for b in scope.blocks if b.role == "logo"), None)
    lead = _row(scope, ctx0, shrink, logo, False)
    reg = scope.region
    if logo is None or not _heads_copy(logo, scope.blocks) or reg.w >= STRIP * reg.h or \
            visual_block([b for b in scope.blocks if b is not logo]) is None:
        return lead
    topped = _row(scope, ctx0, shrink, logo, True)
    scale = lambda lays: max((lay.ctx.ts for lay in lays), default=0.0)  # noqa: E731
    return topped if scale(topped) >= LOGO_COST * scale(lead) else lead


def _row(scope: Scope, ctx0: Ctx, shrink: float, logo: Optional[Block], topped: bool) -> List[Layout]:
    reg, blocks = scope.region, scope.blocks
    rest = [b for b in blocks if b is not logo]
    vis = visual_block(rest)
    cta = [b for b in rest if b.role == "cta"][-1:]
    middle = [b for b in rest if b not in cta and b is not vis]
    if topped and not middle:
        return []
    lead = ([logo] if logo is not None and not topped else []) + ([vis] if vis is not None else [])
    gap = max(4.0, 0.6 * margin(reg.w, reg.h))
    lo, hi0 = scale_bounds(scope)
    heads = [i.font for b in blocks if b.role == "headline" for i in b.texts]
    # the text may grow until a headline fills two lines of the row's height; logo and button keep the usual cap
    hi = max(hi0, reg.h / 2.6 / max(heads)) if heads else hi0
    layouts = []
    for parts in (_partitions(middle, 3) if middle else [[]]):
        if topped:  # the logo heads the column holding the headline
            k = next((i for i, part in enumerate(parts) if any(b.role == "headline" for b in part)), 0)
            parts = parts[:k] + [[logo] + parts[k]] + parts[k + 1:]

        def columns(ts, relax, even):
            c = Ctx(ctx0.W, ctx0.H, ctx0.src_W, ctx0.src_H, ts, ts, relax)
            cf = Ctx(ctx0.W, ctx0.H, ctx0.src_W, ctx0.src_H, min(ts, hi0), min(ts, hi0), relax)
            fixed = [(b, _slot_size(b, cf, reg)) for b in lead]
            tail = [(b, _slot_size(b, cf, reg)) for b in cta]
            inset = (_edge_inset(fixed[0], 0, reg.x) if fixed else 0.0,
                     _edge_inset(tail[-1], 2, c.W - reg.x1) if tail else 0.0)
            if even:  # a padded end sets the drawn margin on both ends
                inset = (max(inset),) * 2
            gaps = _row_gaps([b for b, _ in fixed] + list(parts) + [b for b, _ in tail], ts, gap)
            used = sum(inset) + sum(w for _, (w, _) in fixed + tail) + sum(gaps)
            weights = [_text_weight(p) for p in parts]
            widths = [(reg.w - used) * w / sum(weights) for w in weights] if parts else []
            return c, fixed, tail, widths, inset, gaps

        def fits(ts, relax, even):
            c, fixed, tail, widths, _, _ = columns(ts, relax, even)
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
            c, fixed, tail, widths, inset, gaps = columns(ts * shrink, relax, even)
            made.append((ts, _row_layout(c, fixed, tail, parts, widths, inset, reg, gaps, cta, blocks, hi0,
                                         f"row {len(parts)}col s={shrink}")))
            if inset[0] == inset[1]:
                break  # the ends are already even
        if len(made) == 2 and made[1][0] >= EVEN_COST * made[0][0] and _lines(made[1][1]) == _lines(made[0][1]):
            made.pop(0)
        layouts += [lay for _, lay in made[:1]]
    return layouts


EVEN_COST = 0.9  # even end margins may cost a banner's type up to 10%, never a line break
TEXT_GAP_EM = 0.35  # copy keeps at least this many em of its largest text from its neighbours in a row


def _row_gaps(seq, ts: float, base: float) -> List[float]:
    """Gap after each item of a banner row: the usual gap, widened where copy
    sits beside something (a headline must not touch the product or the button)."""
    def em(obj) -> float:
        blocks = obj if isinstance(obj, list) else [obj]
        return max((i.font for b in blocks if b.role != "cta" for i in b.texts), default=0.0) * ts

    return [max(base, TEXT_GAP_EM * max(em(a), em(b))) for a, b in zip(seq, seq[1:])]


def _lines(lay: Layout) -> Dict[int, int]:
    """Line count of every visible text in a layout."""
    return {it.idx: it.text_layout(p.font, p.w).n_lines for b, _ in lay.placed for it in b.texts
            if (p := lay.out.get(it.idx)) is not None and not p.hidden and p.font}


def _row_layout(c: Ctx, fixed, tail, parts, widths, inset, reg: Rect, gaps: List[float], cta, blocks, hi0: float,
                name: str) -> Layout:
    cf = c.with_scale(min(c.ts, hi0), min(c.ts, hi0))
    lay = Layout(name, c)
    seq = [(b, wh[0]) for b, wh in fixed] + [(p, w) for p, w in zip(parts, widths)] + [(b, wh[0]) for b, wh in tail]
    free = reg.w - sum(inset) - sum(w for _, w in seq) - sum(gaps)
    extra = max(0.0, free) / max(1, len(seq) - 1)
    x = reg.x + inset[0]
    for (obj, w), g in zip(seq, gaps + [0.0]):
        if isinstance(obj, Block):
            bc = _slot_ctx(obj, cf, reg)
            bw, bh = measure(obj, bc, reg.w / 3)
            lay.placed.append((obj, place(obj, bc, x, reg.y + (reg.h - bh) / 2, reg.w / 3, INF, lay.out)))
        else:
            lay.placed += stack_place(obj, c, Rect(x, reg.y, w, reg.h), lay.out, valign="center")
        x += w + g + extra
    if cta:
        _cta_below_headline(lay, cta[0], cf, reg)
    _centre_columns(lay, [obj if isinstance(obj, list) else [obj] for obj, _ in seq], reg.cy)
    _center_ink(lay, blocks, reg, min(gaps, default=0.0))
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
    from .objective import evaluate, rank

    lays = arrangements(scope, ctx0, items, allow_preserve)
    if not lays:
        return None
    return max(lays, key=lambda lay: rank(evaluate(lay, scope, items)))


def _panel_inner(children: List[Block], src: Rect, region: Rect, ctx: Ctx, items) -> Dict[int, Placement]:
    """Lay out a panel's children inside its new box (hooked into blocks.py).
    Panels nested deeper simply stack, which keeps the search linear in depth."""
    if not children:
        return {}
    hook, B.panel_layout_hook = B.panel_layout_hook, None
    try:
        lay = best_layout(Scope(children, src, region), ctx, items)
    finally:
        B.panel_layout_hook = hook
    return lay.out if lay else {}
