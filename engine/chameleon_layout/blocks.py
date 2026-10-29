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
import re
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

from . import text_metrics as tm
from .geometry import Rect
from .scene import Block, Item

INF = float("inf")
SMALL_ROLES = {"legal", "badge", "ribbon", "divider"}
MAX_MEASURE = 1.6  # text may grow at most this much wider than its scaled source box,
LINE_EM = 20.0  # or to a comfortable line of ~40 characters, whichever is wider (long copy re-wraps to the room)

# Set by families.py: (children, source frame, target region, ctx) -> placements.
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
    under: Optional[int] = None  # hidden text: the opaque shape (item idx) it is tucked beneath

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


def _pair_width(it: Item, font: int) -> float:
    """Width of the widest two consecutive words: a short title set narrower
    than this breaks one word per line."""
    e, words = it.el, it.content.split()
    return max(tm.natural_width(f"{a} {b}", e.get("font_family", ""), e.get("font_weight"), e.get("font_style"), font,
                                it.letter_spacing(font)) for a, b in zip(words, words[1:]))


def fit_text(it: Item, font: int, max_w: float, pairs: bool = False) -> Tuple[int, float, float]:
    """(font, box width, box height) for `it` wrapped inside `max_w`.

    The font shrinks if a single word (with `pairs`, two consecutive words) is
    wider than `max_w` (the renderer never breaks words).  The renderer wraps ignoring letter spacing, so the
    wrap width is narrowed until the spaced lines really fit.  Finally the box
    is tightened to the widest line, verified to wrap identically."""
    if max_w == INF:
        e = it.el
        max_w = tm.natural_width(it.content, e.get("font_family", ""), e.get("font_weight"), e.get("font_style"),
                                 font, it.letter_spacing(font)) + 2
    unit = _pair_width if pairs else _word_width
    word = unit(it, font)
    while word > max_w and font > 1:
        font = max(1, min(font - 1, int(font * max_w / word)))
        word = unit(it, font)
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
        return w <= max_w and h <= max_h

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
    fitted = None
    if b.role in ("cta", "badge") and it.text_layout().n_lines == 1:  # a one-line label shrinks before it wraps
        f, floor = font, ctx.font_floor(it, b.role)
        f, w, h = fit_text(it, f, INF)
        while w > max_w and f > max(1.0, floor):
            f, w, h = fit_text(it, max(1, min(f - 1, int(f * max_w / w))), INF)
        fitted = (f, w, h) if w <= max_w else None
    if fitted is None:
        measure_w = max(it.box.w * MAX_MEASURE * font / it.font, LINE_EM * font)
        words = len(it.content.split())
        pairs = b.role in ("headline", "subhead") and 3 <= words <= 6 and "\n" not in it.content
        fitted = fit_text(it, font, min(max_w, measure_w), pairs)  # short titles keep two words a line
    font, w, h = fitted
    align = it.el.get("text_align", "left")
    if b.role in BALANCED and align == "center":  # a narrower centred box stays centred
        w = balance(it, font, w)
    drawn = _drawn(it, font, w)
    if out is not None:  # a lone last word is avoided within the room measured, so the layout stays as it is
        bw = balance(it, font, w) if _widowed(it, font, w) else w
        bd = _drawn(it, font, bw)
        out[it.idx] = Placement(x - _ink_offset(it, bd, drawn) - _ink_offset(it, bw, bd), y, bw, h, font)
    return drawn, h


def _widowed(it: Item, font: int, w: float) -> bool:
    """Wrapped text whose last line is one word, which three or more words can avoid."""
    lines = it.text_layout(font, w).lines
    return len(lines) > 1 and len(lines[-1].split()) == 1 and len(it.content.split()) >= 3


def _drawn(it: Item, font: int, w: float) -> float:
    """The width a text's lines are drawn in: letter-spaced lines can reach past their box (any box wide enough
    to hold them would re-wrap them, the renderer wrapping without the spacing)."""
    return max(w, it.text_layout(font, w).max_line_width)


def _ink_offset(it: Item, w: float, drawn: float) -> float:
    """Where lines `drawn` wide start, aligned in a box `w` wide, relative to the box."""
    return {"center": (w - drawn) / 2, "right": w - drawn}.get(it.el.get("text_align", "left"), 0.0)


BALANCED = ("headline", "subhead")  # wrapped titles get even lines instead of a lone last word


def balance(it: Item, font: int, w: float) -> float:
    """The narrowest box that keeps the same number of lines (like CSS
    `text-wrap: balance`): the renderer wraps greedily, which can leave a
    widow - one short word alone on the last line."""
    n = it.text_layout(font, w).n_lines
    return w if n < 2 else _narrowest(it, font, w, lambda lay: lay.n_lines == n)


def snug(it: Item, font: int, w: float) -> float:
    """The narrowest box that wraps into exactly the same lines."""
    lines = it.text_layout(font, w).lines
    return _narrowest(it, font, w, lambda lay: lay.lines == lines)


def _narrowest(it: Item, font: int, w: float, same) -> float:
    lo, hi = _word_width(it, font), w
    for _ in range(12):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if same(it.text_layout(font, mid)) else (mid, hi)
    tight = hi + 0.05 * font + 1  # the narrowest width that still qualifies, plus rounding room
    return tight if tight < w and same(it.text_layout(font, tight)) else w


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
        need = min(28.0, vis.h * ctx.src_view, 0.25 * ctx.H * ctx.view) / ctx.view * ctx.floor_relax  # short strips: at most 25% of the height
        s = max(s, need / vis.h)
    s = _uniform_fit(vis, s, max_w, max_h)
    if out is not None:
        out[it.idx] = _image_on_canvas(it, s, Rect(x, y, vis.w * s, vis.h * s), ctx)
    return vis.w * s, vis.h * s


def image_pads(b: Block) -> Tuple[float, float, float, float]:
    """Transparent margins (left, top, right, bottom) of an image block as
    multiples of its visible width / height; zero for other blocks."""
    if b.kind != "image":
        return (0.0, 0.0, 0.0, 0.0)
    fx0, fy0, fx1, fy1 = b.items[0].visible_frac
    vw, vh = max(fx1 - fx0, 1e-6), max(fy1 - fy0, 1e-6)
    return (fx0 / vw, fy0 / vh, (1 - fx1) / vw, (1 - fy1) / vh)


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
    return _uniform_fit(b.visible, s, max_w, max_h)


PAD_EM = (1.0, 0.45)  # a snug button keeps at least this much padding round its label (em, across and up)
BALLOON = 0.2  # a lifted button this wide (of the canvas) or wider has ballooned: it hugs its label instead


def _button(b: Block):
    """(pill, label) when a rigid group is one shape with one text on it, else None."""
    shapes, texts = [i for i in b.items if i.type == "shape"], [i for i in b.items if i.type == "text"]
    if len(b.items) == 2 and len(shapes) == len(texts) == 1 and not texts[0].rotation and \
            shapes[0].box.contains(texts[0].ink, 0.95):
        return shapes[0], texts[0]
    return None


def _snug(pill: Item, label: Item, s: float, base: float, out, x: float, y: float) -> Tuple[float, float]:
    """A button whose label was lifted to its legibility floor: the label grows, its padding only follows
    the layout (at least PAD_EM) - the pill hugs the label instead of ballooning with it."""
    font = keep_lines(label, label.font * s, label.box.w * s)
    p = _tighten(label, Placement(0.0, 0.0, label.box.w * s, label.box.h * s, font))
    ink = label.ink_at(Rect(p.x, p.y, p.w, p.h), font)
    # the source's padding round the label's ink (none where the label overflowed its pill)
    pads = (max(0.0, pill.box.w - label.ink.w) / 2, max(0.0, pill.box.h - label.ink.h) / 2)
    px, py = (min(pad * s, max(pad * base, em * font)) for pad, em in zip(pads, PAD_EM))
    if out is not None:
        out[pill.idx] = Placement(x, y, ink.w + 2 * px, ink.h + 2 * py)
        out[label.idx] = replace(p, x=x + px - (ink.x - p.x), y=y + py - (ink.y - p.y))
    return ink.w + 2 * px, ink.h + 2 * py


def _rigid(b, ctx, max_w, max_h, out, x, y):
    src = b.visible
    s = rigid_scale(b, ctx, max_w, max_h)
    base = _uniform_fit(src, ctx.ts if b.texts else ctx.img, max_w, max_h)
    if s > 1.05 * base and src.w * s >= BALLOON * ctx.W and (pair := _button(b)):
        return _snug(*pair, s, base, out, x, y)
    if out is not None:
        for it in b.items:
            p = Placement(x + (it.box.x - src.x) * s, y + (it.box.y - src.y) * s, it.box.w * s, it.box.h * s)
            if it.type == "text":
                p.font = keep_lines(it, it.font * s, p.w)
                if not it.rotation:
                    p = _tighten(it, p)
            out[it.idx] = p
    return src.w * s, src.h * s


def _tighten(it: Item, p: Placement) -> Placement:
    """Shrink a label's box to its measured lines, aligned as the text is, so
    a wide centred box cannot reach past the group (or off the canvas)."""
    lay = it.text_layout(p.font, p.w)
    w = min(p.w, lay.max_line_width + 0.1 * p.font + 2)
    if it.text_layout(p.font, w).lines != lay.lines:
        return p
    align = it.el.get("text_align", "left")
    x = p.x + {"center": (p.w - w) / 2, "right": p.w - w}.get(align, 0.0)
    return replace(p, x=x, w=w)


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


def group_breaks(blocks: List[Block]) -> List[bool]:
    """Which gaps separate groups: the widest ones of the source (within 15%
    of the widest, as the layout tree cuts first); the rest lie inside a group."""
    src = source_gaps(blocks)
    widest = max(src[1:], default=0.0)
    return [False] + [g >= 0.85 * widest for g in src[1:]]


GROUP_EM = (0.5, 1.2)  # a gap inside a group: between half and 1.2 em of the larger text beside it


def stack_gaps(blocks: List[Block], ctx: Ctx, region_h: float) -> List[float]:
    lo, hi = 0.012 * region_h + 2, 0.09 * region_h + 4
    gaps = [0.0] + [min(hi, max(lo, g * ctx.ts)) for g in source_gaps(blocks)[1:]]
    for k, brk in enumerate(group_breaks(blocks)):
        em = max(_lead_font(blocks[k - 1], ctx), _lead_font(blocks[k], ctx)) if k else 0.0
        if em and not brk:  # what belongs together stays together, with air enough to read as two lines
            gaps[k] = min(max(gaps[k], GROUP_EM[0] * em), GROUP_EM[1] * em)
    return gaps


def _lead_font(b: Block, ctx: Ctx) -> float:
    return max((text_font(it, b.role, ctx) for it in b.texts), default=0.0)


def stack_measure(blocks: List[Block], ctx: Ctx, width: float, region_h: float):
    sizes = [measure(b, ctx, width) for b in blocks]
    gaps = stack_gaps(blocks, ctx, region_h)
    h = sum(s[1] for s in sizes) + sum(gaps)
    w = max((s[0] for s in sizes), default=0.0)
    return w, h, sizes, gaps


def _slack_shares(blocks: List[Block], breaks: List[bool], src: Rect) -> Optional[Tuple[float, float]]:
    """(top, between) shares of the space the source left around and between its groups, or None if the
    source stacked nothing (a row restacked keeps the default spread)."""
    top = min(b.src.y for b in blocks) - src.y
    bottom = src.y1 - max(b.src.y1 for b in blocks)
    between = sum(g for g, brk in zip(source_gaps(blocks), breaks) if brk)
    total = max(0.0, top) + max(0.0, bottom) + between
    return (max(0.0, top) / total, between / total) if between > 0 and total > 0 else None


def stack_place(blocks: List[Block], ctx: Ctx, region: Rect, out: Dict[int, Placement],
                valign: str = "spread", src: Optional[Rect] = None) -> List[Tuple[Block, Rect]]:
    w, h, sizes, gaps = stack_measure(blocks, ctx, region.w, region.h)
    free = max(0.0, region.h - h)
    n = len(blocks)
    aligns = {b.align for b in blocks}
    axis = aligns.pop() if len(aligns) == 1 else "center"  # one alignment per column; mixed ones centre
    breaks = group_breaks(blocks)
    between = sum(g for g, brk in zip(gaps, breaks) if brk)
    shares = _slack_shares(blocks, breaks, src) if src is not None else None
    if valign == "center" or n == 1 or between <= 0:
        y, stretch = region.y + free / 2, 1.0
    else:  # half the slack to the outer margins, half to the gaps between groups in proportion (groups stay
        # compact) - drawn halfway to where the source left its space: above, between the groups, below
        top, mid = ((0.25 + shares[0]) / 2, (0.5 + shares[1]) / 2) if shares else (0.25, 0.5)
        y, stretch = region.y + free * top, 1.0 + free * mid / between
    lists = _list_runs(blocks, sizes, region)
    placed = []
    for b, (bw, bh), g, brk in zip(blocks, sizes, gaps, breaks):
        y += g * (stretch if brk else 1.0)
        x = lists.get(id(b), {"left": region.x, "right": region.x1 - bw}.get(axis, region.x + (region.w - bw) / 2))
        r = place(b, ctx, x, y, region.w, INF, out)
        if axis == "center" and b.kind == "text" and id(b) not in lists:
            r = _centre_snug(b, r, out)
        placed.append((b, r))
        y += bh
    return placed


_BULLET = re.compile(r"\s*([•·▪●◦‣⁃–—*✓✔►]|\d{1,2}[.)])\s")


def list_item(b: Block) -> bool:
    """An icon with its label, or a text that opens with a bullet or a number ("• Real fruit", "2. Chill")."""
    if b.items and all(str(i.group or "").startswith("icon:") for i in b.items):
        return True
    return b.kind == "text" and bool(_BULLET.match(str(b.items[0].el.get("content") or "")))


def _list_runs(blocks: List[Block], sizes, region: Rect) -> Dict[int, float]:
    """Consecutive list items keep one left edge, the list centred as a whole: x of each, by id."""
    xs: Dict[int, float] = {}
    run: List[Tuple[Block, float]] = []
    for b, (bw, _) in list(zip(blocks, sizes)) + [(None, (0.0, 0.0))]:
        if b is not None and list_item(b):
            run.append((b, bw))
            continue
        if len(run) >= 2:
            x0 = region.x + (region.w - max(w for _, w in run)) / 2
            xs.update({id(r): x0 for r, _ in run})
        run = []
    return xs


def _centre_snug(b: Block, r: Rect, out: Dict[int, Placement]) -> Rect:
    """Left- or right-aligned text in a centred column: the box shrinks to its
    lines and stays centred, so its slack cannot pull the words to one side."""
    it = b.items[0]
    p = out.get(it.idx)
    if p is None or p.hidden or not p.font or it.el.get("text_align", "left") == "center":
        return r
    w = snug(it, p.font, p.w)
    drawn = _drawn(it, p.font, w)
    out[it.idx] = replace(p, x=r.cx - drawn / 2 - _ink_offset(it, w, drawn), w=w)
    return Rect(r.cx - drawn / 2, r.y, drawn, r.h)


def panel_pads(b: Block) -> Tuple[float, float, float, float]:
    inner, f = b.inner or b.frame.box, b.frame.box
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
        kids = panel_layout_hook(b.children, b.inner or b.frame.box, inner, ctx) \
            if panel_layout_hook else None
        if kids:
            out.update(kids)
        else:
            stack_place(b.children, ctx, inner, out, valign="center")
    return width, h


# ---------------------------------------------------------------------------
# rows (flex-wrap)


def _row_gap(b: Block, ctx: Ctx) -> float:
    """Median source gap between neighbours on the same line (children are in reading order) - for units of
    a stat over its label, as drawn: their captions sit centred in boxes as wide as the columns, which nearly
    touch, while the units are sized by what they draw."""
    box = (lambda c: c.visible) if all(c.role == "feature" for c in b.children) else (lambda c: c.src)
    gaps = [box(c).x - box(p).x1 for p, c in zip(b.children, b.children[1:])
            if min(p.src.y1, c.src.y1) > max(p.src.y, c.src.y) and box(c).x >= box(p).x1]
    g = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    return max(2.0, g * ctx.ts)


def row_lines(b: Block, ctx: Ctx, max_w: float):
    """Flex-wrap the children, then even out the lines (9 tiles: 5+4, not 7+2)."""
    gap = _row_gap(b, ctx)
    sized = [(c, *measure(c, ctx, max_w)) for c in b.children]
    lines, cur, cur_w = [], [], 0.0
    for c, w, h in sized:
        if cur and cur_w + gap + w > max_w:
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur.append((c, w, h))
        cur_w += (gap if len(cur) > 1 else 0.0) + w
    if cur:
        lines.append(cur)
    per = -(-len(sized) // len(lines))
    even = [sized[i:i + per] for i in range(0, len(sized), per)]
    if len(even) == len(lines) and all(sum(w for _, w, _ in ln) + gap * (len(ln) - 1) <= max_w for ln in even):
        lines = even
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


TABLE_GAP_EM = 1.5  # a table's columns sit this many em of their text apart (not the source's spread: a menu
                    # set across a wide canvas would otherwise force its type down to keep the gaps)


def _table(b, ctx, max_w, max_h, out, x, y):
    """A table keeps its columns: each as wide as its widest cell and aligned as in the source,
    TABLE_GAP_EM apart.  Too wide, every row folds the same way (four columns become two over two,
    two become one centred column, an item over its price); an odd number of columns instead
    shares the width in proportion, its cells wrapping."""
    cols, em = b.cols, max((_lead_font(c, ctx) for c in b.children), default=0.0)
    gap = max(2.0, TABLE_GAP_EM * em)
    while True:
        widths = [max(measure(c, ctx, INF)[0] for c in b.children[j::cols]) for j in range(cols)]
        if sum(widths) + gap * (cols - 1) <= max_w or cols % 2:
            break
        cols //= 2
    room = max_w - gap * (cols - 1)
    if sum(widths) > room:
        widths = [w * room / sum(widths) for w in widths]
    rows = [b.children[i:i + cols] for i in range(0, len(b.children), cols)]
    # folded into one column (item, price, item, price...) a record spans two lines: kept tight, spaced apart
    record = 2 if cols == 1 and b.cols % 2 == 0 else 1
    pitch = max((0.6 if record > 1 else 0.35) * em, _row_spacing(rows[::record]) * ctx.ts)
    sides = [_column_align(b.children[j::cols]) for j in range(cols)] if cols > 1 else ["center"]
    yy = y
    for k, r in enumerate(rows):
        sizes = [measure(c, ctx, w) for c, w in zip(r, widths)]
        rh = max(h for _, h in sizes)
        if out is not None:
            xx = x
            for c, (cw, ch), w, side in zip(r, sizes, widths, sides):
                dx = {"left": 0.0, "right": w - cw}.get(side, (w - cw) / 2)
                # each cell in a box of its own width: its text alignment inside a wider box would undo the column's
                placed = place(c, ctx, xx + dx, yy + (rh - ch) / 2, cw + 0.01, INF, out)
                if side == "center" and c.kind == "text":
                    _centre_snug(c, placed, out)
                xx += w + gap
        yy += rh + (pitch if k % record == record - 1 else 0.15 * em)
    return sum(widths) + gap * (cols - 1), yy - y - pitch


def _row_spacing(rows) -> float:
    """Median source gap between a table's rows."""
    gaps = sorted(min(c.src.y for c in b) - max(c.src.y1 for c in a) for a, b in zip(rows, rows[1:]))
    return max(0.0, gaps[len(gaps) // 2]) if gaps else 0.0


def _column_align(cells) -> str:
    """How a column's cells line up in the source: the edge (or centre) they share - or, sharing
    none (a folded column gathers cells from several source columns), their own text alignment."""
    spread = {a: max(f(c.src) for c in cells) - min(f(c.src) for c in cells)
              for a, f in (("left", lambda r: r.x), ("right", lambda r: r.x1), ("center", lambda r: r.cx))}
    side = min(spread, key=spread.get)
    if spread[side] > 0.5 * min(c.src.w for c in cells):
        aligns = [{"right": "right", "center": "center"}.get(c.items[0].el.get("text_align"), "left") for c in cells]
        side = max(("left", "center", "right"), key=aligns.count)
    return side


_SIZERS = {"text": _text, "image": _image, "shape": _shape, "rigid": _rigid, "panel": _panel, "row": _row,
           "table": _table}
