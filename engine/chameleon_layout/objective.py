"""Rank candidate layouts the way the rubric would.

Each term is in [0, 1] (higher is better):
  legibility   text stays above a readable size for this canvas
  size         elements keep their size relative to the region (hierarchy)
  fill         content spans the available area instead of floating small
  coverage     visible content area relative to the source's
  headline     the headline is big enough to lead
  hero         the product imagery keeps its share of the canvas
  balance      visual mass is centred
  wrap         texts do not break into more lines than they had
  kept         important elements stay visible
  overlap      elements do not collide (beyond what the source layered)
  faithful     blocks stay roughly where they were (same composition)
plus one-hot arrangement-family features.  `WEIGHTS` combine them into the
ranking score (fitted to AI-judge preferences by eval/fit_prefs.py).
"""

from __future__ import annotations

import math
from typing import Dict, List

from .arrange import Layout, Scope
from .blocks import SMALL_ROLES
from .geometry import bounding
from .scene import Block

# Direction fitted to AI-judge rankings of candidates (eval/fit_prefs.py), kept
# conservative where the data was thin (overlap/kept stay as safety terms).
WEIGHTS = {"legibility": 0.24, "headline": 0.14, "hero": 0.14, "coverage": 0.10, "fill": 0.08, "kept": 0.12,
           "overlap": 0.12, "faithful": 0.04, "size": 0.02, "wrap": 0.08, "is_row": 0.03, "is_stack": -0.03}


def leaf_blocks(blocks: List[Block]) -> List[Block]:
    out = []
    for b in blocks:
        out += leaf_blocks(b.children) if b.kind in ("panel", "row") else [b]
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
                extra = it.text_layout(p.font, p.w).n_lines - it.text_layout().n_lines
                wraps.append((0.5 ** max(0, extra), b.importance))
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

    total = sum(b.importance for b in scope.blocks) or 1.0
    t["kept"] = max(0.0, 1.0 - sum(b.importance * (1.5 if b.hero else 1.0) for b in lay.hidden) / total)

    vis = visible_inks(lay.out, scope.blocks)
    t["overlap"] = math.exp(-3 * new_overlap(vis))
    content = [(b, o, s_) for b, it, o, s_ in vis if b.role not in ("panel",)]
    src_cov = sum(s_.area for _, _, s_ in content) / src.area
    out_cov = sum(o.area for _, o, _ in content) / reg.area
    t["coverage"] = min(1.0, out_cov / src_cov) if src_cov > 0 else 1.0
    heads = [lay.out[it.idx].font for b, it, _, _ in vis if b.role == "headline" and lay.out[it.idx].font]
    t["headline"] = min(1.0, max(heads) * ctx.view / 28.0) if heads else 1.0
    hero = [(o.area / reg.area, s_.area / src.area) for b, it, o, s_ in vis if b.hero or b.role == "hero"]
    t["hero"] = min(1.0, math.sqrt(sum(h[0] for h in hero) / sum(h[1] for h in hero))) if hero and \
        sum(h[1] for h in hero) > 0 else (0.0 if any(b.hero for b in lay.hidden) else 1.0)
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
    for f in FAMILIES:
        t["is_" + f] = 1.0 if family == f else 0.0
    t["total"] = sum(WEIGHTS.get(k, 0.0) * v for k, v in t.items())
    return t


FAMILIES = ("preserve", "stack", "split", "row")


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


def _wavg(pairs) -> float:
    tot = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / tot if tot > 0 else 1.0
