"""Pairwise judges.  Each takes (source, a, b, target) designs and returns a
preference in [-1, 1]: positive when `a` is the better resize.  The VLM ones
use the local OpenAI-compatible endpoint; `eval.judge_bench` measures them.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
import urllib.request
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from eval.render import _font, render

ENDPOINT = os.environ.get("JUDGE_ENDPOINT", "http://127.0.0.1:8000/v1")
MODEL = os.environ.get("JUDGE_MODEL", "qwen3.8-27b-abliterated")
SIDE = 1024


CACHE = Path(__file__).resolve().parent / "judge_bench" / "renders"


def render_path(d: dict, side: int = SIDE) -> Path:
    """The design rendered once and kept on disk (renders are the slow part of judging)."""
    key = hashlib.sha1(f"{side}:{json.dumps(d, sort_keys=True)}".encode()).hexdigest()
    f = CACHE / f"{key}.png"
    if not f.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f".{os.getpid()}.tmp")
        render(d, max_size=side)[0].convert("RGB").save(tmp, "PNG")
        tmp.replace(f)
    return f


def _img(d: dict, side: int = SIDE) -> Image.Image:
    return Image.open(render_path(d, side)).convert("RGB")


@lru_cache(maxsize=256)
def _file_url(path: str) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def _url(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _chat(content, max_tokens=8, thinking=False, logprobs=False) -> dict:
    body = {"model": MODEL, "temperature": 0.0, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": thinking},
            "messages": [{"role": "user", "content": content}]}
    if logprobs:
        body.update(logprobs=True, top_logprobs=10)
    req = urllib.request.Request(ENDPOINT.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())["choices"][0]


def _letter_pref(choice: dict) -> float:
    """P(A) - P(B) from the first answer token's top logprobs ("=" counts as neither)."""
    top = (choice.get("logprobs") or {}).get("content") or []
    if not top:
        return 0.0
    p = {"A": 0.0, "B": 0.0}
    for t in top[0]["top_logprobs"]:
        k = t["token"].strip().upper()
        if k in p:
            p[k] += math.exp(t["logprob"])
    return p["A"] - p["B"]


def _images(source, a, b):
    return [{"type": "image_url", "image_url": {"url": _file_url(str(render_path(x)))}} for x in (source, a, b)]


INTRO = ("You are a senior brand designer reviewing an automatic design-resizing engine. Image 1 is the ORIGINAL "
         "design. Images 2 and 3 are two candidate versions of it for a {w}x{h} canvas: Image 2 is candidate A, "
         "Image 3 is candidate B.\n")

# --- 1. the prompt eval/vlm_pairwise.py has used so far -----------------------

HOLISTIC = INTRO + ("Judge which candidate is better overall: no unwanted overlaps, readable text (size, contrast, "
                    "nothing cut off), brand intact (logo/product art not distorted), an intentional balanced layout "
                    "that uses the space well, and faithful to the original's message and important content.\n"
                    'Answer with JSON only: {{"better": "A" or "B" or "=" (equally good), "reason": "short phrase"}}')


def holistic(source, a, b, target) -> float:
    text = _chat([{"type": "text", "text": HOLISTIC.format(w=target["width"], h=target["height"])}]
                 + _images(source, a, b), max_tokens=80)["message"]["content"] or ""
    m = re.search(r'"better"\s*:\s*"?([AB=])', text)
    return {"A": 1.0, "B": -1.0}.get(m.group(1), 0.0) if m else 0.0


# --- 2. same question, answer read as probabilities --------------------------

LETTER = INTRO + ("Judge which candidate a professional designer would ship: no unwanted overlaps, readable text "
                  "(size, contrast, nothing cut off), brand intact, things line up, spacing is even and related items "
                  "sit together, margins are consistent, the most important element stands out, and it stays faithful "
                  "to the original.\nAnswer with a single letter: A or B.")


def holistic_lp(source, a, b, target) -> float:
    return _letter_pref(_chat(_images(source, a, b) + [
        {"type": "text", "text": LETTER.format(w=target["width"], h=target["height"])}], max_tokens=1, logprobs=True))


# --- 3. one question per rubric criterion ------------------------------------

CRITERIA = {
    "overlap": "Which candidate has fewer unwanted overlaps or collisions (text on busy art, elements touching)?",
    "readable": "In which candidate is all text easier to read (large enough, nothing cut off or crowded)?",
    "align": "In which candidate do elements line up better along shared edges or a shared centre line?",
    "spacing": "Which candidate has more even, deliberate spacing, with related items grouped and margins consistent?",
    "hierarchy": "In which candidate does the most important element (headline / product) stand out more clearly?",
    "faithful": "Which candidate stays more faithful to the original's content, look and arrangement?",
}


def rubric_lp(source, a, b, target, weights=None) -> float:
    imgs = _images(source, a, b)  # same prefix for every question, so the server's prefix cache reuses it
    intro = INTRO.format(w=target["width"], h=target["height"])
    prefs = {k: _letter_pref(_chat(imgs + [{"type": "text", "text": intro + q + "\nAnswer with a single letter: A or B."}],
                                   max_tokens=1, logprobs=True)) for k, q in CRITERIA.items()}
    w = weights or {k: 1.0 for k in CRITERIA}
    return sum(prefs[k] * w[k] for k in CRITERIA) / sum(w.values())


# --- 4. think first ------------------------------------------------------------

THINK = LETTER.replace("Answer with a single letter: A or B.",
                       "Compare the two carefully, element by element, then end with exactly one line: ANSWER: A or ANSWER: B.")


def think(source, a, b, target) -> float:
    msg = _chat(_images(source, a, b) + [{"type": "text", "text": THINK.format(w=target["width"], h=target["height"])}],
                max_tokens=3000, thinking=True)["message"]
    m = re.findall(r"ANSWER:\s*([AB])", msg.get("content") or "")
    return {"A": 1.0, "B": -1.0}.get(m[-1], 0.0) if m else 0.0


# --- 5. both candidates in one labelled image ---------------------------------

def side_by_side(a, b, side=SIDE) -> Image.Image:
    ia, ib = _img(a, side // 2 + 128), _img(b, side // 2 + 128)
    h = max(ia.height, ib.height)
    pad, top = 24, 56
    im = Image.new("RGB", (ia.width + ib.width + 3 * pad, h + top + pad), (128, 128, 128))
    d = ImageDraw.Draw(im)
    for k, (x, sub) in enumerate(((pad, ia), (2 * pad + ia.width, ib))):
        im.paste(sub, (x, top))
        d.text((x, 10), "AB"[k], fill=(255, 255, 255), font=_font(36))
    return im


SBS = ("You are a senior brand designer reviewing an automatic design-resizing engine. The first image is the "
       "ORIGINAL design. The second image shows two candidate versions of it for a {w}x{h} canvas side by side, "
       "labelled A (left) and B (right).\n") + LETTER.split("\n", 1)[1]


def sbs_lp(source, a, b, target) -> float:
    return _letter_pref(_chat([{"type": "image_url", "image_url": {"url": _file_url(str(render_path(source)))}},
                               {"type": "image_url", "image_url": {"url": _url(side_by_side(a, b))}},
                               {"type": "text", "text": SBS.format(w=target["width"], h=target["height"])}],
                              max_tokens=1, logprobs=True))


# --- 6. no model: exact design-rule metrics, and the structural scorer --------

def rules(source, a, b, target) -> float:
    from eval.design_rules import preference

    return preference(source, a, b)[0]


def scorer(source, a, b, target) -> float:
    from eval.score import score_task

    sa, sb = (score_task(source, target, x, do_render=False)["score"] for x in (a, b))
    return math.tanh((sa - sb) / 0.5)


JUDGES = {"holistic": holistic, "holistic_lp": holistic_lp, "rubric_lp": rubric_lp, "think": think, "sbs_lp": sbs_lp,
          "rules": rules, "scorer": scorer}
