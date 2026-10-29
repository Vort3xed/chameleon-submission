"""Every pair of design-property values (eval/combos.py: layouts, source and
target sizes, headline texts, fonts, sizes, weights, alignment, line height,
letter spacing, max lines, style runs, colours, button shapes and strokes,
groups, body copy, products, logos, badges, backgrounds, decoration, z-order
and opacity quirks, image fit) appears in some design here; each must be laid
out by the main engine, not the fallback, and pass every hard rule."""

import json
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.chameleon_layout.pipeline import retarget  # noqa: E402
from eval.combos import build_design, covering_array  # noqa: E402
from eval.score import gate  # noqa: E402

CHUNK = 10


@lru_cache(maxsize=1)
def _rows():
    return covering_array(2, seed=0)


@pytest.mark.parametrize("chunk", range(11))
def test_every_pair_of_property_values_is_laid_out_legally(chunk):
    for row in _rows()[chunk * CHUNK:(chunk + 1) * CHUNK]:
        src, target, factors = build_design(row)
        out = retarget(src, target)
        assert gate(src, target, out) == [], factors


def test_an_image_squeezed_to_a_speck_keeps_its_proportions():
    """A logo inside an 11 px header bar on a 728x90 strip came out 1.5 x 0.1 px: rounding bent its aspect
    past the hard rule.  A speck is kept in proportion (and hidden: it could not be seen anyway)."""
    task = json.loads((ROOT / "tests" / "fixtures" / "thin_header_logo.json").read_text())
    out = retarget(task["source"], task["target_canvas"])
    assert gate(task["source"], task["target_canvas"], out) == []
