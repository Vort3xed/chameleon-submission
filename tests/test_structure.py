"""The engine understands structure, not just roles: full-width bars on an
edge (header, footer, photo scrim) stay bars on that edge, with their content
inside, whatever the new canvas."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.resize import resize  # noqa: E402

BARS = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill": "#2a1a2e", "z_index": 0},
        {"id": "header", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 140, "fill": "#1b1020", "z_index": 1},
        {"id": "brand", "type": "text", "x": 340, "y": 45, "width": 400, "height": 50, "content": "SOLSTICE",
         "font_size": 40, "font_family": "Poppins", "color": "#ffffff", "text_align": "center", "z_index": 2},
        {"id": "product", "type": "shape", "x": 340, "y": 220, "width": 400, "height": 400, "fill": "#e8693a",
         "z_index": 2},
        {"id": "headline", "type": "text", "x": 90, "y": 680, "width": 900, "height": 110, "content": "Stay Golden",
         "font_size": 90, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 2},
        {"id": "footer", "type": "shape", "x": 0, "y": 990, "width": 1080, "height": 90, "fill": "#1b1020", "z_index": 1},
        {"id": "legal", "type": "text", "x": 40, "y": 1020, "width": 1000, "height": 30, "content": "All rights reserved.",
         "font_size": 22, "font_family": "Poppins", "color": "#ffffff", "text_align": "center", "z_index": 2},
    ],
}


@pytest.mark.parametrize("target", [(1920, 1080), (1080, 1920), (1200, 628)])
def test_edge_bars_stay_on_their_edges(target):
    W, H = target
    out = {e["id"]: e for e in resize(BARS, {"width": W, "height": H})["elements"]}
    header, footer = out["header"], out["footer"]
    assert header["x"] == 0 and header["width"] == W and header["y"] == 0
    assert footer["x"] == 0 and footer["width"] == W and footer["y"] + footer["height"] == H
    for bar, kid in ((header, out["brand"]), (footer, out["legal"])):  # the content stays inside its bar
        assert bar["y"] <= kid["y"] and kid["y"] + kid["height"] <= bar["y"] + bar["height"] + 1


WATERMARK = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill": "#2a1a2e", "z_index": 0},
        {"id": "texture", "type": "text", "x": 0, "y": 320, "width": 1080, "height": 360, "content": "SUMMER",
         "font_size": 300, "font_family": "Lora", "color": "rgba(255,255,255,0.08)", "text_align": "center", "z_index": 1},
        {"id": "headline", "type": "text", "x": 90, "y": 640, "width": 900, "height": 90, "content": "Stay Golden",
         "font_size": 72, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 2},
        {"id": "cta", "type": "text", "x": 390, "y": 860, "width": 300, "height": 40, "content": "Order Today",
         "font_size": 30, "font_family": "Poppins", "color": "#ffffff", "text_align": "center", "z_index": 2},
    ],
}


@pytest.mark.parametrize("target", [(1920, 1080), (1080, 1920), (728, 90)])
def test_faint_text_is_texture_not_the_headline(target):
    """Huge faint type behind the content is decoration: it keeps its place on
    the canvas, and the real headline stays the most prominent opaque text."""
    W, H = target
    out = {e["id"]: e for e in resize(WATERMARK, {"width": W, "height": H})["elements"]}
    tex, head = out["texture"], out["headline"]
    assert abs((tex["y"] + tex["height"] / 2) / H - 0.5) < 0.1  # centred vertically, as in the source
    assert head["font_size"] > out["cta"]["font_size"]


UNKNOWN_ART = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill": "#2a1a2e", "z_index": 0},
        {"id": "photo", "type": "image", "x": 240, "y": 120, "width": 600, "height": 600, "asset_id": "not_in_our_bundle.png",
         "fit": "contain", "z_index": 1},
        {"id": "sticker", "type": "image", "x": 900, "y": 960, "width": 120, "height": 80, "asset_id": "also_unknown.png",
         "fit": "contain", "z_index": 1},
        {"id": "headline", "type": "text", "x": 90, "y": 780, "width": 900, "height": 90, "content": "Stay Golden",
         "font_size": 72, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 2},
    ],
}


@pytest.mark.parametrize("target", [(1920, 1080), (1080, 1920)])
def test_unknown_assets_large_laid_out_small_skipped(target):
    """Only the logo is a fixed asset, so an image we cannot find may exist in
    the scorer's bundle: a large one is laid out, a small one (sticker) skipped."""
    out = {e["id"]: e for e in resize(UNKNOWN_ART, {"width": target[0], "height": target[1]})["elements"]}
    assert out["photo"].get("opacity", 1) != 0 and out["photo"]["width"] > 0.3 * min(target)
    assert out["sticker"].get("opacity") == 0


def test_group_straddling_a_card_stays_its_own_unit():
    """A rotated ribbon (shape + label sharing a group_id) laid over a card's
    corner must not pull the card and its copy into one rigid ornament
    (found by the random-design hunt: every layout then collided)."""
    from engine.chameleon_layout.scene import analyze

    els = [
        {"id": "card", "type": "shape", "x": 60, "y": 15, "width": 527, "height": 302, "shape_type": "rectangle",
         "fill_color": "rgba(245,236,220,1)", "z_index": 4},
        {"id": "headline", "type": "text", "x": 72, "y": 27, "width": 504, "height": 252, "font_family": "Solstice Serif",
         "content": "Everything You Love About Golden Hour, Now in a Bottle You Can Take Anywhere You Go This Summer",
         "font_size": 41, "color": "rgba(35,24,38,1)", "text_align": "left", "z_index": 5},
        {"id": "subhead", "type": "text", "x": 72, "y": 295, "width": 504, "height": 22, "font_family": "Solstice Sans",
         "content": "Sparkling botanicals for long summer evenings.", "font_size": 14, "color": "rgba(35,24,38,1)",
         "text_align": "left", "z_index": 6},
        {"id": "ribbon_bg", "type": "shape", "x": 23, "y": 20, "width": 151, "height": 30, "rotation": 12,
         "shape_type": "rectangle", "fill_color": "rgba(220,60,50,1)", "group_id": "ribbon", "z_index": 10},
        {"id": "ribbon_label", "type": "text", "x": 23, "y": 27, "width": 151, "height": 16, "rotation": 12,
         "content": "LAST CHANCE", "font_family": "Solstice Sans", "font_size": 11, "color": "rgba(255,255,255,1)",
         "text_align": "center", "group_id": "ribbon", "z_index": 11},
    ]
    sc = analyze(els, 1200, 628)
    card = next(b for b in sc.blocks + sc.ornaments if any(i.el["id"] == "card" for i in b.items))
    assert {i.el["id"] for i in card.items} == {"card", "headline", "subhead"} and not card.ornament
