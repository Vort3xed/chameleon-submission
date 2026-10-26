"""Hunt for weaknesses: rank a run's outputs by discriminator quality and show
the worst, each with the features that pulled it down (source | output).

    python -m eval.run_eval --name r_v37v --tasks eval/testsets/random
    python -m eval.hunt --run r_v37v --tasks eval/testsets/random --n 12 --out eval/gallery/hunt.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.discriminator import _weights, quality  # noqa: E402
from eval.judge_fit import features, save_cache  # noqa: E402


def worst(run: str, tasks: str, n: int):
    """[(quality, task id, task, output, weakest features)] for the n lowest-quality outputs,
    judged on what the engine did: the absolute taste features, which also mark a source
    that was plain to begin with, are left out."""
    w, rows = {k: v for k, v in _weights().items() if not k.startswith("taste_")}, []
    for p in sorted((ROOT / "eval" / "runs" / run / "outputs").glob("*.json")):
        task = json.loads((Path(tasks) / "tasks" / p.name).read_text())
        out = json.loads(p.read_text())
        f = features(task["source"], task["target_canvas"], out)
        weak = sorted(((v - 1.0) * w.get(k, 0.0), k, v) for k, v in f.items() if v < 0.99)[:3]
        rows.append((quality(task["source"], task["target_canvas"], out, w), p.stem, task, out, weak))
    save_cache()
    return sorted(rows, key=lambda r: r[0])[:n]


def main():
    from PIL import Image, ImageDraw

    from eval.render import render

    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    for q, tid, task, out, weak in worst(a.run, a.tasks, a.n):
        label = f"{tid}  q={q:.2f}  " + ", ".join(f"{k.split('_', 1)[1]}={v:.2f}" for _, k, v in weak)
        print(label)
        ims = [render(task["source"], max_size=260)[0].convert("RGB"), render(out, max_size=420)[0].convert("RGB")]
        row = Image.new("RGB", (ims[0].width + ims[1].width + 20, max(i.height for i in ims) + 16), (255, 255, 255))
        row.paste(ims[0], (0, 16))
        row.paste(ims[1], (ims[0].width + 20, 16))
        ImageDraw.Draw(row).text((3, 2), label, fill=(0, 0, 0))
        rows.append(row)
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height + 6 for r in rows)), (130, 130, 130))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 6
    sheet.save(a.out)


if __name__ == "__main__":
    main()
