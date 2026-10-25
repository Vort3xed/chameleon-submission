"""Fit and audit the discriminator: a logistic model on per-design features
(design rules + the structural scorer's metrics), optionally plus VLM votes.

Weights are non-negative (every feature is "higher = better"), there is no
intercept (the model compares two designs symmetrically) and L2 keeps them
small.  Overfitting is audited three ways:

  * by task      k-fold with every task's pairs held out together
  * by defect    leave one defect type out entirely (does it catch defects it never saw?)
  * by source    fit on synthetic defects, test on human labels (and vice versa)

    python -m eval.judge_fit                 # audit + save eval/judge_weights.json
    python -m eval.judge_fit --vlm holistic_lp
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.design_rules import RULES, evaluate  # noqa: E402

BENCH = ROOT / "eval" / "judge_bench"
WEIGHTS = ROOT / "eval" / "judge_weights.json"
SCORER = ("overlap", "cutoff", "text_fit", "readability", "hierarchy", "prominence", "groups", "distortion",
          "margins", "space", "balance", "alignment", "completeness", "reading_order", "bg_coverage",
          "missing_visible")
FEATURES = tuple(f"rule_{k}" for k in RULES) + tuple(f"score_{k}" for k in SCORER)

# cache keyed by the metric code too: editing the rules or the scorer invalidates it
_CODE = hashlib.sha1(b"".join((ROOT / "eval" / f).read_bytes() for f in ("design_rules.py", "score.py"))).hexdigest()[:12]
_cache_path = BENCH / f"features_{_CODE}.json"
_cache = json.loads(_cache_path.read_text()) if _cache_path.exists() else {}


def features(source: dict, target: dict, design: dict) -> dict:
    """Every feature of one design (cached: the scorer is the slow part)."""
    from eval.score import score_task

    key = hashlib.sha1((json.dumps(source, sort_keys=True) + json.dumps(design, sort_keys=True)).encode()).hexdigest()
    if key not in _cache:
        f = {f"rule_{k}": v for k, v in evaluate(source, design).items()}
        m = score_task(source, target, design, do_render=False)["metrics"]
        f.update({f"score_{k}": float(m.get(k, 1.0)) for k in SCORER})
        _cache[key] = f
    return _cache[key]


def save_cache():
    _cache_path.write_text(json.dumps(_cache))


def load(which: str):
    path = BENCH / {"synthetic": "pairs.jsonl", "human": "human_pairs.jsonl", "unseen": "unseen_pairs.jsonl"}[which]
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def vlm_votes(name: str, which: str) -> dict:
    path = BENCH / f"results_{name if which == 'synthetic' else which + '_' + name}.jsonl"
    if not path.exists():
        return {}
    return {r["id"]: sum(r["orders"]) / 2 for r in map(json.loads, path.read_text().splitlines())}


def design_matrix(pairs, vlm: str = ""):
    """Rows of feature differences (good - bad); the VLM vote, if used, is a last column."""
    votes = {}
    if vlm:
        for which in ("synthetic", "human"):
            votes.update(vlm_votes(vlm, which))
        pairs = [p for p in pairs if p["id"] in votes]
    rows = []
    for p in pairs:
        fg, fb = features(p["source"], p["target"], p["good"]), features(p["source"], p["target"], p["bad"])
        row = [fg[k] - fb[k] for k in FEATURES]
        if vlm:
            row.append(votes[p["id"]])
        rows.append(row)
    return pairs, np.array(rows, dtype=float).reshape(len(rows), len(FEATURES) + bool(vlm))


RULE_PRIOR = 0.5  # every design rule keeps at least this weight (in units of its typical range)


def fit(X: np.ndarray, l2: float = 0.01, steps: int = 3000, lr: float = 0.5) -> np.ndarray:
    """Non-negative logistic regression on differences, mirrored so it is symmetric.
    Design rules have a floor (a prior that each principle matters, so one the
    benchmark happens not to exercise is not silently switched off)."""
    if len(X) == 0:
        return np.zeros(X.shape[1])
    Xs = np.vstack([X, -X])
    y = np.concatenate([np.ones(len(X)), np.zeros(len(X))])
    scale = np.abs(Xs).max(axis=0)
    scale = np.where(scale < 1e-3, 1.0, scale)  # a feature the data never moves keeps its natural 0-1 range
    floor = np.array([RULE_PRIOR if n.startswith("rule_") else 0.0 for n in FEATURES] + [0.0] * (X.shape[1] - len(FEATURES)))
    w = floor.copy()
    Z = Xs / scale
    for _ in range(steps):
        p = 1 / (1 + np.exp(-Z @ w))
        w = np.maximum(floor, w - lr * (Z.T @ (p - y) / len(y) + l2 * w))
    return w / scale


def accuracy(X: np.ndarray, w: np.ndarray) -> float:
    if len(X) == 0:
        return float("nan")
    s = X @ w
    return float(np.mean(np.where(np.abs(s) < 1e-9, 0.5, s > 0)))


def audit(vlm: str = "", l2: float = 0.01):
    ties = [p for p in load("synthetic") if p["kind"] in ("same", "invisible")]
    syn = [p for p in load("synthetic") if p["kind"] not in ("same", "invisible")]
    hum = load("human")
    syn, Xs = design_matrix(syn, vlm)
    hum, Xh = design_matrix(hum, vlm)
    ties, Xt = design_matrix(ties, vlm)
    save_cache()
    names = list(FEATURES) + (["vlm"] if vlm else [])
    print(f"synthetic pairs {len(syn)}, human pairs {len(hum)}, features {len(names)}")

    # by task: 5 folds of whole tasks
    tasks = sorted({p["task_id"] for p in syn})
    fold = {t: i % 5 for i, t in enumerate(tasks)}
    f_of = np.array([fold[p["task_id"]] for p in syn])
    accs = [accuracy(Xs[f_of == k], fit(Xs[f_of != k], l2)) for k in range(5)]
    print(f"  by task (5-fold, synthetic):       {np.mean(accs):.1%}  train {accuracy(Xs, fit(Xs, l2)):.1%}")

    # by defect: never seen this kind of defect
    kinds = sorted({p["kind"] for p in syn})
    k_of = np.array([p["kind"] for p in syn])
    print("  leave one defect type out:")
    for k in kinds:
        w = fit(Xs[k_of != k], l2)
        print(f"    {k:<16}{accuracy(Xs[k_of == k], w):>7.1%}  (n={int((k_of == k).sum())})")

    # by source
    if len(hum):
        w = fit(Xs, l2)
        print(f"  fit synthetic -> human labels:     {accuracy(Xh, w):.1%}  (n={len(hum)})")
        h_tasks = sorted({p["task_id"] for p in hum})
        hf = {t: i % 5 for i, t in enumerate(h_tasks)}
        hfo = np.array([hf[p["task_id"]] for p in hum])
        accs = [accuracy(Xh[hfo == k], fit(np.vstack([Xs, Xh[hfo != k]]), l2)) for k in range(5) if (hfo == k).any()]
        print(f"  fit synthetic + other human -> held-out human: {np.mean(accs):.1%}")
    w = fit(np.vstack([Xs, Xh]) if len(hum) else Xs, l2)
    unseen, Xu = design_matrix(load("unseen"), vlm)
    if len(unseen):
        print("  defect kinds never used in fitting (other tasks, newer engine):")
        u_of = np.array([p["kind"] for p in unseen])
        for k in sorted(set(u_of)):
            print(f"    {k:<16}{accuracy(Xu[u_of == k], w):>7.1%}  (n={int((u_of == k).sum())})")
        print(f"    {'all':<16}{accuracy(Xu, w):>7.1%}")
    save_cache()
    # invisible changes must not move the verdict: |score| on them vs a typical real defect
    typical = float(np.median(np.abs(Xs @ w))) if len(Xs) else 1.0
    if len(Xt):
        print(f"  invisible-change sensitivity: {float(np.mean(np.abs(Xt @ w))) / max(typical, 1e-9):.2f} "
              f"of a typical defect (0 = ideal), {float(np.mean(np.abs(Xt @ w) > 0.5 * typical)):.0%} "
              f"of them would read as a real preference")
    top = sorted(zip(names, w), key=lambda t: -t[1])
    print("  weights:", ", ".join(f"{n}={v:.2f}" for n, v in top if v > 1e-3))
    WEIGHTS.write_text(json.dumps({"features": names, "weights": [float(v) for v in w], "vlm": vlm}, indent=1))
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vlm", default="")
    ap.add_argument("--l2", type=float, default=0.01)
    a = ap.parse_args()
    audit(a.vlm, a.l2)


if __name__ == "__main__":
    main()
