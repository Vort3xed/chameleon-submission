"""The engine understands structure, not just roles: bars on an edge (header,
footer, photo scrim, a colour panel bleeding off one side) stay bars on that
edge, with their content inside, whatever the new canvas."""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.resize import resize  # noqa: E402

BARS = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "#2a1a2e", "z_index": 0},
        {"id": "header", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 140, "fill_color": "#1b1020", "z_index": 1},
        {"id": "brand", "type": "text", "x": 340, "y": 45, "width": 400, "height": 50, "content": "SOLSTICE",
         "font_size": 40, "font_family": "Poppins", "color": "#ffffff", "text_align": "center", "z_index": 2},
        {"id": "product", "type": "shape", "x": 340, "y": 220, "width": 400, "height": 400, "fill_color": "#e8693a",
         "z_index": 2},
        {"id": "headline", "type": "text", "x": 90, "y": 680, "width": 900, "height": 110, "content": "Stay Golden",
         "font_size": 90, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 2},
        {"id": "footer", "type": "shape", "x": 0, "y": 990, "width": 1080, "height": 90, "fill_color": "#1b1020", "z_index": 1},
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


@pytest.mark.parametrize("target", [(728, 90), (600, 200), (970, 90)])
def test_thin_bars_stay_on_their_edges(target):
    """A bar too thin to hold its content on a strip stays a stripe on its edge
    (its content flows with the rest) - it never floats as a box."""
    W, H = target
    out = {e["id"]: e for e in resize(BARS, {"width": W, "height": H})["elements"]}
    header, footer = out["header"], out["footer"]
    assert header["x"] == 0 and header["width"] == W and header["y"] == 0
    assert footer["x"] == 0 and footer["width"] == W and footer["y"] + footer["height"] == H


def _light_footer():
    d = copy.deepcopy(BARS)
    for e in d["elements"]:
        if e["id"] == "footer":
            e["fill_color"] = "#f5ebdc"  # cream, on a dark canvas
        if e["id"] == "legal":
            e["color"] = "#1b1020"  # dark small print, legible only on the footer
    return d


@pytest.mark.parametrize("target", [(728, 90), (600, 200), (970, 90)])
def test_content_never_loses_the_bar_it_needs(target):
    """Dark small print on a cream footer cannot be lifted onto a dark canvas: on a strip the
    footer keeps holding it (or it is hidden), whatever happens to the bar."""
    W, H = target
    out = {e["id"]: e for e in resize(_light_footer(), {"width": W, "height": H})["elements"]}
    legal, footer = out["legal"], out["footer"]
    if legal.get("opacity", 1) > 0 and footer.get("opacity", 1) > 0:
        assert footer["x"] <= legal["x"] + 1 and legal["x"] + legal["width"] <= footer["x"] + footer["width"] + 1
        assert footer["y"] <= legal["y"] + 1 and legal["y"] + legal["height"] <= footer["y"] + footer["height"] + 1


PHOTO = {  # from the wild random set (random_066): copy centred on a translucent scrim over a full-bleed photo
    "canvas": {"width": 1200, "height": 628},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1200, "height": 628, "fill_color": "rgba(30,18,34,1)",
         "z_index": 0},
        {"id": "photo", "type": "image", "x": 0, "y": 0, "width": 1200, "height": 628, "asset_id": "solstice_bottle.png",
         "fit": "cover", "z_index": 1},
        {"id": "scrim", "type": "shape", "x": 0, "y": 427, "width": 1200, "height": 201,
         "fill_color": "rgba(35,24,38,0.6)", "z_index": 2},
        {"id": "headline", "type": "text", "x": 72, "y": 444.5, "width": 1056, "height": 59, "content": "Hello Summer",
         "font_size": 44, "font_family": "Solstice Serif", "font_weight": "bold", "color": "rgba(255,255,255,1)",
         "text_align": "center", "z_index": 3},
        {"id": "cta_bg", "type": "shape", "x": 502.5, "y": 564, "width": 195, "height": 36,
         "fill_color": "rgba(232,106,58,1)", "corner_radius": 18, "group_id": "cta", "z_index": 4},
        {"id": "cta_label", "type": "text", "x": 502.5, "y": 571.6, "width": 195, "height": 21,
         "content": "Reserve Your Spot", "font_size": 15, "font_family": "Solstice Sans", "font_weight": "bold",
         "color": "rgba(255,255,255,1)", "text_align": "center", "group_id": "cta", "z_index": 5},
    ],
}


@pytest.mark.parametrize("target", [(336, 280), (300, 250), (1080, 1080)])
def test_photo_scrim_stays_at_the_bottom(target):
    """Copy on a translucent scrim over a full-bleed photo: the scrim keeps its edge with the copy on it,
    rather than floating as a card over the product (whose label would show through)."""
    W, H = target
    out = {e["id"]: e for e in resize(PHOTO, {"width": W, "height": H})["elements"]}
    scrim, head = out["scrim"], out["headline"]
    assert scrim["x"] == 0 and scrim["width"] == W and scrim["y"] + scrim["height"] == H
    assert scrim["y"] <= head["y"] and head["y"] + head["height"] <= H + 1


def _offer(i, x, name, price):
    g, f = f"offer{i}", {"font_family": "Solstice Sans", "color": "#ffffff", "text_align": "center"}
    return [
        {"id": f"product{i}", "type": "image", "x": x + 32, "y": 405, "width": 324, "height": 324,
         "asset_id": "solstice_bottle.png", "fit": "contain", "group_id": g, "z_index": 3},
        {"id": f"name{i}", "type": "text", "x": x, "y": 739, "width": 389, "height": 43, "content": name,
         "font_size": 32, **f, "font_family": "Solstice Serif", "group_id": g, "z_index": 4},
        {"id": f"price{i}", "type": "text", "x": x, "y": 785, "width": 389, "height": 39, "content": price,
         "font_size": 26, **f, "group_id": g, "z_index": 4},
        {"id": f"cta_bg{i}", "type": "shape", "x": x + 94, "y": 829, "width": 201, "height": 53,
         "fill_color": "#e8693a", "corner_radius": 26, "group_id": g, "z_index": 5},
        {"id": f"cta_label{i}", "type": "text", "x": x + 94, "y": 840, "width": 201, "height": 31,
         "content": "Add to Cart", "font_size": 22, **f, "group_id": g, "z_index": 6},
    ]


DUO = {  # from the wild random set (random_045): two grouped offers under a headline
    "canvas": {"width": 1080, "height": 1350},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1350, "fill_color": "#2a1a2e",
         "z_index": 0},
        {"id": "logo", "type": "image", "x": 440, "y": 40, "width": 200, "height": 62.5,
         "asset_id": "solstice_logo_lockup.png", "fit": "contain", "z_index": 1},
        {"id": "headline", "type": "text", "x": 86, "y": 162, "width": 907, "height": 84, "content": "Golden Hour",
         "font_size": 64, "font_family": "Solstice Serif", "font_weight": "bold", "color": "#ffffff",
         "text_align": "center", "z_index": 2},
    ] + _offer(0, 108, "Hibiscus", "2 for $8") + _offer(1, 583, "Blood Orange", "$12.50"),
}


@pytest.mark.parametrize("target", [(300, 600), (160, 600), (300, 250), (1080, 1920)])
def test_groups_never_outgrow_the_headline(target):
    """Groups keep their small labels legible by scaling up as one picture; that must not make
    their names (half the headline's size in the source) bigger than the headline."""
    W, H = target
    out = resize(DUO, {"width": W, "height": H})["elements"]
    fonts = {e["id"]: e["font_size"] for e in out if e["type"] == "text" and e.get("opacity", 1) > 0}
    assert fonts["headline"] >= max(v for k, v in fonts.items() if k != "headline")


MENU = {
    "canvas": {"width": 1920, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1920, "height": 1080, "fill_color": "#2a1a2e",
         "z_index": 0},
        {"id": "headline", "type": "text", "x": 460, "y": 60, "width": 1000, "height": 110, "content": "Tasting Menu",
         "font_size": 90, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 1},
    ] + [e for i, (name, price) in enumerate([("Blood Orange Spritz", "$4.99"), ("Wild Honey Tonic", "2 for $8"),
                                               ("Yuzu Mint Fizz", "From $24"), ("Hibiscus Spritz", "$12.50"),
                                               ("Pink Grapefruit Tonic", "$3.49"), ("Elderflower Fizz", "$4.99")])
         for e in ({"id": f"item{i}", "type": "text", "x": 200, "y": 260 + 110 * i, "width": 900, "height": 50,
                    "content": name, "font_size": 40, "font_family": "Poppins", "color": "#ffffff",
                    "text_align": "left", "z_index": 2},
                   {"id": f"price{i}", "type": "text", "x": 1420, "y": 260 + 110 * i, "width": 300, "height": 50,
                    "content": price, "font_size": 40, "font_family": "Poppins", "color": "#f0b242",
                    "text_align": "right", "z_index": 2})],
}


@pytest.mark.parametrize("target", [(1080, 1080), (300, 250), (160, 600), (1080, 1920)])
def test_a_table_keeps_its_rows(target):
    """A price list keeps each price with its item - on the item's row, or under it before the next
    item - and on a roomy canvas its items keep one left edge (a column) or one centre line (folded)."""
    W, H = target
    out = {e["id"]: e for e in resize(MENU, {"width": W, "height": H})["elements"] if e.get("opacity", 1) > 0}
    items = [k for k in out if k.startswith("item")]
    for i in range(6):
        if f"price{i}" in out and f"item{i}" in out:
            p, nxt = out[f"price{i}"], out.get(f"item{i + 1}", {"y": H})
            assert out[f"item{i}"]["y"] - 1 <= p["y"] + p["height"] / 2 <= nxt["y"] + 1
    if W >= 1000:
        spread = lambda f: max(map(f, items)) - min(map(f, items))  # noqa: E731
        assert min(spread(lambda k: out[k]["x"]), spread(lambda k: out[k]["x"] + out[k]["width"] / 2)) <= 1


SHADOWED = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "#2a1a2e",
         "z_index": 0},
        {"id": "shadow", "type": "text", "x": 96, "y": 306, "width": 900, "height": 110, "content": "Stay Golden",
         "font_size": 90, "font_family": "Lora", "color": "#000000", "text_align": "center", "z_index": 1},
        {"id": "headline", "type": "text", "x": 90, "y": 300, "width": 900, "height": 110, "content": "Stay Golden",
         "font_size": 90, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 2},
        {"id": "sub", "type": "text", "x": 140, "y": 520, "width": 800, "height": 40, "content": "Naturally bright.",
         "font_size": 32, "font_family": "Poppins", "color": "#ffffff", "text_align": "center", "z_index": 2},
        {"id": "parked", "type": "text", "x": 1400, "y": 200, "width": 400, "height": 60, "content": "Draft copy",
         "font_size": 40, "font_family": "Poppins", "color": "#ffffff", "z_index": 2},
    ],
}


@pytest.mark.parametrize("target", [(1920, 1080), (1080, 1920), (728, 90), (300, 250)])
def test_a_drop_shadow_stays_with_its_text_and_off_canvas_copy_stays_unseen(target):
    """A text stacked on a copy of itself (a drop shadow) is one piece of type: the copy keeps its
    offset, scaled, and the size; and copy parked off the source canvas was never seen, so it stays hidden."""
    W, H = target
    out = {e["id"]: e for e in resize(SHADOWED, {"width": W, "height": H})["elements"]}
    head, shadow = out["headline"], out["shadow"]
    s = head["font_size"] / 90
    assert shadow["font_size"] == head["font_size"]
    assert abs(shadow["x"] - head["x"] - 6 * s) <= 1.5 and abs(shadow["y"] - head["y"] - 6 * s) <= 1.5
    assert out["parked"].get("opacity") == 0 and out["parked"]["z_index"] < out["bg"]["z_index"]


CARD_SHADOW = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "rgba(42,26,46,1)",
         "z_index": 0},
        {"id": "shadow", "type": "shape", "x": 190, "y": 330, "width": 720, "height": 460,
         "fill_color": "rgba(0,0,0,0.35)", "corner_radius": 24, "z_index": 1},
        {"id": "card", "type": "shape", "x": 180, "y": 320, "width": 720, "height": 460,
         "fill_color": "rgba(245,235,220,1)", "corner_radius": 24, "z_index": 2},
        {"id": "headline", "type": "text", "x": 230, "y": 380, "width": 620, "height": 90, "content": "Golden Hour",
         "font_size": 72, "font_family": "Lora", "color": "rgba(35,24,38,1)", "text_align": "center", "z_index": 3},
        {"id": "sub", "type": "text", "x": 230, "y": 500, "width": 620, "height": 40, "content": "Small-batch.",
         "font_size": 30, "font_family": "Poppins", "color": "rgba(35,24,38,1)", "text_align": "center", "z_index": 3},
    ],
}


@pytest.mark.parametrize("target", [(1920, 1080), (1080, 1920), (728, 90), (300, 250)])
def test_a_card_keeps_its_shadow(target):
    """A translucent copy of a card just behind it is its shadow, not the card: the copy stays the
    card's size and keeps its small offset, and the copy is what holds the text."""
    W, H = target
    out = {e["id"]: e for e in resize(CARD_SHADOW, {"width": W, "height": H})["elements"]}
    card, shadow, head = out["card"], out["shadow"], out["headline"]
    k = min(card["width"] / 720, card["height"] / 460)  # an offset is a distance: it scales uniformly
    assert abs(shadow["width"] - card["width"]) <= 1 and abs(shadow["height"] - card["height"]) <= 1
    assert abs(shadow["x"] - card["x"] - 10 * k) <= 1.5 and abs(shadow["y"] - card["y"] - 10 * k) <= 1.5
    assert card["x"] <= head["x"] and head["x"] + head["width"] <= card["x"] + card["width"] + 1


def _bare(*shapes):
    els = [{"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "rgba(42,26,46,1)",
            "z_index": 0}]
    els += [{"id": k, "type": "shape", "x": x, "y": y, "width": w, "height": h, "fill_color": "rgba(232,106,58,1)",
             "z_index": 1} for k, x, y, w, h in shapes]
    els.append({"id": "headline", "type": "text", "x": 600, "y": 400, "width": 420, "height": 200, "content": "Golden Hour",
                "font_size": 72, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 2})
    return {"canvas": {"width": 1080, "height": 1080}, "elements": els}


@pytest.mark.parametrize("target", [(1920, 1080), (1080, 1920), (728, 90), (320, 50)])
def test_bare_edge_bars_keep_their_edges(target):
    """A two-tone background (a bare half-canvas panel) and a bare colour strip hold nothing, yet they
    are part of the composition: they stay on their edges at full length, never floating as boxes."""
    W, H = target
    out = {e["id"]: e for e in resize(_bare(("half", 0, 0, 540, 1080), ("strip", 0, 1000, 1080, 80)),
                                      {"width": W, "height": H})["elements"]}
    half, strip = out["half"], out["strip"]
    assert half["x"] == 0 and half["y"] == 0 and half["height"] == H
    assert strip["x"] == 0 and strip["width"] == W and strip["y"] + strip["height"] == H


BUTTON_SHADOW = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "rgba(42,26,46,1)",
         "z_index": 0},
        {"id": "headline", "type": "text", "x": 90, "y": 300, "width": 900, "height": 110, "content": "Golden Hour",
         "font_size": 90, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 2},
        {"id": "cta_shadow", "type": "shape", "x": 398, "y": 608, "width": 300, "height": 70,
         "fill_color": "rgba(0,0,0,0.6)", "corner_radius": 35, "z_index": 2},
        {"id": "cta_bg", "type": "shape", "x": 390, "y": 600, "width": 300, "height": 70,
         "fill_color": "rgba(232,106,58,1)", "corner_radius": 35, "group_id": "cta", "z_index": 3},
        {"id": "cta_label", "type": "text", "x": 390, "y": 615, "width": 300, "height": 40, "content": "Shop Now",
         "font_size": 28, "font_family": "Poppins", "color": "#ffffff", "text_align": "center", "group_id": "cta",
         "z_index": 4},
    ],
}


@pytest.mark.parametrize("target", [(1920, 1080), (1080, 1920), (728, 90), (300, 250)])
def test_a_button_keeps_its_shadow_whatever_its_opacity(target):
    """A shape just beneath a button, of nearly its box, is the button's shadow even when fairly opaque."""
    W, H = target
    out = {e["id"]: e for e in resize(BUTTON_SHADOW, {"width": W, "height": H})["elements"]}
    btn, shadow = out["cta_bg"], out["cta_shadow"]
    k = min(btn["width"] / 300, btn["height"] / 70)
    assert abs(shadow["width"] - btn["width"]) <= 1 and abs(shadow["height"] - btn["height"]) <= 1
    assert abs(shadow["x"] - btn["x"] - 8 * k) <= 1.5 and abs(shadow["y"] - btn["y"] - 8 * k) <= 1.5


def _long_headline(shadow: bool) -> dict:
    copy_ = {"content": "The Botanical Sparkling Collection Crafted for Golden Hour", "font_size": 64, "width": 900,
             "height": 220, "font_family": "Lora", "text_align": "center", "type": "text"}
    els = [{"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "rgba(42,26,46,1)",
            "z_index": 0}]
    if shadow:
        els.append({**copy_, "id": "shadow", "x": 96, "y": 306, "color": "#000000", "z_index": 1})
    els.append({**copy_, "id": "headline", "x": 90, "y": 300, "color": "#ffffff", "z_index": 2})
    return {"canvas": {"width": 1080, "height": 1080}, "elements": els}


@pytest.mark.parametrize("target", [(160, 600), (728, 90), (1920, 1080)])
def test_a_shadowed_headline_rewraps_like_a_plain_one(target):
    """The shadow follows its text; it must not freeze the text's wrap (as a rigid group would)."""
    W, H = target
    plain = {e["id"]: e for e in resize(_long_headline(False), {"width": W, "height": H})["elements"]}
    shadowed = {e["id"]: e for e in resize(_long_headline(True), {"width": W, "height": H})["elements"]}
    head, shadow = shadowed["headline"], shadowed["shadow"]
    assert head["font_size"] == plain["headline"]["font_size"] and head["width"] == plain["headline"]["width"]
    k = head["font_size"] / 64
    assert shadow["font_size"] == head["font_size"] and abs(shadow["x"] - head["x"] - 6 * k) <= 1.5


ICON_LIST = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "rgba(42,26,46,1)",
         "z_index": 0},
        {"id": "headline", "type": "text", "x": 90, "y": 120, "width": 900, "height": 110, "content": "Why Solstice",
         "font_size": 90, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 1},
    ] + [e for i, lab in enumerate(["Zero sugar", "Real fruit", "Small batch", "Vegan"]) for e in (
        {"id": f"icon{i}", "type": "shape", "shape_type": "ellipse", "x": 280, "y": 340 + 130 * i, "width": 60,
         "height": 60, "fill_color": "rgba(232,106,58,1)", "z_index": 1},
        {"id": f"label{i}", "type": "text", "x": 370, "y": 348 + 130 * i, "width": 450, "height": 44, "content": lab,
         "font_size": 36, "font_family": "Poppins", "color": "#ffffff", "text_align": "left", "z_index": 1})],
}


@pytest.mark.parametrize("target", [(1920, 1080), (1080, 1920), (300, 600), (728, 90)])
def test_icons_stay_beside_their_labels(target):
    """A small icon just left of a one-line label travels with it: centred on it, just before it; and
    stacked, the list keeps one left edge (it is centred as a whole, not item by item)."""
    W, H = target
    out = {e["id"]: e for e in resize(ICON_LIST, {"width": W, "height": H})["elements"]}
    xs = [out[f"icon{i}"]["x"] for i in range(4)]
    if H > W:
        assert max(xs) - min(xs) <= 4
    for i in range(4):
        icon, label = out[f"icon{i}"], out[f"label{i}"]
        assert abs((icon["y"] + icon["height"] / 2) - (label["y"] + label["height"] / 2)) <= 2
        assert 0 <= label["x"] - (icon["x"] + icon["width"]) <= 2 * icon["width"]


BULLETS = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "rgba(42,26,46,1)",
         "z_index": 0},
        {"id": "headline", "type": "text", "x": 90, "y": 100, "width": 900, "height": 110, "content": "Why Solstice",
         "font_size": 90, "font_family": "Lora", "color": "#ffffff", "text_align": "center", "z_index": 1},
    ] + [{"id": f"item{i}", "type": "text", "x": 300, "y": 300 + 90 * i, "width": 600, "height": 50, "content": f"• {t}",
          "font_size": 40, "font_family": "Poppins", "color": "#ffffff", "text_align": "left", "z_index": 1}
         for i, t in enumerate(["Real fruit", "No added sugar", "Small batches", "Recyclable cans"])],
}


@pytest.mark.parametrize("target", [(1080, 1920), (1920, 1080), (300, 600)])
def test_a_bullet_list_keeps_one_left_edge(target):
    """Bulleted lines stacked under a centred heading keep their shared left edge (centred as a list)."""
    W, H = target
    out = {e["id"]: e for e in resize(BULLETS, {"width": W, "height": H})["elements"]}
    xs = [out[f"item{i}"]["x"] for i in range(4)]
    assert max(xs) - min(xs) <= 4


SIDE_PANEL = {
    "canvas": {"width": 1080, "height": 1920},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1920, "fill_color": "#2a1a2e", "z_index": 0},
        {"id": "panel", "type": "shape", "x": 0, "y": 0, "width": 540, "height": 1920, "fill_color": "#e8693a", "z_index": 1},
        {"id": "product", "type": "shape", "x": 120, "y": 760, "width": 300, "height": 400, "fill_color": "#f4c542",
         "z_index": 2},
        {"id": "headline", "type": "text", "x": 605, "y": 480, "width": 410, "height": 181, "content": "Golden Hour",
         "font_size": 72, "font_family": "Lora", "color": "#ffffff", "text_align": "left", "z_index": 3},
        {"id": "subhead", "type": "text", "x": 605, "y": 960, "width": 410, "height": 36, "font_size": 24,
         "content": "Naturally bright, never too sweet.", "font_family": "Poppins", "color": "#ffffff", "z_index": 3},
        {"id": "cta_bg", "type": "shape", "x": 595, "y": 1305, "width": 220, "height": 58, "fill_color": "#e8693a",
         "corner_radius": 29, "group_id": "cta", "z_index": 4},
        {"id": "cta_label", "type": "text", "x": 595, "y": 1318, "width": 220, "height": 34, "content": "Get 20% Off",
         "font_size": 24, "font_family": "Poppins", "color": "#ffffff", "text_align": "center", "group_id": "cta",
         "z_index": 5},
    ],
}


@pytest.mark.parametrize("target", [(1200, 480), (1920, 1080), (1080, 1080)])
def test_side_panel_stays_a_full_height_bar(target):
    """A colour panel bleeding off one side stays on that side at full height,
    holding the product; the copy sits beside it in its source reading order."""
    W, H = target
    out = {e["id"]: e for e in resize(SIDE_PANEL, {"width": W, "height": H})["elements"]}
    panel, product = out["panel"], out["product"]
    assert panel["x"] == 0 and panel["y"] == 0 and panel["height"] == H and panel["width"] < W
    assert panel["x"] <= product["x"] and product["x"] + product["width"] <= panel["x"] + panel["width"] + 1
    assert all(out[k]["x"] >= panel["width"] for k in ("headline", "subhead", "cta_bg"))
    assert out["headline"]["y"] < out["subhead"]["y"] < out["cta_bg"]["y"]


WATERMARK = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "#2a1a2e", "z_index": 0},
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
    """Huge faint type behind the content is decoration: it stays drawn on the
    canvas (moved off copy it did not cover, as decoration is), and the real
    headline stays the most prominent opaque text."""
    W, H = target
    out = {e["id"]: e for e in resize(WATERMARK, {"width": W, "height": H})["elements"]}
    tex, head = out["texture"], out["headline"]
    assert tex.get("opacity", 1) > 0 and 0 <= tex["y"] and tex["y"] + tex["height"] <= H + 1
    assert head["font_size"] > out["cta"]["font_size"]


UNKNOWN_ART = {
    "canvas": {"width": 1080, "height": 1080},
    "elements": [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "fill_color": "#2a1a2e", "z_index": 0},
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


def test_a_card_holding_only_the_headline_is_not_a_badge():
    """A card with the headline alone in it (its button hanging off the edge)
    was read as a badge: the headline could be dropped and the legal line
    became the headline (found by the random-design hunt)."""
    els = [
        {"id": "bg", "type": "shape", "x": 0, "y": 0, "width": 1080, "height": 1080, "shape_type": "rectangle",
         "fill_color": "rgba(43,27,46,1)", "z_index": 0},
        {"id": "card", "type": "shape", "x": 40, "y": 186, "width": 1000, "height": 520, "shape_type": "rectangle",
         "fill_color": "rgba(245,236,220,1)", "z_index": 2},
        {"id": "headline", "type": "text", "x": 60, "y": 206, "width": 960, "height": 129, "content": "Stay Golden",
         "font_family": "Solstice Serif", "font_size": 96, "color": "rgba(35,24,38,1)", "z_index": 3},
        {"id": "cta_bg", "type": "shape", "x": -51, "y": 362, "width": 440, "height": 70, "shape_type": "rectangle",
         "fill_color": "rgba(232,106,58,1)", "group_id": "cta", "z_index": 4},
        {"id": "cta_label", "type": "text", "x": -51, "y": 376, "width": 440, "height": 41, "content": "Discover the Collection",
         "font_family": "Solstice Sans", "font_size": 28, "color": "rgba(255,255,255,1)", "group_id": "cta", "z_index": 5},
        {"id": "legal", "type": "text", "x": 60, "y": 1030, "width": 960, "height": 22, "font_family": "Solstice Sans",
         "content": "Please drink responsibly. Botanical Sparkling Co., 2026.", "font_size": 15,
         "color": "rgba(35,24,38,0.7)", "z_index": 6},
    ]
    src = {"canvas": {"width": 1080, "height": 1080}, "elements": els}
    for W, H in ((728, 90), (320, 50), (1080, 1920)):
        out = {e["id"]: e for e in resize(src, {"width": W, "height": H})["elements"]}
        assert out["headline"].get("opacity", 1) != 0 and out["card"].get("opacity", 1) != 0


def test_text_hides_beneath_its_card_when_there_is_no_background():
    """The renderer ignores opacity on text, so a dropped text must be covered:
    with no opaque background, it goes beneath its own opaque card."""
    els = [
        {"id": "card", "type": "shape", "x": 60, "y": 100, "width": 960, "height": 700, "shape_type": "rectangle",
         "fill_color": "rgba(245,236,220,1)", "z_index": 5},
        {"id": "headline", "type": "text", "x": 100, "y": 150, "width": 880, "height": 110, "content": "New Season",
         "font_family": "Solstice Serif", "font_size": 90, "color": "rgba(35,24,38,1)", "z_index": 6},
        {"id": "body", "type": "text", "x": 100, "y": 300, "width": 880, "height": 200, "font_family": "Solstice Sans",
         "content": "Each bottle is brewed in small batches using hand-picked botanicals and real fruit. " * 3,
         "font_size": 24, "color": "rgba(35,24,38,1)", "z_index": 7},
        {"id": "cta_bg", "type": "shape", "x": 380, "y": 600, "width": 320, "height": 70, "shape_type": "rectangle",
         "fill_color": "rgba(232,106,58,1)", "group_id": "cta", "z_index": 8},
        {"id": "cta_label", "type": "text", "x": 380, "y": 614, "width": 320, "height": 41, "content": "Buy Tickets",
         "font_family": "Solstice Sans", "font_size": 28, "color": "rgba(255,255,255,1)", "group_id": "cta", "z_index": 9},
    ]
    out = {e["id"]: e for e in resize({"canvas": {"width": 1080, "height": 1080}, "elements": els},
                                      {"width": 320, "height": 50})["elements"]}
    body, card = out["body"], out["card"]
    if body.get("opacity") == 0:  # dropped: it must be fully covered by the card
        assert body["z_index"] < card["z_index"]
        assert card["x"] <= body["x"] and body["x"] + body["width"] <= card["x"] + card["width"]
        assert card["y"] <= body["y"] and body["y"] + body["height"] <= card["y"] + card["height"]
    assert out["headline"].get("opacity", 1) != 0


def test_text_hides_beneath_a_button_without_background_or_card():
    """No opaque background, no card: a dropped text goes beneath the button."""
    els = [
        {"id": "headline", "type": "text", "x": 60, "y": 200, "width": 960, "height": 120, "content": "Stay Golden",
         "font_family": "Solstice Serif", "font_size": 96, "color": "rgba(35,24,38,1)", "z_index": 2},
        {"id": "legal", "type": "text", "x": 60, "y": 1000, "width": 960, "height": 40, "font_family": "Solstice Sans",
         "content": "Please drink responsibly. Botanical Sparkling Co., 2026. Void where prohibited. " * 2,
         "font_size": 14, "color": "rgba(35,24,38,1)", "z_index": 3},
        {"id": "cta_bg", "type": "shape", "x": 380, "y": 700, "width": 320, "height": 70, "shape_type": "rectangle",
         "fill_color": "rgba(232,106,58,1)", "group_id": "cta", "z_index": 4},
        {"id": "cta_label", "type": "text", "x": 380, "y": 714, "width": 320, "height": 41, "content": "Shop Now",
         "font_family": "Solstice Sans", "font_size": 28, "color": "rgba(255,255,255,1)", "group_id": "cta", "z_index": 5},
    ]
    out = {e["id"]: e for e in resize({"canvas": {"width": 1080, "height": 1080}, "elements": els},
                                      {"width": 320, "height": 50})["elements"]}
    legal, button = out["legal"], out["cta_bg"]
    assert legal.get("opacity") == 0, "the legal line should be dropped at 320x50"
    assert legal["z_index"] < button["z_index"]
    assert button["x"] <= legal["x"] and legal["x"] + legal["width"] <= button["x"] + button["width"]
    assert button["y"] <= legal["y"] and legal["y"] + legal["height"] <= button["y"] + button["height"]


CORE = json.loads((ROOT / "input" / "chameleon_sample_level2_core.json").read_text())


@pytest.mark.parametrize("target", [(1200, 480), (820, 312), (1500, 500)])
def test_the_logo_keeps_heading_the_copy_beside_product_art(target):
    """In a banner the logo that sat above the headline stays above it - set apart beside the product, as a
    column of its own, it reads as a stray (people's notes on these banners)."""
    W, H = target
    out = {e["id"]: e for e in resize(CORE.get("source", CORE), {"width": W, "height": H})["elements"]}
    logo, head = out["logo"], out["headline"]
    assert logo["y"] + logo["height"] <= head["y"] + 1
    assert head["x"] <= logo["x"] + logo["width"] / 2 <= head["x"] + head["width"]


WARMUP = json.loads((ROOT / "input" / "chameleon_sample_level1_warmup.json").read_text())


@pytest.mark.parametrize("target", [(1080, 1920), (1170, 2532), (1000, 2100)])
def test_a_centred_headline_stays_near_the_middle_of_a_tall_canvas(target):
    """The warm-up sample: logo at the top, headline and button at the middle. On a tall canvas the slack
    is shared as the source spaced it, so the headline does not sink toward the bottom."""
    W, H = target
    out = {e["id"]: e for e in resize(WARMUP.get("source", WARMUP), {"width": W, "height": H})["elements"]}
    head = out["headline"]
    assert 0.40 * H <= head["y"] + head["height"] / 2 <= 0.65 * H


def test_a_narrowed_row_column_keeps_its_line_breaks():
    """Banner-row copy columns narrow to their lines, but spaced type wraps narrower than it measures:
    the date of this event flyer must keep its two lines in a 970x250 billboard."""
    task = json.loads((ROOT / "tests" / "fixtures" / "event_flyer_billboard.json").read_text())
    out = {e["id"]: e for e in resize(task["source"], task["target_canvas"])["elements"]}
    date = out["date_line"]
    assert date["height"] <= 2.6 * date["font_size"]


def _units(name):
    return json.loads((ROOT / "tests" / "fixtures" / f"{name}.json").read_text())


@pytest.mark.parametrize("name,top", [("stats_row", "stat"), ("steps_row", "step_dot")])
@pytest.mark.parametrize("target", [(1080, 1920), (1920, 1080), (300, 250), (320, 100), (1080, 1080)])
def test_each_column_keeps_its_caption(name, top, target):
    """A stat over its label, a numbered step over what it says: each column is one unit whatever the
    canvas - the number stays just above its own caption, centred on it (they were split into a list of
    numbers and a list of captions)."""
    W, H = target
    out = {e["id"]: e for e in resize(_units(name), {"width": W, "height": H})["elements"]}
    for k, suffix in enumerate(("", "_2", "_3", "_4")):
        t, c = out.get(top + suffix), out.get("caption" + suffix)
        if t is None or c is None or t.get("opacity", 1) == 0 or c.get("opacity", 1) == 0:
            continue
        assert t["y"] + t["height"] <= c["y"] + 1 and c["y"] - (t["y"] + t["height"]) <= max(t["height"], c["height"])
        assert abs((t["x"] + t["width"] / 2) - (c["x"] + c["width"] / 2)) <= 0.3 * max(t["width"], c["width"])


@pytest.mark.parametrize("target", [(1080, 1920), (1920, 1080), (1080, 1080), (300, 600)])
def test_a_was_and_now_price_stay_side_by_side(target):
    """$29.99 $19.99: split, the old price could end up larger than the new one, far from it."""
    src = json.loads((ROOT / "tests" / "fixtures" / "was_now.json").read_text())
    out = {e["id"]: e for e in resize(src, {"width": target[0], "height": target[1]})["elements"]}
    was, now = out["price_was"], out["price_now"]
    if was.get("opacity", 1) == 0 or now.get("opacity", 1) == 0:
        assert was.get("opacity", 1) == now.get("opacity", 1) == 0  # together or not at all
        return
    assert now["font_size"] > was["font_size"]
    assert min(was["y"] + was["height"], now["y"] + now["height"]) > max(was["y"], now["y"])  # one line
    assert was["x"] < now["x"]


@pytest.mark.parametrize("target", [(3508, 2480), (1080, 1080), (1920, 1080)])
def test_a_bullet_list_is_never_split_across_columns(target):
    """A pricing card's three bullet points keep one left edge: a row of columns never cuts inside a list."""
    src = json.loads((ROOT / "tests" / "fixtures" / "pricing_cards.json").read_text())
    out = {e["id"]: e for e in resize(src, {"width": target[0], "height": target[1]})["elements"]}
    for card in (("point", "point_2", "point_3"), ("point_4", "point_5", "point_6")):
        shown = [out[k] for k in card if out[k].get("opacity", 1) > 0]
        assert len({round(e["x"]) for e in shown}) <= 1


def test_no_card_stands_empty_round_its_button():
    """Buttons repeated on every card ("Choose") are the items', not the call to action: no card is kept
    for its button alone once its plan, price and points are dropped (320x100)."""
    task = json.loads((ROOT / "tests" / "fixtures" / "pricing_strip.json").read_text())
    out = {e["id"]: e for e in resize(task["source"], task["target_canvas"])["elements"]}
    for card, btn in (("card", "plan_btn"), ("card_2", "plan_btn_2")):
        if out[card].get("opacity", 1) > 0:
            inside = [k for k, e in out.items() if k.startswith(("plan", "point")) and not k.startswith("plan_btn")
                      and e.get("opacity", 1) > 0]
            assert inside, f"{card} holds nothing but its button"


@pytest.mark.parametrize("target", [(1200, 480), (1500, 500), (820, 312), (1584, 396)])
def test_banner_row_items_keep_an_em_apart(target):
    """Headline and button side by side in a banner keep at least 3/4 em of the headline between them
    (people's notes: "too stuck to each other"); the type gives up some size for the air."""
    out = {e["id"]: e for e in resize(_units("minimal_row"), {"width": target[0], "height": target[1]})["elements"]}
    head, cta = out["headline"], out["cta"]
    assert cta["x"] - (head["x"] + head["width"]) >= 0.75 * head["font_size"]


def test_a_row_of_price_cards_keeps_its_cards():
    """Two price cards beside the headline of a 600x200 email header stay, on gutters, rather than being
    dropped to give the headline air."""
    out = resize(_units("pricing_duo"), {"width": 600, "height": 200})
    assert all(e.get("opacity", 1) > 0 for e in out["elements"])


@pytest.mark.parametrize("target,most", [((300, 250), 0.6), ((336, 280), 0.56), ((250, 250), 0.7)])
def test_a_lifted_button_hugs_its_label(target, most):
    """The core sample's label is lifted to its legibility floor on small canvases; its pill hugs the label
    (padding at least an em across) instead of ballooning to two thirds of the width over a 12 px headline."""
    W, H = target
    out = {e["id"]: e for e in resize(CORE.get("source", CORE), {"width": W, "height": H})["elements"]}
    pill, label = out["cta_bg"], out["cta_label"]
    assert pill["width"] <= most * W
    assert pill["x"] <= label["x"] and label["x"] + label["width"] <= pill["x"] + pill["width"]
    assert pill["y"] <= label["y"] and label["y"] + label["height"] <= pill["y"] + pill["height"] + 1


def test_wrapped_copy_keeps_no_lone_last_word():
    """A billboard subhead wrapped as 'Naturally bright, never too / sweet.': the lines are balanced within the
    room the layout measured ('Naturally bright, / never too sweet.'), which leaves the layout as it was."""
    from engine.chameleon_layout import text_metrics as tm

    task = json.loads((ROOT / "tests" / "fixtures" / "widow_subhead.json").read_text())
    for e in resize(task["source"], task["target_canvas"])["elements"]:
        if e["type"] == "text" and len(e["content"].split()) >= 3:
            lines = tm.layout_text(e["content"], e["font_family"], e.get("font_weight"), e.get("font_style"),
                                   e["font_size"], e["width"], e.get("line_height") or 1.2,
                                   e.get("letter_spacing") or 0.0).lines
            assert len(lines) == 1 or len(lines[-1].split()) > 1, (e["id"], lines)


def test_wrapped_copy_in_a_centred_column_is_centred():
    """A banner row's left-aligned 'Bright / Days Ahead' restacked into a story's centred column: ragged-left lines
    would sit off the axis the logo, product and button share, so wrapped copy is centred with them."""
    task = json.loads((ROOT / "tests" / "fixtures" / "row_to_story.json").read_text())
    W = task["target_canvas"]["width"]
    out = {e["id"]: e for e in resize(task["source"], task["target_canvas"])["elements"]}
    for key in ("headline", "subhead"):
        e = out[key]
        assert e["text_align"] == "center" and abs(e["x"] + e["width"] / 2 - W / 2) < 0.005 * W, (key, e)


@pytest.mark.parametrize("target", [(728, 90), (1080, 1920), (320, 50), (2560, 1440)])
def test_corners_keep_their_shape(target):
    """A pill button or badge stays a pill however it is scaled, and other rounded corners keep their share of the
    shape's short side: an unscaled radius turns a card shrunk into a banner into a blob, a grown pill into a slab."""
    for path in sorted((ROOT / "input").glob("*.json")) + [ROOT / "tests" / "fixtures" / "rounded_card.json"]:
        src = json.loads(path.read_text())["source"]
        out = {e["id"]: e for e in resize(src, {"width": target[0], "height": target[1]})["elements"]}
        for s in src["elements"]:
            r, short = s.get("corner_radius") or 0, min(s["width"], s["height"])
            if s["type"] != "shape" or s.get("shape_type") in ("ellipse", "line") or r <= 0 or short <= 0:
                continue
            o = out[s["id"]]
            want = min(o["width"], o["height"]) / 2 if r >= 0.45 * short else r * min(o["width"], o["height"]) / short
            assert abs(o["corner_radius"] - want) < 0.02, (path.stem, s["id"], o["corner_radius"], want)


@pytest.mark.parametrize("target,inset", [((160, 600), 1.0), ((300, 250), 1.0), ((1080, 1920), 0.6), ((728, 90), 0.6)])
def test_a_corner_badge_sits_a_margin_in_when_there_is_room(target, inset):
    """The core sample's 'NEW FLAVOR' badge sits a full margin in from its corner, as the source's does, where that
    leaves air between it and the content; where the corner is crowded it tucks in closer rather than leave it."""
    from engine.chameleon_layout.families import margin

    W, H = target
    src = json.loads((ROOT / "input" / "chameleon_sample_level2_core.json").read_text())["source"]
    badge = next(e for e in resize(src, {"width": W, "height": H})["elements"] if e["id"] == "badge_bg")
    m = margin(W, H)
    assert abs(badge["x"] - inset * m) < 0.05 * m and abs(badge["y"] - inset * m) < 0.05 * m, (badge, m)
