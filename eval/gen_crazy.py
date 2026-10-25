"""Stress test set: unusual but plausible designs, each paired with ordinary
and extreme targets (10:1 and 1:10 strips, 64 px squares, 4K canvases).

    python -m eval.gen_crazy --out eval/testsets/crazy

The regular generator (gen_testset.py) covers common ad archetypes; this one
covers what it never produces: walls of text, a dozen badges, 3x3 product
grids, one giant word, two CTAs, photo backgrounds with a scrim, no
background at all, vertical and rotated type, collages, non-Latin scripts and
emoji, unbreakable words, hard line breaks, nested cards, one group holding
everything, edge-to-edge bars, price lists, and lone elements.
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

from eval.gen_testset import (BADGES, BG, BODY, BOTTLE, CREAM, CTAS, DEEP, FLAVORS, GOLD, HEAD_LONG,  # noqa: E402
                              HEAD_SHORT, INK, LEGAL, ORANGE, PLUM, PRICES, RED, SANS, SERIF, SUBHEADS, WHITE,
                              Design, rgba)

TARGETS = [(1080, 1080), (1080, 1920), (1920, 1080), (728, 90), (320, 50), (160, 600), (2000, 200), (200, 2000),
           (64, 64), (3840, 2160)]


def _base(rng, W, H):
    d = Design(W, H, rng)
    d.bg_image()
    return d


def _cta(d, label, cx, y, size, fill=ORANGE):
    w, _ = d.pill_size(label, size)
    return d.pill("cta", label, cx - w / 2, y, size, fill)


def c_wall_of_text(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.logo(W / 2, 40 * u, 260 * u)
    y = d.text("headline", rng.choice(HEAD_LONG), SERIF, 52 * u, rgba(*WHITE), 80 * u, 150 * u, W - 160 * u,
               weight="bold")["height"] + 170 * u
    for para in BODY:
        y += d.text("body", para, SANS, 24 * u, rgba(*WHITE), 80 * u, y, W - 160 * u, align="left")["height"] + 24 * u
    _cta(d, rng.choice(CTAS), W / 2, y + 10 * u, 26 * u)
    d.text("legal", rng.choice(LEGAL), SANS, 14 * u, rgba(*WHITE, 0.7), 60 * u, H - 50 * u, W - 120 * u)
    return d


def c_badge_storm(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 90 * u, rgba(*WHITE), 60 * u, 100 * u, W - 120 * u, weight="bold")
    labels = (BADGES * 2)[:12]
    for i, lab in enumerate(labels):
        r, c = divmod(i, 4)
        d.pill("badge", lab, 60 * u + c * (W - 120 * u) / 4, 330 * u + r * 90 * u, 18 * u,
               [ORANGE, GOLD, INK][i % 3], padx=0.8)
    _cta(d, rng.choice(CTAS), W / 2, H - 200 * u, 32 * u)
    return d


def c_big_grid(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.text("headline", "Find Your Flavor", SERIF, 70 * u, rgba(*WHITE), 60 * u, 40 * u, W - 120 * u, weight="bold")
    cw, ch = (W - 120 * u) / 3, (H - 300 * u) / 3
    for i in range(9):
        r, c = divmod(i, 3)
        x, y, g = 60 * u + c * cw, 150 * u + r * ch, f"tile{i}"
        s = min(cw, ch) * 0.62
        d.image("product", BOTTLE, x + (cw - s) / 2, y, s, s, group=g)
        d.text("name", FLAVORS[i % len(FLAVORS)], SERIF, 22 * u, rgba(*WHITE), x, y + s, cw, weight="bold", group=g)
        d.text("price", PRICES[i % len(PRICES)], SANS, 18 * u, rgba(*GOLD), x, y + s + 32 * u, cw, group=g)
    _cta(d, "Shop All", W / 2, H - 110 * u, 26 * u)
    return d


def c_huge_type(rng, W, H):
    d, u = Design(W, H, rng), min(W, H) / 1080
    d.bg_solid(RED)
    d.text("headline", "SALE", SERIF, 420 * u, rgba(*WHITE), 0, H * 0.18, W, weight="bold")
    d.text("subhead", "Everything 40% off this weekend only", SANS, 26 * u, rgba(*WHITE), 80 * u, H * 0.68, W - 160 * u)
    _cta(d, "Shop Now", W / 2, H * 0.8, 22 * u, fill=INK)
    return d


def c_two_ctas(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.logo(W / 2, 60 * u, 300 * u)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 100 * u, rgba(*WHITE), 60 * u, H * 0.3, W - 120 * u, weight="bold")
    d.text("subhead", rng.choice(SUBHEADS), SANS, 30 * u, rgba(*WHITE), 100 * u, H * 0.5, W - 200 * u)
    w1, _ = d.pill_size("Shop Now", 28 * u)
    w2, _ = d.pill_size("Find a Store", 28 * u)
    x = W / 2 - (w1 + w2 + 30 * u) / 2
    d.pill("cta", "Shop Now", x, H * 0.68, 28 * u, ORANGE)
    d.pill("cta2", "Find a Store", x + w1 + 30 * u, H * 0.68, 28 * u, INK)
    return d


def c_photo_overlay(rng, W, H):
    d, u = Design(W, H, rng), min(W, H) / 1080
    d.image("photo", BOTTLE, 0, 0, W, H, fit="cover")
    d.shape("scrim", 0, H * 0.58, W, H * 0.42, DEEP, alpha=0.8)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 84 * u, rgba(*WHITE), 60 * u, H * 0.63, W - 120 * u, weight="bold")
    _cta(d, rng.choice(CTAS), W / 2, H * 0.83, 26 * u)
    return d


def c_no_background(rng, W, H):
    d, u = Design(W, H, rng), min(W, H) / 1080
    d.image("product", BOTTLE, W * 0.25, H * 0.1, W * 0.5, W * 0.5)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 80 * u, rgba(*INK), 60 * u, H * 0.62, W - 120 * u, weight="bold")
    _cta(d, rng.choice(CTAS), W / 2, H * 0.8, 26 * u)
    return d


def c_vertical_text(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    t = d.text("headline", "SUMMER COLLECTION", SANS, 70 * u, rgba(*WHITE), 0, 0, H * 0.8, weight="bold", ls=6 * u)
    t["rotation"], t["x"], t["y"] = -90, 70 * u - H * 0.4 + t["height"] / 2, H / 2 - t["height"] / 2
    d.image("product", BOTTLE, W * 0.3, H * 0.15, W * 0.55, W * 0.55)
    _cta(d, rng.choice(CTAS), W * 0.6, H * 0.82, 26 * u)
    return d


def c_collage(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    for i, (fx, fy, fs) in enumerate([(0.05, 0.1, 0.5), (0.35, 0.18, 0.42), (0.6, 0.05, 0.36)]):
        d.image("product", BOTTLE, W * fx, H * fy, W * fs, W * fs)
    d.shape("band", 0, H * 0.6, W, 150 * u, ORANGE)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 90 * u, rgba(*WHITE), 40 * u, H * 0.6 + 20 * u, W - 80 * u,
           weight="bold")
    _cta(d, rng.choice(CTAS), W / 2, H * 0.85, 26 * u, fill=INK)
    return d


def c_multilingual(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.logo(W / 2, 50 * u, 280 * u)
    d.text("headline", "夏の光を追いかけて", SANS, 90 * u, rgba(*WHITE), 60 * u, H * 0.25, W - 120 * u, weight="bold")
    d.text("subhead", "تذوق غروب الشمس — Летний вкус", SANS, 40 * u, rgba(*GOLD), 60 * u, H * 0.45, W - 120 * u)
    d.text("body", "🍊✨ Fresh citrus vibes 🌅 Ünïcödé Çafé déjà vu", SANS, 30 * u, rgba(*WHITE), 60 * u, H * 0.58,
           W - 120 * u)
    _cta(d, "Shop Now →", W / 2, H * 0.75, 28 * u)
    return d


def c_tiny_on_huge(rng, W, H):
    d = _base(rng, 4000, 4000)
    d.logo(2000, 300, 300)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 60, rgba(*WHITE), 1500, 1800, 1000, weight="bold")
    d.text("subhead", rng.choice(SUBHEADS), SANS, 22, rgba(*WHITE), 1500, 1900, 1000)
    _cta(d, rng.choice(CTAS), 2000, 2000, 20)
    return d


def c_logo_only(rng, W, H):
    d = _base(rng, W, H)
    d.logo(W / 2, H / 2 - W * 0.6 / 6.4, W * 0.6)
    return d


def c_long_words(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.text("headline", "Donaudampfschifffahrtsgesellschaftskapitän", SERIF, 80 * u, rgba(*WHITE), 60 * u, H * 0.2,
           W - 120 * u, weight="bold")
    d.text("url", "https://www.solstice-botanical-sparkling.com/summer-collection-2026", SANS, 28 * u,
           rgba(*GOLD), 60 * u, H * 0.45, W - 120 * u)
    d.text("hashtag", "#ChaseTheLightSummerCollection2026", SANS, 34 * u, rgba(*WHITE), 60 * u, H * 0.55, W - 120 * u)
    _cta(d, rng.choice(CTAS), W / 2, H * 0.75, 26 * u)
    return d


def c_newline_heavy(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.text("headline", "Chase\nthe\nLight", SERIF, 110 * u, rgba(*WHITE), 60 * u, H * 0.08, W - 120 * u, weight="bold")
    d.text("address", "Solstice Tasting Room\n123 Harbor Pier\nDock 9, Suite 4\nOpen daily 12–9pm", SANS, 30 * u,
           rgba(*WHITE), 60 * u, H * 0.55, W - 120 * u)
    _cta(d, "Get Directions", W / 2, H * 0.82, 26 * u)
    return d


def c_nested_cards(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.shape("outer", 60 * u, 60 * u, W - 120 * u, H - 120 * u, CREAM, radius=40 * u)
    d.image("product", BOTTLE, W * 0.3, 100 * u, W * 0.4, W * 0.4)
    d.shape("inner", 120 * u, H * 0.5, W - 240 * u, H * 0.4, WHITE, radius=30 * u)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 70 * u, rgba(*INK), 160 * u, H * 0.54, W - 320 * u, weight="bold")
    d.text("subhead", rng.choice(SUBHEADS), SANS, 26 * u, rgba(*INK), 160 * u, H * 0.68, W - 320 * u)
    _cta(d, rng.choice(CTAS), W / 2, H * 0.78, 24 * u)
    return d


def c_one_group(rng, W, H):
    d = c_two_ctas(rng, W, H)
    for e in d.els[1:]:
        e["group_id"] = "everything"
    return d


def c_edge_bars(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.shape("header", 0, 0, W, 140 * u, INK)
    d.logo(W / 2, 30 * u, 260 * u)
    d.image("product", BOTTLE, W * 0.3, H * 0.2, W * 0.4, W * 0.4)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 80 * u, rgba(*WHITE), 60 * u, H * 0.62, W - 120 * u, weight="bold")
    d.shape("footer", 0, H - 90 * u, W, 90 * u, PLUM)
    d.text("legal", rng.choice(LEGAL), SANS, 16 * u, rgba(*WHITE), 40 * u, H - 60 * u, W - 80 * u)
    return d


def c_diagonal(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    h = d.text("headline", rng.choice(HEAD_SHORT), SERIF, 100 * u, rgba(*WHITE), 60 * u, H * 0.3, W - 120 * u,
               weight="bold")
    h["rotation"] = -8
    for i, (lab, rot) in enumerate([("NEW", 15), ("HOT", -30), ("WOW", 45)]):
        d.pill("sticker", lab, W * (0.15 + 0.3 * i), H * 0.62, 30 * u, [RED, GOLD, ORANGE][i], rotation=rot)
    _cta(d, rng.choice(CTAS), W / 2, H * 0.82, 26 * u)
    return d


def c_price_list(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.text("headline", "Tasting Menu", SERIF, 80 * u, rgba(*WHITE), 60 * u, 50 * u, W - 120 * u, weight="bold")
    step = (H - 260 * u) / 12
    for i in range(12):
        y = 180 * u + i * step
        d.text("item", f"{FLAVORS[i % len(FLAVORS)]} {['Spritz', 'Tonic', 'Fizz'][i % 3]}", SANS, 24 * u,
               rgba(*WHITE), 100 * u, y, W * 0.55, align="left")
        d.text("price", PRICES[i % len(PRICES)], SANS, 24 * u, rgba(*GOLD), W * 0.7, y, W * 0.2, align="right")
    return d


def c_single_text(rng, W, H):
    d, u = Design(W, H, rng), min(W, H) / 1080
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 120 * u, rgba(*INK), 60 * u, H * 0.4, W - 120 * u, weight="bold")
    return d


def c_flat_type(rng, W, H):
    """No headline: four lines of copy at one size (what leads?)."""
    d, u = _base(rng, W, H), min(W, H) / 1080
    for i, line in enumerate(rng.sample(SUBHEADS, 4)):
        d.text("line", line, SANS, 34 * u, rgba(*WHITE), 80 * u, H * 0.2 + i * 110 * u, W - 160 * u)
    _cta(d, rng.choice(CTAS), W / 2, H * 0.75, 26 * u)
    return d


def c_three_ctas(rng, W, H):
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.logo(W / 2, 60 * u, 280 * u)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 96 * u, rgba(*WHITE), 60 * u, H * 0.3, W - 120 * u, weight="bold")
    labels = ["Shop Now", "Find a Store", "Learn More"]
    widths = [d.pill_size(lab, 24 * u)[0] for lab in labels]
    x = W / 2 - (sum(widths) + 40 * u) / 2
    for lab, w, fill in zip(labels, widths, (ORANGE, INK, GOLD)):
        d.pill("cta", lab, x, H * 0.62, 24 * u, fill)
        x += w + 20 * u
    return d


def c_corner_cluster(rng, W, H):
    """Everything packed into the top-left quarter; the rest is empty."""
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.logo(60 * u + 110 * u, 50 * u, 220 * u)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 60 * u, rgba(*WHITE), 60 * u, 140 * u, W * 0.45, weight="bold",
           align="left")
    d.text("subhead", rng.choice(SUBHEADS), SANS, 22 * u, rgba(*WHITE), 60 * u, 300 * u, W * 0.4, align="left")
    d.pill("cta", rng.choice(CTAS), 60 * u, 400 * u, 22 * u, ORANGE)
    return d


def c_two_logos(rng, W, H):
    """Co-branding: two logos in opposite top corners."""
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.logo(60 * u + 120 * u, 50 * u, 240 * u)
    d.logo(W - 60 * u - 120 * u, 50 * u, 240 * u)
    d.image("product", BOTTLE, W * 0.3, H * 0.2, W * 0.4, W * 0.4)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 80 * u, rgba(*WHITE), 60 * u, H * 0.65, W - 120 * u, weight="bold")
    _cta(d, rng.choice(CTAS), W / 2, H * 0.83, 26 * u)
    return d


def c_dense_decor(rng, W, H):
    """Forty decorative dots scattered over and around the content."""
    d, u = _base(rng, W, H), min(W, H) / 1080
    for _ in range(40):
        s = rng.uniform(8, 60) * u
        d.shape("dot", rng.uniform(0, W - s), rng.uniform(0, H - s), s, s, WHITE, alpha=rng.uniform(0.08, 0.3),
                kind="ellipse")
    d.image("product", BOTTLE, W * 0.32, H * 0.15, W * 0.36, W * 0.36)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 84 * u, rgba(*WHITE), 60 * u, H * 0.6, W - 120 * u, weight="bold")
    _cta(d, rng.choice(CTAS), W / 2, H * 0.8, 26 * u)
    return d


def c_bullets(rng, W, H):
    """A left-aligned list of six short lines."""
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.text("headline", "Why Solstice", SERIF, 76 * u, rgba(*WHITE), 80 * u, 90 * u, W - 160 * u, weight="bold",
           align="left")
    items = ["Real fruit", "No added sugar", "Small batches", "Sparkling botanicals", "Recyclable cans", "Made locally"]
    for i, it in enumerate(items):
        d.text("bullet", f"• {it}", SANS, 30 * u, rgba(*WHITE), 90 * u, 240 * u + i * 62 * u, W - 180 * u, align="left")
    d.pill("cta", rng.choice(CTAS), 80 * u, 240 * u + 6 * 62 * u + 40 * u, 24 * u, ORANGE)
    return d


def c_text_over_product(rng, W, H):
    """The headline deliberately laid over the lower half of the product art."""
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.image("product", BOTTLE, W * 0.2, H * 0.08, W * 0.6, W * 0.6)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 110 * u, rgba(*WHITE), 40 * u, H * 0.42, W - 80 * u, weight="bold")
    _cta(d, rng.choice(CTAS), W / 2, H * 0.82, 26 * u)
    return d


def c_right_aligned(rng, W, H):
    """Copy right-aligned against the right margin, product on the left."""
    d, u = _base(rng, W, H), min(W, H) / 1080
    d.image("product", BOTTLE, 40 * u, H * 0.25, W * 0.42, W * 0.42)
    d.text("headline", rng.choice(HEAD_SHORT), SERIF, 72 * u, rgba(*WHITE), W * 0.45, H * 0.3, W * 0.5, weight="bold",
           align="right")
    d.text("subhead", rng.choice(SUBHEADS), SANS, 26 * u, rgba(*WHITE), W * 0.45, H * 0.5, W * 0.5, align="right")
    w, _ = d.pill_size("Shop Now", 24 * u)
    d.pill("cta", "Shop Now", W * 0.95 - w, H * 0.62, 24 * u, ORANGE)
    return d


CRAZY = {name[2:]: fn for name, fn in globals().items() if name.startswith("c_") and callable(fn)}
SOURCES = [(1080, 1080), (1080, 1350), (1920, 1080), (1080, 1920)]


def generate(out_dir: Path, seed: int):
    tasks_dir = Path(out_dir) / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    rng_master, manifest = random.Random(seed), []
    for i, (arch, fn) in enumerate(CRAZY.items()):
        rng = random.Random(rng_master.random())
        W, H = SOURCES[i % len(SOURCES)]
        src = fn(rng, W, H).to_source()
        sw, sh = src["canvas"]["width"], src["canvas"]["height"]
        for tw, th in TARGETS:
            tid = f"crazy_{arch}__{tw}x{th}"
            lvl = 3 if min(tw, th) < 100 or max(tw / th, th / tw) > 4 else (2 if (tw > th) != (sw > sh) else 1)
            task = {"task_id": tid, "archetype": arch, "ratio_level": lvl, "source": copy.deepcopy(src),
                    "target_canvas": {"width": tw, "height": th}}
            (tasks_dir / f"{tid}.json").write_text(json.dumps(task, ensure_ascii=False))
            manifest.append({"task_id": tid, "archetype": arch, "complexity": 3, "ratio_level": lvl, "difficulty": lvl,
                             "source": [sw, sh], "target": [tw, th], "target_name": f"{tw}x{th}",
                             "n_elements": len(src["elements"])})
    (Path(out_dir) / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {len(manifest)} tasks ({len(CRAZY)} designs) to {tasks_dir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "eval" / "testsets" / "crazy"))
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    generate(Path(a.out), a.seed)


if __name__ == "__main__":
    main()
