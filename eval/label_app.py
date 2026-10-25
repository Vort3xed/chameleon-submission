"""Human labels: which of two real resizes is better?  The yardstick every
judge is measured against.

    python -m eval.label_app build --n 80      # pick pairs, render them
    python -m eval.label_app serve             # http://127.0.0.1:8790, keys A / B / = (S skips)

Pairs are real decisions: two engine versions that disagree on a task, or the
engine's best layout against the best one from a different family (what the
objective has to choose between).  Labels land in eval/labels/human.jsonl and
labelled pairs are exported to eval/judge_bench/human_pairs.jsonl for
`python -m eval.judge_bench run --set human`.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LABELS = ROOT / "eval" / "labels"
BENCH = ROOT / "eval" / "judge_bench"
FAMILIES = ("preserve", "stack", "split", "row")


def _family(name: str) -> str:
    return next((f for f in FAMILIES if name.startswith(f)), name.split()[0])


def build(n: int, seed: int, versions):
    from engine.chameleon_layout.pipeline import candidate_outputs
    from eval.render import render
    from eval.vlm_pairwise import differs

    tasks = ROOT / "eval" / "testsets" / "formats" / "tasks"
    rng = random.Random(seed)
    pairs = []
    # 1. engine versions that disagree
    for a, b in versions:
        ra, rb = ROOT / "eval" / "runs" / a / "outputs", ROOT / "eval" / "runs" / b / "outputs"
        ids = sorted(p.stem for p in ra.glob("*.json") if (rb / p.name).exists())
        rng.shuffle(ids)
        got = 0
        for tid in ids:
            da, db = json.loads((ra / f"{tid}.json").read_text()), json.loads((rb / f"{tid}.json").read_text())
            if differs(da, db):
                pairs.append({"id": f"{tid}|{a}|{b}", "task_id": tid, "origin": "versions", "a": da, "b": db})
                got += 1
                if got >= n // (2 * len(versions)):
                    break
    # 2. the objective's own decision: best layout vs best of another family
    ids = sorted(p.stem for p in tasks.glob("*.json"))
    rng.shuffle(ids)
    for tid in ids:
        if sum(p["origin"] == "families" for p in pairs) >= n - n // 2:
            break
        task = json.loads((tasks / f"{tid}.json").read_text())
        cands = sorted(candidate_outputs(task["source"], task["target_canvas"]), key=lambda c: -c[0]["total"])
        best = cands[0]
        other = next((c for c in cands if _family(c[1]) != _family(best[1])), None)
        if other is not None:
            pairs.append({"id": f"{tid}|{best[1]}|{other[1]}", "task_id": tid, "origin": "families",
                          "a": best[2], "b": other[2]})
    rng.shuffle(pairs)
    (LABELS / "img").mkdir(parents=True, exist_ok=True)
    for k, p in enumerate(pairs):
        p["key"] = f"p{k:03d}"
        task = json.loads((tasks / f"{p['task_id']}.json").read_text())
        p["source"], p["target"] = task["source"], task["target_canvas"]
        if rng.random() < 0.5:  # which one shows on the left is random
            p["a"], p["b"] = p["b"], p["a"]
        for side in ("source", "a", "b"):
            render(p[side], max_size=900)[0].convert("RGB").save(LABELS / "img" / f"{p['key']}_{side}.png")
    (LABELS / "pairs.jsonl").write_text("\n".join(json.dumps(p) for p in pairs))
    print(f"{len(pairs)} pairs -> {LABELS / 'pairs.jsonl'}")


PAGE = """<!doctype html><meta charset=utf-8><title>Which resize is better?</title>
<style>body{font:15px system-ui;margin:16px;background:#e9ecee;color:#14181c}
.row{display:flex;gap:16px;align-items:flex-start}.col{flex:1;min-width:0}
img{max-width:100%;max-height:78vh;box-shadow:0 0 0 1px #0003;display:block}
.src img{max-height:40vh}h2{margin:4px 0 8px;font-size:15px}kbd{background:#fff;border:1px solid #999;
border-radius:3px;padding:0 5px}.bar{margin-bottom:10px}</style>
<div class=bar><b>{done}/{total}</b> labelled &nbsp; {target} &nbsp;&nbsp; <kbd>A</kbd> left better &nbsp;
<kbd>B</kbd> right better &nbsp; <kbd>=</kbd> can't tell &nbsp; <kbd>S</kbd> skip</div>
<div class=row><div class="col src" style="flex:.6"><h2>Original</h2><img src="/img/{key}_source.png"></div>
<div class=col><h2>A</h2><img src="/img/{key}_a.png"></div><div class=col><h2>B</h2><img src="/img/{key}_b.png"></div></div>
<script>document.onkeydown=e=>{const k={a:'A',b:'B','=':'=',s:'S'}[e.key.toLowerCase()];if(!k)return;
fetch('/label',{method:'POST',body:JSON.stringify({key:'{key}',choice:k})}).then(()=>location.reload())}</script>"""

DONE = "<!doctype html><meta charset=utf-8><body style='font:16px system-ui;margin:40px'>All {total} pairs labelled. Thanks!"


def _fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def _labels():
    path = LABELS / "human.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def export():
    pairs = {json.loads(l)["key"]: json.loads(l) for l in (LABELS / "pairs.jsonl").read_text().splitlines()}
    latest = {r["key"]: r["choice"] for r in _labels()}
    out = []
    for key, c in latest.items():
        if c in ("A", "B"):
            p = pairs[key]
            good, bad = (p["a"], p["b"]) if c == "A" else (p["b"], p["a"])
            out.append({"id": p["id"], "task_id": p["task_id"], "kind": f"human_{p['origin']}", "sev": 0,
                        "source": p["source"], "target": p["target"], "good": good, "bad": bad})
    BENCH.mkdir(parents=True, exist_ok=True)
    (BENCH / "human_pairs.jsonl").write_text("\n".join(json.dumps(p) for p in out))
    ties = sum(c == "=" for c in latest.values())
    print(f"{len(out)} decided pairs exported ({ties} can't-tell)")


def serve(port: int):
    pairs = [json.loads(l) for l in (LABELS / "pairs.jsonl").read_text().splitlines()]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/img/"):
                f = LABELS / "img" / Path(self.path).name
                return self._send(f.read_bytes(), "image/png") if f.exists() else self.send_error(404)
            seen = {r["key"] for r in _labels()}
            todo = [p for p in pairs if p["key"] not in seen]
            if not todo:
                return self._send(_fill(DONE, total=len(pairs)).encode(), "text/html")
            p = todo[0]
            page = _fill(PAGE, key=p["key"], done=len(pairs) - len(todo), total=len(pairs),
                         target=f"target {p['target']['width']}x{p['target']['height']}")
            self._send(page.encode(), "text/html")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with (LABELS / "human.jsonl").open("a") as f:
                f.write(json.dumps({"key": body["key"], "choice": body["choice"]}) + "\n")
            self._send(b"ok", "text/plain")

    print(f"label at http://127.0.0.1:{port}  (Ctrl-C to stop; then run: python -m eval.label_app export)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--n", type=int, default=80)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--versions", default="v12_allformats:v35f_allformats,v27b_allformats:v35f_allformats")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8790)
    sub.add_parser("export")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.n, a.seed, [tuple(v.split(":")) for v in a.versions.split(",")])
    elif a.cmd == "serve":
        serve(a.port)
    else:
        export()


if __name__ == "__main__":
    main()
