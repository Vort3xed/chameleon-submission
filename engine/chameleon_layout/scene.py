"""Understand a source design without semantic labels.

Turns the raw element list into a `Scene`:
  * backgrounds  - full-bleed images/shapes (re-fitted to the new canvas)
  * decor        - faint / tiny / bleeding shapes that hold no content
  * hidden       - invisible elements, and small images whose asset is missing
                   (a large one is laid out: the scorer's bundle may have it)
  * blocks       - layout units in reading order: single texts/images,
                   rigid groups (buttons, badges, ribbons, product tiles),
                   panels (containers whose children are re-laid inside them)
                   and rows (side-by-side runs of similar blocks)
  * ornaments    - rotated or corner-pinned small blocks placed after the flow
Each block gets a role (headline, cta, logo, hero, ...) and an importance.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Dict, List, Optional, Tuple

from . import assets
from . import text_metrics as tm
from .geometry import Rect, bounding

_RGBA = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")
_CTA_WORDS = re.compile(r"^(shop|buy|order|get|learn|discover|try|find|reserve|book|join|sign|download|start|"
                        r"rsvp|subscribe|explore|see|view|claim|grab|register|call|visit|watch|read|apply)\b", re.I)

_PRICE = re.compile(r"^((from|only|just|now)\s+)?[$€£¥]\s?\d[\d.,]*\b.{0,12}$", re.I)

IMPORTANCE = {"headline": 1.0, "cta": 0.85, "logo": 0.85, "hero": 0.75, "subhead": 0.6, "price": 0.6, "text": 0.5,
              "feature": 0.5,
              "body": 0.4, "image": 0.5, "badge": 0.35, "ribbon": 0.35, "legal": 0.2, "divider": 0.15,
              "shape": 0.2, "panel": 0.8, "row": 0.4, "table": 0.4}


def num(v, default=0.0) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except Exception:
        return default


def luminance(v) -> Optional[float]:
    """Relative luminance (0 black - 1 white) of an rgb(a) or hex colour, None if unreadable."""
    m = _RGBA.match(str(v or "").strip())
    if m:
        return assets.relative_luminance(*(float(m.group(i)) for i in (1, 2, 3)))
    h = str(v or "").strip().lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        return None
    return assets.relative_luminance(*(int(h[i:i + 2], 16) for i in (0, 2, 4)))


def backdrop(scene: "Scene") -> Optional[float]:
    """Luminance of what the canvas shows behind everything: its lowest full-canvas background."""
    full = [it for it in scene.backgrounds if it.box.area >= 0.9 * scene.W * scene.H]
    if not full:
        return None
    it = min(full, key=lambda it: it.z)
    return luminance(it.el.get("fill_color")) if it.type == "shape" else assets.mean_luminance(it.el.get("asset_id"))


def color_alpha(v) -> float:
    m = _RGBA.match(str(v or "").strip())
    if m and m.group(4) is not None:
        return max(0.0, min(1.0, float(m.group(4))))
    return 1.0


@dataclass(eq=False)
class Item:
    idx: int
    el: dict
    type: str
    box: Rect
    rotation: float
    alpha: float
    z: float
    group: Optional[str]
    missing: bool = False
    echo_of: Optional[int] = None  # a copy stacked beneath another text (its shadow, its outline): follows it
    font: float = 0.0
    _layouts: Dict = field(default_factory=dict, repr=False)

    @property
    def bounds(self) -> Rect:
        """Visible footprint: rotated box."""
        return self.box.rotated_bounds(self.rotation)

    def letter_spacing(self, font=None) -> float:
        """Letter spacing scaled with the font so the typographic look is kept."""
        return num(self.el.get("letter_spacing"), 0.0) * (font or self.font) / self.font

    def text_layout(self, font=None, width=None) -> tm.TextLayout:
        key = (font or self.font, round(width if width is not None else self.box.w, 2))
        if key not in self._layouts:
            e = self.el
            self._layouts[key] = tm.layout_text(e.get("content", ""), e.get("font_family", ""), e.get("font_weight"),
                                                e.get("font_style"), key[0], key[1], num(e.get("line_height"), 1.2) or 1.2,
                                                self.letter_spacing(key[0]))
        return self._layouts[key]

    @property
    def ink(self) -> Rect:
        return self.ink_at(self.box, self.font)

    def ink_at(self, b: Rect, font=None) -> Rect:
        """What a viewer sees when the element occupies `b`: text glyph extents,
        image opaque content, shape box (rotation included)."""
        if self.type == "text":
            lay = self.text_layout(font or self.font, b.w)
            lw = lay.max_line_width
            align = self.el.get("text_align", "left")
            x = b.x if align == "left" else (b.x + (b.w - lw) / 2 if align == "center" else b.x1 - lw)
            r = Rect(x, b.y + lay.ink_top, lw, max(1.0, lay.ink_bottom - lay.ink_top))
        elif self.type == "image" and not self.missing:
            fx0, fy0, fx1, fy1 = assets.content_bounds(self.el.get("asset_id"))
            size = assets.pixel_size(self.el.get("asset_id"))
            if size and self.el.get("fit", "contain") == "contain":
                s = min(b.w / size[0], b.h / size[1]) if size[0] and size[1] else 1.0
                dw, dh = size[0] * s, size[1] * s
                ox, oy = b.x + (b.w - dw) / 2, b.y + (b.h - dh) / 2
                r = Rect(ox + fx0 * dw, oy + fy0 * dh, (fx1 - fx0) * dw, (fy1 - fy0) * dh)
            else:
                r = Rect(b.x + fx0 * b.w, b.y + fy0 * b.h, (fx1 - fx0) * b.w, (fy1 - fy0) * b.h)
        else:
            r = b
        return r.rotated_bounds(self.rotation)

    @property
    def content(self) -> str:
        return str(self.el.get("content", "") or "")

    @property
    def visible_frac(self) -> Tuple[float, float, float, float]:
        """Visible (opaque) part of the box as fractions (x0, y0, x1, y1)."""
        if self.type != "image" or self.missing or self.box.w <= 0 or self.box.h <= 0:
            return (0.0, 0.0, 1.0, 1.0)
        ink = Item(self.idx, self.el, self.type, self.box, 0.0, self.alpha, self.z, self.group).ink
        b = self.box
        return ((ink.x - b.x) / b.w, (ink.y - b.y) / b.h, (ink.x1 - b.x) / b.w, (ink.y1 - b.y) / b.h)


@dataclass(eq=False)
class Block:
    kind: str  # text | image | shape | rigid | panel | row | table
    items: List[Item]
    children: List["Block"] = field(default_factory=list)
    frame: Optional[Item] = None
    role: str = "text"
    importance: float = 0.5
    ornament: bool = False
    align: str = "center"
    corner: str = ""  # for ornaments: tl/tr/bl/br
    hero: bool = False  # carries the main product imagery
    inner: Optional[Rect] = None  # panels: where the children sat inside the frame
    band: str = ""  # panels: the edge a full-width/-height bar sits on (header, footer, scrim, side panel)
    cols: int = 0  # tables: cells per row (the children are the cells, row by row)

    @property
    def src(self) -> Rect:
        return bounding([i.bounds for i in self.items])

    @cached_property
    def visible(self) -> Rect:
        """Like `src`, but unrotated text counts by its words' horizontal extent
        (centred labels often sit in boxes far wider than the words)."""
        return bounding([Rect(i.ink.x, i.box.y, i.ink.w, i.box.h) if i.type == "text" and not i.rotation else i.bounds
                         for i in self.items])

    @property
    def texts(self) -> List[Item]:
        return [i for i in self.items if i.type == "text"]

    @property
    def rotated(self) -> bool:
        return any(i.rotation for i in self.items)

    def __repr__(self):
        ids = ",".join(str(i.el.get("id")) for i in self.items[:4])
        return f"<{self.kind}:{self.role} {ids}{'…' if len(self.items) > 4 else ''}>"


@dataclass
class Scene:
    W: float
    H: float
    items: List[Item]
    backgrounds: List[Item]
    decor: List[Item]
    hidden: List[Item]
    blocks: List[Block]
    ornaments: List[Block]
    hide_z: Optional[int] = None  # z_index that puts an element under an opaque full-canvas background


# ---------------------------------------------------------------------------

TEXT_FIELDS = ("content", "font_family", "font_weight", "font_style", "text_align", "asset_id", "fit", "shape_type",
               "color", "fill_color", "id")


def _scalars(el: dict) -> dict:
    """The element with junk (a list, a dict) in a field meant to hold a string read as absent: text
    measurement and asset lookups are cached on these values."""
    bad = [k for k in TEXT_FIELDS if isinstance(el.get(k), (list, dict, set))]
    return {k: v for k, v in el.items() if k not in bad} if bad else el


def make_items(elements: List[dict]) -> List[Item]:
    items = []
    for idx, el in enumerate(elements):
        el = _scalars(el)
        t = el.get("type") if isinstance(el.get("type"), str) else ""
        g = el.get("group_id")
        box = Rect(num(el.get("x")), num(el.get("y")), max(0.0, num(el.get("width"))), max(0.0, num(el.get("height"))))
        op = max(0.0, min(1.0, num(el.get("opacity"), 1.0)))
        if t == "text":
            alpha = color_alpha(el.get("color"))  # the renderer ignores text opacity
        elif t == "shape":
            alpha = op * color_alpha(el.get("fill_color"))
        else:
            alpha = op
        it = Item(idx, el, t, box, num(el.get("rotation")), alpha, num(el.get("z_index"), 0.0),
                  str(g) if isinstance(g, (str, int, float)) and g != "" else None)
        it.missing = t == "image" and assets.is_missing(el.get("asset_id"))
        it.font = max(1.0, num(el.get("font_size"), 16.0)) if t == "text" else 0.0
        items.append(it)
    return items


def _paints_above(child: Item, parent: Item) -> bool:
    return (child.z, child.idx) > (parent.z, parent.idx)


def find_containers(content: List[Item]) -> Dict[int, Item]:
    """Map item idx -> innermost opaque-enough shape that visually holds it.
    A group travels together, so it is adopted whole or not at all."""
    shapes = [s for s in content if s.type == "shape" and s.alpha >= 0.3 and s.el.get("shape_type") != "line"
              and not s.rotation]
    parent: Dict[int, Item] = {}
    for c in content:
        best = None
        for s in shapes:
            if s is c or s.box.area <= c.bounds.area * 1.1:
                continue
            if _paints_above(c, s) and s.box.contains(c.ink, 0.85):
                # the innermost; of two alike (a card and its shadow) the one painted just beneath
                if best is None or s.box.area < 0.98 * best.box.area or s.box.area < 1.02 * best.box.area and s.z > best.z:
                    best = s
        if best is not None:
            parent[c.idx] = best
    groups: Dict[str, List[Item]] = {}
    for c in content:
        if c.group:
            groups.setdefault(c.group, []).append(c)
    for members in groups.values():  # a group straddling a container's edge (a ribbon over a card's corner)
        inside = {m.idx for m in members}  # is a unit of its own: none of it is adopted (a button's label sits
        outer = [parent.get(m.idx) for m in members if getattr(parent.get(m.idx), "idx", None) not in inside]
        if len({id(o) for o in outer}) > 1:  # in its own shape - only containers outside the group count)
            for m in members:
                if getattr(parent.get(m.idx), "idx", None) not in inside:
                    parent.pop(m.idx, None)
    return parent


MISSING_HIDE = 0.02  # an image whose asset is not in our bundle is skipped only when this small (canvas share)


def _shadows(it: Item, shapes: List[Item]) -> bool:
    """`it` lies just beneath a shape of nearly its own box (a drop shadow, an outline, a border)."""
    def iou(a: Rect, b: Rect) -> float:
        inter = a.intersection(b)
        return inter / max(1e-6, a.area + b.area - inter)

    return not it.rotation and any(s is not it and s.z > it.z and iou(it.box, s.box) >= 0.7 for s in shapes)


def classify(items: List[Item], W: float, H: float):
    canvas = Rect(0, 0, W, H)
    bgs, decor, hidden, content = [], [], [], []
    for it in items:
        if it.missing and it.box.area > MISSING_HIDE * canvas.area:
            it.missing = False  # only the logo is a fixed asset: the scorer's bundle may well have this one
        if it.alpha <= 0.02 or it.box.w <= 0 or it.box.h <= 0 or it.missing or it.bounds.intersection(canvas) <= 0:
            hidden.append(it)  # (wholly off the canvas, it was never seen)
        elif it.type in ("image", "shape") and not it.rotation and it.box.intersection(canvas) >= 0.9 * canvas.area:
            bgs.append(it)
        else:
            content.append(it)
    parent = find_containers(content)
    holders = {p.idx for p in parent.values()}
    shapes = [s for s in content if s.type == "shape" and not s.rotation]
    rest = []
    for it in content:
        if it.echo_of is not None:  # laid out with the text it echoes
            decor.append(it)
            continue
        if it.type == "shape" and not it.group and it.idx not in holders and _shadows(it, shapes):
            decor.append(it)  # a shadow or outline of the shape above it, at any opacity: it follows that shape
            continue
        faint_frame = it.type == "shape" and it.alpha < 0.3 and it.box.area >= 0.5 * canvas.area
        if it.type == "shape" and not it.group and it.idx not in holders and it.el.get("shape_type") != "line":
            tiny = it.box.area < 0.004 * canvas.area
            bleeding = it.box.intersection(canvas) < 0.9 * it.box.area
            if it.alpha < 0.45 or tiny or bleeding:
                decor.append(it)
                continue
        if faint_frame or it.type == "text" and it.alpha < 0.3:  # faint type is texture, not copy
            decor.append(it)
            continue
        rest.append(it)
    kept = {it.idx for it in rest}
    parent = {k: v for k, v in parent.items() if k in kept and v.idx in kept}
    return bgs, decor, hidden, rest, parent


# ---------------------------------------------------------------------------
# block construction


def _descendants(root: Item, children_of: Dict[int, List[Item]]) -> List[Item]:
    out, stack = [], [root]
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(children_of.get(n.idx, []))
    return out


def build_blocks(scope_items: List[Item], children_of: Dict[int, List[Item]], scope: Rect) -> List[Block]:
    """Blocks for the items directly inside `scope` (canvas or a panel)."""
    units: List[List[Item]] = []
    unit_of: Dict[int, int] = {}

    def add_unit(members):
        ids = {m.idx for m in members}
        hit = sorted({unit_of[i] for i in ids if i in unit_of})
        if hit:  # merge with existing units sharing members
            merged = list({m.idx: m for u in hit for m in units[u]}.values())
            merged += [m for m in members if m.idx not in {x.idx for x in merged}]
            keep = hit[0]
            for u in hit[1:]:
                units[u] = []
            units[keep] = merged
            for m in merged:
                unit_of[m.idx] = keep
        else:
            units.append(list(members))
            for m in members:
                unit_of[m.idx] = len(units) - 1

    for it in scope_items:
        add_unit(_descendants(it, children_of))
    groups: Dict[str, List[Item]] = {}
    for it in scope_items:
        for m in _descendants(it, children_of):
            if m.group:
                groups.setdefault(m.group, []).append(it)
    for members in groups.values():
        members = list({m.idx: m for m in members}.values())
        # a group sprawling over most of the scope (say every element tagged with
        # one id) is a label, not a unit that must move rigidly
        sprawling = len(members) > 4 and bounding([m.bounds for m in members]).area > 0.4 * scope.area
        if len(members) > 1 and not sprawling:
            add_unit([d for m in members for d in _descendants(m, children_of)])

    blocks = []
    for u in units:
        if not u:
            continue
        u = sorted({m.idx: m for m in u}.values(), key=lambda m: m.idx)
        blocks.append(make_block(u, children_of, scope))
    return blocks


def make_block(members: List[Item], children_of: Dict[int, List[Item]], scope: Rect) -> Block:
    if len(members) == 1:
        it = members[0]
        kind = {"text": "text", "image": "image"}.get(it.type, "shape")
        band = _band(it, scope) if kind == "shape" else ""
        if band:  # a bare bar on an edge (a two-tone background, a colour strip): a band holding nothing
            return Block("panel", members, frame=it, band=band)
        return Block(kind, members)
    frames = [m for m in members if m.idx in children_of and m.type == "shape"]
    frame = max(frames, key=lambda f: f.box.area) if frames else None
    inner = [m for m in members if m is not frame]
    band = _band(frame, scope) if frame is not None else ""
    side = band in ("left", "right")
    # a card holds copy (even a single headline); a lone image on a tile stays rigid, scaling as one picture -
    # on a side bar too, where it is fitted into the bar when the bar keeps its edge
    card = len(inner) >= 2 or bool(inner) and inner[0].type == "text"
    big = frame is not None and (band and not side or (side or frame.box.area >= 0.12 * scope.area) and card)
    if big and not any(m.rotation for m in members) and frame.box.contains(bounding([m.bounds for m in inner]), 0.95):
        direct = [m for m in inner if not any(m in children_of.get(o.idx, []) for o in inner)]
        kids = build_blocks(direct, children_of, frame.box)
        return Block("panel", members, children=kids, frame=frame, inner=bounding([k.src for k in kids]), band=band)
    if side:
        return Block("rigid", members, frame=frame, inner=bounding([m.box for m in inner]), band=band)
    return Block("rigid", members, frame=frame)


def _band(frame: Item, scope: Rect) -> str:
    """The edge a full-width (or full-height) bar sits on - "top", "bottom", "left" or "right" - else ""."""
    b = frame.box
    if frame.rotation or frame.el.get("shape_type", "rectangle") != "rectangle":
        return ""
    if b.w >= 0.9 * scope.w and b.h <= 0.45 * scope.h:
        if b.y <= scope.y + 0.01 * scope.h:
            return "top"
        return "bottom" if b.y1 >= scope.y1 - 0.01 * scope.h else ""
    if b.h >= 0.9 * scope.h and b.w <= 0.55 * scope.w:  # a side panel, e.g. a colour block bleeding off half the canvas
        if b.x <= scope.x + 0.01 * scope.w:
            return "left"
        return "right" if b.x1 >= scope.x1 - 0.01 * scope.w else ""
    return ""


def _side_rows(blocks: List[Block], least: int = 2) -> List[List[Block]]:
    """Runs of side-by-side blocks of one kind and similar height, left to right (at least `least` long)."""
    rows: List[List[Block]] = []
    for b in sorted(blocks, key=lambda b: b.src.x):
        r = b.src
        for row in rows:
            ref = row[0].src
            ov = min(r.y1, ref.y1) - max(r.y, ref.y)
            if row[0].kind == b.kind and max(r.h, ref.h) / max(1e-6, min(r.h, ref.h)) < 1.6 and \
                    ov >= 0.6 * min(r.h, ref.h) and all(r.x >= o.src.x1 - 0.5 or r.x1 <= o.src.x + 0.5 for o in row):
                row.append(b)
                break
        else:
            rows.append([b])
    return [sorted(r, key=lambda b: b.src.x) for r in rows if len(r) >= least]


def _over(top: Block, cap: Block) -> bool:
    """The caption sits just below the piece, centred under it."""
    t, c = top.src, cap.src
    return 0 <= c.y - t.y1 <= 1.2 * max(t.h, c.h) and abs(t.cx - c.cx) <= 0.3 * max(t.w, c.w)


def _font(row: List[Block]) -> float:
    fonts = sorted(t.font for b in row for t in b.texts)
    return fonts[len(fonts) // 2] if fonts else 0.0


def _captions(top: List[Block], texts: List[Block], used) -> Optional[List[Block]]:
    """The texts just below each block of a row, one each and alike, set apart in style from the row
    (a smaller label under a big stat, a detail under its title) - rows that look alike are a table's
    records, not columns."""
    caps = [min((c for c in texts if c not in top and id(c) not in used and _over(t, c)),
                key=lambda c: c.src.y, default=None) for t in top]
    if None in caps or len({id(c) for c in caps}) < len(caps):
        return None
    fonts = [c.items[0].font for c in caps]
    if max(fonts) > 1.3 * min(fonts):
        return None
    up = _font(top)
    if all(b.kind == "text" for b in top) and not (up >= 1.15 * _font(caps) or _font(caps) >= 1.15 * up):
        return None
    return caps


def column_units(blocks: List[Block]) -> List[Block]:
    """A row of pieces each set over its caption - a stat over its label, a numbered step over what it
    says, a feature title over its detail - is a row of units: each column stays together whatever the
    canvas (as a price stays beside its item in a table), and a big stat never passes for the headline.
    (Product tiles keep their own handling: a picture over its name already travels as a tile.)"""
    texts = [b for b in blocks if b.kind == "text"]
    pieces = [b for b in blocks if b.kind == "text" or b.kind == "rigid" and not any(i.type == "image" for i in b.items)]
    used, units = set(), {}
    for top in sorted(_side_rows(pieces), key=lambda r: r[0].src.y):
        crowned = all(any(_over(o, t) for o in blocks if o not in top) for t in top)  # a product, an icon above:
        if crowned or used & {id(b) for b in top} or (caps := _captions(top, texts, used)) is None:
            continue  # a column of more levels, left to the tiles it belongs to
        used |= {id(b) for b in top + caps}
        for t, c in zip(top, caps):
            units[id(t)] = Block("rigid", t.items + c.items, role="feature")
    out = []
    for b in blocks:
        if id(b) in units:
            out.append(units[id(b)])
        elif id(b) not in used:
            out.append(b)
    return out


def group_rows(blocks: List[Block]) -> List[Block]:  # noqa: C901
    """Merge side-by-side blocks of similar height (badge rows, product tiles)."""
    eligible = [b for b in blocks if not b.ornament and b.kind in ("rigid", "image", "text", "shape")]
    rows = _side_rows(eligible, 1)
    out = [b for b in blocks if b not in eligible]
    tiles = [r for r in rows if len(r) >= 2 and r[0].kind in ("rigid", "image")]
    tables = _tables([r for r in rows if len(r) >= 2 and r[0].kind == "text"])
    out += [b for r in rows if r not in tiles and not any(r in t for t in tables) for b in r]
    for kids in [[b for r in grid for b in r] for grid in _stack_rows(tiles)]:
        out.append(Block("row", [i for b in kids for i in b.items], children=kids, role="row",
                         importance=max(b.importance for b in kids), hero=any(b.hero for b in kids)))
    for t in tables:
        cells = [b for r in t for b in r]
        out.append(Block("table", [i for b in cells for i in b.items], children=cells, role="row",
                         importance=max(b.importance for b in cells), cols=len(t[0])))
    return out


def _tables(rows: List[List[Block]]) -> List[List[List[Block]]]:
    """Rows of text that form tables - at least three stacked rows with the same number of cells
    in aligned columns (a menu, a price list): a table keeps its rows and columns whatever the
    canvas, so a price stays beside its item."""
    out: List[List[List[Block]]] = []
    run: List[List[Block]] = []
    for r in sorted(rows, key=lambda r: r[0].src.y) + [[]]:
        if run and r and _next_row(run[-1], r):
            run.append(r)
            continue
        if len(run) >= 3:
            out.append(run)
        run = [r]
    return out


def _next_row(a: List[Block], b: List[Block]) -> bool:
    h = max(c.src.h for c in a + b)
    gap = min(c.src.y for c in b) - max(c.src.y1 for c in a)
    return len(a) == len(b) and 0 <= gap <= 3 * h and \
        all(min(abs(p.src.x - q.src.x), abs(p.src.x1 - q.src.x1)) <= 0.5 * h for p, q in zip(a, b))


def _stack_rows(rows: List[List[Block]]) -> List[List[List[Block]]]:
    """Rows of like tiles stacked one above the other form one grid."""
    def extent(r):
        return bounding([b.src for b in r])

    grids: List[List[List[Block]]] = []
    for r in sorted(rows, key=lambda r: extent(r).y):
        e, t = extent(r), r[0].src
        for g in grids:
            ge, gt = extent(g[-1]), g[-1][0].src
            like = r[0].kind == g[-1][0].kind and max(t.h, gt.h) / max(1e-6, min(t.h, gt.h)) < 1.3
            aligned = min(e.x1, ge.x1) - max(e.x, ge.x) >= 0.6 * min(e.w, ge.w)
            if like and aligned and 0 <= e.y - ge.y1 <= max(t.h, gt.h):
                g.append(r)
                break
        else:
            grids.append([r])
    return grids


def reading_order(blocks: List[Block]) -> List[Block]:
    """Top-to-bottom bands, left-to-right within a band.  A full-height side
    panel spans every band, so it frames the rest instead of joining one."""
    sides = {e: [b for b in blocks if b.band == e] for e in ("left", "right")}
    bands: List[List[Block]] = []
    for b in sorted((b for b in blocks if b.band not in sides), key=lambda b: b.src.cy):
        if bands:
            ref = bounding([x.src for x in bands[-1]])
            if ref.y <= b.src.cy <= ref.y1:
                bands[-1].append(b)
                continue
        bands.append([b])
    return sides["left"] + [b for band in bands for b in sorted(band, key=lambda b: b.src.x)] + sides["right"]


# ---------------------------------------------------------------------------
# roles


def assign_roles(blocks: List[Block], W: float, H: float):
    flat = []
    for b in blocks:
        flat.append(b)
        flat.extend(_all_children(b))
    singles = [b for b in flat if b.kind == "text"]
    prices = {id(b) for b in singles if _PRICE.match(b.items[0].content.strip())}
    # a price can be the biggest type on a card, but the message is the headline
    titled = [b for b in singles if id(b) not in prices] or singles
    fonts = sorted({round(b.items[0].font, 1) for b in titled}, reverse=True)
    for b in flat:
        if b.kind == "text":
            it = b.items[0]
            n = len(it.content)
            rank = fonts.index(round(it.font, 1)) if round(it.font, 1) in fonts else 0
            if id(b) in prices and titled is not singles:
                b.role = "price"
            elif rank == 0 and n <= 160:
                b.role = "headline"
            elif _CTA_WORDS.match(it.content.strip()) and n <= 30:
                b.role = "cta"
            elif len(fonts) > 2 and it.font <= fonts[-1] and it.font <= 0.6 * fonts[0] and n >= 30 and it.box.cy > 0.6 * H:
                b.role = "legal"
            elif n >= 110:
                b.role = "body"
            elif rank == 1:
                b.role = "subhead"
            else:
                b.role = "text"
        elif b.kind == "image":
            it = b.items[0]
            name = str(it.el.get("asset_id", "")).lower()
            wide = it.box.w / max(1e-6, it.box.h) >= 1.8
            if "logo" in name or (wide and it.box.area < 0.06 * W * H):
                b.role = "logo"
            else:
                b.role = "image"
        elif b.kind == "shape":
            b.role = "divider" if b.items[0].el.get("shape_type") == "line" else "shape"
        elif b.kind == "rigid":
            labels = [t.content.strip() for t in b.texts]
            if b.role == "feature":
                pass
            elif b.rotated:
                b.role = "ribbon"
            elif any(it.type == "image" for it in b.items):
                b.role = "image"
            elif labels and any(_CTA_WORDS.match(l) for l in labels) and len(labels) == 1:
                b.role = "cta"
            else:
                b.role = "badge"
        elif b.kind == "panel":
            b.role = "panel"
        elif b.kind == "row":
            b.role = "row"
    def image_area(b):
        if b.role == "logo":
            return 0.0
        return sum(it.box.area for it in b.items if it.type == "image" and not it.missing)

    heroes = [b for b in flat if image_area(b) > 0 and b.kind in ("image", "rigid", "row")]
    if heroes:
        hero = max(heroes, key=image_area)
        hero.role = "hero" if hero.kind != "row" else "row"
        hero.hero = True
    chips = [b for b in flat if b.kind == "rigid" and b.role in ("badge", "cta")]
    if chips and not any(b.role == "cta" for b in flat):
        # biggest label, lowest on the page = the call to action
        best = max(chips, key=lambda b: max(t.font for t in b.texts) * (1 + 0.3 * b.src.cy / H) if b.texts else 0)
        best.role = "cta"
    for b in flat:
        b.importance = IMPORTANCE.get(b.role, 0.4)
        if b.kind in ("panel", "row", "table") and b.children:
            b.importance = max(c.importance for c in b.children)
        if b.hero:
            b.importance = max(b.importance, IMPORTANCE["hero"])


def _all_children(b: Block) -> List[Block]:
    out = []
    for c in b.children:
        out.append(c)
        out.extend(_all_children(c))
    return out


def detect_alignment(blocks: List[Block], scope: Rect):
    """Left/centre/right anchor of each block relative to its scope."""
    tol = 0.02 * scope.w + 1
    for b in blocks:
        r = b.src
        lefts = sum(1 for o in blocks if o is not b and abs(o.src.x - r.x) < tol)
        centers = sum(1 for o in blocks if o is not b and abs(o.src.cx - r.cx) < tol)
        if abs(r.cx - scope.cx) < 0.06 * scope.w or centers > lefts:
            b.align = "center"
        elif lefts and r.cx < scope.cx:
            b.align = "left"
        elif r.cx >= scope.cx and abs(scope.x1 - r.x1) < abs(r.x - scope.x):
            b.align = "right"
        else:
            b.align = "left" if r.cx < scope.cx else "right"
        if b.kind == "panel":
            detect_alignment(b.children, b.frame.box)


def mark_ornaments(blocks: List[Block], W: float, H: float):
    for b in blocks:
        r = b.src
        if b.rotated:
            b.ornament = True
        elif b.role in ("badge", "image") and b.kind != "row" and r.area < 0.04 * W * H:
            in_x = r.cx < 0.25 * W or r.cx > 0.75 * W
            in_y = r.cy < 0.2 * H or r.cy > 0.8 * H
            b.ornament = in_x and in_y
        if b.ornament:
            b.corner = ("t" if r.cy < H / 2 else "b") + ("l" if r.cx < W / 2 else "r")


def mark_echoes(items: List[Item]):
    """Copies of one text stacked on each other (a drop shadow, an outline, a duplicate) read as one
    piece of type: the topmost copy is laid out, the others echo it - same width and wrap, scaled offset."""
    texts = [it for it in items if it.type == "text" and str(it.el.get("content") or "").strip() and it.bounds.area > 0]
    for a in texts:
        stack = [b for b in texts if str(b.el.get("content")).strip() == str(a.el.get("content")).strip()
                 and b.group == a.group  # (two buttons' labels are not one text's copies)
                 and a.bounds.intersection(b.bounds) >= 0.5 * min(a.bounds.area, b.bounds.area) > 0]
        top = max(stack, key=lambda b: (b.z, b.idx))
        if top is not a:
            a.echo_of = top.idx


def icon_labels(items: List[Item], W: float, H: float):
    """A small icon just beside a one-line label (a feature list, a tick before a claim) is one unit with
    it, as a button's shape is with its label."""
    texts = [t for t in items if t.type == "text" and not t.group and t.echo_of is None and t.font > 0
             and t.box.h <= 1.8 * t.font and str(t.el.get("content") or "").strip()]
    for ic in items:
        if ic.type not in ("shape", "image") or ic.group or ic.rotation or ic.box.area > 0.02 * W * H:
            continue
        for t in texts:  # an opaque mark about the text's size (not a faint background dot)
            gap = max(t.ink.x - ic.box.x1, ic.box.x - t.ink.x1)
            if ic.alpha >= 0.6 and 0.25 * t.font ** 2 <= ic.box.area and ic.box.h <= 2.5 * t.font and \
                    0 <= gap <= 1.5 * max(ic.box.w, t.font) and \
                    t.box.y - 0.5 * t.font <= ic.box.cy <= t.box.y1 + 0.5 * t.font:
                ic.group = t.group = f"icon:{t.idx}"
                texts.remove(t)
                break


def analyze(elements: List[dict], W: float, H: float) -> Scene:
    items = make_items(elements)
    mark_echoes(items)
    icon_labels(items, W, H)
    bgs, decor, hidden, content, parent = classify(items, W, H)
    children_of: Dict[int, List[Item]] = {}
    for idx, p in parent.items():
        children_of.setdefault(p.idx, []).append(items[idx])
    top = [it for it in content if it.idx not in parent]
    blocks = column_units(build_blocks(top, children_of, Rect(0, 0, W, H)))
    assign_roles(blocks, W, H)
    mark_ornaments(blocks, W, H)
    flow = [b for b in blocks if not b.ornament]
    flow = reading_order(group_rows(flow))
    for b in flow:
        if b.kind == "panel":
            b.children = reading_order(group_rows(b.children))
    sides = [b for b in flow if b.band in ("left", "right")]
    detect_alignment(sides, Rect(0, 0, W, H))
    detect_alignment([b for b in flow if b not in sides], _beside(sides, W, H))
    return Scene(W, H, items, bgs, decor, hidden, flow, [b for b in blocks if b.ornament], cover_z(bgs))


def _beside(sides: List[Block], W: float, H: float) -> Rect:
    """The canvas beside full-height side panels: the space the rest of the content is aligned in."""
    x0 = max([0.0] + [b.frame.box.x1 for b in sides if b.band == "left"])
    x1 = min([W] + [b.frame.box.x for b in sides if b.band == "right"])
    return Rect(x0, 0.0, max(1.0, x1 - x0), H)


def cover_z(backgrounds: List[Item]) -> Optional[int]:
    """z_index just below the lowest fully opaque background, if there is one.

    The renderer ignores text opacity, so a text element that must disappear
    (opacity 0) is also tucked beneath such a background."""
    def opaque(it):
        if it.rotation or it.alpha < 0.99:
            return False
        if it.type == "shape":
            return it.el.get("shape_type", "rectangle") == "rectangle"
        return it.el.get("fit", "contain") in ("cover", "fill") and assets.is_opaque(it.el.get("asset_id"))
    zs = [it.z for it in backgrounds if opaque(it)]
    return int(math.floor(min(zs))) - 1 if zs else None
