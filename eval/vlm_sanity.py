"""How far can the VLM judge be trusted? Show it a resize next to a copy with a
known defect (the clean one should win) and next to an identical copy (should
tie), in both orders, using the same prompt as eval/vlm_pairwise.py.

    python -m eval.vlm_sanity --n 60
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.resize import resize  # noqa: E402
from eval.render import render  # noqa: E402
from eval.vlm_pairwise import ask  # noqa: E402


def _headline(d):
    texts = [e for e in d["elements"] if e.get("type") == "text" and not e.get("rotation")]
    return max(texts, key=lambda e: e.get("font_size", 0), default=None)


def _product(d):
    W, H = d["canvas"]["width"], d["canvas"]["height"]
    imgs = [e for e in d["elements"] if e.get("type") == "image" and e["width"] * e["height"] < 0.5 * W * H]
    return max(imgs, key=lambda e: e["width"] * e["height"], default=None)


def text_scale(f):
    def damage(d):
        for e in d["elements"]:
            if e.get("type") == "text":
                e["font_size"] = max(1, round(e["font_size"] * f))
        return d
    return damage


def collide(d):
    h, p = _headline(d), _product(d)
    if not (h and p):
        return None
    h["x"], h["y"] = p["x"] + (p["width"] - h["width"]) / 2, p["y"] + (p["height"] - h["height"]) / 2
    return d


def squash(d):
    p = _product(d)
    if not p:
        return None
    p["fit"], p["x"], p["width"] = "fill", p["x"] - 0.3 * p["width"], 1.6 * p["width"]
    return d


def cut(d):
    h = _headline(d)
    if not h:
        return None
    h["x"] = d["canvas"]["width"] - 0.5 * h["width"]
    return d


def drop_headline(d):
    h = _headline(d)
    if not h:
        return None
    d["elements"].remove(h)
    return d


DAMAGE = {"same": lambda d: d, "text_90": text_scale(0.9), "text_75": text_scale(0.75), "text_50": text_scale(0.5),
          "collide": collide, "squash": squash, "cut": cut, "drop_headline": drop_headline, "stretch": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "main"))
    ap.add_argument("--stretch-run", default="baseline_stretch")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--endpoint", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="qwen3.8-27b-abliterated")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    paths = sorted((Path(a.tasks) / "tasks").glob("*.json"))
    random.Random(a.seed).shuffle(paths)
    stretch = ROOT / "eval" / "runs" / a.stretch_run / "outputs"

    jobs = []
    for p in paths[: a.n]:
        task = json.loads(p.read_text())
        good = resize(task["source"], task["target_canvas"])
        for kind, damage in DAMAGE.items():
            if damage is None:
                s = stretch / p.name
                bad = json.loads(s.read_text()) if s.exists() else None
            else:
                bad = damage(copy.deepcopy(good))
            if bad is not None:
                jobs.append((p.stem, kind, task, good, bad))

    def one(job):
        tid, kind, task, good, bad = job
        src, g, b = (render(x, max_size=1024)[0] for x in (task["source"], good, bad))
        tw, th = task["target_canvas"]["width"], task["target_canvas"]["height"]
        try:
            v1 = int(ask(src, g, b, tw, th, a.endpoint, a.model).get("better", 0))  # clean shown first
            v2 = int(ask(src, b, g, tw, th, a.endpoint, a.model).get("better", 0))  # clean shown second
        except Exception as e:
            return {"task_id": tid, "kind": kind, "error": repr(e)[:120]}
        # per order: +1 clean preferred, -1 damaged preferred, 0 tie
        return {"task_id": tid, "kind": kind, "votes": [{2: 1, 3: -1}.get(v1, 0), {3: 1, 2: -1}.get(v2, 0)],
                "positions": [v1, v2]}

    with ThreadPoolExecutor(a.workers) as ex:
        recs = [r for r in ex.map(one, jobs) if "votes" in r]

    by = defaultdict(list)
    for r in recs:
        by[r["kind"]].append(r)
    print(f"{'defect':<14}{'pairs':>6}{'clean wins':>12}{'ties':>7}{'damaged wins':>14}{'order-dependent':>17}")
    for kind in DAMAGE:
        rs = by.get(kind, [])
        if not rs:
            continue
        votes = [v for r in rs for v in r["votes"]]
        flips = sum(1 for r in rs if r["votes"][0] != r["votes"][1])
        print(f"{kind:<14}{len(rs):>6}{votes.count(1) / len(votes):>12.0%}{votes.count(0) / len(votes):>7.0%}"
              f"{votes.count(-1) / len(votes):>14.0%}{flips / len(rs):>17.0%}")
    first = sum(1 for r in recs for p in r["positions"] if p == 2)
    second = sum(1 for r in recs for p in r["positions"] if p == 3)
    print(f"position: image 2 picked {first}x, image 3 picked {second}x over {2 * len(recs)} verdicts")
    if a.out:
        Path(a.out).write_text("\n".join(json.dumps(r) for r in recs))


if __name__ == "__main__":
    main()
