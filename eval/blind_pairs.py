"""Blind A/B sheets for judging two engine runs by eye (a person, or a model
that can read images), and the verdict from the labels that come back.

    python -m eval.blind_pairs build --a runA --b runB --tasks eval/testsets/formats --n 40 --out DIR
    python -m eval.blind_pairs score --out DIR --labels labels.jsonl

`build` renders ORIGINAL | A | B for n tasks on which the runs differ visibly,
with each pair's sides shuffled; the key (which side is which run) goes to
DIR/key.json, never into the images.  `score` reads {"key", "choice"} lines
(A / B / = / X for both bad) and reports how often run b won.

eval/blind_rubric.txt holds the labeller's standards, written from their notes
on eval/labels/human.jsonl; give it to whoever judges the sheets.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUNS = ROOT / "eval" / "runs"


def _sheet(docs, labels, height: int = 420):
    from PIL import Image, ImageDraw

    from eval.render import render

    ims = [render(d, max_size=900)[0].convert("RGB") for d in docs]
    ims = [im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
           for im in ims for s in [min(height / im.height, 700 / im.width)]]
    out = Image.new("RGB", (sum(im.width for im in ims) + 30 * len(ims), height + 30), "white")
    x = 0
    for lab, im in zip(labels, ims):
        out.paste(im, (x, 30))
        ImageDraw.Draw(out).text((x + 4, 8), lab, fill="black")
        x += im.width + 30
    return out


def build(a: str, b: str, tasks: Path, n: int, out: Path, seed: int):
    from eval.vlm_pairwise import differs

    rng = random.Random(seed)
    ra, rb = RUNS / a / "outputs", RUNS / b / "outputs"
    ids = sorted(q.stem for q in ra.glob("*.json") if (rb / q.name).exists())
    rng.shuffle(ids)
    out.mkdir(parents=True, exist_ok=True)
    key = {}
    for tid in ids:
        da, db = (json.loads((r / f"{tid}.json").read_text()) for r in (ra, rb))
        if not differs(da, db):
            continue
        flip = rng.random() < 0.5
        name = f"q{len(key):03d}"
        src = json.loads((tasks / "tasks" / f"{tid}.json").read_text())["source"]
        _sheet([src] + ([db, da] if flip else [da, db]), ("ORIGINAL", "A", "B")).save(out / f"{name}.png")
        key[name] = {"task_id": tid, "A": b if flip else a, "B": a if flip else b}
        if len(key) >= n:
            break
    (out / "key.json").write_text(json.dumps({"a": a, "b": b, "pairs": key}, indent=1))
    print(f"{len(key)} pairs -> {out}")


def score(out: Path, labels: Path):
    from scipy.stats import binomtest

    key = json.loads((out / "key.json").read_text())
    b, wins, losses, ties, bad = key["b"], [], [], 0, 0
    for line in labels.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        pair = key["pairs"].get(d["key"])
        if pair is None:
            continue
        c = d["choice"]
        if c in "AB":
            (wins if pair[c] == b else losses).append(pair["task_id"])
        else:
            ties += c == "="
            bad += c == "X"
    n = len(wins) + len(losses)
    p = binomtest(len(wins), n).pvalue if n else 1.0
    print(f"{b} vs {key['a']}: {b} better {len(wins)}, worse {len(losses)}, ties {ties}, both bad {bad}; sign test p={p:.3g}")
    for tid in losses:
        print("  worse", tid)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    bp = sub.add_parser("build")
    bp.add_argument("--a", required=True)
    bp.add_argument("--b", required=True)
    bp.add_argument("--tasks", type=Path, required=True)
    bp.add_argument("--n", type=int, default=40)
    bp.add_argument("--out", type=Path, required=True)
    bp.add_argument("--seed", type=int, default=0)
    sp = sub.add_parser("score")
    sp.add_argument("--out", type=Path, required=True)
    sp.add_argument("--labels", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "build":
        build(args.a, args.b, args.tasks, args.n, args.out, args.seed)
    else:
        score(args.out, args.labels)


if __name__ == "__main__":
    main()
