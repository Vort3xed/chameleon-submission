"""Collect AI-judge preferences between an engine's own candidate layouts.

For each task the engine's candidates are reduced to the best one per
(arrangement family, drops-something) bucket, the top few are rendered, and
the local VLM ranks them twice (shuffled).  `eval/fit_prefs.py` then fits the
objective weights to these rankings.

    python -m eval.collect_prefs --out eval/prefs/p1 --tasks eval/testsets/main --max-cands 4
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.chameleon_layout.pipeline import candidate_outputs  # noqa: E402
from eval.render import render  # noqa: E402
from eval.vlm_judge import _b64  # noqa: E402

PROMPT = """You are a senior brand designer reviewing an automatic design-resizing engine.
Image 1 is the ORIGINAL design. Images 2 to {last} are candidate versions of it for a {tw}x{th} canvas.
Rank the candidates from best to worst, judging: no unwanted overlaps; readable text (size, contrast,
nothing cut off); brand intact (logo/product art undistorted); an intentional, balanced layout that uses
the space well; faithful to the original's message and important content.
Answer with JSON only: {{"ranking": [best image number, ..., worst image number]}}"""


def pick(cands, k):
    """Best candidate per (family, drops) bucket, then the top-k buckets."""
    best = {}
    for terms, name, out in cands:
        key = (name.split()[0].rstrip("0123456789."), terms["kept"] < 0.999)
        if key not in best or terms["total"] > best[key][0]["total"]:
            best[key] = (terms, name, out)
    return sorted(best.values(), key=lambda c: -c[0]["total"])[:k]


def rank(src_img, imgs, tw, th, endpoint, model):
    content = [{"type": "text", "text": PROMPT.format(last=len(imgs) + 1, tw=tw, th=th)},
               {"type": "image_url", "image_url": {"url": _b64(src_img)}}]
    content += [{"type": "image_url", "image_url": {"url": _b64(im)}} for im in imgs]
    body = {"model": model, "temperature": 0.0, "max_tokens": 80, "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", text, re.S)
    order = [int(x) - 2 for x in json.loads(m.group(0)).get("ranking", [])] if m else []
    seen = []
    for o in order:  # keep a clean permutation of 0..n-1
        if 0 <= o < len(imgs) and o not in seen:
            seen.append(o)
    return seen if len(seen) == len(imgs) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "main"))
    ap.add_argument("--max-cands", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="qwen3.8-27b-abliterated")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted((Path(a.tasks) / "tasks").glob("*.json"))
    if a.only:
        files = [f for f in files if any(s in f.stem for s in a.only.split(","))]
    if a.limit:
        random.Random(0).shuffle(files)
        files = files[: a.limit]
    done = {json.loads(l)["task_id"] for l in (out_dir / "prefs.jsonl").read_text().splitlines()} \
        if (out_dir / "prefs.jsonl").exists() else set()

    def one(f):
        task = json.loads(f.read_text())
        tid = task.get("task_id", f.stem)
        if tid in done:
            return None
        try:
            cands = pick(candidate_outputs(task["source"], task["target_canvas"]), a.max_cands)
            if len(cands) < 2:
                return None
            src, _ = render(task["source"], max_size=1024)
            imgs = [render(c[2], max_size=1024)[0] for c in cands]
            tw, th = task["target_canvas"]["width"], task["target_canvas"]["height"]
            rankings = []
            for seed in (1, 2):
                perm = list(range(len(imgs)))
                random.Random(f"{tid}:{seed}").shuffle(perm)  # str seeds are stable across runs
                r = rank(src, [imgs[i] for i in perm], tw, th, a.endpoint, a.model)
                if r is not None:
                    rankings.append([perm[i] for i in r])
        except Exception as e:
            return {"task_id": tid, "error": repr(e)[:200]}
        return {"task_id": tid, "names": [c[1] for c in cands], "terms": [c[0] for c in cands], "rankings": rankings}

    with ThreadPoolExecutor(a.workers) as ex, open(out_dir / "prefs.jsonl", "a") as fh:
        n = 0
        for rec in ex.map(one, files):
            if rec and "rankings" in rec:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                n += 1
    print(f"collected {n} tasks into {out_dir / 'prefs.jsonl'}")


if __name__ == "__main__":
    main()
