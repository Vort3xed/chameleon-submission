"""Attack the discriminator: hill-climb engine outputs on its score (random
moves and resizes of whole blocks, kept only when the score rises) and show
what it rewarded.  If the "improved" design looks worse, the discriminator has
a hole - this is how the label-wrapping exploit was found.

    python -m eval.attack --run v36k_allformats --tasks eval/testsets/formats \\
        --ids official_core_01__instagram_story,minimal_02__linkedin_banner --out /tmp/attack.png
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

from engine.chameleon_layout.scene import analyze  # noqa: E402
from eval.discriminator import _weights, quality  # noqa: E402
from eval.judge_fit import features, save_cache  # noqa: E402
from eval.score import gate  # noqa: E402


def _mutate(d: dict, groups, rng: random.Random) -> dict:
    """Move one block by up to 3% of the canvas, or scale it by up to ±15% about its centre."""
    W, H = d["canvas"]["width"], d["canvas"]["height"]
    out = copy.deepcopy(d)
    els = [out["elements"][i] for i in rng.choice(groups)]
    if rng.random() < 0.6:
        dx, dy = rng.uniform(-0.03, 0.03) * W, rng.uniform(-0.03, 0.03) * H
        for e in els:
            e["x"], e["y"] = e["x"] + dx, e["y"] + dy
    else:
        f = rng.uniform(0.85, 1.15)
        cx = sum(e["x"] + e["width"] / 2 for e in els) / len(els)
        cy = sum(e["y"] + e["height"] / 2 for e in els) / len(els)
        for e in els:
            e["x"], e["y"] = cx + (e["x"] - cx) * f, cy + (e["y"] - cy) * f
            e["width"], e["height"] = e["width"] * f, e["height"] * f
            if e.get("type") == "text":
                e["font_size"] = max(1, int(round(e["font_size"] * f)))
    return out


def climb(source: dict, target: dict, design: dict, steps: int, seed: int = 0):
    """(climbed design, start score, end score)."""
    w, rng = _weights(), random.Random(seed)
    sc = analyze(design["elements"], target["width"], target["height"])
    groups = [[it.idx for it in b.items] for b in sc.blocks + sc.ornaments]
    best, q0 = design, quality(source, target, design, w)
    q = q0
    for _ in range(steps if groups else 0):
        cand = _mutate(best, groups, rng)
        if not gate(source, target, cand):
            qc = quality(source, target, cand, w)
            if qc > q + 1e-6:
                best, q = cand, qc
    return best, q0, q


def main():
    from PIL import Image, ImageDraw

    from eval.render import render

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "formats"))
    ap.add_argument("--ids", required=True, help="comma-separated task ids")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    for tid in a.ids.split(","):
        task = json.loads((Path(a.tasks) / "tasks" / f"{tid}.json").read_text())
        start = json.loads((ROOT / "eval" / "runs" / a.run / "outputs" / f"{tid}.json").read_text())
        end, q0, q = climb(task["source"], task["target_canvas"], start, a.steps)
        f0, f1 = (features(task["source"], task["target_canvas"], d) for d in (start, end))
        print(f"{tid}: {q0:.2f} -> {q:.2f}", {k: round(f1[k] - f0[k], 2) for k in f0 if abs(f1[k] - f0[k]) > 0.02})
        ims = [render(d, max_size=360)[0].convert("RGB") for d in (start, end)]
        row = Image.new("RGB", (sum(i.width for i in ims) + 16, max(i.height for i in ims) + 18), (255, 255, 255))
        x = 0
        for im in ims:
            row.paste(im, (x, 18))
            x += im.width + 16
        ImageDraw.Draw(row).text((4, 3), f"{tid}  {q0:.2f} -> {q:.2f}  (engine | climbed on the discriminator)",
                                 fill=(0, 0, 0))
        rows.append(row)
    save_cache()
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height + 8 for r in rows)), (120, 120, 120))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 8
    sheet.save(a.out)


if __name__ == "__main__":
    main()
