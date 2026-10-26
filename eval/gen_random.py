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
from eval.gen_testset import (BADGES, BODY, BOTTLE, CREAM, CTAS, DEEP, GOLD, HEAD_LONG, HEAD_SHORT, INK, LEGAL,  # noqa: E402
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


def generate(out_dir: Path, n: int, seed: int, strips: bool = False, tall: bool = False):
    tasks_dir = Path(out_dir) / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    rng, manifest = random.Random(seed), []
    for i in range(n):
        r = random.Random(rng.random())
        src = (strip_design(r) if strips else design(r, TALL if tall else SOURCES)).to_source()
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
    a = ap.parse_args()
    generate(Path(a.out), a.n, a.seed, a.strips, a.tall)


if __name__ == "__main__":
    main()
