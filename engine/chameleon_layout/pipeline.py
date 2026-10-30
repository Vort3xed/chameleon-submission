"""retarget(): analyse the source, generate candidate layouts, keep the best."""

from __future__ import annotations

import copy
import os
import sys
from typing import Tuple

from .arrange import candidates, letterbox
from .finishing import settle_decor, snap_alignment, lift_small_text, finish
from .blocks import Ctx
from .finalize import finalize
from .objective import evaluate, rank, leaf_blocks, visible_inks, new_overlap, CLEAN
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
    # A readable caption is not a successful grid if its product shrinks to
    # the finalizer's hidden-speck threshold. Keep a composition fallback.
    products = {it.idx for b in leaf_blocks(scene.blocks) if b.kind == "rigid" and b.texts
                and b.role in ("hero", "image") for it in b.items
                if it.type == "image" and not it.missing and it.alpha > 0}
    if len(products) >= 2:
        def retained(lay):
            return all(i in lay.out and not lay.out[i].hidden and lay.out[i].opacity != 0
                       and min(lay.out[i].w, lay.out[i].h) >= 2 for i in products)
        kept = [lay for lay in layouts if retained(lay)]
        if not kept:
            fallback = finish(scene, letterbox(scene, Ctx(W, H, sW, sH)), [])
            if retained(fallback):
                kept = [fallback]
        if kept:
            layouts = kept
    scored = [(evaluate(lay, scope, scene.items), lay) for lay in layouts]
    return elements, W, H, scene, scored


def retarget(source: dict, target_canvas: dict) -> dict:
    elements, W, H, scene, scored = _candidates(source, target_canvas)
    best_terms, best = max(scored, key=lambda t: rank(t[0]))
    if os.environ.get("CHAMELEON_DEBUG"):
        for terms, lay in sorted(scored, key=lambda t: rank(t[0]), reverse=True):
            print(f"  {terms['total']:.3f} {lay.name:24s} " + " ".join(f"{k}={v:.2f}" for k, v in terms.items()
                                                                       if k != "total" and not k.startswith("is_")),
                  file=sys.stderr)
    def prepared(lay):
        # A trial must not mutate another candidate through shared placements.
        lay = copy.copy(lay)
        lay.out = {i: copy.copy(p) for i, p in lay.out.items()}
        snap_alignment(scene, lay)
        settle_decor(scene, lay)
        lift_small_text(scene, lay)
        out = finalize({"elements": elements}, W, H, lay.out, scene.hide_z)
        return lay, out

    best, output = prepared(best)
    if not all(isinstance(e, dict) and isinstance(e.get("id"), str) for e in elements):
        return output  # Preserve the engine's permissive handling of malformed input.
    originally_hidden = {e.get("id") for e in elements if isinstance(e, dict) and e.get("opacity", 1) == 0}

    def hidden(out):
        return {e["id"] for e in out["elements"] if isinstance(e, dict) and e.get("opacity", 1) == 0} - originally_hidden

    def tiny(out):
        return {e["id"] for e in out["elements"] if isinstance(e, dict) and e.get("type") == "text"
                and e.get("opacity", 1) > 0 and e.get("font_size", 0) < 7}

    missing = hidden(output)
    if missing:
        # Readability must not win by dropping copy when a clean, equally
        # readable candidate retains it. Compare finished outputs, because the
        # guarded text lift can make a previously undersized caption readable.
        allowed_tiny = tiny(output)
        blocks = scene.blocks + scene.ornaments
        overlap = new_overlap(visible_inks(best.out, blocks))
        items_by_idx = {it.idx: it for it in scene.items}
        trials = sorted(scored, key=lambda pair: (sum(p.hidden for p in pair[1].out.values()),
                                                  tuple(-float(v) for v in rank(pair[0]))))
        for terms, trial in trials:
            trial_missing = {items_by_idx[i].el.get("id") for i, p in trial.out.items() if p.hidden} - originally_hidden
            if terms["overlap"] < CLEAN or not trial_missing < missing:
                continue
            ready, out = prepared(trial)
            actual_missing = hidden(out)
            if not actual_missing < missing or not tiny(out) <= allowed_tiny:
                continue
            if new_overlap(visible_inks(ready.out, blocks)) > max(overlap, .001) + 1e-6:
                continue
            best, output, missing = ready, out, actual_missing
            if not missing:
                break
    return output


def candidate_outputs(source: dict, target_canvas: dict):
    """[(terms, layout name, finalized design)] for every candidate - used by
    the evaluation tooling to learn the objective weights."""
    elements, W, H, scene, scored = _candidates(source, target_canvas)
    for _, lay in scored:
        snap_alignment(scene, lay)
        settle_decor(scene, lay)
        lift_small_text(scene, lay)
    return [(terms, lay.name, finalize({"elements": elements}, W, H, lay.out, scene.hide_z))
            for terms, lay in scored]
