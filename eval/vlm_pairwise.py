"""A/B test two runs with the local VLM: for tasks where the outputs differ,
show the original plus both resizes (twice, order swapped to cancel position
bias) and ask which one a designer would ship.

    python -m eval.vlm_pairwise --a v2 --b v3 --n 80
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

from eval.render import render  # noqa: E402
from eval.vlm_judge import _b64  # noqa: E402

PROMPT = """You are a senior brand designer reviewing an automatic design-resizing engine.
Image 1 is the ORIGINAL design. Images 2 and 3 are two candidate versions of it for a {tw}x{th} canvas.
Judge which candidate is better overall: no unwanted overlaps, readable text (size, contrast, nothing cut off),
brand intact (logo/product art not distorted), an intentional balanced layout that uses the space well,
and faithful to the original's message and important content.
Answer with JSON only: {{"better": 2 or 3 or 0 (0 = equally good), "reason": "short phrase"}}"""


def ask(src_img, a_img, b_img, tw, th, endpoint, model) -> dict:
    body = {
        "model": model, "temperature": 0.0, "max_tokens": 120,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(tw=tw, th=th)},
            {"type": "image_url", "image_url": {"url": _b64(src_img)}},
            {"type": "image_url", "image_url": {"url": _b64(a_img)}},
            {"type": "image_url", "image_url": {"url": _b64(b_img)}},
        ]}],
    }
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        content = json.loads(r.read())["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", content, re.S)
    return json.loads(m.group(0)) if m else {}


def differs(a: dict, b: dict) -> bool:
    def geo(d):
        return [(e.get("id"), round(e.get("x", 0)), round(e.get("y", 0)), round(e.get("width", 0)),
                 round(e.get("height", 0)), e.get("font_size"), e.get("opacity"), e.get("z_index"),
                 e.get("corner_radius"), e.get("text_align"))
                for e in d.get("elements", []) if isinstance(e, dict)]
    return geo(a) != geo(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "main"))
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="qwen3.8-27b-abliterated")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    ra, rb = ROOT / "eval" / "runs" / a.a / "outputs", ROOT / "eval" / "runs" / a.b / "outputs"
    ids = sorted(p.stem for p in ra.glob("*.json") if (rb / p.name).exists())
    if a.only:
        ids = [i for i in ids if any(s in i for s in a.only.split(","))]
    ids = [i for i in ids if differs(json.loads((ra / f"{i}.json").read_text()), json.loads((rb / f"{i}.json").read_text()))]
    random.Random(a.seed).shuffle(ids)
    ids = ids[: a.n]

    def one(tid):
        task = json.loads((Path(a.tasks) / "tasks" / f"{tid}.json").read_text())
        src, _ = render(task["source"], max_size=1024)
        ia, _ = render(json.loads((ra / f"{tid}.json").read_text()), max_size=1024)
        ib, _ = render(json.loads((rb / f"{tid}.json").read_text()), max_size=1024)
        tw, th = task["target_canvas"]["width"], task["target_canvas"]["height"]
        votes = 0.0
        reasons = []
        try:
            r1 = ask(src, ia, ib, tw, th, a.endpoint, a.model)  # A shown first
            r2 = ask(src, ib, ia, tw, th, a.endpoint, a.model)  # B shown first
            votes += {2: -0.5, 3: 0.5}.get(int(r1.get("better", 0)), 0.0)
            votes += {2: 0.5, 3: -0.5}.get(int(r2.get("better", 0)), 0.0)
            reasons = [r1.get("reason", ""), r2.get("reason", "")]
        except Exception as e:
            return {"task_id": tid, "error": repr(e)[:120]}
        return {"task_id": tid, "b_minus_a": votes, "reasons": reasons}

    with ThreadPoolExecutor(a.workers) as ex:
        recs = [r for r in ex.map(one, ids) if "b_minus_a" in r]
    wins = sum(1 for r in recs if r["b_minus_a"] > 0)
    losses = sum(1 for r in recs if r["b_minus_a"] < 0)
    print(f"{a.b} vs {a.a}: {len(recs)} differing tasks judged -> B wins {wins}, A wins {losses}, "
          f"ties {len(recs) - wins - losses}; net preference {sum(r['b_minus_a'] for r in recs) / max(1, len(recs)):+.3f}")
    for r in [r for r in sorted(recs, key=lambda r: r["b_minus_a"]) if r["b_minus_a"] < 0][:6]:
        print(f"  A better: {r['task_id']}: {r['reasons']}")
    for r in [r for r in sorted(recs, key=lambda r: -r["b_minus_a"]) if r["b_minus_a"] > 0][:6]:
        print(f"  B better: {r['task_id']}: {r['reasons']}")
    out = ROOT / "eval" / "runs" / a.b / f"pairwise_vs_{a.a}.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in recs))


if __name__ == "__main__":
    main()
