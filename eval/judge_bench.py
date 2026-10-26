"""A benchmark for judges: pairs of designs where we know which one is better.

Each pair is a real engine output and a copy of it with one design defect
applied at a given severity (an element knocked off its alignment, two
blocks crammed together, lopsided margins, ...), plus identical pairs that
should tie.  A judge that cannot tell these apart cannot steer the engine.

    python -m eval.judge_bench build --run v35f_allformats --n 40
    python -m eval.judge_bench build --set unseen3 --run v39p_allformats --seed 3   # held-out kinds
    python -m eval.judge_bench run --judge holistic
    python -m eval.judge_bench report
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.chameleon_layout.scene import analyze  # noqa: E402

BENCH = ROOT / "eval" / "judge_bench"


# ---------------------------------------------------------------------------
# defects


def _blocks(d):
    W, H = d["canvas"]["width"], d["canvas"]["height"]
    scene = analyze(d["elements"], W, H)
    return W, H, scene


def _move(d, idxs, dx, dy):
    """Shift elements together, clamped so every box stays on the canvas; the
    shift actually applied."""
    W, H = d["canvas"]["width"], d["canvas"]["height"]
    els = [d["elements"][i] for i in idxs]
    x0, y0 = min(e["x"] for e in els), min(e["y"] for e in els)
    x1, y1 = max(e["x"] + e["width"] for e in els), max(e["y"] + e["height"] for e in els)
    dx, dy = max(-x0, min(dx, W - x1)), max(-y0, min(dy, H - y1))
    for e in els:
        e["x"], e["y"] = round(e["x"] + dx, 2), round(e["y"] + dy, 2)
    return dx, dy


def _idxs(b):
    return [it.idx for it in b.items]


def _pick(blocks, roles, rng):
    cands = [b for b in blocks if b.role in roles]
    return rng.choice(cands) if cands else None


def nudge(d, sev, rng):
    """One block knocked off the shared alignment axis."""
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks, ("headline", "subhead", "body", "text", "cta", "logo", "hero"), rng)
    if b is None:
        return None
    want = sev * W * rng.choice((-1, 1))
    dx, _ = _move(d, _idxs(b), want, 0)
    if abs(dx) < 0.5 * abs(want):
        dx, _ = _move(d, _idxs(b), -want - dx, 0)
    return d if abs(dx) >= 0.5 * abs(want) else None


def cramp(d, sev, rng):
    """The gap between two stacked blocks mostly closed: the lower one moves up."""
    W, H, sc = _blocks(d)
    bs = sorted(sc.blocks, key=lambda b: b.src.y)
    pairs = [(a, b) for a, b in zip(bs, bs[1:])
             if b.src.y - a.src.y1 > 0.02 * H and min(a.src.x1, b.src.x1) > max(a.src.x, b.src.x)]
    if not pairs:
        return None
    a, b = rng.choice(pairs)
    _move(d, _idxs(b), 0, -sev * (b.src.y - a.src.y1))
    return d


def lopsided(d, sev, rng):
    """All content shifted sideways: one margin wide, the other thin."""
    W, H, sc = _blocks(d)
    idxs = [i for b in sc.blocks + sc.ornaments for i in _idxs(b)]
    if not idxs:
        return None
    want = sev * W * rng.choice((-1, 1))
    dx, _ = _move(d, idxs, want, 0)
    if abs(dx) < 0.5 * abs(want):
        dx, _ = _move(d, idxs, -want - dx, 0)
    return d if abs(dx) >= 0.5 * abs(want) else None


def edge(d, sev, rng):
    """A headline or button pushed flush against the nearest canvas edge."""
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks, ("headline", "cta"), rng)
    if b is None:
        return None
    r = b.src
    dx = -r.x if r.cx < W / 2 else W - r.x1
    if abs(dx) < 0.02 * W:
        return None
    _move(d, _idxs(b), dx, 0)
    return d


def shrink_hero(d, sev, rng):
    """The product art scaled down about its centre."""
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks, ("hero",), rng)
    if b is None or b.kind != "image":
        return None
    e = d["elements"][b.items[0].idx]
    cx, cy = e["x"] + e["width"] / 2, e["y"] + e["height"] / 2
    e["width"], e["height"] = e["width"] * sev, e["height"] * sev
    e["x"], e["y"] = cx - e["width"] / 2, cy - e["height"] / 2
    return d


def flat_hierarchy(d, sev, rng):
    """The headline shrunk so it no longer leads."""
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks, ("headline",), rng)
    if b is None or b.kind != "text":
        return None
    e = d["elements"][b.items[0].idx]
    e["font_size"] = max(1, int(round(e["font_size"] * sev)))
    return d


def jitter(d, sev, rng):
    """Every block nudged a little in a random direction: general messiness."""
    W, H, sc = _blocks(d)
    if len(sc.blocks) < 2:
        return None
    for b in sc.blocks:
        _move(d, _idxs(b), rng.uniform(-sev, sev) * W, rng.uniform(-sev, sev) * H)
    return d


def text_small(d, sev, rng):
    for e in d["elements"]:
        if e.get("type") == "text":
            e["font_size"] = max(1, int(round(e["font_size"] * sev)))
    return d


def collide(d, sev, rng):
    """Control: the headline dropped onto the product."""
    W, H, sc = _blocks(d)
    h, p = _pick(sc.blocks, ("headline",), rng), _pick(sc.blocks, ("hero",), rng)
    if h is None or p is None:
        return None
    _move(d, _idxs(h), p.src.cx - h.src.cx, p.src.cy - h.src.cy)
    return d


def same(d, sev, rng):
    return d


def invisible(d, sev, rng):
    """Control: one block moved by `sev` (pixels if >= 1, else a canvas fraction) - nobody can see
    this, so a judge should call it a tie."""
    W, H, sc = _blocks(d)
    if not sc.blocks:
        return None
    b = rng.choice(sc.blocks)
    step = sev if sev >= 1 else sev * W
    dx, dy = _move(d, _idxs(b), step * rng.choice((-1, 1)), 0)
    return d if dx else None


def _scale_block(d, b, f):
    """Scale a block's elements (and fonts) by f about the block's centre."""
    r = b.src
    for i in _idxs(b):
        e = d["elements"][i]
        e["x"], e["y"] = r.cx + (e["x"] - r.cx) * f, r.cy + (e["y"] - r.cy) * f
        e["width"], e["height"] = e["width"] * f, e["height"] * f
        if e.get("type") == "text":
            e["font_size"] = max(1, int(round(e["font_size"] * f)))
    W, H = d["canvas"]["width"], d["canvas"]["height"]
    _move(d, _idxs(b), 0, 0)  # clamp back on canvas
    els = [d["elements"][i] for i in _idxs(b)]
    if min(e["x"] for e in els) < 0 or max(e["x"] + e["width"] for e in els) > W:
        return None
    return d


def swap_order(d, sev, rng):
    """Reading order broken: the headline and the button trade places."""
    W, H, sc = _blocks(d)
    h, c = _pick(sc.blocks, ("headline",), rng), _pick(sc.blocks, ("cta",), rng)
    if h is None or c is None or abs(h.src.cy - c.src.cy) < 0.1 * H:
        return None
    _move(d, _idxs(h), c.src.cx - h.src.cx, c.src.cy - h.src.cy)
    _move(d, _idxs(c), h.src.cx - c.src.cx, h.src.cy - c.src.cy)
    return d


def text_on_art(d, sev, rng):
    """A text block slid part-way over the product art."""
    W, H, sc = _blocks(d)
    t, p = _pick(sc.blocks, ("headline", "subhead", "body", "text"), rng), _pick(sc.blocks, ("hero",), rng)
    if t is None or p is None:
        return None
    _move(d, _idxs(t), sev * (p.src.cx - t.src.cx), sev * (p.src.cy - t.src.cy))
    return d


def tiny_logo(d, sev, rng):
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks + sc.ornaments, ("logo",), rng)
    return None if b is None else _scale_block(d, b, sev)


def huge_cta(d, sev, rng):
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks, ("cta",), rng)
    return None if b is None else _scale_block(d, b, sev)


def shrink_all(d, sev, rng):
    """Everything scaled toward the canvas centre: wasted space all round."""
    W, H = d["canvas"]["width"], d["canvas"]["height"]
    W_, H_, sc = _blocks(d)
    for b in sc.blocks + sc.ornaments:
        for i in _idxs(b):
            e = d["elements"][i]
            e["x"], e["y"] = W / 2 + (e["x"] - W / 2) * sev, H / 2 + (e["y"] - H / 2) * sev
            e["width"], e["height"] = e["width"] * sev, e["height"] * sev
            if e.get("type") == "text":
                e["font_size"] = max(1, int(round(e["font_size"] * sev)))
    return d


def drift(d, sev, rng):
    """All content shifted down: bottom-heavy, empty top."""
    W, H, sc = _blocks(d)
    idxs = [i for b in sc.blocks + sc.ornaments for i in _idxs(b)]
    dx, dy = _move(d, idxs, 0, sev * H)
    return d if dy > 0.5 * sev * H else None


def halve_gaps(d, sev, rng):
    """Every vertical gap between stacked blocks halved toward the middle block."""
    W, H, sc = _blocks(d)
    bs = sorted(sc.blocks, key=lambda b: b.src.cy)
    if len(bs) < 3:
        return None
    mid = bs[len(bs) // 2].src.cy
    for b in bs:
        _move(d, _idxs(b), 0, (mid - b.src.cy) * (1 - sev))
    return d


def shrunk(task, sev):
    """The brief's anti-example: the design just scaled to fit, when the shape changes a lot."""
    import math

    from engine.chameleon_layout.fallback import letterbox

    s, t = task["source"]["canvas"], task["target_canvas"]
    if abs(math.log((t["width"] / t["height"]) / (s["width"] / s["height"]))) < 0.7:
        return None  # nearly the same shape: scaling may be a fair answer
    return letterbox(copy.deepcopy(task["source"]), t)


def stretched(task, sev):
    """The starter's answer: every box scaled by the canvas ratio (fonts by the smaller one)."""
    s, t = task["source"]["canvas"], task["target_canvas"]
    sx, sy = t["width"] / s["width"], t["height"] / s["height"]
    d = copy.deepcopy(task["source"])
    d["canvas"] = {"width": t["width"], "height": t["height"]}
    for e in d["elements"]:
        e["x"], e["y"], e["width"], e["height"] = e["x"] * sx, e["y"] * sy, e["width"] * sx, e["height"] * sy
        if e.get("type") == "text":
            e["font_size"] = max(1, int(round(e["font_size"] * min(sx, sy))))
    return d


FROM_SOURCE = {"shrunk": shrunk, "stretched": stretched}  # bad answers built from the source, not the output


def widow(d, sev, rng):
    """The headline's box narrowed until its last line is one lone word."""
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks, ("headline",), rng)
    if b is None or b.kind != "text":
        return None
    it = b.items[0]
    e = d["elements"][it.idx]
    for k in range(40):
        w = e["width"] * (1 - 0.02 * k)
        lines = it.text_layout(e["font_size"], w).lines
        if len(lines) >= 2 and len(lines[-1].split()) == 1 and lines != it.text_layout(e["font_size"], e["width"]).lines:
            e["x"], e["width"] = e["x"] + (e["width"] - w) / 2, w
            e["height"] = it.text_layout(e["font_size"], w).box_height
            return d
    return None


def stranded_cta(d, sev, rng):
    """The button pushed far from the copy it belongs to."""
    W, H, sc = _blocks(d)
    c = _pick(sc.blocks, ("cta",), rng)
    if c is None:
        return None
    r = c.src
    dy = (H - r.y1) * 0.9 if r.cy < H / 2 else -r.y * 0.9
    dx, dy = _move(d, _idxs(c), 0, dy)
    return d if abs(dy) > 0.08 * H else None


def logo_drift(d, sev, rng):
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks + sc.ornaments, ("logo",), rng)
    if b is None:
        return None
    dx, dy = _move(d, _idxs(b), rng.uniform(-0.25, 0.25) * W, rng.uniform(-0.25, 0.25) * H)
    return d if abs(dx) + abs(dy) > 0.08 * min(W, H) else None


def badge_on_headline(d, sev, rng):
    W, H, sc = _blocks(d)
    h, g = _pick(sc.blocks, ("headline",), rng), _pick(sc.blocks + sc.ornaments, ("badge", "ribbon"), rng)
    if h is None or g is None:
        return None
    _move(d, _idxs(g), h.src.cx - g.src.cx, h.src.cy - g.src.cy)
    return d


def tilt(d, sev, rng):
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks, ("headline",), rng)
    if b is None or b.kind != "text":
        return None
    d["elements"][b.items[0].idx]["rotation"] = sev * rng.choice((-1, 1))
    return d


def squeeze(d, sev, rng):
    """All content compressed horizontally toward one side (positions only)."""
    W, H, sc = _blocks(d)
    side = rng.choice((0.0, W))
    for b in sc.blocks + sc.ornaments:
        r = b.src
        _move(d, _idxs(b), (side - r.cx) * sev, 0)
    return d


UNSEEN2 = {"widow": (1,), "stranded_cta": (1,), "logo_drift": (1,), "badge_on_headline": (1,), "tilt": (4,),
           "squeeze": (0.15,)}
UNSEEN2_FNS = {"widow": widow, "stranded_cta": stranded_cta, "logo_drift": logo_drift,
               "badge_on_headline": badge_on_headline, "tilt": tilt, "squeeze": squeeze}


def _shown(d, b) -> bool:
    """The block is drawn (the engine hides dropped content at opacity 0)."""
    return all(d["elements"][i].get("opacity", 1) > 0.5 for i in _idxs(b))


def uneven_gaps(d, sev, rng):
    """A stack's rhythm broken: its first gap mostly closes and its last widens by as much."""
    W, H, sc = _blocks(d)
    bs = sorted(sc.blocks, key=lambda b: b.src.y)
    stacked = [k for k in range(1, len(bs)) if bs[k].src.y - bs[k - 1].src.y1 > 0.01 * H
               and min(bs[k].src.x1, bs[k - 1].src.x1) > max(bs[k].src.x, bs[k - 1].src.x)]
    if len(stacked) < 2:
        return None
    first, last = stacked[0], stacked[-1]
    shift = sev * (bs[first].src.y - bs[first - 1].src.y1)
    for b in bs[first:last]:
        _move(d, _idxs(b), 0, -shift)
    return d


def off_card(d, sev, rng):
    """A text lifted off the card it sat on, onto the background beside the card."""
    W, H, sc = _blocks(d)
    cards = [b for b in sc.blocks if b.kind == "panel" and b.frame is not None and any(c.texts for c in b.children)]
    if not cards:
        return None
    card = rng.choice(cards)
    texts = [c for c in card.children if c.texts and _shown(d, c)]
    if not texts:
        return None
    t, f = rng.choice(texts), card.frame.box
    if max(H - f.y1, f.y) < t.src.h + 4:
        return None
    _move(d, _idxs(t), 0, f.y1 + 4 - t.src.y if H - f.y1 >= f.y else f.y - 4 - t.src.y1)
    return d


def align_break(d, sev, rng):
    """A centred text switched to ragged left: its lines leave the axis the rest share."""
    W, H, sc = _blocks(d)
    cands = [it for b in sc.blocks if b.kind == "text" and _shown(d, b) for it in b.texts  # its lines moving visibly
             if d["elements"][it.idx].get("text_align") == "center" and it.box.w - it.ink.w > 0.04 * W]
    if not cands:
        return None
    d["elements"][rng.choice(cands).idx]["text_align"] = "left"
    return d


def hero_crop(d, sev, rng):
    """The product art pushed part-way off the nearer canvas edge."""
    W, H, sc = _blocks(d)
    b = _pick(sc.blocks, ("hero",), rng)
    if b is None:
        return None
    r = b.src
    dx = W + sev * r.w - r.x1 if r.cx > W / 2 else -sev * r.w - r.x
    for i in _idxs(b):
        d["elements"][i]["x"] = round(d["elements"][i]["x"] + dx, 2)
    return d


def band_float(d, sev, rng):
    """A header or footer bar pulled off its edge, a strip of background beyond it."""
    W, H, sc = _blocks(d)
    bars = [b for b in sc.blocks if b.band in ("top", "bottom")]
    if not bars:
        return None
    b = rng.choice(bars)
    _, dy = _move(d, _idxs(b), 0, sev * H if b.band == "top" else -sev * H)
    return d if abs(dy) >= 0.5 * sev * H else None


def overflow(d, sev, rng):
    """A text box narrowed without growing taller: its lines spill out below it."""
    W, H, sc = _blocks(d)
    b = _pick([b for b in sc.blocks if _shown(d, b)], ("headline", "subhead", "body"), rng)
    if b is None or b.kind != "text":
        return None
    it = b.items[0]
    e = d["elements"][it.idx]
    w = e["width"] * sev
    if it.text_layout(e["font_size"], w).n_lines <= it.text_layout(e["font_size"], e["width"]).n_lines:
        return None
    e["x"], e["width"] = e["x"] + (e["width"] - w) / 2, w
    return d


UNSEEN3 = {"uneven_gaps": (0.67,), "off_card": (1,), "align_break": (1,), "hero_crop": (0.35,), "band_float": (0.06,),
           "overflow": (0.6,)}
UNSEEN3_FNS = {"uneven_gaps": uneven_gaps, "off_card": off_card, "align_break": align_break, "hero_crop": hero_crop,
               "band_float": band_float, "overflow": overflow}


UNSEEN = {  # kinds never used to fit the discriminator: a check of how it generalises
    "swap_order": (1,), "text_on_art": (0.5,), "tiny_logo": (0.5,), "huge_cta": (1.6,), "shrink_all": (0.75,),
    "drift": (0.08,), "halve_gaps": (0.5,),
}
UNSEEN_FNS = {"swap_order": swap_order, "text_on_art": text_on_art, "tiny_logo": tiny_logo, "huge_cta": huge_cta,
              "shrink_all": shrink_all, "drift": drift, "halve_gaps": halve_gaps}


DEFECTS = {  # kind: severities
    "same": (0,), "invisible": (1, 0.0015), "nudge": (0.03, 0.08), "cramp": (0.6, 0.95), "lopsided": (0.04, 0.08), "edge": (1,),
    "shrink_hero": (0.8, 0.6), "flat_hierarchy": (0.8, 0.6), "jitter": (0.02, 0.04), "text_small": (0.85,),
    "collide": (1,), "shrunk": (1,), "stretched": (1,),
}
TIES = ("same", "invisible")  # pairs a judge should call even
FNS = {"same": same, "invisible": invisible, "nudge": nudge, "cramp": cramp, "lopsided": lopsided, "edge": edge, "shrink_hero": shrink_hero,
       "flat_hierarchy": flat_hierarchy, "jitter": jitter, "text_small": text_small, "collide": collide}


SETS = {"synthetic": "pairs.jsonl", "human": "human_pairs.jsonl", "unseen": "unseen_pairs.jsonl",
        "unseen2": "unseen2_pairs.jsonl", "unseen3": "unseen3_pairs.jsonl"}
KINDS = {  # defect set: (kind -> severities, kind -> defect); unseen sets are never used in fitting
    "synthetic": (DEFECTS, FNS), "unseen": (UNSEEN, UNSEEN_FNS), "unseen2": (UNSEEN2, UNSEEN2_FNS),
    "unseen3": (UNSEEN3, UNSEEN3_FNS),
}


def build(run: str, tasks: str, n: int, seed: int, which: str = "synthetic"):
    outs = ROOT / "eval" / "runs" / run / "outputs"
    ids = sorted(p.stem for p in outs.glob("*.json"))
    rng = random.Random(seed)
    rng.shuffle(ids)
    pairs = []
    for tid in ids[:n]:
        task = json.loads((Path(tasks) / "tasks" / f"{tid}.json").read_text())
        good = json.loads((outs / f"{tid}.json").read_text())
        kinds, fns = KINDS[which]
        for kind, sevs in kinds.items():
            for sev in sevs:
                if kind in FROM_SOURCE:
                    bad = FROM_SOURCE[kind](task, sev)
                else:
                    bad = fns[kind](copy.deepcopy(good), sev, random.Random(f"{tid}:{kind}:{sev}"))
                if bad is not None and (kind in TIES or bad != good):
                    pairs.append({"id": f"{tid}|{kind}|{sev}", "task_id": tid, "kind": kind, "sev": sev,
                                  "source": task["source"], "target": task["target_canvas"], "good": good, "bad": bad})
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / SETS[which]).write_text("\n".join(json.dumps(p) for p in pairs))
    counts = defaultdict(int)
    for p in pairs:
        counts[(p["kind"], p["sev"])] += 1
    print(f"{len(pairs)} pairs from {n} tasks:", dict(counts))


# ---------------------------------------------------------------------------
# running a judge


def _render_one(d):
    from eval.judges import render_path

    render_path(d)


def prerender(designs, procs: int = 6):
    """Render every design once, in parallel processes (threads cannot: the renderer holds the GIL)."""
    from multiprocessing import Pool

    from eval.judges import CACHE, SIDE

    uniq = {json.dumps(d, sort_keys=True): d for d in designs}
    todo = [d for d in uniq.values()
            if not (CACHE / f"{hashlib.sha1(f'{SIDE}:{json.dumps(d, sort_keys=True)}'.encode()).hexdigest()}.png").exists()]
    if todo:
        with Pool(procs) as pool:
            pool.map(_render_one, todo, chunksize=4)





def run(judge_name: str, workers: int, limit: int, which: str = "synthetic"):
    from eval.judges import JUDGES

    judge = JUDGES[judge_name]
    pairs = [json.loads(l) for l in (BENCH / SETS[which]).read_text().splitlines()]
    if limit:
        pairs = pairs[:limit]
    name = judge_name if which == "synthetic" else f"{which}_{judge_name}"
    out = BENCH / f"results_{name}.jsonl"
    done = {json.loads(l)["id"] for l in out.read_text().splitlines()} if out.exists() else set()
    todo = [p for p in pairs if p["id"] not in done]

    def one(p):
        try:
            first = judge(p["source"], p["good"], p["bad"], p["target"])  # >0: first candidate better
            second = judge(p["source"], p["bad"], p["good"], p["target"])
        except Exception as e:  # noqa: BLE001 - a failed call is retried on the next run
            return {"id": p["id"], "error": repr(e)[:200]}
        return {"id": p["id"], "kind": p["kind"], "sev": p["sev"], "orders": [first, -second]}

    prerender([d for p in todo for d in (p["source"], p["good"], p["bad"])])
    with ThreadPoolExecutor(workers) as ex, out.open("a") as f:
        for r in ex.map(one, todo):
            if "orders" in r:
                f.write(json.dumps(r) + "\n")
                f.flush()
    report([name])


def report(names):
    for name in names:
        path = BENCH / f"results_{name}.jsonl"
        if not path.exists():
            continue
        recs = [json.loads(l) for l in path.read_text().splitlines()]
        by = defaultdict(list)
        for r in recs:
            by[(r["kind"], r["sev"])].append(r)
        print(f"\n{name}: {len(recs)} pairs")
        print(f"  {'defect':<16}{'sev':>5}{'n':>5}{'right':>8}{'tie':>6}{'wrong':>7}{'flips':>7}{'mean':>7}")
        right_all, ties_all = [], []
        order = [(k, s) for k, sevs in DEFECTS.items() for s in sevs]
        for kind, sev in sorted(by, key=lambda ks: order.index(ks) if ks in order else len(order)):
            rs = by[(kind, sev)]
            score = [sum(r["orders"]) / 2 for r in rs]
            flips = sum(1 for r in rs if r["orders"][0] * r["orders"][1] < 0) / len(rs)
            right = sum(s > 0 for s in score) / len(rs)
            wrong = sum(s < 0 for s in score) / len(rs)
            if kind in TIES:
                ties_all += [abs(s) for s in score]
            else:
                right_all += [1.0 if s > 0 else 0.5 if s == 0 else 0.0 for s in score]
            print(f"  {kind:<16}{sev:>5}{len(rs):>5}{right:>8.0%}{1 - right - wrong:>6.0%}{wrong:>7.0%}"
                  f"{flips:>7.0%}{sum(score) / len(rs):>+7.2f}")
        if right_all:
            print(f"  accuracy on defects (ties = half): {sum(right_all) / len(right_all):.1%}")
        if ties_all:
            print(f"  mean |preference| where it should tie: {sum(ties_all) / len(ties_all):.2f}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--run", default="v35f_allformats")
    b.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "formats"))
    b.add_argument("--n", type=int, default=40)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--set", default="synthetic", choices=sorted(KINDS), help="which defect kinds to build")
    r = sub.add_parser("run")
    r.add_argument("--judge", required=True)
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--set", default="synthetic", choices=sorted(SETS))
    rep = sub.add_parser("report")
    rep.add_argument("names", nargs="*")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.run, a.tasks, a.n, a.seed, a.set)
    elif a.cmd == "run":
        run(a.judge, a.workers, a.limit, a.set)
    else:
        report(a.names or sorted(p.stem[len("results_"):] for p in BENCH.glob("results_*.jsonl")))


if __name__ == "__main__":
    main()
