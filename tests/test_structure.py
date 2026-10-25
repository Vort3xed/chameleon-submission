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
