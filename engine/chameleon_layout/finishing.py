"""Finishing touches shared by every candidate layout: backgrounds re-fitted,
decoration re-anchored (and kept with its card), hidden items tucked away,
corner ornaments placed in free corner space (product art giving way a
little), decoration settled off the content, and near-miss alignments
snapped onto shared lines.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from .blocks import INF, Ctx, Placement, measure, place, list_item
from .geometry import Rect, bounding
from .scene import Block, Scene, corner_radius, num

from .families import Layout, margin


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


def _in_corner(b: Block, ctx: Ctx, rot: float, m: float, taken, shrinks=CORNER_SHRINKS):
    """The ornament in its own corner, shrunk a little if that is what it takes to stay clear."""
    for shrink in shrinks:
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
    full = margin(ctx.W, ctx.H)
    m = full * 0.6
    for b in ornaments:
        taken = [r for _, r in lay.placed]
        # a single rotated element measures unrotated; groups already measure rotated bounds
        rot = b.items[0].rotation if b.kind in ("text", "image", "shape") else 0.0
        # a full margin in, as designers set corner badges, where that leaves air round it; else tucked closer
        roomy = [r.inset(-m) for r in taken]
        spot = _in_corner(b, ctx, rot, full, roomy, (1.0,)) or _in_corner(b, ctx, rot, m, taken)
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


def _frames(blocks: List[Block]) -> List:
    """The frame shapes of every card and button, at any depth."""
    out = []
    for b in blocks:
        out += ([b.frame] if b.frame is not None else []) + _frames(b.children)
    return out


def _twin(it, frames: List):
    """The card or button `it` is a shadow or outline of: an unrotated shape of nearly the same box."""
    c = it.bounds
    if it.rotation or it.type != "shape":
        return None
    return next((f for f in frames if c.intersection(f.box) >= 0.7 * (c.area + f.box.area - c.intersection(f.box))),
                None)


def _mirror(it, frame, p: Placement) -> Placement:
    """A card's shadow or outline: offset and size relative to the card, kept as the card moves and resizes
    (an offset is a distance, so it scales uniformly)."""
    f = frame.box
    k = min(p.w / max(f.w, 1e-6), p.h / max(f.h, 1e-6))
    return Placement(p.x + (it.box.x - f.x) * k, p.y + (it.box.y - f.y) * k,
                     p.w + (it.box.w - f.w) * k, p.h + (it.box.h - f.h) * k)


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
    shapes = [f for f in _frames(scene.blocks) if f.idx in lay.out and not lay.out[f.idx].hidden]
    for it in (d for d in scene.decor if d.echo_of is None):  # echoes follow their text, at the end
        visible = it.bounds.intersection(canvas_src) / max(1e-6, it.bounds.area)
        c = it.bounds
        twin = _twin(it, shapes)
        card = next((f for f in frames if f.box.x <= c.cx <= f.box.x1 and f.box.y <= c.cy <= f.box.y1
                     and c.area < 0.5 * f.box.area), None)
        if twin is not None:  # a card's or button's shadow or outline stays with it
            lay.out[it.idx] = _mirror(it, twin, lay.out[twin.idx])
        elif card is not None:  # decoration on a card moves with the card
            lay.out[it.idx] = _on_frame(it, card, lay.out[card.idx])
        else:
            lay.out[it.idx] = _anchored(it, scene, W, H, m) if _is_frame(it, scene) else \
                _proportional(it, scene, W, H, m * math.sqrt(max(0.2, visible)))
    covers = opaque_covers(scene)
    spare = max((c for c in covers.values() if c.idx in lay.out and not lay.out[c.idx].hidden),
                key=lambda c: c.box.area, default=None)  # a cover for text that has no block of its own
    for it in scene.hidden:  # a missing asset is skipped, and what lay off the canvas stays unseen
        p = _proportional(it, scene, W, H, m)
        p.hidden = it.missing or it.bounds.intersection(Rect(0, 0, scene.W, scene.H)) <= 0
        if p.hidden and it.type == "text" and scene.hide_z is None and spare is not None:
            p = _beneath(it, lay.out[spare.idx], spare)
            p.hidden = True
        lay.out[it.idx] = p
    for b in lay.hidden:
        cover = covers.get(id(b)) if scene.hide_z is None else None
        for it in b.items:
            if cover is not None and it.type == "text" and cover.idx in lay.out and not lay.out[cover.idx].hidden:
                p = _beneath(it, lay.out[cover.idx], cover)
            else:
                p = _proportional(it, scene, W, H, m)
            p.hidden = True
            lay.out[it.idx] = p
    follow_echoes(scene, lay)
    return lay


def follow_echoes(scene: Scene, lay: Layout) -> None:
    """Each echo (a text's shadow or outline copy) takes its text's box, font and fate, at the source offset
    scaled with the font: it wraps exactly as its text does and moves with it."""
    for it in scene.decor:
        top = scene.items[it.echo_of] if it.echo_of is not None else None
        p = lay.out.get(top.idx) if top is not None else None
        if p is not None:
            k = (p.font or top.font) / max(top.font, 1e-6)
            lay.out[it.idx] = replace(p, x=p.x + (it.box.x - top.box.x) * k, y=p.y + (it.box.y - top.box.y) * k,
                                      font=p.font and it.font * k)


def _opaque(it) -> bool:
    return it.type == "shape" and it.alpha >= 0.99 and not it.rotation and \
        it.el.get("shape_type", "rectangle") == "rectangle"


def opaque_covers(scene: Scene) -> Dict[int, object]:
    """id(block) -> the opaque shape (item) that can hide its text: text cannot
    be hidden by opacity (the renderer ignores it on text), so without an
    opaque full-canvas background it goes beneath the card it belongs to, or
    else beneath the design's biggest opaque button (buttons are never dropped)."""
    buttons = [it for b in scene.blocks if b.role == "cta" for it in b.items if _opaque(it)]
    host = max(buttons, key=lambda it: it.box.area, default=None)
    out: Dict[int, object] = {}

    def walk(blocks: List[Block], cover):
        for b in blocks:
            if b.kind == "panel":
                walk(b.children, b.frame if _opaque(b.frame) else cover)
            if cover is not None and b.role != "cta":
                out[id(b)] = cover

    walk(scene.blocks, host)
    return out


def _beneath(it, frame: Placement, cover) -> Placement:
    """A hidden text squeezed to 1 px in the middle of an opaque shape, under it - inside the part that is opaque
    edge to edge (a pill's rounded ends are not)."""
    r = min(corner_radius(cover.el, frame.w, frame.h), frame.w / 2, frame.h / 2)
    w = max(1.0, (frame.w - 2 * r) * 0.8)
    h = min(max(1.0, it.text_layout(1, w).box_height), max(1.0, frame.h * 0.8))
    return Placement(frame.x + frame.w / 2 - w / 2, frame.y + frame.h / 2 - h / 2, w, h, 1, under=cover.idx)


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
    frames = _frames(scene.blocks)
    for d in scene.decor:
        p = lay.out.get(d.idx)
        if p is None or p.hidden or _is_frame(d, scene) or _twin(d, frames) or d.echo_of is not None:
            continue  # (a shadow or outline stays with its shape or text)

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
    frames = _frames(scene.blocks)
    shadows: Dict[int, List] = {}  # frame idx -> the shadows and outlines that move with it
    for d in scene.decor:
        if (f := _twin(d, frames)) is not None:
            shadows.setdefault(f.idx, []).append(d)

    def ink(b: Block) -> Optional[Rect]:
        return bounding([scene.items[it.idx].ink_at(lay.out[it.idx].rect, lay.out[it.idx].font)
                         for it in b.items if it.idx in lay.out and not lay.out[it.idx].hidden])

    def moved(b: Block, dx: float, dy: float) -> Dict[int, Placement]:
        items = b.items + [d for it in b.items for d in shadows.get(it.idx, [])]
        return {it.idx: replace(lay.out[it.idx], x=lay.out[it.idx].x + dx, y=lay.out[it.idx].y + dy)
                for it in items if it.idx in lay.out}

    def overlap(b: Block) -> float:  # all that moving b can change
        return new_overlap(visible_inks(lay.out, every), {it.idx for it in b.items})

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
            if r is None or list_item(b):  # (list items already share their edge: moving one would break it)
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
                before, gap, side, old = overlap(b), clearance(b), lopsided(), {i: lay.out[i] for i in new}
                lay.out.update(new)
                if overlap(b) > before + 1e-6 or clearance(b) < min(0.75 * gap, room) or \
                        lopsided() > side + 0.005 * frame.w:
                    lay.out.update(old)  # no new collision, no crammed neighbour, no lopsided margins
                else:
                    r = ink(b)
        for b in group:  # inside each card, its children against the card
            if b.kind == "panel" and b.frame is not None and b.frame.idx in lay.out:
                snap(b.children, lay.out[b.frame.idx].rect)

    snap([b for b in every if b not in scene.ornaments], Rect(0, 0, W, H))
    follow_echoes(scene, lay)


def lift_small_text(scene: Scene, lay: Layout) -> None:
    """Use free space for tiny banner labels and supporting copy without hiding content.

    Re-measure each proposed font/box and reject it if it leaves its container,
    leaves the canvas, or increases overlap. Buttons grow with their labels.
    """
    from .blocks import fit_text

    from .objective import leaf_blocks

    W, H = lay.ctx.W, lay.ctx.H
    banner = W >= 3 * H and H <= 150
    supporting = {it.idx for b in leaf_blocks(scene.blocks) if b.role in ("legal", "body") for it in b.texts}
    if not banner and not supporting:
        return
    canvas = Rect(0, 0, W, H)
    visible = [it for it in scene.items if it.idx in lay.out and not lay.out[it.idx].hidden
               and lay.out[it.idx].opacity != 0 and it.alpha > 0]
    for it in visible:
        p = lay.out[it.idx]
        if (not banner and it.idx not in supporting) or it.type != "text" or it.rotation or not p.font or p.font >= 7:
            continue
        # A single-label pill can expand; larger panels must continue to contain the text.
        pills = [s for s in visible if s.type == "shape" and not s.rotation
                 and s.box.contains(it.ink, .95) and s.box.area < .15 * scene.W * scene.H
                 and sum(s.box.contains(t.ink, .95) for t in visible if t.type == "text") == 1]
        pill = min(pills, key=lambda s: s.box.area, default=None)
        font = 9 if pill else 7
        center = lay.out[pill.idx].rect if pill else p.rect
        for width in (p.w, fit_text(it, font, INF)[1]):
            f, w, h = fit_text(it, font, width)
            if f < font or w > W or h > H:
                continue
            q = replace(p, x=min(max(0, center.cx - w / 2), W - w),
                        y=min(max(0, center.cy - h / 2), H - h), w=w, h=h, font=f)
            positions = [q.y]
            if not banner and not pill:
                # Supporting copy in a footer may need to move below its logos
                # when wrapping at a readable size. Keep every neighbor fixed.
                for other in visible:
                    if other.idx == it.idx or (other.z < it.z and other.box.contains(it.ink, .95)):
                        continue
                    op = lay.out[other.idx]
                    obstacle = other.ink_at(op.rect, op.font)
                    if obstacle.x < q.x + q.w and obstacle.x1 > q.x:
                        positions += [obstacle.y1 + 2, obstacle.y - h - 2]
                positions = sorted(set(positions), key=lambda y: abs(y - q.y))
            accepted = False
            for top in positions:
                q = replace(q, y=top)
                changes = {it.idx: q}
                if pill:
                    old = lay.out[pill.idx]
                    pw, ph = max(old.w, w + 4), max(old.h, h + 2)
                    if pw > W or ph > H:
                        continue
                    changes[pill.idx] = replace(old, x=min(max(0, center.cx - pw / 2), W - pw),
                                               y=min(max(0, center.cy - ph / 2), H - ph), w=pw, h=ph)
                    box = changes[pill.idx].rect
                    changes[it.idx] = q = replace(q, x=box.cx-w/2, y=box.cy-h/2)
                valid = True
                for changed in [v for v in visible if v.idx in changes]:
                    old = lay.out[changed.idx]
                    new = changes[changed.idx]
                    ink = changed.ink_at(new.rect, new.font)
                    if not canvas.contains(ink, .999) or not canvas.contains(new.rect, .999):
                        valid = False
                        break
                    old_ink = changed.ink_at(old.rect, old.font)
                    for other in visible:
                        if other.idx in changes:
                            continue
                        op = lay.out[other.idx]
                        obstacle = other.ink_at(op.rect, op.font)
                        if other.z < changed.z and other.box.contains(changed.ink, .95):
                            if not op.rect.contains(ink, .99):
                                valid = False
                                break
                            continue
                        overlap = ink.intersection(obstacle) / max(1, min(ink.area, obstacle.area))
                        previous = old_ink.intersection(obstacle) / max(1, min(old_ink.area, obstacle.area))
                        if overlap > max(.02, previous) + .001:
                            valid = False
                            break
                    if not valid:
                        break
                if valid:
                    lay.out.update(changes)
                    accepted = True
                    break
            if accepted:
                break
