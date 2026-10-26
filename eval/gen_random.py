"""Random plausible designs: the pieces real designs are made of, combined at
random - several products or none, cards, header and footer bars, badges,
ribbons, faint texture type, prices, a second button, no background - in one
of four skeletons (a column, product beside copy, copy over a big product,
loose scatter), each paired with random catalogue targets.

The archetypes (gen_testset.py) and stress designs (gen_crazy.py) only cover
structures someone thought of; this searches for the rest.  `python -m
eval.hunt` ranks the engine's outputs on it and shows the worst.

    python -m eval.gen_random --out eval/testsets/random --n 150
    python -m eval.gen_random --out eval/testsets/strips --n 80 --strips   # banner sources -> tall / square
    python -m eval.gen_random --out eval/testsets/tall --n 80 --tall       # skyscraper sources -> wide / square
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.catalogue import FORMATS  # noqa: E402
from eval.gen_crazy import _cta  # noqa: E402
from eval.gen_testset import (BADGES, BODY, BOTTLE, CREAM, CTAS, DEEP, FLAVORS, GOLD, HEAD_LONG, HEAD_SHORT, INK, LEGAL,  # noqa: E402
                              ORANGE, PLUM, PRICES, RIBBONS, SANS, SERIF, SUBHEADS, WHITE, Design, rgba)

SOURCES = [(1080, 1080), (1080, 1350), (1080, 1920), (1920, 1080), (1200, 628), (1600, 900)]
SKELETONS = ("column", "split", "overlay", "scatter")


TALL = [(160, 600), (300, 600), (300, 1050), (120, 600)]


def design(rng: random.Random, sources=SOURCES) -> Design:
    W, H = rng.choice(sources)
    d, u = Design(W, H, rng), min(W, H) / 1080
    bg = rng.random()
    if bg < 0.65:
        d.bg_image()
    elif bg < 0.9:
        d.bg_solid(rng.choice((PLUM, DEEP, ORANGE, CREAM)))
    ink = INK if bg >= 0.9 or d.els and d.els[0].get("fill_color", "").startswith("rgba(245") else WHITE
    if rng.random() < 0.4:
        d.decor_circles(rng.randint(1, 3))
    if rng.random() < 0.4:
        d.dots(rng.randint(3, 9))
    top, bottom = 40 * u, H - 40 * u
    if rng.random() < 0.2:  # a header or footer bar
        h = rng.uniform(80, 160) * u
        if rng.random() < 0.5:
            d.shape("header", 0, 0, W, h, INK)
            d.logo(W / 2, h * 0.2, h * 1.8)
            top = h + 30 * u
        else:
            d.shape("footer", 0, H - h, W, h, PLUM)
            d.text("legal", rng.choice(LEGAL), SANS, 15 * u, rgba(*WHITE, 0.8), 40 * u, H - h * 0.65, W - 80 * u)
            bottom = H - h - 30 * u
    elif rng.random() < 0.7:
        d.logo(rng.choice((W / 2, W * 0.2, W * 0.8)), top, rng.uniform(180, 300) * u)
        top += 140 * u
    if rng.random() < 0.1:
        d.text("texture", "SUMMER", SERIF, 260 * u, rgba(*WHITE, 0.07), 0, H * 0.35, W, weight="bold")
    skeleton = rng.choice(SKELETONS)
    copy_x, copy_w = 60 * u, W - 120 * u
    products = rng.choice((0, 1, 1, 1, 2, 3))
    if skeleton == "split" and products:
        left = rng.random() < 0.5
        size = min(W * 0.42, bottom - top)
        x = W * 0.06 if left else W * 0.52
        d.image("product", BOTTLE, x, top + (bottom - top - size) / 2, size, size)
        copy_x, copy_w = (W * 0.52, W * 0.42) if left else (W * 0.06, W * 0.42)
    elif skeleton == "overlay" and products:
        size = min(W, H) * rng.uniform(0.5, 0.8)
        d.image("product", BOTTLE, (W - size) / 2, (H - size) / 2, size, size)
    else:
        for i in range(products):
            size = min(W, H) * rng.uniform(0.18, 0.4)
            x = rng.uniform(0, W - size) if skeleton == "scatter" else (i + 0.5) * W / products - size / 2
            d.image("product", BOTTLE, x, top, size, size)
        if products and skeleton != "scatter":
            top += min(W, H) * 0.42
    card = rng.random() < 0.25
    y = top + (rng.uniform(0, 80) * u if skeleton != "scatter" else rng.uniform(0, max(1.0, (bottom - top) * 0.4)))
    if card:
        d.shape("card", copy_x - 20 * u, y - 20 * u, copy_w + 40 * u, min(bottom - y + 20 * u, 520 * u), CREAM, radius=28 * u)
        ink = INK
    align = rng.choice(("center", "center", "left"))
    head = rng.choice(HEAD_LONG if rng.random() < 0.3 else HEAD_SHORT)
    y += d.text("headline", head, SERIF, rng.uniform(44, 110) * u, rgba(*ink), copy_x, y, copy_w, weight="bold",
                align=align)["height"] + rng.uniform(12, 40) * u
    if rng.random() < 0.6:
        y += d.text("subhead", rng.choice(SUBHEADS), SANS, rng.uniform(20, 32) * u, rgba(*ink), copy_x, y, copy_w,
                    align=align)["height"] + rng.uniform(10, 30) * u
    if rng.random() < 0.3:
        y += d.text("body", rng.choice(BODY), SANS, 20 * u, rgba(*ink), copy_x, y, copy_w, align=align)["height"] + 20 * u
    if rng.random() < 0.15:
        y += d.text("price", rng.choice(PRICES), SERIF, 44 * u, rgba(*GOLD), copy_x, y, copy_w, weight="bold",
                    align=align)["height"] + 16 * u
    if rng.random() < 0.25:
        labels = rng.sample(BADGES, rng.randint(2, 4))
        x = copy_x
        for lab in labels:
            w, _ = d.pill_size(lab, 16 * u)
            d.pill("badge", lab, x, y, 16 * u, rng.choice((ORANGE, GOLD, INK)))
            x += w + 14 * u
        y += 60 * u
    cx = copy_x + copy_w / 2 if align == "center" else copy_x + d.pill_size("Shop Now", 26 * u)[0] / 2
    if rng.random() < 0.85:
        _cta(d, rng.choice(CTAS), cx, min(y + 10 * u, bottom - 70 * u), rng.uniform(22, 30) * u)
        if rng.random() < 0.15:
            _cta(d, "Find a Store", cx, min(y + 80 * u, bottom - 70 * u), 22 * u, fill=INK)
    if rng.random() < 0.2:
        d.ribbon(rng.choice(RIBBONS), rng.choice(("tr", "tl")))
    if rng.random() < 0.3 and bottom == H - 40 * u:
        d.text("legal", rng.choice(LEGAL), SANS, 14 * u, rgba(*ink, 0.7), 60 * u, H - 50 * u, W - 120 * u)
    return d


STRIPS = [(728, 90), (970, 250), (320, 100), (1500, 500), (1200, 300), (468, 60)]


def strip_design(rng: random.Random) -> Design:
    """A banner source: logo, product art, copy and a button side by side in a strip, at random proportions -
    the reverse direction (banner -> story / square / portrait) the poster-shaped sources never test."""
    W, H = rng.choice(STRIPS)
    d, u = Design(W, H, rng), H / 250
    if rng.random() < 0.8:
        d.bg_image()
    else:
        d.bg_solid(rng.choice((PLUM, DEEP, ORANGE)))
    x = 0.04 * W
    if rng.random() < 0.7:
        w = H * rng.uniform(0.9, 1.4)
        d.logo(x + w / 2, H * 0.32, w)
        x += w + 0.03 * W
    for _ in range(rng.choice((0, 1, 1, 2))):
        size = H * rng.uniform(0.7, 0.95)
        d.image("product", BOTTLE, x, (H - size) / 2, size, size)
        x += size * 0.8 + 0.02 * W
    cta_w = d.pill_size("Shop the Summer Line", 22 * u)[0] if rng.random() < 0.85 else 0.0
    copy_w = max(W * 0.15, W - x - cta_w - 0.08 * W)
    y = H * rng.uniform(0.12, 0.3)
    y += d.text("headline", rng.choice(HEAD_LONG if rng.random() < 0.25 else HEAD_SHORT), SERIF, rng.uniform(44, 72) * u,
                rgba(*WHITE), x, y, copy_w, weight="bold", align=rng.choice(("left", "center")))["height"] + 8 * u
    if rng.random() < 0.6 and y < H * 0.75:
        d.text("subhead", rng.choice(SUBHEADS), SANS, rng.uniform(18, 26) * u, rgba(*WHITE), x, y, copy_w)
    if cta_w:
        _cta(d, rng.choice(CTAS), W - 0.04 * W - cta_w / 2, H / 2 - 28 * u, 22 * u)
    if rng.random() < 0.2:
        d.ribbon(rng.choice(RIBBONS), "tr", size=14 * u)
    return d


def pattern_design(rng: random.Random) -> Design:
    """Three more common skeletons: a Z-pattern (headline top-left, product top-right, copy bottom-left, button
    bottom-right), a 2x2 product grid with names and prices, and a colour panel bleeding off one side holding the
    product, copy on the other side."""
    W, H = rng.choice(SOURCES)
    d, u = Design(W, H, rng), min(W, H) / 1080
    d.bg_image() if rng.random() < 0.7 else d.bg_solid(rng.choice((PLUM, DEEP)))
    kind = rng.choice(("z", "grid", "half_bleed"))
    if kind == "z":
        d.text("headline", rng.choice(HEAD_SHORT), SERIF, rng.uniform(64, 100) * u, rgba(*WHITE), W * 0.06, H * 0.08,
               W * 0.48, weight="bold", align="left")
        size = min(W * 0.38, H * 0.45)
        d.image("product", BOTTLE, W * 0.58, H * 0.06, size, size)
        d.text("subhead", rng.choice(SUBHEADS), SANS, 26 * u, rgba(*WHITE), W * 0.06, H * 0.62, W * 0.46, align="left")
        _cta(d, rng.choice(CTAS), W * 0.76, H * 0.8, 26 * u)
        d.logo(W * 0.14, H * 0.86, 200 * u)
    elif kind == "grid":
        d.text("headline", rng.choice(HEAD_SHORT), SERIF, 70 * u, rgba(*WHITE), W * 0.08, H * 0.06, W * 0.84, weight="bold")
        tile = min(W * 0.3, H * 0.26)
        for i, flavor in enumerate(rng.sample(FLAVORS, 4)):
            x, y = W * (0.2 + 0.32 * (i % 2)), H * (0.22 + 0.34 * (i // 2))
            d.image("product", BOTTLE, x, y, tile, tile)
            d.text("name", flavor, SERIF, 24 * u, rgba(*WHITE), x - 20 * u, y + tile, tile + 40 * u, weight="bold")
            d.text("price", rng.choice(PRICES), SANS, 20 * u, rgba(*GOLD), x - 20 * u, y + tile + 32 * u, tile + 40 * u)
        _cta(d, rng.choice(CTAS), W / 2, H * 0.9, 24 * u)
    else:
        left = rng.random() < 0.5
        d.shape("panel", 0 if left else W * 0.5, 0, W * 0.5, H, ORANGE)
        size = min(W * 0.36, H * 0.6)
        d.image("product", BOTTLE, (W * 0.25 if left else W * 0.75) - size / 2, (H - size) / 2, size, size)
        x = W * 0.56 if left else W * 0.06
        d.text("headline", rng.choice(HEAD_SHORT), SERIF, 72 * u, rgba(*WHITE), x, H * 0.25, W * 0.38, weight="bold",
               align="left")
        d.text("subhead", rng.choice(SUBHEADS), SANS, 24 * u, rgba(*WHITE), x, H * 0.5, W * 0.38, align="left")
        _cta(d, rng.choice(CTAS), x + d.pill_size("Shop Now", 24 * u)[0] / 2, H * 0.68, 24 * u)
    return d


def skeleton_design(rng: random.Random) -> Design:
    """Five more skeletons: the copy inside a colour block bleeding off one side (product on the other), a full-bleed
    product under a scrim band holding the copy, three feature columns, a footer band of partner marks and legal
    text, and a cream card the product overlaps."""
    W, H = rng.choice(SOURCES)
    d, u = Design(W, H, rng), min(W, H) / 1080
    d.bg_image() if rng.random() < 0.7 else d.bg_solid(rng.choice((PLUM, DEEP)))
    kind = rng.choice(("copy_block", "scrim", "features", "partner_footer", "card_overlap"))
    head, cta = rng.choice(HEAD_SHORT), rng.choice(CTAS)
    if kind == "copy_block":
        left, bw = rng.random() < 0.5, W * rng.uniform(0.4, 0.55)
        x0 = 0 if left else W - bw
        d.shape("block", x0, 0, bw, H, rng.choice((ORANGE, CREAM)))
        ink = INK
        d.logo(x0 + bw / 2, H * 0.08, 200 * u)
        y = H * 0.3 + d.text("headline", head, SERIF, 76 * u, rgba(*ink), x0 + bw * 0.1, H * 0.3, bw * 0.8,
                             weight="bold")["height"]
        y += 24 * u + d.text("subhead", rng.choice(SUBHEADS), SANS, 26 * u, rgba(*ink), x0 + bw * 0.1, y + 24 * u,
                             bw * 0.8)["height"]
        _cta(d, cta, x0 + bw / 2, y + 40 * u, 26 * u, fill=INK)
        size = min(W - bw, H) * 0.7
        d.image("product", BOTTLE, (bw if left else 0) + (W - bw - size) / 2, (H - size) / 2, size, size)
    elif kind == "scrim":
        size = min(W, H) * 0.9
        d.image("product", BOTTLE, (W - size) / 2, (H - size) / 2 - H * 0.1, size, size)
        sh = H * rng.uniform(0.25, 0.35)
        d.shape("scrim", 0, H - sh, W, sh, INK, alpha=rng.choice((0.75, 1.0)))
        d.text("headline", head, SERIF, 64 * u, rgba(*WHITE), W * 0.06, H - sh + sh * 0.18, W * 0.58, weight="bold",
               align="left")
        _cta(d, cta, W * 0.8, H - sh / 2 - 30 * u, 26 * u)
        d.logo(W * 0.12, 40 * u, 200 * u)
    elif kind == "features":
        d.logo(W / 2, 40 * u, 200 * u)
        d.text("headline", head, SERIF, 70 * u, rgba(*WHITE), W * 0.08, H * 0.16, W * 0.84, weight="bold")
        for i, label in enumerate(rng.sample(BADGES, 3)):
            cx = W * (0.2 + 0.3 * i)
            d.shape("icon", cx - 40 * u, H * 0.42, 80 * u, 80 * u, rng.choice((ORANGE, GOLD)), kind="ellipse")
            d.text("feature", label, SANS, 26 * u, rgba(*WHITE), cx - W * 0.13, H * 0.42 + 100 * u, W * 0.26,
                   weight="bold")
            d.text("detail", rng.choice(SUBHEADS), SANS, 18 * u, rgba(*WHITE, 0.85), cx - W * 0.13, H * 0.42 + 145 * u,
                   W * 0.26)
        _cta(d, cta, W / 2, H * 0.82, 26 * u)
    elif kind == "partner_footer":
        size = min(W * 0.5, H * 0.45)
        d.image("product", BOTTLE, (W - size) / 2, H * 0.08, size, size)
        d.text("headline", head, SERIF, 72 * u, rgba(*WHITE), W * 0.08, H * 0.08 + size + 20 * u, W * 0.84,
               weight="bold")
        fh = H * 0.16
        d.shape("footer", 0, H - fh, W, fh, CREAM)
        for i in range(3):
            d.logo(W * (0.15 + 0.2 * i), H - fh * 0.75, 140 * u)
        d.text("legal", rng.choice(LEGAL), SANS, 14 * u, rgba(*INK, 0.8), W * 0.62, H - fh * 0.7, W * 0.34, align="left")
    else:
        cw, ch = W * 0.7, H * 0.38
        cx, cy = (W - cw) / 2, H * 0.5
        d.shape("card", cx, cy, cw, ch, CREAM, radius=28 * u)
        size = min(W, H) * 0.42
        d.image("product", BOTTLE, (W - size) / 2, cy - size * 0.7, size, size)
        y = cy + size * 0.35 + d.text("headline", head, SERIF, 56 * u, rgba(*INK), cx + 40 * u, cy + size * 0.35,
                                      cw - 80 * u, weight="bold")["height"]
        d.text("price", rng.choice(PRICES), SERIF, 40 * u, rgba(*ORANGE), cx + 40 * u, y + 10 * u, cw - 80 * u,
               weight="bold")
        _cta(d, cta, W / 2, min(y + 70 * u, cy + ch - 80 * u), 24 * u)
        d.logo(W / 2, 40 * u, 200 * u)
    return d


def wild_design(rng: random.Random) -> Design:
    """Five more kinds: a full-bleed product photo under a translucent scrim, a dense two-column menu of
    flavours and prices, two grouped offers each with its own button, a product ringed by badges, and a
    testimonial quote."""
    W, H = rng.choice(SOURCES)
    d, u = Design(W, H, rng), min(W, H) / 1080
    kind = rng.choice(("photo", "menu", "duo", "badges", "quote"))
    head, cta = rng.choice(HEAD_SHORT), rng.choice(CTAS)
    if kind == "photo":
        d.bg_solid(DEEP)
        d.image("photo", BOTTLE, 0, 0, W, H, fit="cover")
        sh = H * 0.32
        d.shape("scrim", 0, H - sh, W, sh, INK, alpha=0.6)
        d.text("headline", head, SERIF, 76 * u, rgba(*WHITE), W * 0.06, H - sh + 30 * u, W * 0.88, weight="bold")
        _cta(d, cta, W / 2, H - 110 * u, 26 * u)
    else:
        d.bg_image() if rng.random() < 0.7 else d.bg_solid(rng.choice((PLUM, DEEP)))
        d.logo(W / 2, 40 * u, 200 * u)
    if kind == "menu":
        d.text("headline", head, SERIF, 64 * u, rgba(*WHITE), W * 0.08, H * 0.14, W * 0.84, weight="bold")
        for i, flavor in enumerate(rng.sample(FLAVORS, 6)):
            x, y = W * (0.1 + 0.42 * (i % 2)), H * (0.32 + 0.12 * (i // 2))
            d.text("item", flavor, SERIF, 30 * u, rgba(*WHITE), x, y, W * 0.26, align="left", weight="bold")
            d.text("price", rng.choice(PRICES), SANS, 26 * u, rgba(*GOLD), x + W * 0.26, y, W * 0.12, align="right")
        _cta(d, cta, W / 2, H * 0.8, 26 * u)
    elif kind == "duo":
        d.text("headline", head, SERIF, 64 * u, rgba(*WHITE), W * 0.08, H * 0.12, W * 0.84, weight="bold")
        for i, flavor in enumerate(rng.sample(FLAVORS, 2)):
            cx, size, g = W * (0.28 + 0.44 * i), min(W * 0.3, H * 0.3), f"offer{i}"
            d.image("product", BOTTLE, cx - size / 2, H * 0.3, size, size, group=g)
            d.text("name", flavor, SERIF, 32 * u, rgba(*WHITE), cx - W * 0.18, H * 0.3 + size + 10 * u, W * 0.36,
                   weight="bold", group=g)
            d.text("price", rng.choice(PRICES), SANS, 26 * u, rgba(*GOLD), cx - W * 0.18, H * 0.3 + size + 56 * u,
                   W * 0.36, group=g)
            w, _ = d.pill_size("Add to Cart", 22 * u)
            d.pill("cta", "Add to Cart", cx - w / 2, H * 0.3 + size + 100 * u, 22 * u, ORANGE, group=g)
    elif kind == "badges":
        size = min(W, H) * 0.45
        cx, cy = W / 2, H * 0.45
        d.image("product", BOTTLE, cx - size / 2, cy - size / 2, size, size)
        for i, lab in enumerate(rng.sample(BADGES, 4)):
            bx, by = cx + (size * 0.62) * (-1 if i % 2 == 0 else 1), cy + (size * 0.4) * (-1 if i < 2 else 1)
            w, _ = d.pill_size(lab, 16 * u)
            d.pill("badge", lab, bx - w / 2, by, 16 * u, rng.choice((ORANGE, GOLD, INK)))
        d.text("headline", head, SERIF, 70 * u, rgba(*WHITE), W * 0.08, cy + size / 2 + 40 * u, W * 0.84, weight="bold")
        _cta(d, cta, W / 2, min(H - 110 * u, cy + size / 2 + 160 * u), 26 * u)
    elif kind == "quote":
        d.text("quote", "\u201cThe brightest thing I have tasted all summer. I keep a case in the fridge.\u201d", SERIF,
               54 * u, rgba(*WHITE), W * 0.1, H * 0.2, W * 0.8, style="italic")
        d.text("author", "- Maya R., Portland", SANS, 24 * u, rgba(*GOLD), W * 0.1, H * 0.52, W * 0.8)
        size = min(W, H) * 0.22
        d.image("product", BOTTLE, (W - size) / 2, H * 0.6, size, size)
        _cta(d, cta, W / 2, H * 0.6 + size + 30 * u, 24 * u)
    return d


def effects_design(rng: random.Random) -> Design:
    """Common effects: a card with a translucent shadow, a headline with a drop shadow and a shadowed button,
    an outlined headline (four offset copies), a two-tone background, and bare colour strips."""
    W, H = rng.choice(SOURCES)
    d, u = Design(W, H, rng), min(W, H) / 1080
    d.bg_solid(rng.choice((PLUM, DEEP)))
    kind = rng.choice(("card_shadow", "text_shadow", "outline", "two_tone", "strips"))
    head, cta, size = rng.choice(HEAD_SHORT), rng.choice(CTAS), min(W, H) * 0.32
    hx, hw = W * 0.08, W * 0.84
    if kind == "card_shadow":
        cw, ch = W * 0.76, H * 0.36
        cx, cy = (W - cw) / 2, H * 0.52
        d.shape("shadow", cx + 12 * u, cy + 12 * u, cw, ch, INK, alpha=0.4, radius=24 * u)
        d.shape("card", cx, cy, cw, ch, CREAM, radius=24 * u)
        d.image("product", BOTTLE, (W - size) / 2, cy - size - 20 * u, size, size)
        y = cy + 40 * u + d.text("headline", head, SERIF, 64 * u, rgba(*INK), cx + 40 * u, cy + 40 * u, cw - 80 * u,
                                 weight="bold")["height"]
        d.text("subhead", rng.choice(SUBHEADS), SANS, 26 * u, rgba(*INK), cx + 40 * u, y + 16 * u, cw - 80 * u)
    elif kind in ("text_shadow", "outline"):
        offsets = [(6 * u, 6 * u)] if kind == "text_shadow" else [(-3 * u, 0), (3 * u, 0), (0, -3 * u), (0, 3 * u)]
        for dx, dy in offsets:
            d.text("headline_fx", head, SERIF, 90 * u, rgba(*(INK if kind == "text_shadow" else ORANGE)), hx + dx,
                   H * 0.18 + dy, hw, weight="bold")
        d.text("headline", head, SERIF, 90 * u, rgba(*WHITE), hx, H * 0.18, hw, weight="bold")
        d.image("product", BOTTLE, (W - size) / 2, H * 0.4, size, size)
        w, _ = d.pill_size(cta, 26 * u)
        d.shape("cta_shadow", (W - w) / 2 + 5 * u, H * 0.82 + 5 * u, w, 62 * u, INK, alpha=0.45, radius=31 * u)
    elif kind == "two_tone":
        left = rng.random() < 0.5
        d.shape("tone", 0 if left else W / 2, 0, W / 2, H, rng.choice((ORANGE, CREAM)))
        d.image("product", BOTTLE, (W / 4 if left else W * 0.75) - size / 2, (H - size) / 2, size, size)
        x = W * 0.56 if left else W * 0.06
        d.text("headline", head, SERIF, 72 * u, rgba(*WHITE), x, H * 0.3, W * 0.38, weight="bold", align="left")
        d.text("subhead", rng.choice(SUBHEADS), SANS, 26 * u, rgba(*WHITE), x, H * 0.52, W * 0.38, align="left")
    else:
        sh = H * rng.uniform(0.03, 0.08)
        d.shape("strip_top", 0, 0, W, sh, ORANGE)
        d.shape("strip_bottom", 0, H - sh, W, sh, ORANGE)
        d.text("headline", head, SERIF, 90 * u, rgba(*WHITE), hx, H * 0.2, hw, weight="bold")
        d.image("product", BOTTLE, (W - size) / 2, H * 0.4, size, size)
    _cta(d, cta, W / 2, H * 0.82, 26 * u)
    d.logo(W / 2, H * 0.06 + (H * 0.06 if kind == "strips" else 0), 180 * u)
    return d


def generate(out_dir: Path, n: int, seed: int, strips: bool = False, tall: bool = False, patterns: bool = False,
             skeletons: bool = False, wild: bool = False, effects: bool = False):
    tasks_dir = Path(out_dir) / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    rng, manifest = random.Random(seed), []
    for i in range(n):
        r = random.Random(rng.random())
        src = (strip_design(r) if strips else pattern_design(r) if patterns else skeleton_design(r) if skeletons else
               wild_design(r) if wild else effects_design(r) if effects else
               design(r, TALL if tall else SOURCES)).to_source()
        sw, sh = src["canvas"]["width"], src["canvas"]["height"]
        wanted = (lambda f: f[2] >= 0.6 * f[1]) if strips else (lambda f: f[1] >= f[2]) if tall else (lambda f: True)
        targets = [f for f in FORMATS if (f[1], f[2]) != (sw, sh) and wanted(f)]
        for name, tw, th in rng.sample(targets, 2):
            tid = f"random_{i:03d}__{name.lower().replace(' ', '_')}"
            lvl = 3 if max(tw / th, th / tw) > 3 else (2 if (tw > th) != (sw > sh) else 1)
            task = {"task_id": tid, "archetype": "random", "ratio_level": lvl, "source": copy.deepcopy(src),
                    "target_canvas": {"width": tw, "height": th}}
            (tasks_dir / f"{tid}.json").write_text(json.dumps(task))
            manifest.append({"task_id": tid, "archetype": "random", "complexity": 2, "ratio_level": lvl,
                             "difficulty": lvl, "source": [sw, sh], "target": [tw, th], "target_name": name,
                             "n_elements": len(src["elements"])})
    (Path(out_dir) / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {len(manifest)} tasks ({n} designs) to {tasks_dir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "eval" / "testsets" / "random"))
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--strips", action="store_true", help="banner-shaped sources, resized to square and tall formats")
    ap.add_argument("--tall", action="store_true", help="skyscraper sources, resized to square and wide formats")
    ap.add_argument("--patterns", action="store_true", help="Z-pattern, 2x2 product grid and half-bleed panel designs")
    ap.add_argument("--skeletons", action="store_true",
                    help="copy in a colour block, scrim band, feature columns, partner footer, card overlap designs")
    ap.add_argument("--wild", action="store_true",
                    help="full-bleed photo, dense menu, grouped duo offers, badge ring, testimonial designs")
    ap.add_argument("--effects", action="store_true",
                    help="card and text shadows, outlined type, two-tone backgrounds, bare colour strips")
    a = ap.parse_args()
    generate(Path(a.out), a.n, a.seed, a.strips, a.tall, a.patterns, a.skeletons, a.wild, a.effects)


if __name__ == "__main__":
    main()
