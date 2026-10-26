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
from test_structure import BARS  # noqa: E402

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


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_same_size_keeps_the_composition(path):
    """Asked for its own size, a design is kept, not rearranged: every visible element's centre
    stays within 10% of the canvas of where the designer put it."""
    s = source(path)
    target = {"width": s["canvas"]["width"], "height": s["canvas"]["height"]}
    out = {e["id"]: e for e in resize(copy.deepcopy(s), target)["elements"]}
    W, H = target["width"], target["height"]
    for e in s["elements"]:
        o = out[e["id"]]
        if o.get("opacity", 1) == 0:
            continue
        dx = abs((o["x"] + o["width"] / 2) - (e["x"] + e["width"] / 2)) / W
        dy = abs((o["y"] + o["height"] / 2) - (e["y"] + e["height"] / 2)) / H
        assert dx < 0.1 and dy < 0.1, (e["id"], dx, dy)


def test_loop_acceptance_rule():
    from eval.loop import verdict

    assert verdict(60, 20, 0.1, 0, 100)  # clear win
    assert not verdict(60, 20, -0.1, 0, 100)  # wins on count, loses on average
    assert not verdict(60, 20, 0.1, 5, 100)  # too many severe losses
    assert not verdict(12, 8, 0.1, 0, 20)  # not significant
    assert verdict(300, 200, 0.05, 4, 500)  # severe losses allowed up to 1% of a large set


def test_loop_veto_rule():
    from eval.loop import blocks

    assert not blocks(0, 0, 0, 0)  # nothing changed: neutral
    assert not blocks(9, 11, 0, 20)  # slightly worse but not significantly: neutral
    assert blocks(5, 30, 0, 35)  # significantly worse
    assert blocks(60, 20, 3, 100)  # better on count, but too many severe losses


def test_bar_floating_from_its_content_scores_lower():
    """A header bar must stay on its edge, or stay a card behind what it holds: a slab
    floating loose from its (shrunk-to-a-speck) logo is a stray box."""
    W, H = 728, 90
    out = resize(BARS, {"width": W, "height": H})
    assert evaluate(BARS, out)["bars"] == pytest.approx(1.0)
    loose = copy.deepcopy(out)
    bar, logo = element(loose, "header"), element(loose, "brand")
    bar.update(x=150, y=30, width=300, height=30)  # a slab mid-row
    logo.update(x=600, y=40, width=1, height=1)
    assert evaluate(BARS, loose)["bars"] < 1.0
    card = copy.deepcopy(loose)
    element(card, "brand").update(x=200, y=35, width=100, height=20)  # the slab holds its content again
    assert evaluate(BARS, card)["bars"] == pytest.approx(1.0)
    gone = copy.deepcopy(loose)
    element(gone, "header")["opacity"] = 0
    assert evaluate(BARS, gone)["bars"] == pytest.approx(1.0)


def test_a_full_width_bar_pulled_off_its_edge_scores_lower():
    """Still spanning the canvas but a strip of background beyond it: not a card, a header that slipped."""
    W, H = 1920, 1080
    out = resize(BARS, {"width": W, "height": H})
    slipped = copy.deepcopy(out)
    for el_id in ("header", "brand"):
        element(slipped, el_id)["y"] += 0.06 * H
    assert evaluate(BARS, out)["bars"] == pytest.approx(1.0)
    assert evaluate(BARS, slipped)["bars"] < 1.0


def test_roles_are_read_in_the_source():
    """Product art is the source's product, followed by id: a resize that merely nudges a side panel must not
    flip what reads as the product (analysed afresh, the panel and all it holds once became 'product art')."""
    task = json.loads((ROOT / "eval" / "testsets" / "crazy" / "tasks" / "crazy_sidebar__728x90.json").read_text())
    runs = [json.loads((ROOT / "tests" / "fixtures" / f"sidebar_{k}.json").read_text()) for k in ("a", "b")]
    a, b = (quality(task["source"], task["target_canvas"], d) for d in runs)
    assert abs(a - b) < 0.2
