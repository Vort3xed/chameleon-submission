"""Rank candidate layouts the way the rubric would.

Each term is in [0, 1] (higher is better):
  legibility   text stays above a readable size for this canvas
  size         elements keep their size relative to the region (hierarchy)
  fill         content uses the available area instead of floating small
  kept         important elements stay visible
  overlap      placed blocks do not collide
  faithful     blocks stay roughly where they were (same composition)
"""

from __future__ import annotations

import math
from typing import Dict, List

from .arrange import Layout, Scope
from .blocks import SMALL_ROLES
from .geometry import bounding
from .scene import Block

WEIGHTS = {"legibility": 0.26, "size": 0.2, "fill": 0.14, "kept": 0.14, "overlap": 0.16, "faithful": 0.10}


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

    leg, size = [], []
    for b in leaf_blocks(scope.blocks):
        for it in b.items:
            p = lay.out.get(it.idx)
            if p is None or p.hidden:
                continue
            if it.type == "text" and p.font:
                need = min(7.0 if b.role in SMALL_ROLES else 10.5, it.font * ctx.src_view)
                leg.append((min(1.0, p.font * ctx.view / max(need, 1e-6)) ** 2, b.importance))
                r = (p.font / lin_out) / (it.font / lin_src)
            else:
                share = it.box.area / src.area
                r = math.sqrt((p.w * p.h / reg.area) / share) if share > 0 else 1.0
            size.append((min(r, 1 / r) ** 0.5 if r > 0 else 0.0, b.importance))
    t["legibility"] = _wavg(leg)
    t["size"] = _wavg(size)

    box = bounding([r for b, r in lay.placed if not b.ornament])
    t["fill"] = min(1.0, (box.intersection(reg) / reg.area) / 0.55) if box else 0.0

    total = sum(b.importance for b in scope.blocks) or 1.0
    t["kept"] = 1.0 - sum(b.importance for b in lay.hidden) / total

    t["overlap"] = math.exp(-3 * new_overlap(lay.out, scope.blocks, items))

    dist = []
    for b, r in lay.placed:
        s = b.src
        d = math.hypot((r.cx - reg.x) / reg.w - (s.cx - src.x) / src.w, (r.cy - reg.y) / reg.h - (s.cy - src.y) / src.h)
        dist.append((max(0.0, 1 - d * 1.5), b.importance))
    t["faithful"] = _wavg(dist)

    t["total"] = sum(WEIGHTS[k] * t[k] for k in WEIGHTS)
    return t


def new_overlap(out, blocks: List[Block], items) -> float:
    """Sum of visible overlap between elements of different blocks beyond
    what those two elements already had in the source."""
    vis = []
    for b in leaf_blocks(blocks):
        for it in b.items:
            p = out.get(it.idx)
            if p is not None and not p.hidden:
                vis.append((b, it, it.ink_at(p.rect, p.font), it.ink))
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
