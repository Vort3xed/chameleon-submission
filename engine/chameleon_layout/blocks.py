"""Measure and place layout blocks at a given scale.

Every block kind answers two questions through `measure` / `place`:
how big it is at text scale `ctx.ts` / image scale `ctx.img` when it may use
at most `max_w` x `max_h`, and where each of its elements lands.

  text   re-wrapped with the renderer's exact algorithm, box tightened to
         the widest line, font kept above a legibility floor
  image  aspect locked, scaled by ctx.img
  shape  dividers stretch with the text scale, other shapes scale uniformly
  rigid  the whole group scaled uniformly (buttons, badges, ribbons, tiles)
  panel  container shape wrapped around its own re-stacked children
  row    flex-wrap of side-by-side blocks (badge rows, product tiles)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import text_metrics as tm
from .geometry import Rect, bounding
from .scene import Block, Item, num

INF = float("inf")
SMALL_ROLES = {"legal", "badge", "ribbon", "divider"}
MAX_MEASURE = 1.6  # text may grow at most this much wider than its scaled source box

# Set by arrange.py: (children, source frame, target region, ctx) -> placements.
# Lets a panel give its children their own best arrangement.
panel_layout_hook = None


@dataclass
class Placement:
    x: float
    y: float
    w: float
    h: float
    font: Optional[int] = None
    opacity: Optional[float] = None
    hidden: bool = False

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.w, self.h)


@dataclass
class Ctx:
    """Target canvas facts plus the current text / image scale."""

    W: float
    H: float
    src_W: float
    src_H: float
    ts: float = 1.0
    img: float = 1.0
    floor_relax: float = 1.0

    def with_scale(self, ts: float, img: float) -> "Ctx":
        return Ctx(self.W, self.H, self.src_W, self.src_H, ts, img, self.floor_relax)

    def scaled(self, f: float) -> "Ctx":
        return self.with_scale(self.ts * f, self.img * f)

    @property
    def view(self) -> float:
        """How much a judge viewing at ~1024px shrinks this canvas."""
        return min(1.0, 1024.0 / max(self.W, self.H))

    @property
    def src_view(self) -> float:
        return min(1.0, 1024.0 / max(self.src_W, self.src_H))

    def font_floor(self, it: Item, role: str) -> float:
        """Smallest font that stays legible, never demanding more than the source had."""
        target = (7.0 if role in SMALL_ROLES else 10.5) * self.floor_relax
        return max(1.0, min(target, it.font * self.src_view) / self.view)


# ---------------------------------------------------------------------------
# text


def text_font(it: Item, role: str, ctx: Ctx) -> int:
    return max(1, int(round(max(it.font * ctx.ts, ctx.font_floor(it, role)))))


def _word_width(it: Item, font: int) -> float:
    e = it.el
    return tm.longest_word_width(it.content, e.get("font_family", ""), e.get("font_weight"), e.get("font_style"),
                                 font, it.letter_spacing(font))


def fit_text(it: Item, font: int, max_w: float) -> Tuple[int, float, float]:
    """(font, box width, box height) for `it` wrapped inside `max_w`.

    The font shrinks if a single word is wider than `max_w` (the renderer
    never breaks words).  The renderer wraps ignoring letter spacing, so the
    wrap width is narrowed until the spaced lines really fit.  Finally the box
    is tightened to the widest line, verified to wrap identically."""
    if max_w == INF:
        e = it.el
        max_w = tm.natural_width(it.content, e.get("font_family", ""), e.get("font_weight"), e.get("font_style"),
                                 font, it.letter_spacing(font)) + 2
    word = _word_width(it, font)
    while word > max_w and font > 1:
        font = max(1, min(font - 1, int(font * max_w / word)))
        word = _word_width(it, font)
    wrap_w = max(1.0, max_w)
    lay = it.text_layout(font, wrap_w)
    for _ in range(6):
        if lay.max_line_width <= max_w + 0.5 or wrap_w <= word:
            break
        wrap_w = max(word, wrap_w - (lay.max_line_width - max_w) - 1)
        lay = it.text_layout(font, wrap_w)
    tight = min(max(max_w, lay.max_line_width), lay.max_line_width + 0.6 * font + 2)
    if it.text_layout(font, tight).lines != lay.lines:
        tight = wrap_w
    return font, max(1.0, tight), max(1.0, lay.box_height)


# ---------------------------------------------------------------------------
# generic measure / place


def fit_block(b: Block, ctx: Ctx, max_w: float, max_h: float) -> Ctx:
    """Context whose text/image scales make `b` as large as possible inside
    max_w x max_h (legibility floors are dropped if they make it impossible)."""
    def fits(c, f):
        w, h = measure(b, c.with_scale(c.ts * f, c.img * f), max_w)
        return w <= max_w + 0.5 and h <= max_h + 0.5

    for c in (ctx, Ctx(ctx.W, ctx.H, ctx.src_W, ctx.src_H, ctx.ts, ctx.img, 0.0)):
        lo, hi = 1e-3, 1e3
        if not fits(c, lo):
            continue
        for _ in range(30):
            mid = math.sqrt(lo * hi)
            lo, hi = (mid, hi) if fits(c, mid) else (lo, mid)
        return c.with_scale(c.ts * lo, c.img * lo)
    return ctx.with_scale(ctx.ts * 1e-3, ctx.img * 1e-3)


def measure(b: Block, ctx: Ctx, max_w: float, max_h: float = INF) -> Tuple[float, float]:
    return _SIZERS[b.kind](b, ctx, max_w, max_h, None, 0.0, 0.0)


def place(b: Block, ctx: Ctx, x: float, y: float, max_w: float, max_h: float, out: Dict[int, Placement]) -> Rect:
    w, h = _SIZERS[b.kind](b, ctx, max_w, max_h, out, x, y)
    return Rect(x, y, w, h)


def _text(b, ctx, max_w, max_h, out, x, y):
    it = b.items[0]
    font = text_font(it, b.role, ctx)
    measure_w = max(it.box.w * MAX_MEASURE * font / it.font, 4.0 * font)
    font, w, h = fit_text(it, font, min(max_w, measure_w))
    if out is not None:
        out[it.idx] = Placement(x, y, w, h, font)
    return w, h


def _uniform_fit(src: Rect, scale: float, max_w: float, max_h: float) -> float:
    return max(1e-4, min(scale, max_w / max(src.w, 1e-6), max_h / max(src.h, 1e-6)))


def _image(b, ctx, max_w, max_h, out, x, y):
    """Images are measured by their visible pixels: transparent padding in the
    asset may overlap neighbours' boxes without anything visibly touching."""
    it = b.items[0]
    fx0, fy0, fx1, fy1 = it.visible_frac
    vis = Rect(0, 0, it.box.w * (fx1 - fx0), it.box.h * (fy1 - fy0))
    s = ctx.img
    if b.role == "logo" and vis.h > 0:  # keep the brand mark legible
        need = min(18.0, vis.h * ctx.src_view) / ctx.view * ctx.floor_relax
        s = max(s, need / vis.h)
    s = _uniform_fit(vis, s, max_w, max_h)
    if out is not None:
        out[it.idx] = _image_on_canvas(it, s, Rect(x, y, vis.w * s, vis.h * s), ctx)
    return vis.w * s, vis.h * s


def _image_on_canvas(it: Item, s: float, slot: Rect, ctx: Ctx) -> Placement:
    """Centre the visible pixels on `slot`; if the padded box would leave the
    canvas, shrink around that centre instead of letting it be shifted."""
    fx0, fy0, fx1, fy1 = it.visible_frac
    fcx, fcy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
    bw, bh = it.box.w, it.box.h
    limits = [s]
    for c, f, size, extent in ((slot.cx, fcx, bw, ctx.W), (slot.cy, fcy, bh, ctx.H)):
        if f > 0:
            limits.append(c / (f * size))
        if f < 1:
            limits.append((extent - c) / ((1 - f) * size))
    s = max(1e-4, min(limits))
    w, h = bw * s, bh * s
    return Placement(slot.cx - fcx * w, slot.cy - fcy * h, w, h)


def _shape(b, ctx, max_w, max_h, out, x, y):
    it = b.items[0]
    if b.role == "divider":
        w = min(max_w, it.box.w * ctx.ts)
        h = min(max_h, max(1.0, it.box.h * min(1.0, ctx.ts)))
    else:
        s = _uniform_fit(it.box, ctx.img, max_w, max_h)
        w, h = it.box.w * s, it.box.h * s
    if out is not None:
        out[it.idx] = Placement(x, y, w, h)
    return w, h


def rigid_scale(b: Block, ctx: Ctx, max_w: float = INF, max_h: float = INF) -> float:
    """Uniform scale for a rigid group: follows the text scale, never lets a
    label drop below its legibility floor, and shrinks to fit the slot."""
    s = ctx.ts if b.texts else ctx.img
    for t in b.texts:
        s = max(s, ctx.font_floor(t, b.role) / t.font)
    return _uniform_fit(b.src, s, max_w, max_h)


def _rigid(b, ctx, max_w, max_h, out, x, y):
    src = b.src
    s = rigid_scale(b, ctx, max_w, max_h)
    if out is not None:
        for it in b.items:
            p = Placement(x + (it.box.x - src.x) * s, y + (it.box.y - src.y) * s, it.box.w * s, it.box.h * s)
            if it.type == "text":
                p.font = keep_lines(it, it.font * s, p.w)
            out[it.idx] = p
    return src.w * s, src.h * s


def keep_lines(it: Item, font: float, width: float) -> int:
    """Scaled font that wraps into no more lines than the source did."""
    target = it.text_layout().n_lines
    f = max(1, int(round(font)))
    while f > 1 and it.text_layout(f, width).n_lines > target:
        f -= 1
    return f


# ---------------------------------------------------------------------------
# stacks (used by panels here and by the top-level arrangements)


def source_gaps(blocks: List[Block]) -> List[float]:
    """Vertical gap above each block in the source (0 for the first)."""
    gaps = [0.0]
    for prev, cur in zip(blocks, blocks[1:]):
        gaps.append(max(0.0, cur.src.y - prev.src.y1))
    return gaps


def stack_gaps(blocks: List[Block], ctx: Ctx, region_h: float) -> List[float]:
    lo, hi = 0.012 * region_h + 2, 0.09 * region_h + 4
    return [0.0] + [min(hi, max(lo, g * ctx.ts)) for g in source_gaps(blocks)[1:]]


def stack_measure(blocks: List[Block], ctx: Ctx, width: float, region_h: float):
    sizes = [measure(b, ctx, width) for b in blocks]
    gaps = stack_gaps(blocks, ctx, region_h)
    h = sum(s[1] for s in sizes) + sum(gaps)
    w = max((s[0] for s in sizes), default=0.0)
    return w, h, sizes, gaps


def stack_place(blocks: List[Block], ctx: Ctx, region: Rect, out: Dict[int, Placement],
                valign: str = "spread") -> List[Tuple[Block, Rect]]:
    w, h, sizes, gaps = stack_measure(blocks, ctx, region.w, region.h)
    free = max(0.0, region.h - h)
    n = len(blocks)
    mixed = {"left", "right"} <= {b.align for b in blocks}  # a column cannot hug both sides
    if valign == "center" or n == 1:
        y, extra = region.y + free / 2, 0.0
    else:  # half the slack to the outer margins, half spread between blocks
        y, extra = region.y + free / 4, free / 2 / (n - 1)
    placed = []
    for b, (bw, bh), g in zip(blocks, sizes, gaps):
        y += g + (extra if placed else 0.0)
        align = "center" if mixed else b.align
        x = {"left": region.x, "right": region.x1 - bw}.get(align, region.x + (region.w - bw) / 2)
        r = place(b, ctx, x, y, region.w, INF, out)
        placed.append((b, r))
        y += bh
    return placed


def panel_pads(b: Block) -> Tuple[float, float, float, float]:
    inner = bounding([c.src for c in b.children]) or b.frame.box
    f = b.frame.box
    return (max(0.0, inner.x - f.x), max(0.0, inner.y - f.y), max(0.0, f.x1 - inner.x1), max(0.0, f.y1 - inner.y1))


def _panel(b, ctx, max_w, max_h, out, x, y):
    l, t, r, bt = (p * min(1.0, ctx.ts) for p in panel_pads(b))
    width = min(max_w, max(b.frame.box.w * ctx.ts, 0.0)) if max_w == INF else max_w
    inner_w = max(1.0, width - l - r)
    region_h = max_h if max_h < INF else ctx.H
    _, ih, _, _ = stack_measure(b.children, ctx, inner_w, region_h)
    h = ih + t + bt
    if max_h < INF:
        h = max(h, min(max_h, b.frame.box.h * ctx.ts))
    if out is not None:
        out[b.frame.idx] = Placement(x, y, width, h)
        inner = Rect(x + l, y + t, inner_w, h - t - bt)
        kids = panel_layout_hook(b.children, bounding([c.src for c in b.children]), inner, ctx) \
            if panel_layout_hook else None
        if kids:
            out.update(kids)
        else:
            stack_place(b.children, ctx, inner, out, valign="center")
    return width, h


# ---------------------------------------------------------------------------
# rows (flex-wrap)


def _row_gap(b: Block, ctx: Ctx) -> float:
    xs = sorted(b.children, key=lambda c: c.src.x)
    gaps = [max(0.0, c.src.x - p.src.x1) for p, c in zip(xs, xs[1:])]
    g = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    return max(2.0, g * ctx.ts)


def row_lines(b: Block, ctx: Ctx, max_w: float):
    gap = _row_gap(b, ctx)
    lines, cur, cur_w = [], [], 0.0
    for c in b.children:
        w, h = measure(c, ctx, max_w)
        if cur and cur_w + gap + w > max_w:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur.append((c, w, h))
        cur_w += (gap if len(cur) > 1 else 0.0) + w
    if cur:
        lines.append(cur)
    return lines, gap


def _row(b, ctx, max_w, max_h, out, x, y):
    lines, gap = row_lines(b, ctx, max_w)
    widths = [sum(w for _, w, _ in ln) + gap * (len(ln) - 1) for ln in lines]
    total_w = max(widths)
    yy = y
    for ln, lw in zip(lines, widths):
        lh = max(h for _, _, h in ln)
        xx = x + (total_w - lw) / 2
        if out is not None:
            for c, w, h in ln:
                place(c, ctx, xx, yy + (lh - h) / 2, w + 0.01, INF, out)
                xx += w + gap
        yy += lh + gap
    return total_w, yy - y - gap


_SIZERS = {"text": _text, "image": _image, "shape": _shape, "rigid": _rigid, "panel": _panel, "row": _row}
