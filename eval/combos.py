"""Combinatorial designs: every value of every design property, combined so that
each pair of values (or nearly every triple) appears in some design.

A full cross product of ~24 properties is ~10^13 designs; a covering array
reaches every interaction of two properties in a few hundred, and a few
thousand random rows cover almost every interaction of three (most layout bugs
need one value, or two or three together).  Each design records its property
values, so `check` can say which values make outputs fail.

    python -m eval.combos build --strength 2 --out eval/testsets/combos2     # pairwise covering array
    python -m eval.combos build --random 3000 --out eval/testsets/combos3    # ~3-wise by sampling
    python -m eval.combos build --random 1000 --wellformed --out eval/testsets/combosw   # sources worth judging
    python -m eval.run_eval --name c2 --tasks eval/testsets/combos2 --no-render
    python -m eval.combos check --run c2 --tasks eval/testsets/combos2       # legal? looks good? which values fail?
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.chameleon_layout import text_metrics as tm  # noqa: E402

LONG = "Introducing the all-new limited-batch botanical sparkling collection for golden hour"
FACTORS = {
    "layout": ["stack", "split_left", "split_right", "row", "card", "text_only", "photo_scrim", "grid", "bars"],
    "source": [(1080, 1080), (1080, 1920), (1920, 1080), (1500, 500), (300, 250), (728, 90)],
    "target": [(1080, 1080), (1080, 1920), (1920, 1080), (1200, 628), (1584, 396), (300, 250), (728, 90),
               (320, 50), (160, 600), (2560, 1440)],
    "headline": ["Sale", "Hello Summer", LONG, "Supercalifragilisticexpialidocious", "Line one\nLine two",
                 "Ünïcødé café — naïve résumé", "50% OFF", ""],
    "font": ["Solstice Serif", "Solstice Sans", "Comic Mystery", "solstice sans"],  # unknown, odd case
    "size": [0.03, 0.07, 0.15],  # headline size as a share of the source's short side
    "weight_style": [("regular", "normal"), ("bold", "normal"), ("regular", "italic"), ("bold", "italic")],
    "align": ["left", "center", "right"],
    "line_height": [None, 0.9, 1.2, 1.8],
    "letter_spacing": [None, 0, 4, -1],
    "max_lines": [None, 1, 2],
    "runs": ["none", "colour", "bold", "out_of_range"],
    "color": ["rgba(255,255,255,1)", "rgba(25,20,30,1)", "rgba(255,255,255,0.6)", "#ffcc00"],
    "button": ["rect", "pill", "rounded", "ellipse", "huge_radius", "link"],
    "stroke": [None, 2, 8],
    "grouped": [True, False],
    "body": ["none", "line", "paragraph", "bullets"],
    "product": ["none", "bottle", "bottle_large", "unknown_asset"],
    "logo": ["none", "top", "corner", "bottom"],
    "badge": ["none", "corner_rect", "corner_ellipse_rotated", "ribbon_rotated"],
    "background": ["dark", "light", "gradient_image", "none"],
    "decor": ["none", "dots", "lines", "big_circle"],
    "quirk": ["none", "translucent_card", "reversed_z", "hidden_element"],
    "fit": ["contain", "cover", "fill"],
}
NAMES = list(FACTORS)


def covering_array(strength: int, seed: int = 0, candidates: int = 40) -> list:
    """Rows (level index per factor) covering every `strength`-way combination of levels (greedy, AETG-style:
    each row is the best of `candidates` built factor by factor to cover the most uncovered tuples)."""
    rng = random.Random(seed)
    sizes = [len(FACTORS[n]) for n in NAMES]
    combos = list(itertools.combinations(range(len(NAMES)), strength))
    uncovered = {c: set(itertools.product(*(range(sizes[f]) for f in c))) for c in combos}
    left = sum(map(len, uncovered.values()))
    rows = []
    while left:
        best, gain = None, -1
        for _ in range(candidates):
            row = [None] * len(NAMES)
            for f in rng.sample(range(len(NAMES)), len(NAMES)):
                scores = []
                for lv in range(sizes[f]):
                    row[f] = lv
                    scores.append(sum(1 for c in combos if f in c and all(row[g] is not None for g in c)
                                      and tuple(row[g] for g in c) in uncovered[c]))
                top = max(scores)
                row[f] = rng.choice([lv for lv, s in enumerate(scores) if s == top])
            g = sum(1 for c in combos if tuple(row[i] for i in c) in uncovered[c])
            if g > gain:
                best, gain = row, g
        for c in combos:
            uncovered[c].discard(tuple(best[i] for i in c))
        left -= gain
        rows.append(best)
    return rows


def wellformed(row: list) -> bool:
    """A source a designer could have made: text that contrasts with what is behind it (the cream card, on a
    card), the background beneath everything, a banner row only on a banner, a grid only where it has room,
    a headline large enough to lead, and every text legible in its place once typeset.  (Legality is tested on every row;
    how good an output looks only means something for these.)"""
    f = {n: FACTORS[n][i] for n, i in zip(NAMES, row)}
    W, H = f["source"]
    dark_text = f["color"] == "rgba(25,20,30,1)"
    light_ground = f["layout"] == "card" or f["background"] in ("light", "none") and f["layout"] != "photo_scrim"
    return dark_text == light_ground and f["quirk"] != "reversed_z" and (f["layout"] == "row") == (W >= 2 * H) \
        and not (f["layout"] == "grid" and min(W, H) < 250) and f["size"] > 0.03 \
        and not (f["max_lines"] == 1 and f["headline"] in (LONG, "Line one\nLine two")) and _settable(row)


def _settable(row: list) -> bool:
    try:
        build_design(row, typeset=True)
        return True
    except ValueError:
        return False


def coverage(rows: list, strength: int) -> float:
    """Share of all `strength`-way level combinations that some row covers."""
    sizes = [len(FACTORS[n]) for n in NAMES]
    total = hit = 0
    for c in itertools.combinations(range(len(NAMES)), strength):
        seen = {tuple(r[i] for i in c) for r in rows}
        total += len(list(itertools.product(*(range(sizes[f]) for f in c))))
        hit += len(seen)
    return hit / total


# ---------------------------------------------------------------------------
# a design from one row


def _text(eid, content, x, y, w, size, f, z, **extra):
    weight, style = f["weight_style"]
    lines = max(1, content.count("\n") + 1, round(len(content) * size * 0.55 / max(w, 1)) + 1)
    el = {"id": eid, "type": "text", "x": x, "y": y, "width": w, "height": lines * size * (f["line_height"] or 1.2),
          "content": content, "font_size": size, "font_weight": weight, "font_style": style, "color": f["color"],
          "text_align": f["align"], "z_index": z}
    for key in ("line_height", "letter_spacing", "max_lines"):
        if f[key] is not None:
            el[key] = f[key]
    el["font_family"] = f["font"]
    el.update(extra)
    return el


def _typeset(el: dict, max_w: float, max_h: float, one_line: bool = False, tracked: bool = True) -> dict:
    """A text set as a designer sets it: the largest whole size, up to its own, whose lines (as the renderer wraps
    them, never breaking a word) fit max_w - on one line for a label, within max_lines otherwise - and max_h;
    its box exactly as tall as those lines, and its tracking at most a tenth of an em either way (none for
    body copy: tracking is for display type)."""
    ls = (el.get("letter_spacing") or 0.0) if tracked else 0.0
    track = lambda size: max(-0.1 * size, min(0.1 * size, ls))  # noqa: E731

    def layout(size):
        return tm.layout_text(el["content"], el["font_family"], el["font_weight"], el["font_style"], size, max_w,
                              el.get("line_height") or 1.2, track(size))

    cap = 1 if one_line else max(el.get("max_lines") or len(el["content"]), el["content"].count("\n") + 1)
    size = max(4, int(el["font_size"]))  # whole pixels: the converter wraps at the size the renderer draws
    lay = layout(size)
    unfit = lambda lay: max(lay.line_widths) > max_w or lay.n_lines > cap or lay.box_height > max_h  # noqa: E731
    while size > 4 and unfit(lay):
        size = max(4, size - max(1, round(0.05 * size)))
        lay = layout(size)
    if unfit(lay):
        raise ValueError(f"{el['id']} cannot be set in {max_w:.0f} x {max_h:.0f} px")
    out = {**el, "font_size": size, "width": round(max_w, 1), "height": round(lay.box_height, 1)}
    if "letter_spacing" in el:
        out["letter_spacing"] = round(track(out["font_size"]), 2)
    return out


def _runs(kind: str, content: str) -> list:
    n = len(content)
    if kind == "none" or n < 2:
        return []
    if kind == "colour":
        return [{"start": n // 2, "end": n, "color": "rgba(240,178,66,1)"}]
    if kind == "bold":
        return [{"start": 0, "end": n // 2, "font_weight": "bold"}]
    return [{"start": n - 1, "end": n + 40, "color": "rgba(240,178,66,1)"}]  # runs past the end of the text


def _shape(eid, x, y, w, h, fill, z, **extra):
    return {"id": eid, "type": "shape", "x": x, "y": y, "width": w, "height": h, "shape_type": "rectangle",
            "fill_color": fill, "z_index": z, **extra}


def _image(eid, asset, x, y, w, h, fit, z):
    return {"id": eid, "type": "image", "x": x, "y": y, "width": w, "height": h, "asset_id": asset, "fit": fit,
            "z_index": z}


# where each piece sits, as (x, y, w, h) shares of the source canvas
SLOTS = {
    "stack": {"logo": (0.35, 0.04, 0.3, 0.08), "product": (0.3, 0.15, 0.4, 0.38), "copy": (0.1, 0.56, 0.8, 0.3),
              "button": (0.32, 0.88, 0.36, 0.07)},
    "split_left": {"logo": (0.55, 0.08, 0.3, 0.08), "product": (0.04, 0.12, 0.42, 0.76),
                   "copy": (0.52, 0.22, 0.42, 0.5), "button": (0.55, 0.78, 0.3, 0.08)},
    "split_right": {"logo": (0.08, 0.08, 0.3, 0.08), "product": (0.54, 0.12, 0.42, 0.76),
                    "copy": (0.06, 0.22, 0.42, 0.5), "button": (0.08, 0.78, 0.3, 0.08)},
    "row": {"logo": (0.02, 0.3, 0.12, 0.4), "product": (0.16, 0.08, 0.14, 0.84), "copy": (0.33, 0.12, 0.4, 0.76),
            "button": (0.77, 0.32, 0.2, 0.36)},
    "card": {"logo": (0.38, 0.03, 0.24, 0.07), "product": (0.35, 0.18, 0.3, 0.3), "copy": (0.16, 0.52, 0.68, 0.24),
             "button": (0.34, 0.8, 0.32, 0.07), "card": (0.1, 0.13, 0.8, 0.8)},
    "text_only": {"logo": (0.35, 0.05, 0.3, 0.08), "copy": (0.1, 0.25, 0.8, 0.45), "button": (0.32, 0.78, 0.36, 0.08)},
    "photo_scrim": {"logo": (0.04, 0.04, 0.22, 0.07), "product": (0.25, 0.1, 0.5, 0.5),
                    "copy": (0.08, 0.68, 0.84, 0.18), "button": (0.34, 0.88, 0.32, 0.07), "scrim": (0, 0.64, 1, 0.36)},
    "grid": {"logo": (0.38, 0.03, 0.24, 0.07), "copy": (0.1, 0.12, 0.8, 0.14), "grid": (0.06, 0.32, 0.88, 0.46),
             "button": (0.34, 0.85, 0.32, 0.08)},
    "bars": {"logo": (0.04, 0.02, 0.2, 0.08), "product": (0.32, 0.16, 0.36, 0.36), "copy": (0.1, 0.55, 0.8, 0.24),
             "button": (0.34, 0.8, 0.32, 0.06), "header": (0, 0, 1, 0.12), "footer": (0, 0.9, 1, 0.1)},
}
BODY = {"none": [], "line": ["Small-batch. Low sugar. All flavour."],
        "paragraph": ["Each bottle is brewed in small batches using hand-picked botanicals and real fruit, "
                      "no shortcuts, just bright sparkling refreshment for warm evenings."],
        "bullets": ["• Real fruit", "• No added sugar", "• Ships in 2 days"]}


def build_design(row: list, typeset: bool = False) -> tuple:
    """(source design, target canvas, factor values) for one row of level indices; with `typeset`, every
    text fits its place as a designer would have set it (legality tests keep the raw sizes: overflowing
    labels and words wider than the canvas are cases to survive too)."""
    f = {n: FACTORS[n][i] for n, i in zip(NAMES, row)}
    W, H = f["source"]
    S, slots, z = min(W, H), SLOTS[f["layout"]], iter(range(1, 100))
    box = lambda k: tuple(round(v * s, 1) for v, s in zip(slots[k], (W, H, W, H)))  # noqa: E731
    els = []
    bg = {"dark": "rgba(36,22,40,1)", "light": "rgba(246,236,220,1)", "none": None}.get(f["background"])
    if f["background"] == "gradient_image":
        els.append(_image("bg", "solstice_bg_gradient.png", 0, 0, W, H, "cover", 0))
    elif bg:
        els.append(_shape("bg", 0, 0, W, H, bg, 0))
    if f["decor"] == "dots":
        els += [_shape(f"dot{i}", (i * 0.17 % 1) * W, (i * 0.29 % 1) * H, S * 0.012, S * 0.012, "rgba(255,255,255,0.35)",
                       next(z), shape_type="ellipse") for i in range(1, 7)]
    elif f["decor"] == "lines":
        els += [_shape(f"rule{i}", 0.1 * W, (0.5 + 0.02 * i) * H, 0.8 * W, max(1, S * 0.004), "rgba(240,178,66,1)",
                       next(z), shape_type="line") for i in range(2)]
    elif f["decor"] == "big_circle":
        els.append(_shape("circle", -0.2 * W, -0.2 * H, 0.7 * S, 0.7 * S, "rgba(255,255,255,0.12)", next(z),
                          shape_type="ellipse"))
    for key, fill in (("card", "rgba(246,236,220,1)"), ("scrim", "rgba(0,0,0,0.55)"), ("header", "rgba(232,106,58,1)"),
                      ("footer", "rgba(25,20,30,1)")):
        if key in slots:
            extra = {"corner_radius": 0.03 * S} if key == "card" else {}
            if key == "card" and f["quirk"] == "translucent_card":
                extra["opacity"] = 0.6
            els.append(_shape(key, *box(key), fill, next(z), **extra))
    if f["product"] != "none" and "product" in slots:
        x, y, w, h = box("product")
        if f["product"] == "bottle_large":
            x, y, w, h = x - 0.25 * w, y - 0.1 * h, 1.5 * w, 1.2 * h
        asset = "missing_asset_7.png" if f["product"] == "unknown_asset" else "solstice_bottle.png"
        els.append(_image("product", asset, x, y, w, h, f["fit"], next(z)))
    if "grid" in slots:
        gx, gy, gw, gh = box("grid")
        for i in range(3):
            cx = gx + i * gw / 3
            els.append(_image(f"item{i}", "solstice_bottle.png", cx + 0.15 * gw / 3, gy, 0.7 * gw / 3, 0.65 * gh,
                              f["fit"], next(z)))
            els.append(_text(f"item_name{i}", ["Wild Honey", "Yuzu Mint", "Hibiscus"][i], cx, gy + 0.7 * gh, gw / 3,
                             max(4, 0.025 * S), f, next(z), text_align="center"))
            els.append(_text(f"item_price{i}", ["$4.99", "$5.49", "2 for $8"][i], cx, gy + 0.85 * gh, gw / 3,
                             max(4, 0.022 * S), f, next(z), text_align="center"))
    if f["logo"] != "none":
        x, y, w, h = box("logo")
        if f["logo"] == "corner":
            x, y = W - w - 0.03 * W, 0.03 * H
        elif f["logo"] == "bottom":
            y = H - h - 0.03 * H
        els.append(_image("logo", "solstice_logo_lockup.png", x, y, w, h, "contain", next(z)))
    cx, cy, cw, ch = box("copy")
    bx, by, bw, bh = _badge_box(f["badge"], W, H)
    if typeset and f["badge"] != "none" and cy < by + bh and cx + cw > bx:  # the copy keeps clear of the badge
        cw = max(0.5 * cw, bx - 0.03 * W - cx)
    size = max(4.0, f["size"] * S)
    head = _text("headline", f["headline"], cx, cy, cw, size, f, next(z))
    if typeset:
        head = _typeset(head, cw, ch * (0.55 if BODY[f["body"]] else 1.0))
    if runs := _runs(f["runs"], f["headline"]):
        head["style_runs"] = runs
    els.append(head)
    y = cy + head["height"] + 0.3 * size
    lines = BODY[f["body"]]
    for i, line in enumerate(lines):
        body = _text(f"body{i}", line, cx, y, cw, max(4.0, 0.025 * S), f, next(z), font_weight="regular",
                     font_style="normal")
        if typeset:
            body = _typeset(body, cw, max(4.0, (cy + ch - y) / (len(lines) - i)), tracked=False)
        els.append(body)
        y += body["height"] + 0.2 * body["font_size"]
    els += _button(f, *box("button"), z, head["font_size"], typeset)
    if f["badge"] != "none":
        extra = {"rotation": -15} if f["badge"] == "ribbon_rotated" else \
            {"rotation": 12, "shape_type": "ellipse"} if f["badge"] == "corner_ellipse_rotated" else {}
        els.append(_shape("badge_bg", bx, by, bw, bh, "rgba(232,106,58,1)", next(z), group_id="badge", **extra))
        els.append(_text("badge_label", "NEW", bx, by + bh / 2 - 0.02 * S, bw, max(4, 0.03 * S), f, next(z),
                         group_id="badge", text_align="center", color="rgba(255,255,255,1)",
                         **({"rotation": extra["rotation"]} if "rotation" in extra else {})))
    if f["quirk"] == "reversed_z":
        top = max(e["z_index"] for e in els)
        for e in els:
            e["z_index"] = top - e["z_index"]
    elif f["quirk"] == "hidden_element" and len(els) > 2:
        els[-1]["opacity"] = 0
    return {"canvas": {"width": W, "height": H}, "elements": els}, \
        {"width": f["target"][0], "height": f["target"][1]}, {n: str(v) for n, v in f.items()}


def _badge_box(badge: str, W: float, H: float) -> tuple:
    S = min(W, H)
    bw, bh = 0.2 * S, (0.2 if badge == "corner_ellipse_rotated" else 0.06) * S
    return W - bw - 0.03 * W, 0.03 * H, bw, bh


CTA = "Shop the Summer Line"


def _button(f, x, y, w, h, z, head: float, typeset: bool = False) -> list:
    size, set_h = max(4.0, min(0.45 * h, 0.8 * head)), None  # a button label never outranks the headline
    if typeset:  # as a designer sets it: the label on one line, the button hugging it, centred where it was
        label_set = _typeset(_text("cta_label", CTA, x, y, w, size, f, 0), 0.8 * w, 0.5 * h, one_line=True)
        size, set_h = label_set["font_size"], label_set["height"]
        lw = tm.natural_width(CTA, f["font"], *f["weight_style"], size, label_set.get("letter_spacing", 0.0))
        pw, ph = min(w, lw + (3 if f["button"] == "ellipse" else 2) * size), min(h, set_h + size)
        x, y, w, h = x + (w - pw) / 2, y + (h - ph) / 2, pw, ph

    def label(color):
        el = _text("cta_label", CTA, x, y + 0.2 * h, w, size, f, next(z), text_align="center", color=color)
        return el if set_h is None else {**el, "y": y + (h - set_h) / 2, "height": set_h,
                                         **{k: label_set[k] for k in ("letter_spacing",) if k in label_set}}

    if f["button"] == "link":
        return [label("rgba(232,106,58,1)")]
    radius = {"rect": 0, "pill": h / 2, "rounded": 0.15 * h, "ellipse": 0, "huge_radius": 3 * h}[f["button"]]
    pill = _shape("cta_bg", x, y, w, h, "rgba(232,106,58,1)", next(z), corner_radius=radius)
    if f["button"] == "ellipse":
        pill["shape_type"] = "ellipse"
    if f["stroke"]:
        pill.update(stroke_color="rgba(255,255,255,1)", stroke_width=f["stroke"])
    text = label("rgba(255,255,255,1)")
    if f["grouped"]:
        pill["group_id"] = text["group_id"] = "cta"
    return [pill, text]


def build(out: Path, rows: list, label: str, typeset: bool = False):
    tasks = out / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, row in enumerate(rows):
        src, target, factors = build_design(row, typeset)
        tid = f"{label}_{i:04d}"
        (tasks / f"{tid}.json").write_text(json.dumps({"task_id": tid, "archetype": "combos", "source": src,
                                                       "target_canvas": target, "factors": factors}))
        manifest.append({"task_id": tid, "archetype": factors["layout"], "difficulty": 2, "ratio_level": 2,
                         "n_elements": len(src["elements"])})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{len(rows)} designs -> {tasks}")


# ---------------------------------------------------------------------------
# legal? looks good? which values fail?

RULE_FLOOR = 0.5  # a design rule scoring under this (1 = as good as the source) is a visible failure


def check(run: str, tasks: Path, worst: int = 12):
    from eval.design_rules import RULES, evaluate

    results = {json.loads(l)["task_id"]: json.loads(l)
               for l in (ROOT / "eval" / "runs" / run / "results.jsonl").read_text().splitlines()}
    fails, by_level, n = Counter(), defaultdict(Counter), Counter()
    deficits = []
    for p in sorted((tasks / "tasks").glob("*.json")):
        task = json.loads(p.read_text())
        rec = results.get(task["task_id"], {})
        out_path = ROOT / "eval" / "runs" / run / "outputs" / p.name
        bad = []
        if rec.get("crash") or not out_path.exists():
            bad.append("crash")
        elif rec.get("gate"):
            bad.append("illegal")
        else:
            m = evaluate(task["source"], json.loads(out_path.read_text()))
            bad += [f"rule_{k}" for k in RULES if m[k] < RULE_FLOOR]
            deficits.append((sum(max(0.0, 1 - m[k]) for k in RULES), task["task_id"], bad))
        for f, v in task["factors"].items():
            n[(f, v)] += 1
            for b in bad:
                by_level[b][(f, v)] += 1
        fails.update(bad)
    total = len(list((tasks / "tasks").glob("*.json")))
    print(f"{run}: {total} designs; " + ", ".join(f"{k} {v} ({v / total:.0%})" for k, v in fails.most_common()))
    for b, _ in fails.most_common(6):
        rate = fails[b] / total
        lifts = sorted(((c / n[k]) / rate, k, c) for k, c in by_level[b].items() if n[k] >= 5)[::-1][:4]
        print(f"  {b}: most likely with " + "; ".join(f"{f}={v} x{lift:.1f} ({c}/{n[(f, v)]})"
                                                     for lift, (f, v), c in lifts))
    print("  worst:", " ".join(t for _, t, _ in sorted(deficits, reverse=True)[:worst]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--strength", type=int, default=2)
    b.add_argument("--random", type=int, default=0, help="this many random rows instead of a covering array")
    b.add_argument("--wellformed", action="store_true", help="random rows only where the source is well formed")
    b.add_argument("--seed", type=int, default=0)
    c = sub.add_parser("check")
    c.add_argument("--run", required=True)
    c.add_argument("--tasks", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "build":
        if a.random:
            rng, rows = random.Random(a.seed), []
            while len(rows) < a.random:
                row = [rng.randrange(len(FACTORS[n])) for n in NAMES]
                if not a.wellformed or wellformed(row):
                    rows.append(row)
        else:
            rows = covering_array(a.strength, a.seed)
        print(f"pairwise coverage {coverage(rows, 2):.1%}, 3-wise {coverage(rows, 3):.1%}")
        build(a.out, rows, "combo", typeset=a.wellformed)
    else:
        check(a.run, a.tasks)


if __name__ == "__main__":
    main()
