"""Procedural CHAMELEON test-set generator.

Builds realistic Solstice-brand source designs from a dozen archetypes
(centered posters, split heroes, banners, typographic flyers, cards with
contained-but-ungrouped content, scrims, product grids, event flyers, sale
promos, minimal, story stacks, adversarial messes) at many source formats,
then pairs each design with target canvases drawn from the format catalogue
at three distances: near ratio, far ratio and extreme/unseen.

Text boxes are sized with the same metrics the renderer uses, so every
source design renders cleanly (no overflow) - any problem in an output is
the engine's doing.

Usage:
    python -m eval.gen_testset --out eval/testsets/main --designs-per-archetype 10 --seed 7
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.chameleon_layout import text_metrics as tm  # noqa: E402
from eval.catalogue import FORMATS, ratio_distance  # noqa: E402

BG = "solstice_bg_gradient.png"
LOGO = "solstice_logo_lockup.png"
BOTTLE = "solstice_bottle.png"
MISSING = ["solstice_holiday_badge_2025.png", "solstice_qr_code.png", "partner_logo_acme.png", "solstice_seal_award.png"]

SERIF, SANS = "Solstice Serif", "Solstice Sans"


def rgba(r, g, b, a=1.0):
    a = round(a, 2)
    return f"rgba({r},{g},{b},{a:g})"


PLUM = (43, 27, 46)
DEEP = (30, 18, 34)
ORANGE = (232, 106, 58)
GOLD = (240, 178, 66)
CREAM = (245, 236, 220)
WHITE = (255, 255, 255)
RED = (220, 60, 50)
SAGE = (122, 150, 110)
INK = (35, 24, 38)

HEAD_SHORT = ["Chase the Light", "Golden Hour", "Taste the Sunset", "Hello Summer", "Sip Slowly", "New Season",
              "Pure Glow", "Bright Days Ahead", "Made for Sunsets", "Summer, Bottled", "Stay Golden", "Light & Bright"]
HEAD_LONG = [
    "Introducing the All-New Limited-Batch Solstice Chase the Light Botanical Sparkling Collection — Crafted Exclusively for Golden Hour Gatherings",
    "The Botanical Sparkling Collection Crafted for Long Summer Evenings With Friends",
    "Everything You Love About Golden Hour, Now in a Bottle You Can Take Anywhere You Go This Summer",
    "Celebrate Twenty-Five Years of Small-Batch Botanical Brewing at the Annual Solstice Summer Festival",
]
SUBHEADS = ["Botanical sparkling infusions, crafted for golden hour.", "Small-batch. Low sugar. All flavor.",
            "Blood orange, wild honey and a hint of rosemary.", "Sparkling botanicals for long summer evenings.",
            "Naturally bright, never too sweet.", "Four new flavors, one perfect sunset.",
            "Crafted in small batches with real fruit and botanicals."]
BODY = [
    "Small-batch botanical infusions blended with wild honey, blood orange zest, and a whisper of smoked rosemary, bottled at the peak of golden hour for a taste that lingers long after sunset.",
    "Each bottle is brewed in small batches using hand-picked botanicals and real fruit. No artificial flavors, no shortcuts, just bright sparkling refreshment for warm evenings.",
    "Join us for an evening of tastings, live acoustic music and sunset views. Bring friends, bring a blanket, and discover your new favorite flavor.",
]
CTAS = ["Shop the Summer Line", "Shop Now", "Learn More", "Order Today", "Get 20% Off", "Find a Store", "Try It Free",
        "Discover the Collection", "Reserve Your Spot", "Buy Tickets"]
BADGES = ["NEW FLAVOR", "LIMITED EDITION", "AWARD WINNING 2026", "SMALL BATCH", "ZERO SUGAR", "VEGAN", "BEST SELLER",
          "ORGANIC", "100% NATURAL", "LOCALLY MADE", "GLUTEN FREE"]
RIBBONS = ["SUNSET SALE", "20% OFF", "NEW", "HOT DEAL", "LAST CHANCE", "FREE SHIPPING"]
LEGAL = ["Please drink responsibly. Botanical Sparkling Co., 2026. Void where prohibited. See solstice.com/terms for full details.",
         "Offer valid through 08/31/2026 while supplies last. Terms and conditions apply.",
         "© 2026 Solstice Botanical Co. All rights reserved."]
EVENT_LINES = ["SATURDAY, JUNE 21 · 6PM", "Riverside Park Amphitheater", "Free entry · Live music · Tastings",
               "FRIDAY, JULY 4 · 7PM – 11PM", "Harbor Pier, Dock 9", "Tickets $25 · Kids free"]
PRICES = ["$4.99", "2 for $8", "From $24", "$12.50", "$3.49"]
FLAVORS = ["Blood Orange", "Wild Honey", "Yuzu Mint", "Hibiscus", "Pink Grapefruit", "Elderflower"]
BIG_NUMBERS = ["50% OFF", "BOGO", "SAVE 30%", "$5 OFF", "2 FOR 1"]
ADVERSARIAL_TEXT = ["Supercalifragilisticexpialidociousbotanicalinfusion", "Ünïcödé Çafé — naïve résumé, déjà vu",
                    "Fresh 🍊 citrus ✨ vibes", "Line one\nLine two\nLine three", "WWWWWWWWWWWWWWWWWWWW",
                    "a b c d e f g h i j k l m n o p q r s t u v w x y z"]


class Design:
    def __init__(self, W, H, rng: random.Random):
        self.W, self.H, self.rng = W, H, rng
        self.u = min(W, H) / 1080.0
        self.els = []
        self._z = 0
        self._ids = {}

    def uid(self, base):
        n = self._ids.get(base, 0)
        self._ids[base] = n + 1
        return base if n == 0 else f"{base}_{n + 1}"

    def add(self, el, z=None):
        if z is None:
            self._z += 1
            z = self._z
        el["z_index"] = z
        for k in ("x", "y", "width", "height"):
            el[k] = round(float(el[k]), 1)
        self.els.append(el)
        return el

    # ---- primitives -------------------------------------------------------
    def bg_image(self):
        return self.add({"id": self.uid("bg"), "type": "image", "x": 0, "y": 0, "width": self.W, "height": self.H,
                         "asset_id": BG, "fit": "cover"}, z=0)

    def bg_solid(self, color):
        return self.add({"id": self.uid("bg"), "type": "shape", "x": 0, "y": 0, "width": self.W, "height": self.H,
                         "shape_type": "rectangle", "fill_color": rgba(*color)}, z=0)

    def shape(self, base, x, y, w, h, color, alpha=1.0, kind="rectangle", radius=0, opacity=None, group=None, **extra):
        el = {"id": self.uid(base), "type": "shape", "x": x, "y": y, "width": w, "height": h, "shape_type": kind,
              "fill_color": rgba(*color, alpha)}
        if radius:
            el["corner_radius"] = round(radius, 1)
        if opacity is not None:
            el["opacity"] = round(opacity, 2)
        if group:
            el["group_id"] = group
        el.update(extra)
        return self.add(el)

    def image(self, base, asset, x, y, w, h, fit="contain", group=None, **extra):
        el = {"id": self.uid(base), "type": "image", "x": x, "y": y, "width": w, "height": h, "asset_id": asset, "fit": fit}
        if group:
            el["group_id"] = group
        el.update(extra)
        return self.add(el)

    def measure(self, content, family, size, weight, width, lh=1.2, ls=0.0, style=None):
        return tm.layout_text(content, family, weight, style, size, width, lh, ls)

    def text(self, base, content, family, size, color, x, y, w, weight="regular", align="center", max_lines=None,
             lh=1.2, ls=0.0, style=None, runs=None, group=None, min_size=8, **extra):
        size = max(min_size, int(round(size)))
        lay = self.measure(content, family, size, weight, w, lh, ls, style)
        while max_lines and lay.n_lines > max_lines and size > min_size:
            size = max(min_size, int(size * 0.92))
            lay = self.measure(content, family, size, weight, w, lh, ls, style)
        # widen the box if a single word overflows (renderer never breaks words)
        need = tm.longest_word_width(content, family, weight, style, size, ls)
        while need > w and size > min_size:
            size = max(min_size, int(size * 0.92))
            need = tm.longest_word_width(content, family, weight, style, size, ls)
            lay = self.measure(content, family, size, weight, w, lh, ls, style)
        if need > w:
            if align == "center":
                x -= (need - w) / 2
            w = need + 2
            lay = self.measure(content, family, size, weight, w, lh, ls, style)
        el = {"id": self.uid(base), "type": "text", "x": x, "y": y, "width": w, "height": math.ceil(lay.box_height) + 2,
              "content": content, "font_family": family, "font_size": size, "color": color, "text_align": align}
        if weight != "regular":
            el["font_weight"] = weight
        if style:
            el["font_style"] = style
        if lh != 1.2:
            el["line_height"] = lh
        if ls:
            el["letter_spacing"] = ls
        if runs:
            el["style_runs"] = runs
        if group:
            el["group_id"] = group
        el.update(extra)
        return self.add(el)

    def pill(self, base, label, x, y, size, fill, text_color=WHITE, padx=1.6, hfac=2.4, radius_frac=0.5,
             group=None, rotation=0.0, ls=0.0, weight="bold", family=SANS, min_w=0):
        """Button/badge: rounded rect + centered label, sharing a group_id."""
        size = int(round(size))
        tw = tm.natural_width(label, family, weight, None, size, ls)
        w = max(min_w, tw + 2 * padx * size)
        h = size * hfac
        g = group or self.uid(base)
        shp = {"id": self.uid(base + "_bg"), "type": "shape", "x": x, "y": y, "width": w, "height": h,
               "shape_type": "rectangle", "fill_color": rgba(*fill), "corner_radius": round(h * radius_frac, 1), "group_id": g}
        if rotation:
            shp["rotation"] = rotation
        self.add(shp)
        lay = self.measure(label, family, size, weight, w, 1.2, ls)
        ty = y + h / 2 - lay.cap_center
        lab = {"id": self.uid(base + "_label"), "type": "text", "x": x, "y": ty, "width": w,
               "height": math.ceil(lay.box_height), "content": label, "font_family": family, "font_size": size,
               "font_weight": weight, "color": rgba(*text_color), "text_align": "center", "group_id": g}
        if ls:
            lab["letter_spacing"] = ls
        if rotation:
            lab["rotation"] = rotation
        self.add(lab)
        self.els[-1]["x"] = round(self.els[-1]["x"], 1)
        return shp, lab

    def pill_size(self, label, size, padx=1.6, hfac=2.4, ls=0.0, weight="bold", family=SANS, min_w=0):
        tw = tm.natural_width(label, family, weight, None, int(round(size)), ls)
        return max(min_w, tw + 2 * padx * int(round(size))), int(round(size)) * hfac

    def decor_circles(self, n, color=WHITE, alpha_range=(0.08, 0.18), bleed=True):
        for _ in range(n):
            r = self.rng.uniform(0.15, 0.45) * min(self.W, self.H)
            if bleed and self.rng.random() < 0.6:
                cx = self.rng.choice([0, self.W]) + self.rng.uniform(-0.1, 0.1) * self.W
                cy = self.rng.choice([0, self.H]) + self.rng.uniform(-0.1, 0.1) * self.H
            else:
                cx, cy = self.rng.uniform(0.1, 0.9) * self.W, self.rng.uniform(0.1, 0.9) * self.H
            self.shape("deco_circle", cx - r, cy - r, 2 * r, 2 * r, color, kind="ellipse",
                       opacity=self.rng.uniform(*alpha_range))

    def dots(self, n, color=WHITE):
        for _ in range(n):
            r = self.rng.uniform(4, 14) * self.u
            self.shape("dot", self.rng.uniform(0, self.W - 2 * r), self.rng.uniform(0, self.H - 2 * r), 2 * r, 2 * r,
                       color, kind="ellipse", opacity=round(self.rng.uniform(0.2, 0.5), 2))

    def ribbon(self, label, corner="tr", size=None):
        size = size or 20 * self.u
        w = max(self.pill_size(label, size, padx=2.2, hfac=2.6)[0], 260 * self.u)
        h = size * 2.6
        rot = -12 if corner == "tr" else 12
        x = self.W - w - 40 * self.u if corner == "tr" else 40 * self.u
        y = 34 * self.u
        g = self.uid("ribbon")
        self.add({"id": self.uid("ribbon_bg"), "type": "shape", "x": x, "y": y, "width": w, "height": h, "rotation": rot,
                  "shape_type": "rectangle", "fill_color": rgba(*RED), "group_id": g})
        lay = self.measure(label, SANS, int(size), "bold", w)
        self.add({"id": self.uid("ribbon_label"), "type": "text", "x": x, "y": y + h / 2 - lay.cap_center, "width": w,
                  "height": math.ceil(lay.box_height), "rotation": rot, "content": label, "font_family": SANS,
                  "font_size": int(size), "font_weight": "bold", "color": rgba(*WHITE), "text_align": "center",
                  "group_id": g})

    def logo(self, cx, y, w):
        h = w / 3.2
        return self.image("logo", LOGO, cx - w / 2, y, w, h)

    def to_source(self):
        return {"canvas": {"width": self.W, "height": self.H}, "elements": self.els}


# ---------------------------------------------------------------------------
# Vertical stacking helper: rows are callables (d, x0, y, width, s) -> height
# that add their elements; we dry-run to measure, shrink until they fit, then
# lay them out for real with the leftover space distributed.
# ---------------------------------------------------------------------------

def vstack(d: Design, rows, x0, top, width, bottom, s0=1.0, gap=None, anchor="spread"):
    s = s0
    for _ in range(30):
        probe = Design(d.W, d.H, random.Random(0))
        probe._ids = dict(d._ids)
        heights = [r(probe, x0, 0, width, s) for r in rows]
        g = (gap if gap is not None else 36) * d.u * s
        total = sum(heights) + g * (len(rows) - 1)
        if total <= bottom - top or s < 0.3:
            break
        s *= 0.92
    free = max(0.0, (bottom - top) - total)
    if anchor == "center":
        y = top + free / 2
        extra = 0
    elif anchor == "top":
        y = top
        extra = 0
    else:
        y = top
        extra = free / max(1, len(rows) - 1) if len(rows) > 1 else 0
        if len(rows) == 1:
            y = top + free / 2
    for r, h in zip(rows, heights):
        r(d, x0, y, width, s)
        y += h + g + extra
    return s


def row_logo(wfrac=0.3):
    def f(d, x0, y, w, s):
        lw = min(w * wfrac / max(s, 0.5), 340 * d.u) * s
        d.logo(x0 + w / 2, y, lw)
        return lw / 3.2
    return f


def row_text(base, content, family, size, color, weight="regular", wfrac=0.85, max_lines=None, align="center",
             runs=None, lh=1.2, ls=0.0, style=None):
    def f(d, x0, y, w, s):
        tw = w * wfrac
        tx = x0 + (w - tw) / 2 if align == "center" else (x0 if align == "left" else x0 + w - tw)
        el = d.text(base, content, family, size * d.u * s, color, tx, y, tw, weight=weight, align=align,
                    max_lines=max_lines, runs=runs, lh=lh, ls=ls, style=style)
        return el["height"]
    return f


def row_image(asset, hfrac_px, aspect=1.0, base="product", fit="contain"):
    def f(d, x0, y, w, s):
        h = hfrac_px * d.u * s
        iw = h * aspect
        if iw > w:
            iw = w
            h = iw / aspect
        d.image(base, asset, x0 + (w - iw) / 2, y, iw, h, fit=fit)
        return h
    return f


def row_button(label, size, fill=ORANGE, text_color=WHITE, align="center", radius_frac=0.5, min_w_frac=0.0):
    def f(d, x0, y, w, s):
        sz = size * d.u * s
        bw, bh = d.pill_size(label, sz, padx=1.8, hfac=2.6, min_w=min_w_frac * w)
        bx = x0 + (w - bw) / 2 if align == "center" else (x0 if align == "left" else x0 + w - bw)
        d.pill("cta", label, bx, y, sz, fill, text_color, padx=1.8, hfac=2.6, radius_frac=radius_frac, min_w=min_w_frac * w)
        return bh
    return f


def row_badges(labels, size, fills, align="center"):
    def f(d, x0, y, w, s):
        sz = size * d.u * s
        gap = 14 * d.u * s
        sizes = [d.pill_size(l, sz, padx=1.4, hfac=2.4) for l in labels]
        # wrap into lines that fit the width
        lines, cur, cw = [], [], 0
        for l, (bw, bh) in zip(labels, sizes):
            if cur and cw + gap + bw > w:
                lines.append(cur)
                cur, cw = [], 0
            cur.append((l, bw, bh))
            cw += (gap if len(cur) > 1 else 0) + bw
        if cur:
            lines.append(cur)
        yy = y
        k = 0
        for line in lines:
            lw = sum(b for _, b, _ in line) + gap * (len(line) - 1)
            xx = x0 + (w - lw) / 2 if align == "center" else x0
            for l, bw, bh in line:
                d.pill("badge", l, xx, yy, sz, fills[k % len(fills)], padx=1.4, hfac=2.4)
                xx += bw + gap
                k += 1
            yy += line[0][2] + gap
        return yy - y - gap
    return f


def row_divider(color=WHITE, wfrac=0.25, thick=3):
    def f(d, x0, y, w, s):
        lw = w * wfrac
        d.shape("divider", x0 + (w - lw) / 2, y, lw, max(2, thick * d.u), color, kind="line",
                stroke_color=rgba(*color), stroke_width=max(2, round(thick * d.u)))
        return max(2, thick * d.u)
    return f


def two_tone(content, color2):
    words = content.split(" ")
    if len(words) < 2:
        return None
    k = len(words) // 2
    start = len(" ".join(words[:k])) + 1
    return [{"start": start, "end": len(content), "color": rgba(*color2)}]


# ---------------------------------------------------------------------------
# Archetypes.  Each returns a Design; ``cx`` (complexity 1..3) scales how
# many / how awkward the elements are.
# ---------------------------------------------------------------------------

def a_poster_center(rng, W, H, cx):
    d = Design(W, H, rng)
    d.bg_image()
    if cx >= 2:
        d.decor_circles(rng.randint(1, 3))
    if cx >= 3 and rng.random() < 0.7:
        d.ribbon(rng.choice(RIBBONS))
    head = rng.choice(HEAD_LONG if cx >= 3 and rng.random() < 0.6 else HEAD_SHORT)
    runs = two_tone(head, GOLD) if rng.random() < 0.5 else None
    rows = [row_logo(0.3)]
    rows.append(row_image(BOTTLE, rng.uniform(380, 520) * (H / W if H > W else 1) ** 0.5, 1.0))
    rows.append(row_text("headline", head, SERIF, rng.choice([56, 64, 72]) if len(head) < 30 else 40, rgba(*WHITE),
                         weight="bold", wfrac=0.84, max_lines=4, runs=runs))
    if cx >= 2 or rng.random() < 0.5:
        rows.append(row_text("subhead", rng.choice(BODY if cx >= 3 else SUBHEADS), SANS, 24, rgba(255, 255, 255, 0.85),
                             wfrac=0.78, max_lines=4))
    if cx >= 2 and rng.random() < 0.8:
        k = rng.randint(2, 3) if cx == 2 else rng.randint(3, 5)
        rows.append(row_badges(rng.sample(BADGES, k), 15, [ORANGE, PLUM, GOLD]))
    rows.append(row_button(rng.choice(CTAS), 22))
    vstack(d, rows, W * 0.06, H * 0.04, W * 0.88, H * (0.93 if cx >= 3 else 0.95))
    if cx >= 3:
        d.text("legal_text", rng.choice(LEGAL), SANS, 12 * d.u, rgba(255, 255, 255, 0.6), W * 0.05, H - 40 * d.u, W * 0.9,
               max_lines=2)
        if rng.random() < 0.6:
            d.image("watermark", rng.choice(MISSING), W - 200 * d.u, H - 130 * d.u, 160 * d.u, 70 * d.u)
    return d


def a_split_hero(rng, W, H, cx):
    d = Design(W, H, rng)
    dark = rng.random() < 0.7
    if dark:
        d.bg_image()
    else:
        d.bg_solid(CREAM)
    fg = rgba(*WHITE) if dark else rgba(*INK)
    left_img = rng.random() < 0.5
    landscape = W >= H
    if landscape:
        img_box = (W * 0.04, H * 0.08, W * 0.42, H * 0.84) if left_img else (W * 0.54, H * 0.08, W * 0.42, H * 0.84)
        col = (W * 0.52, W * 0.42) if left_img else (W * 0.06, W * 0.42)
        side = min(img_box[2], img_box[3])
        if cx >= 2:
            d.shape("panel", img_box[0], img_box[1], img_box[2], img_box[3], ORANGE if dark else PLUM, radius=24 * d.u,
                    opacity=0.9 if rng.random() < 0.5 else None)
        d.image("product", BOTTLE, img_box[0] + (img_box[2] - side) / 2, img_box[1] + (img_box[3] - side) / 2, side, side)
        rows = []
        if dark:
            rows.append(row_logo(0.42))
        else:
            rows.append(row_text("wordmark", "SOLSTICE", SANS, 22, rgba(*PLUM), weight="bold", wfrac=1.0, align="left", ls=6))
        head = rng.choice(HEAD_SHORT if cx < 3 else HEAD_LONG)
        rows.append(row_text("headline", head, SERIF, 64 if len(head) < 30 else 40, fg, weight="bold", wfrac=1.0,
                             align="left", max_lines=4, runs=two_tone(head, GOLD if dark else ORANGE) if rng.random() < 0.4 else None))
        rows.append(row_text("subhead", rng.choice(SUBHEADS if cx < 3 else BODY), SANS, 24, fg, wfrac=1.0, align="left", max_lines=5))
        if cx >= 2 and rng.random() < 0.6:
            rows.append(row_badges(rng.sample(BADGES, rng.randint(1, 3)), 15, [ORANGE, PLUM], align="left"))
        rows.append(row_button(rng.choice(CTAS), 22, align="left"))
        vstack(d, rows, col[0], H * 0.1, col[1], H * 0.9, gap=30, anchor="center")
    else:
        # portrait: image top half, text bottom half, left aligned
        side = min(W * 0.8, H * 0.42)
        d.image("product", BOTTLE, (W - side) / 2, H * 0.06, side, side)
        head = rng.choice(HEAD_SHORT if cx < 3 else HEAD_LONG)
        rows = [row_text("headline", head, SERIF, 64 if len(head) < 30 else 40, fg, weight="bold", wfrac=1.0, align="left", max_lines=4),
                row_text("subhead", rng.choice(SUBHEADS), SANS, 24, fg, wfrac=1.0, align="left", max_lines=4),
                row_button(rng.choice(CTAS), 22, align="left")]
        vstack(d, rows, W * 0.08, H * 0.06 + side + 40 * d.u, W * 0.84, H * 0.86, anchor="top")
        if dark:
            d.logo(W * 0.08 + 120 * d.u, H - 110 * d.u, 240 * d.u)
        else:
            d.text("wordmark", "SOLSTICE", SANS, 22 * d.u, rgba(*PLUM), W * 0.08, H - 80 * d.u, W * 0.4, weight="bold", align="left", ls=6)
    if cx >= 3:
        d.dots(rng.randint(3, 8), WHITE if dark else PLUM)
        if rng.random() < 0.5:
            d.ribbon(rng.choice(RIBBONS), corner="tr" if left_img else "tl")
    return d


def a_banner_row(rng, W, H, cx):
    """Wide source banner: logo | product | text | CTA."""
    d = Design(W, H, rng)
    d.bg_image()
    if cx >= 2:
        d.decor_circles(rng.randint(1, 2))
    m = H * 0.12
    lw = min(W * 0.18, H * 0.9 * 3.2)
    d.logo(m + lw / 2, (H - lw / 3.2) / 2, lw)
    x = m + lw + W * 0.03
    side = H * 0.84
    d.image("product", BOTTLE, x, (H - side) / 2, side, side)
    x += side + W * 0.02
    bw, bh = d.pill_size(rng.choice(CTAS), 22 * H / 400)
    cta_label = rng.choice(CTAS)
    bw, bh = d.pill_size(cta_label, 22 * H / 400, padx=1.8, hfac=2.6)
    tx_w = W - x - bw - m - W * 0.04
    head = rng.choice(HEAD_SHORT)
    el = d.text("headline", head, SERIF, 60 * H / 400, rgba(*WHITE), x, H * 0.2, tx_w, weight="bold", align="left", max_lines=2)
    if cx >= 2:
        d.text("subhead", rng.choice(SUBHEADS), SANS, 22 * H / 400, rgba(255, 255, 255, 0.85), x, el["y"] + el["height"] + 8,
               tx_w, align="left", max_lines=2)
    d.pill("cta", cta_label, W - m - bw, (H - bh) / 2, 22 * H / 400, ORANGE, padx=1.8, hfac=2.6)
    if cx >= 3:
        d.pill("badge", rng.choice(BADGES), m, m * 0.4, 12 * H / 400, GOLD, text_color=PLUM, padx=1.2, hfac=2.2)
        d.text("legal_text", rng.choice(LEGAL), SANS, 11 * H / 400, rgba(255, 255, 255, 0.6), x, H - m * 0.9, tx_w,
               align="left", max_lines=1)
    return d


def a_typographic(rng, W, H, cx):
    d = Design(W, H, rng)
    scheme = rng.choice(["plum", "cream", "orange"])
    bgc, fg, acc = {"plum": (PLUM, WHITE, GOLD), "cream": (CREAM, INK, ORANGE), "orange": (ORANGE, WHITE, PLUM)}[scheme]
    d.bg_solid(bgc)
    if cx >= 2:
        d.shape("frame", W * 0.03, H * 0.03, W * 0.94, H * 0.94, acc, alpha=1.0, opacity=0.15, radius=0)
    head = rng.choice(HEAD_SHORT if cx < 3 else HEAD_LONG)
    rows = []
    rows.append(row_text("kicker", rng.choice(["INTRODUCING", "THIS SUMMER", "NOW AVAILABLE", "SAVE THE DATE"]), SANS, 20,
                         rgba(*acc), weight="bold", ls=4))
    rows.append(row_text("headline", head, SERIF, 96 if len(head) < 20 else (72 if len(head) < 40 else 48), rgba(*fg),
                         weight="bold", wfrac=0.86, max_lines=4, lh=1.1, runs=two_tone(head, acc) if rng.random() < 0.5 else None))
    rows.append(row_divider(acc))
    rows.append(row_text("subhead", rng.choice(SUBHEADS), SERIF, 30, rgba(*fg), style="italic", wfrac=0.8, max_lines=3))
    if cx >= 2:
        rows.append(row_text("body", rng.choice(BODY), SANS, 22, rgba(*fg, 0.85), wfrac=0.75, max_lines=6, lh=1.4))
    if cx >= 2 and rng.random() < 0.6:
        rows.append(row_text("date_line", rng.choice(EVENT_LINES[::3]), SANS, 26, rgba(*acc), weight="bold", ls=2))
    rows.append(row_text("wordmark", "SOLSTICE", SANS, 22, rgba(*fg), weight="bold", ls=8))
    vstack(d, rows, W * 0.07, H * 0.08, W * 0.86, H * 0.92, gap=28)
    if cx >= 3:
        d.text("legal_text", rng.choice(LEGAL), SANS, 11 * d.u, rgba(*fg, 0.6), W * 0.1, H - 34 * d.u, W * 0.8, max_lines=2)
    return d


def a_card_overlay(rng, W, H, cx):
    """Cream card on dark bg with content inside the card - contained, NOT grouped."""
    d = Design(W, H, rng)
    d.bg_image()
    if cx >= 2:
        d.decor_circles(rng.randint(1, 3), color=GOLD, alpha_range=(0.08, 0.15))
    landscape = W > H * 1.2
    logo_h = 0
    if not landscape:
        lw = 260 * d.u
        d.logo(W / 2, H * 0.04, lw)
        logo_h = lw / 3.2 + H * 0.04
        card = (W * 0.08, logo_h + H * 0.03, W * 0.84, H - logo_h - H * 0.08)
    else:
        card = (W * 0.06, H * 0.08, W * 0.88, H * 0.84)
    d.shape("card", *card, CREAM, radius=32 * d.u, opacity=rng.choice([None, 0.95]))
    cx0, cy0, cw, ch = card
    pad = 0.07 * min(cw, ch)
    rows = []
    if landscape:
        side = ch - 2 * pad
        d.image("product", BOTTLE, cx0 + pad, cy0 + pad, side, side)
        rows += [row_logo_dark_wordmark(), row_text("headline", rng.choice(HEAD_SHORT), SERIF, 60, rgba(*INK), weight="bold", wfrac=1, align="left", max_lines=3),
                 row_text("subhead", rng.choice(SUBHEADS), SANS, 24, rgba(*INK, 0.8), wfrac=1, align="left", max_lines=3),
                 row_button(rng.choice(CTAS), 22, align="left")]
        vstack(d, rows, cx0 + pad + side + pad, cy0 + pad, cw - side - 3 * pad, cy0 + ch - pad, anchor="center")
    else:
        rows += [row_image(BOTTLE, 420, 1.0),
                 row_text("headline", rng.choice(HEAD_SHORT if cx < 3 else HEAD_LONG), SERIF, 60, rgba(*INK), weight="bold", wfrac=0.9, max_lines=3),
                 row_text("subhead", rng.choice(SUBHEADS), SANS, 24, rgba(*INK, 0.8), wfrac=0.85, max_lines=3)]
        if cx >= 2:
            rows.append(row_text("price", rng.choice(PRICES), SERIF, 44, rgba(*ORANGE), weight="bold"))
        rows.append(row_button(rng.choice(CTAS), 22))
        vstack(d, rows, cx0 + pad, cy0 + pad, cw - 2 * pad, cy0 + ch - pad)
    if cx >= 3:
        d.pill("badge", rng.choice(BADGES), cx0 + cw - 260 * d.u, cy0 - 22 * d.u, 15 * d.u, ORANGE, padx=1.4, hfac=2.4)
    return d


def row_logo_dark_wordmark():
    return row_text("wordmark", "SOLSTICE", SANS, 20, rgba(*PLUM), weight="bold", wfrac=1.0, align="left", ls=6)


def a_scrim_text(rng, W, H, cx):
    d = Design(W, H, rng)
    d.bg_image()
    side = min(W, H) * 0.8
    d.image("product", BOTTLE, (W - side) / 2, H * 0.02, side, side)
    band_h = H * rng.uniform(0.3, 0.42)
    d.shape("scrim", 0, H - band_h, W, band_h, DEEP, alpha=1.0, opacity=round(rng.uniform(0.6, 0.85), 2))
    rows = [row_text("headline", rng.choice(HEAD_SHORT), SERIF, 64, rgba(*WHITE), weight="bold", wfrac=0.9, max_lines=2),
            row_text("subhead", rng.choice(SUBHEADS), SANS, 24, rgba(255, 255, 255, 0.85), wfrac=0.85, max_lines=2),
            row_button(rng.choice(CTAS), 22)]
    vstack(d, rows, W * 0.06, H - band_h + band_h * 0.12, W * 0.88, H - band_h * 0.1, anchor="center", gap=24)
    lw = 220 * d.u
    d.logo(W * 0.05 + lw / 2, H * 0.04, lw)
    if cx >= 2:
        d.pill("badge", rng.choice(BADGES), W - 280 * d.u, H * 0.05, 16 * d.u, GOLD, text_color=PLUM)
    if cx >= 3:
        d.dots(rng.randint(4, 10))
        d.text("legal_text", rng.choice(LEGAL), SANS, 11 * d.u, rgba(255, 255, 255, 0.55), W * 0.05, H - 30 * d.u, W * 0.9, max_lines=1)
    return d


def a_product_grid(rng, W, H, cx):
    d = Design(W, H, rng)
    d.bg_solid(rng.choice([PLUM, DEEP]))
    n = rng.randint(2, 3) if cx < 3 else rng.randint(3, 4)
    head = rng.choice(["Meet the Lineup", "Four New Flavors", "Find Your Flavor", "The Summer Collection"])
    top = d.text("headline", head, SERIF, 64 * d.u, rgba(*WHITE), W * 0.08, H * 0.06, W * 0.84, weight="bold", max_lines=2)
    y0 = top["y"] + top["height"] + 30 * d.u
    cols = n if W >= H or n <= 2 else 2
    rows_n = math.ceil(n / cols)
    cta_label = rng.choice(CTAS)
    bw, bh = d.pill_size(cta_label, 22 * d.u, padx=1.8, hfac=2.6)
    avail_h = H - y0 - bh - 80 * d.u
    cell_w = W * 0.84 / cols
    label_h = 80 * d.u
    side = min(cell_w * 0.9, avail_h / rows_n - label_h - 20 * d.u)
    cell_h = side + label_h + 20 * d.u
    y0 += max(0.0, (avail_h - cell_h * rows_n) / 2)
    flavors = rng.sample(FLAVORS, n)
    for i in range(n):
        r, c = divmod(i, cols)
        gx, gy = W * 0.08 + c * cell_w, y0 + r * cell_h
        g = f"item{i + 1}"
        d.image(f"product{i + 1}", BOTTLE, gx + (cell_w - side) / 2, gy, side, side, group=g)
        t1 = d.text(f"name{i + 1}", flavors[i], SERIF, 30 * d.u, rgba(*WHITE), gx, gy + side + 8 * d.u, cell_w, weight="bold", max_lines=1, group=g)
        d.text(f"price{i + 1}", rng.choice(PRICES), SANS, 22 * d.u, rgba(*GOLD), gx, t1["y"] + t1["height"], cell_w, weight="bold", group=g)
    d.pill("cta", cta_label, (W - bw) / 2, H - bh - 40 * d.u, 22 * d.u, ORANGE, padx=1.8, hfac=2.6)
    if cx >= 2:
        d.logo(W - 150 * d.u, H - 70 * d.u, 200 * d.u)
    return d


def a_event_flyer(rng, W, H, cx):
    d = Design(W, H, rng)
    d.bg_image()
    if cx >= 2:
        d.shape("overlay", 0, 0, W, H, DEEP, opacity=0.35)
    d.decor_circles(rng.randint(1, 2), color=GOLD, alpha_range=(0.1, 0.2))
    rows = [row_logo(0.25),
            row_text("kicker", "YOU'RE INVITED", SANS, 22, rgba(*GOLD), weight="bold", ls=5),
            row_text("headline", rng.choice(["Solstice Summer Social", "Golden Hour Tasting Night", "Sunset Sessions"] + (HEAD_LONG[3:] if cx >= 3 else [])),
                     SERIF, 80, rgba(*WHITE), weight="bold", max_lines=3, lh=1.1),
            row_divider(GOLD),
            row_text("date_line", rng.choice(EVENT_LINES[::3]), SANS, 30, rgba(*WHITE), weight="bold", ls=2),
            row_text("location", rng.choice(EVENT_LINES[1::3]), SANS, 26, rgba(255, 255, 255, 0.85)),
            row_text("details", rng.choice(EVENT_LINES[2::3]), SANS, 22, rgba(255, 255, 255, 0.75))]
    if cx >= 2:
        rows.append(row_badges(["FREE ENTRY"] + rng.sample(BADGES, rng.randint(0, 2)), 15, [ORANGE, GOLD]))
    rows.append(row_button(rng.choice(["Reserve Your Spot", "Buy Tickets", "RSVP Now"]), 22))
    vstack(d, rows, W * 0.08, H * 0.05, W * 0.84, H * 0.92, gap=26)
    if cx >= 3:
        d.image("qr_code", "solstice_qr_code.png", W - 170 * d.u, H - 170 * d.u, 130 * d.u, 130 * d.u)
        d.ribbon(rng.choice(RIBBONS), corner="tl")
    return d


def a_sale_promo(rng, W, H, cx):
    d = Design(W, H, rng)
    d.bg_solid(ORANGE if rng.random() < 0.5 else PLUM)
    d.decor_circles(rng.randint(2, 4), color=GOLD, alpha_range=(0.15, 0.3))
    big = rng.choice(BIG_NUMBERS)
    landscape = W > H * 1.15
    if landscape:
        side = H * 0.8
        d.image("product", BOTTLE, W * 0.62, (H - side) / 2, side, side)
        rows = [row_text("kicker", "SUMMER SALE", SANS, 26, rgba(*CREAM), weight="bold", align="left", wfrac=1, ls=5),
                row_text("big_offer", big, SERIF, 150, rgba(*WHITE), weight="bold", align="left", wfrac=1, max_lines=1),
                row_text("subhead", rng.choice(SUBHEADS), SANS, 26, rgba(*WHITE), align="left", wfrac=1, max_lines=2),
                row_button(rng.choice(CTAS), 24, fill=PLUM if d.els[0]["fill_color"] != rgba(*PLUM) else ORANGE, align="left")]
        vstack(d, rows, W * 0.06, H * 0.1, W * 0.52, H * 0.9, anchor="center")
    else:
        rows = [row_text("kicker", "SUMMER SALE", SANS, 26, rgba(*CREAM), weight="bold", ls=5),
                row_text("big_offer", big, SERIF, 170, rgba(*WHITE), weight="bold", max_lines=2, wfrac=0.9),
                row_image(BOTTLE, 420),
                row_text("subhead", rng.choice(SUBHEADS), SANS, 26, rgba(*WHITE), max_lines=2),
                row_button(rng.choice(CTAS), 24, fill=PLUM if d.els[0]["fill_color"] != rgba(*PLUM) else ORANGE)]
        vstack(d, rows, W * 0.06, H * 0.05, W * 0.88, H * 0.93)
    if cx >= 2:
        d.ribbon(rng.choice(RIBBONS), corner="tr" if not landscape else "tl")
    if cx >= 3:
        for _ in range(rng.randint(2, 4)):
            d.pill("badge", rng.choice(BADGES), rng.uniform(0.05, 0.7) * W, rng.uniform(0.6, 0.9) * H, 14 * d.u, PLUM, padx=1.3)
        d.text("legal_text", LEGAL[1], SANS, 11 * d.u, rgba(255, 255, 255, 0.7), W * 0.05, H - 30 * d.u, W * 0.9, max_lines=1)
    return d


def a_minimal(rng, W, H, cx):
    d = Design(W, H, rng)
    d.bg_image()
    lw = 300 * d.u
    head = rng.choice(HEAD_SHORT)
    if rng.random() < 0.5:
        d.logo(W / 2, H * 0.06, lw)
        d.text("headline", head, SERIF, 72 * d.u, rgba(*WHITE), W * 0.1, H * 0.42, W * 0.8, weight="bold", max_lines=2)
        if rng.random() < 0.6:
            d.text("cta", rng.choice(CTAS), SANS, 30 * d.u, rgba(*ORANGE), W * 0.1, H * 0.6, W * 0.8, weight="bold")
    else:
        side = min(W, H) * 0.5
        d.image("product", BOTTLE, (W - side) / 2, H * 0.12, side, side)
        d.text("headline", head, SERIF, 64 * d.u, rgba(*WHITE), W * 0.1, H * 0.12 + side + 30 * d.u, W * 0.8, weight="bold", max_lines=2)
        d.logo(W / 2, H - 140 * d.u, 240 * d.u)
    return d


def a_story_stack(rng, W, H, cx):
    d = Design(W, H, rng)
    d.bg_image()
    d.decor_circles(rng.randint(0, 2))
    rows = [row_logo(0.3),
            row_text("kicker", rng.choice(["NEW", "JUST DROPPED", "LIMITED RUN"]), SANS, 24, rgba(*GOLD), weight="bold", ls=6),
            row_text("headline", rng.choice(HEAD_SHORT), SERIF, 96, rgba(*WHITE), weight="bold", max_lines=3, lh=1.05),
            row_image(BOTTLE, 640),
            row_text("subhead", rng.choice(SUBHEADS), SANS, 30, rgba(255, 255, 255, 0.9), max_lines=3, wfrac=0.8)]
    if cx >= 2:
        rows.append(row_badges(rng.sample(BADGES, rng.randint(2, 4)), 18, [ORANGE, PLUM, GOLD]))
    rows.append(row_button(rng.choice(CTAS), 28))
    if cx >= 2:
        rows.append(row_text("swipe", "Swipe up to shop", SANS, 20, rgba(255, 255, 255, 0.7)))
    vstack(d, rows, W * 0.06, H * 0.05, W * 0.88, H * 0.95)
    return d


def a_adversarial(rng, W, H, cx):
    """Deliberately awkward: odd fields, overlaps, off-canvas, rotation,
    missing assets, many small elements, nested groups, junk metadata."""
    d = a_poster_center(rng, W, H, 3)
    els = d.els
    u = d.u
    # junk / optional fields
    for el in els:
        if rng.random() < 0.3:
            el["_note"] = "designer note: keep this"
        if rng.random() < 0.15:
            el["locked"] = rng.random() < 0.5
        if rng.random() < 0.12 and el["id"] != "bg":
            el.pop("z_index", None)
    # hidden layer in source
    d.add({"id": "hidden_layer", "type": "shape", "x": W * 0.2, "y": H * 0.2, "width": W * 0.3, "height": H * 0.1,
           "shape_type": "rectangle", "fill_color": rgba(*RED), "opacity": 0.0})
    # tiny + zero-size shapes
    d.add({"id": "speck", "type": "shape", "x": W * 0.5, "y": H * 0.5, "width": 2, "height": 2, "shape_type": "ellipse",
           "fill_color": rgba(*WHITE, 0.5)})
    d.add({"id": "zero_shape", "type": "shape", "x": W * 0.3, "y": H * 0.3, "width": 0, "height": 0, "shape_type": "rectangle",
           "fill_color": rgba(*WHITE)})
    # rotated sticker text (not grouped)
    d.text("sticker", rng.choice(["Only $4.99!", "Wow!", "New!"]), SERIF, 34 * u, rgba(*GOLD), W * 0.04, H * 0.3, 220 * u,
           weight="bold", style="italic", rotation=rng.choice([-20, 15, 90]))
    # adversarial strings
    d.text("weird_text", rng.choice(ADVERSARIAL_TEXT), rng.choice([SANS, SERIF, "Helvetica Neue"]), 20 * u,
           rgba(255, 255, 255, 0.9), W * 0.1, H * 0.22, W * 0.5, max_lines=3)
    # extra missing images
    for k in range(rng.randint(1, 2)):
        d.image("missing_img", rng.choice(MISSING), rng.uniform(0, W - 150 * u), rng.uniform(0, H - 150 * u), 120 * u, 120 * u)
    # 3-member group w/ odd z
    g = "price_tag"
    d.shape("tag_bg", W * 0.7, H * 0.4, 200 * u, 200 * u, GOLD, kind="ellipse", group=g)
    d.text("tag_price", rng.choice(PRICES), SERIF, 44 * u, rgba(*PLUM), W * 0.7, H * 0.4 + 60 * u, 200 * u, weight="bold", group=g)
    d.text("tag_unit", "per bottle", SANS, 16 * u, rgba(*PLUM), W * 0.7, H * 0.4 + 120 * u, 200 * u, group=g)
    # partially off-canvas element in source
    d.shape("bleed_bar", -40 * u, H * 0.6, W * 0.4, 30 * u, ORANGE, opacity=0.5)
    # many dots
    d.dots(rng.randint(8, 16))
    # integer-ish vs float coordinates, colors without alpha
    for el in d.els:
        if el.get("type") == "text" and rng.random() < 0.1:
            el["color"] = el["color"].replace("rgba", "rgb").rsplit(",", 1)[0] + ")"
        if rng.random() < 0.2:
            el["x"] = int(el["x"])
    return d


ARCHETYPES = {
    "poster_center": (a_poster_center, ["portrait", "square", "story"]),
    "split_hero": (a_split_hero, ["landscape", "square", "portrait"]),
    "banner_row": (a_banner_row, ["banner"]),
    "typographic": (a_typographic, ["portrait", "square", "landscape", "story"]),
    "card_overlay": (a_card_overlay, ["portrait", "square", "landscape"]),
    "scrim_text": (a_scrim_text, ["portrait", "square"]),
    "product_grid": (a_product_grid, ["square", "landscape", "portrait"]),
    "event_flyer": (a_event_flyer, ["portrait", "story", "square"]),
    "sale_promo": (a_sale_promo, ["square", "portrait", "landscape"]),
    "minimal": (a_minimal, ["square", "portrait", "landscape"]),
    "story_stack": (a_story_stack, ["story"]),
    "adversarial": (a_adversarial, ["portrait", "square", "story"]),
}

SHAPE_CLASSES = {
    "square": [(1080, 1080), (1200, 1200), (800, 800)],
    "portrait": [(1080, 1350), (1000, 1500), (1275, 1650), (1800, 2400)],
    "story": [(1080, 1920)],
    "landscape": [(1200, 630), (1920, 1080), (1600, 900), (1280, 720)],
    "banner": [(1500, 500), (1600, 400), (1584, 396)],
}


def pick_targets(rng, W, H):
    """One near, one far and one extreme target for a source of size WxH."""
    near, far, extreme = [], [], []
    for name, tw, th in FORMATS:
        if (tw, th) == (W, H):
            continue
        dist = ratio_distance(W, H, tw, th)
        tiny = min(tw, th) <= 100 or max(tw, th) <= 340
        if tiny or dist > 1.55:
            extreme.append((name, tw, th))
        elif dist > 0.55:
            far.append((name, tw, th))
        else:
            near.append((name, tw, th))
    out = []
    for lvl, pool in ((1, near), (2, far), (3, extreme)):
        if not pool:
            pool = far or extreme or near
        out.append((lvl, rng.choice(pool)))
    return out


def complexity_for(arch, rng, i):
    if arch == "adversarial":
        return 3
    if arch == "minimal":
        return 1
    return [1, 2, 3][i % 3]


def generate(out_dir: Path, per_arch: int, seed: int):
    out_dir = Path(out_dir)
    tasks_dir = out_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    rng_master = random.Random(seed)
    for arch, (fn, classes) in ARCHETYPES.items():
        for i in range(per_arch):
            rng = random.Random(rng_master.random())
            klass = classes[i % len(classes)]
            W, H = rng.choice(SHAPE_CLASSES[klass])
            cx = complexity_for(arch, rng, i)
            try:
                design = fn(rng, W, H, cx).to_source()
            except Exception as e:  # generator bug: report and continue
                print(f"[gen] {arch}#{i} failed: {e!r}", file=sys.stderr)
                continue
            for lvl, (tname, tw, th) in pick_targets(rng, W, H):
                # difficulty label combines element complexity with ratio distance
                diff = max(1, min(3, round((cx + lvl) / 2 + 0.01)))
                task_id = f"{arch}_{i:02d}_L{lvl}"
                task = {
                    "task_id": task_id,
                    "difficulty": ["level_1_warmup", "level_2_core", "level_3_advanced"][diff - 1],
                    "archetype": arch,
                    "complexity": cx,
                    "ratio_level": lvl,
                    "target_name": tname,
                    "source": copy.deepcopy(design),
                    "target_canvas": {"width": tw, "height": th},
                }
                (tasks_dir / f"{task_id}.json").write_text(json.dumps(task, indent=1, ensure_ascii=False))
                manifest.append({"task_id": task_id, "archetype": arch, "complexity": cx, "ratio_level": lvl,
                                 "difficulty": diff, "source": [W, H], "target": [tw, th], "target_name": tname,
                                 "n_elements": len(design["elements"])})
    # the three official samples
    for p in sorted((ROOT / "input").glob("chameleon_sample_*.json")):
        t = json.loads(p.read_text())
        tid = "official_" + t.get("task_id", p.stem)
        t["task_id"] = tid
        (tasks_dir / f"{tid}.json").write_text(json.dumps(t, indent=1, ensure_ascii=False))
        lvl = {"level_1_warmup": 1, "level_2_core": 2, "level_3_advanced": 3}.get(t.get("difficulty"), 2)
        manifest.append({"task_id": tid, "archetype": "official", "complexity": lvl, "ratio_level": lvl, "difficulty": lvl,
                         "source": [t["source"]["canvas"]["width"], t["source"]["canvas"]["height"]],
                         "target": [t["target_canvas"]["width"], t["target_canvas"]["height"]], "target_name": "official",
                         "n_elements": len(t["source"]["elements"])})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {len(manifest)} tasks to {tasks_dir}")
    return manifest


def generate_formats(out_dir: Path, per_arch: int, seed: int, formats=None):
    """Exhaustive format coverage: every catalogue format for the official
    samples and for `per_arch` designs of every archetype."""
    out_dir = Path(out_dir)
    tasks_dir = out_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    sources = []
    for p in sorted((ROOT / "input").glob("chameleon_sample_*.json")):
        t = json.loads(p.read_text())
        sources.append(("official_" + t.get("task_id", p.stem), "official", 3, t["source"]))
    rng_master = random.Random(seed)
    for arch, (fn, classes) in ARCHETYPES.items():
        for i in range(per_arch):
            rng = random.Random(rng_master.random())
            W, H = rng.choice(SHAPE_CLASSES[classes[i % len(classes)]])
            cx = complexity_for(arch, rng, i + 1)
            sources.append((f"{arch}_{i:02d}", arch, cx, fn(rng, W, H, cx).to_source()))
    manifest = []
    for sid, arch, cx, src in sources:
        sw, sh = src["canvas"]["width"], src["canvas"]["height"]
        for name, tw, th in formats or FORMATS:
            dist = ratio_distance(sw, sh, tw, th)
            lvl = 3 if (min(tw, th) <= 100 or max(tw, th) <= 340 or dist > 1.55) else (2 if dist > 0.55 else 1)
            slug = name.lower().replace(" ", "_").replace(":", "x")
            tid = f"{sid}__{slug}"
            task = {"task_id": tid, "archetype": arch, "complexity": cx, "ratio_level": lvl, "target_name": name,
                    "source": src, "target_canvas": {"width": tw, "height": th}}
            (tasks_dir / f"{tid}.json").write_text(json.dumps(task, ensure_ascii=False))
            manifest.append({"task_id": tid, "archetype": arch, "complexity": cx, "ratio_level": lvl,
                             "difficulty": max(1, min(3, round((cx + lvl) / 2 + 0.01))), "source": [sw, sh],
                             "target": [tw, th], "target_name": name, "n_elements": len(src["elements"])})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {len(manifest)} tasks to {tasks_dir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "eval" / "testsets" / "main"))
    ap.add_argument("--designs-per-archetype", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--formats", action="store_true", help="every catalogue format per design (coverage set)")
    ap.add_argument("--extra-formats", action="store_true", help="the same designs in the extra presets")
    a = ap.parse_args()
    if a.extra_formats:
        from eval.catalogue import EXTRA_FORMATS

        generate_formats(Path(a.out), a.designs_per_archetype, a.seed, EXTRA_FORMATS)
    else:
        (generate_formats if a.formats else generate)(Path(a.out), a.designs_per_archetype, a.seed)


if __name__ == "__main__":
    main()
