"""
CHAMELEON resize engine - entry point.

`resize(source, target_canvas)` re-lays-out a design for a new canvas instead
of stretching it.  The work lives in `engine/chameleon_layout/`:

  scene.py      infer structure without labels: backgrounds, decor, groups,
                containers, rows, ornaments and roles (headline, CTA, logo...)
  blocks.py     measure/place each layout unit (text re-wrapped exactly like
                the renderer wraps it, images aspect-locked, groups rigid)
  families.py   the arrangement families: preserve composition, stack, split, row
  arrange.py    every candidate: families x drop levels, header/footer bands kept
  finishing.py  decoration, corner ornaments, alignment snapping
  objective.py  rank candidates on legibility, size, fill, overlap, fidelity
  finalize.py   enforce every hard rule on the chosen layout

This function never raises: if the main pipeline fails for any reason it
falls back to a letterboxed copy of the source, and failing that returns the
source elements unchanged on the target canvas.
"""

import sys
import traceback
from typing import Any

try:  # normal case: imported as engine.resize
    from .chameleon_layout.fallback import letterbox
    from .chameleon_layout.pipeline import retarget
except ImportError:  # imported as a top-level module (engine/ on sys.path)
    try:
        from chameleon_layout.fallback import letterbox  # type: ignore
        from chameleon_layout.pipeline import retarget  # type: ignore
    except Exception:  # pragma: no cover
        retarget = None
        letterbox = None


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    for strategy in (retarget, letterbox):
        if strategy is None:
            continue
        try:
            return strategy(source, target_canvas)
        except Exception:
            print(f"[resize] {getattr(strategy, '__name__', strategy)} failed:\n{traceback.format_exc()}",
                  file=sys.stderr)
    tc = target_canvas if isinstance(target_canvas, dict) else {}
    elements = source.get("elements", []) if isinstance(source, dict) else []
    return {"canvas": {"width": tc.get("width", 1080), "height": tc.get("height", 1080)}, "elements": elements}
