"""retarget(): analyse the source, generate candidate layouts, keep the best."""

from __future__ import annotations

import os
import sys
from typing import Tuple

from .arrange import candidates, settle_decor
from .blocks import Ctx
from .finalize import finalize
from .objective import evaluate
from .scene import analyze, num


def canvas_size(c, fallback: Tuple[float, float] = (1080, 1080)) -> Tuple[int, int]:
    """Integer canvas size from a possibly messy {"width", "height"} object."""
    try:
        w, h = int(round(num(c.get("width"), 0))), int(round(num(c.get("height"), 0)))
    except Exception:
        w = h = 0
    if w < 1 or h < 1:
        w, h = int(round(fallback[0])), int(round(fallback[1]))
    return max(1, w), max(1, h)


def _extent(elements) -> Tuple[float, float]:
    xs = [num(e.get("x")) + num(e.get("width")) for e in elements if isinstance(e, dict)]
    ys = [num(e.get("y")) + num(e.get("height")) for e in elements if isinstance(e, dict)]
    return (max(xs, default=1080) or 1080, max(ys, default=1080) or 1080)


def _candidates(source: dict, target_canvas: dict):
    elements = source.get("elements") or []
    work = [e if isinstance(e, dict) else {} for e in elements]
    sW, sH = canvas_size(source.get("canvas") or {}, _extent(work))
    W, H = canvas_size(target_canvas or {}, (sW, sH))
    scene = analyze(work, sW, sH)
    scope, layouts = candidates(scene, Ctx(W, H, sW, sH))
    if not layouts:
        raise RuntimeError("no candidate layout")
    scored = [(evaluate(lay, scope, scene.items), lay) for lay in layouts]
    return elements, W, H, scene, scored


def retarget(source: dict, target_canvas: dict) -> dict:
    elements, W, H, scene, scored = _candidates(source, target_canvas)
    best_terms, best = max(scored, key=lambda t: t[0]["total"])
    if os.environ.get("CHAMELEON_DEBUG"):
        for terms, lay in sorted(scored, key=lambda t: -t[0]["total"]):
            print(f"  {terms['total']:.3f} {lay.name:24s} " + " ".join(f"{k}={v:.2f}" for k, v in terms.items()
                                                                       if k != "total" and not k.startswith("is_")),
                  file=sys.stderr)
    settle_decor(scene, best)
    return finalize({"elements": elements}, W, H, best.out, scene.hide_z)


def candidate_outputs(source: dict, target_canvas: dict):
    """[(terms, layout name, finalized design)] for every candidate - used by
    the evaluation tooling to learn the objective weights."""
    elements, W, H, scene, scored = _candidates(source, target_canvas)
    for _, lay in scored:
        settle_decor(scene, lay)
    return [(terms, lay.name, finalize({"elements": elements}, W, H, lay.out, scene.hide_z))
            for terms, lay in scored]
