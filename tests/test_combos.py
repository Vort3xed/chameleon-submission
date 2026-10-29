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
from eval.score import gate, text_ink  # noqa: E402

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


def test_a_loose_button_label_stays_on_its_pill():
    """An ungrouped button whose label's box overhangs the pill (its ink does not) was read as a bare shape
    and a stray text: the label landed beside an empty pill.  It is one button, the label centred on it."""
    task = json.loads((ROOT / "tests" / "fixtures" / "loose_button.json").read_text())
    out = {e["id"]: e for e in retarget(task["source"], task["target_canvas"])["elements"]}
    pill, label = out["cta_bg"], out["cta_label"]
    assert pill["x"] <= label["x"] + label["width"] / 2 <= pill["x"] + pill["width"]
    assert pill["y"] <= label["y"] <= pill["y"] + pill["height"] / 2  # the renderer sets text from the top of its box


def test_letter_spaced_lines_stay_on_the_canvas():
    """Letter-spaced lines are drawn wider than their box (a box wide enough to hold them would re-wrap them):
    a headline centred by its box ran off a 2560 px canvas.  It is laid out and centred by its lines."""
    task = json.loads((ROOT / "tests" / "fixtures" / "tracked_headline.json").read_text())
    out = retarget(task["source"], task["target_canvas"])
    for e in out["elements"]:
        if e["type"] == "text":
            _, ink, *_ = text_ink(e)
            assert 0 <= ink[0] and ink[2] <= out["canvas"]["width"], e["id"]
