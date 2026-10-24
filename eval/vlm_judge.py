"""AI-evaluator proxy: ask a local multimodal LLM to grade outputs against the
rubric from the brief (collisions, readability, brand, layout, faithfulness).

    python -m eval.vlm_judge --run v1 --n 60

Needs an OpenAI-compatible endpoint (default: local vLLM at 127.0.0.1:8000).
"""

from __future__ import annotations

import argparse
import base64
import io
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

KEYS = ["collisions", "readability", "brand", "layout", "faithfulness", "overall"]

PROMPT = """You are a senior brand designer judging an automatic design-resizing engine.
Image 1 is the ORIGINAL design ({sw}x{sh}). Image 2 is the engine's version for a new {tw}x{th} canvas.
The engine may move, resize and re-stack elements but may not rewrite copy, change fonts or invent imagery.
Grade image 2 from 1 (terrible) to 10 (flawless) on:
- collisions: no unwanted overlaps; intentional layering is fine; text never sits on busy imagery.
- readability: text is large enough to read at this canvas size, has contrast, and nothing is cut off.
- brand: logo, colours, fonts and product art survive intact and in proportion (not stretched or squashed).
- layout: looks intentionally designed for this shape: aligned, balanced, even spacing, clear hierarchy, good use of space.
- faithfulness: clearly the same design with the same message and important content.
- overall: would a marketing team ship it as is?
Reply with JSON only: {{"collisions":n,"readability":n,"brand":n,"layout":n,"faithfulness":n,"overall":n,"worst_problem":"short phrase"}}"""


def _b64(img, max_side=1024):
    im = img.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def judge(source: dict, output: dict, endpoint: str, model: str, timeout=240) -> dict:
    src_img, _ = render(source, max_size=1024)
    out_img, _ = render(output, max_size=1024)
    sc, oc = source["canvas"], output["canvas"]
    text = PROMPT.format(sw=sc["width"], sh=sc["height"], tw=oc["width"], th=oc["height"])
    body = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 300,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": _b64(src_img)}},
            {"type": "image_url", "image_url": {"url": _b64(out_img)}},
        ]}],
    }
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        content = json.loads(r.read())["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", content, re.S)
    data = json.loads(m.group(0)) if m else {}
    return {k: float(data[k]) for k in KEYS if k in data} | {"worst_problem": data.get("worst_problem", "")}


def judge_run(run: str, ids, tasks_dir: Path, endpoint: str, model: str, workers: int = 12):
    """Judge the given task ids of a run; writes vlm.jsonl and returns per-key means."""
    run_dir = ROOT / "eval" / "runs" / run
    outs = [run_dir / "outputs" / f"{i}.json" for i in ids if (run_dir / "outputs" / f"{i}.json").exists()]

    def one(p):
        task = json.loads((tasks_dir / p.name).read_text())
        try:
            res = judge(task["source"], json.loads(p.read_text()), endpoint, model)
        except Exception as e:
            res = {"error": repr(e)[:200]}
        return {"task_id": p.stem} | res

    with ThreadPoolExecutor(workers) as ex:
        recs = list(ex.map(one, outs))
    (run_dir / "vlm.jsonl").write_text("\n".join(json.dumps(r) for r in recs))
    ok = [r for r in recs if "overall" in r]
    means = {k: round(sum(r[k] for r in ok if k in r) / max(1, len(ok)), 3) for k in KEYS}
    means["n"] = len(ok)
    return means


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "main"))
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--endpoint", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="qwen3.8-27b-abliterated")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--ids", default="", help="comma-separated task ids (overrides --n sampling)")
    a = ap.parse_args()

    run_dir = ROOT / "eval" / "runs" / a.run
    ids = sorted(p.stem for p in (run_dir / "outputs").glob("*.json"))
    if a.ids:
        ids = [i for i in ids if i in set(a.ids.split(","))]
    else:
        random.Random(a.seed).shuffle(ids)
        ids = sorted(ids[: a.n])
    means = judge_run(a.run, ids, Path(a.tasks) / "tasks", a.endpoint, a.model, a.workers)
    print(f"{a.run}: judged {means['n']}/{len(ids)}")
    for k in KEYS:
        print(f"  {k:13s} {means[k]:.2f}")


if __name__ == "__main__":
    main()
