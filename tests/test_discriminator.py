"""Invariants of the discriminator (eval/design_rules.py, eval/discriminator.py):
a designer's original is perfect against itself, invisible changes do not
move the verdict, real defects do, and the brief's anti-example loses."""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.chameleon_layout.fallback import letterbox  # noqa: E402
from engine.resize import resize  # noqa: E402
from eval.design_rules import RULES, evaluate  # noqa: E402
from eval.discriminator import quality, sign_test  # noqa: E402

SAMPLES = sorted((ROOT / "input").glob("chameleon_sample_*.json"))


def source(p):
    return json.loads(p.read_text())["source"]


def element(d, el_id):
    return next(e for e in d["elements"] if e["id"] == el_id)


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_source_is_perfect_against_itself(path):
    s = source(path)
    m = evaluate(s, s)
    assert set(m) == set(RULES)
    assert all(v == pytest.approx(1.0) for v in m.values()), m


def test_invisible_change_is_a_tie():
    s = source(SAMPLES[1])
    out = resize(copy.deepcopy(s), {"width": 1080, "height": 1350})
    moved = copy.deepcopy(out)
    element(moved, "product")["x"] += 1  # the product has room on both sides; a full-width box would leave the canvas
    target = {"width": 1080, "height": 1350}
    assert abs(quality(s, target, out) - quality(s, target, moved)) < 0.02


@pytest.mark.parametrize("defect", ["collide", "shrink_headline", "button_on_edge"])
def test_defects_score_lower(defect):
    s = source(SAMPLES[1])
    target = {"width": 1080, "height": 1350}
    out = resize(copy.deepcopy(s), target)
    bad = copy.deepcopy(out)
    head, product = element(bad, "headline"), element(bad, "product")
    if defect == "collide":
        head["x"] = product["x"] + (product["width"] - head["width"]) / 2
        head["y"] = product["y"] + (product["height"] - head["height"]) / 2
    elif defect == "shrink_headline":
        head["font_size"] = max(1, int(head["font_size"] * 0.5))
    else:  # the button group pushed flush against the left edge
        bg, label = element(bad, "cta_bg"), element(bad, "cta_label")
        dx = -bg["x"]
        bg["x"], label["x"] = 0, label["x"] + dx
    assert quality(s, target, bad) < quality(s, target, out)


def test_naive_shrink_loses_when_the_shape_changes():
    s = source(SAMPLES[1])
    target = {"width": 728, "height": 90}
    assert quality(s, target, resize(copy.deepcopy(s), target)) > quality(s, target, letterbox(copy.deepcopy(s), target))


def test_sign_test():
    assert sign_test(0, 0) == 1.0
    assert sign_test(10, 10) == pytest.approx(1.0)
    assert sign_test(30, 5) < 0.001
    assert sign_test(5, 30) == pytest.approx(sign_test(30, 5))
