"""Rank candidate layouts the way the rubric would.

Each term is in [0, 1] (higher is better):
  legibility   text stays above a readable size for this canvas
  size         elements keep their size relative to the region (hierarchy)
  fill         content spans the available area instead of floating small
  coverage     visible content area relative to the source's
  headline     the headline is big enough to read at a glance
  headline_share  and to lead the canvas (full at 12% of its short side, as people prefer)
  hero         the product imagery keeps its share of the canvas
  product_share  and fills it (full at a quarter of the region, as people prefer)
  balance      visual mass is centred
  wrap         short phrases are not shattered into one-word lines
  kept         important elements stay visible
  overlap      elements do not collide (beyond what the source layered)
  faithful     blocks stay roughly where they were (same composition)
plus one-hot features for the arrangement family in each band of region
shape (near-square / wide / very wide, either orientation): which family
suits a canvas depends on how stretched it is.  `WEIGHTS` combine them into
the ranking score (fitted to AI-judge preferences by eval/fit_prefs.py).
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

from .families import Layout, Scope
from .blocks import SMALL_ROLES
from .geometry import bounding
from .scene import Block

# Half the logistic weights fitted to ~300 tasks of AI-judge rankings
# (eval/fit_prefs.py).  Guard terms keep their earlier weights: the judge only
# ever saw candidates these already screened (narrow shattered columns, tiny
# text, overlaps), so the data cannot price them.  The family priors are
# halved once more: they are the judge's taste in arrangements (it is ~65%
# right on known defects), and at full size they outvoted every quality term
# in close calls (a product shrunk to a speck under a card, kept for "stack").
WEIGHTS = {"hero": 0.16, "fill": 0.14, "coverage": 0.12, "headline": 0.20, "kept": 0.18, "legibility": 0.28,
           "balance": 0.07, "faithful": 0.06, "product_share": 0.04, "headline_share": 0.06, "wrap": 0.12, "overlap": 0.12, "hierarchy": 0.08,
           "is_preserve_near": 0.03, "is_stack_near": 0.025, "is_split_near": -0.025,
           "is_preserve_mid": 0.05, "is_split_mid": 0.065, "is_stack_mid": -0.045, "is_row_mid": -0.07,
           "is_split_wide": 0.02, "is_stack_wide": -0.12, "is_row_wide": 0.10}


def _holds_hero(b: Block) -> bool:
    """The block is the product art or holds it (a side panel around the product)."""
    return b.hero or any(map(_holds_hero, b.children))


def leaf_blocks(blocks: List[Block]) -> List[Block]:
    out = []
    for b in blocks:
        out += leaf_blocks(b.children) if b.kind in ("panel", "row", "table") else [b]
        if b.kind == "panel":
            out.append(Block("shape", [b.frame], role="panel", importance=0.2))
    return out


def evaluate(lay: Layout, scope: Scope, items) -> Dict[str, float]:
    ctx = lay.ctx
    reg, src = scope.region, scope.src
    lin_out, lin_src = math.sqrt(reg.area), math.sqrt(src.area)
    t: Dict[str, float] = {}

    leg, size, wraps = [], [], []
    for b in leaf_blocks(scope.blocks):
        for it in b.items:
            p = lay.out.get(it.idx)
            if p is None or p.hidden:
                continue
            if it.type == "text" and p.font:
                need = min(7.0 if b.role in SMALL_ROLES else 10.5, it.font * ctx.src_view)
                leg.append((min(1.0, p.font * ctx.view / max(need, 1e-6)) ** 2, b.importance))
                words = max(1, len(it.content.split()))
                per_line = words / max(1, it.text_layout(p.font, p.w).n_lines)
                src_per_line = words / max(1, it.text_layout().n_lines)
                wraps.append((min(1.0, per_line / min(src_per_line, 3.0)), b.importance))
                r = (p.font / lin_out) / (it.font / lin_src)
            else:
                share = it.box.area / src.area
                r = math.sqrt((p.w * p.h / reg.area) / share) if share > 0 else 1.0
            size.append((min(r, 1 / r) ** 0.5 if r > 0 else 0.0, b.importance))
    t["legibility"] = _wavg(leg)
    t["size"] = _wavg(size)
    t["wrap"] = _wavg(wraps)

    box = bounding([r for b, r in lay.placed if not b.ornament])
    t["fill"] = min(1.0, (box.intersection(reg) / reg.area) / 0.55) if box else 0.0

    lost = sum(_mass([b]) * (1.5 if _holds_hero(b) else 1.0) for b in lay.hidden)
    t["kept"] = max(0.0, 1.0 - lost / (_mass(scope.blocks) or 1.0))

    vis = visible_inks(lay.out, scope.blocks)
    t["overlap"] = math.exp(-3 * new_overlap(vis))
    content = [(b, o, s_) for b, it, o, s_ in vis if b.role not in ("panel",)]
    src_cov = sum(s_.area for _, _, s_ in content) / src.area
    out_cov = sum(o.area for _, o, _ in content) / reg.area
    t["coverage"] = min(1.0, out_cov / src_cov) if src_cov > 0 else 1.0
    heads = [lay.out[it.idx].font for b, it, _, _ in vis if b.role == "headline" and lay.out[it.idx].font]
    t["headline"] = min(1.0, max(heads) * ctx.view / 44.0) if heads else 1.0
    # and leading the canvas, as people prefer: shrinking a headline that already reads still costs something
    t["headline_share"] = min(1.0, max(heads) / (HEADLINE_SHARE * min(reg.w, reg.h))) if heads else 1.0
    t["hierarchy"] = _hierarchy(lay, vis)
    hero = [(o.area / reg.area, s_.area / src.area) for b, it, o, s_ in vis if b.hero or b.role == "hero"]
    t["product_share"] = min(1.0, sum(h[0] for h in hero) / 0.25) if hero else 1.0  # people reward product art
    # that fills the canvas (human labels), beyond merely keeping its source share
    t["hero"] = min(1.0, math.sqrt(sum(h[0] for h in hero) / sum(h[1] for h in hero))) if hero and \
        sum(h[1] for h in hero) > 0 else (0.0 if any(map(_holds_hero, lay.hidden)) else 1.0)
    mass = sum(o.area for _, o, _ in content)
    if mass > 0:
        cx = sum(o.area * o.cx for _, o, _ in content) / mass
        cy = sum(o.area * o.cy for _, o, _ in content) / mass
        t["balance"] = max(0.0, 1 - 2 * math.hypot((cx - reg.cx) / reg.w, (cy - reg.cy) / reg.h))
    else:
        t["balance"] = 1.0

    dist = []
    for b, r in lay.placed:
        s = b.src
        d = math.hypot((r.cx - reg.x) / reg.w - (s.cx - src.x) / src.w, (r.cy - reg.y) / reg.h - (s.cy - src.y) / src.h)
        dist.append((max(0.0, 1 - d * 1.5), b.importance))
    t["faithful"] = _wavg(dist)

    family = lay.name.split()[0].rstrip("0123456789.")
    fr = lay.region or reg  # the family's prior follows the shape it was laid out in
    stretch = max(fr.w / fr.h, fr.h / fr.w) if fr.w > 0 and fr.h > 0 else 1.0
    band = "near" if stretch < 1.5 else ("mid" if stretch < 2.5 else "wide")
    for f in FAMILIES:
        for b in BANDS:
            t[f"is_{f}_{b}"] = 1.0 if (f, b) == (family, band) else 0.0
    t["total"] = sum(WEIGHTS.get(k, 0.0) * v for k, v in t.items())
    return t


CLEAN = 0.9  # overlap term at or above this: no collision worth the name


def rank(terms: Dict[str, float]) -> Tuple[bool, float]:
    """Sort key for candidates: any clean layout before any that collides
    ("no collisions" comes first in the brief), then by total score."""
    return terms["overlap"] >= CLEAN, terms["total"]


def _hierarchy(lay: Layout, vis) -> float:
    """The headline must still lead: every other visible text stays smaller by
    its source ratio (capped at 1.15x); 0 when one is as large or larger."""
    texts = [(b, it, lay.out[it.idx].font) for b, it, _, _ in vis if it.type == "text" and lay.out[it.idx].font]
    heads = [(it, f) for b, it, f in texts if b.role == "headline"]
    if not heads:
        return 1.0
    head, hf = max(heads, key=lambda h: h[1])
    worst = 1.0
    for b, it, f in texts:
        want = min(head.font / max(it.font, 1e-6), 1.15)
        if b.role != "headline" and want > 1.0:
            worst = min(worst, max(0.0, (hf / f - 1.0) / (want - 1.0)))
    return worst


HEADLINE_SHARE = 0.12  # a headline this tall relative to the region's short side earns full marks


FAMILIES = ("preserve", "stack", "split", "row")
BANDS = ("near", "mid", "wide")


def visible_inks(out, blocks: List[Block]):
    """(block, item, output ink, source ink) for every placed, visible element."""
    vis = []
    for b in leaf_blocks(blocks):
        for it in b.items:
            p = out.get(it.idx)
            if p is not None and not p.hidden:
                vis.append((b, it, it.ink_at(p.rect, p.font), it.ink))
    return vis


def new_overlap(vis) -> float:
    """Sum of visible overlap between elements of different blocks beyond
    what those two elements already had in the source."""
    excess = 0.0
    for i, (ba, a, oa, sa) in enumerate(vis):
        for bb, b, ob, sb in vis[i + 1:]:
            if ba is bb:
                continue
            o = oa.intersection(ob) / max(1.0, min(oa.area, ob.area))
            s = sa.intersection(sb) / max(1.0, min(sa.area, sb.area))
            excess += max(0.0, o - s - 0.02)
    return excess


def _mass(blocks: List[Block]) -> float:
    return sum(b.importance for b in leaf_blocks(blocks))


def _wavg(pairs) -> float:
    tot = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / tot if tot > 0 else 1.0
