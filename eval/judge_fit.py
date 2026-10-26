"""Fit and audit the discriminator: a logistic model on per-design features
(design rules, two absolute taste measures found in the human labels, and the
structural scorer's metrics), optionally plus VLM votes.  Human labels count
HUMAN_WEIGHT times a synthetic pair.

Weights are non-negative (every feature is "higher = better"), there is no
intercept (the model compares two designs symmetrically) and L2 keeps them
small.  Overfitting is audited three ways:

  * by task      k-fold with every task's pairs held out together
  * by defect    leave one defect type out entirely (does it catch defects it never saw?)
  * by source    fit on synthetic defects, test on human labels (and vice versa)
  * leakage      the by-task audit with shuffled labels must fall to ~50%

    python -m eval.judge_fit                 # audit + save eval/judge_weights.json
    python -m eval.judge_fit --vlm holistic_lp
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.design_rules import RULES, TASTE, evaluate, role_groups, taste  # noqa: E402

BENCH = ROOT / "eval" / "judge_bench"
WEIGHTS = ROOT / "eval" / "judge_weights.json"
SCORER = ("overlap", "cutoff", "text_fit", "readability", "hierarchy", "prominence", "groups", "distortion",
          "margins", "space", "balance", "alignment", "completeness", "reading_order", "bg_coverage",
          "missing_visible")
FEATURES = tuple(f"rule_{k}" for k in RULES) + tuple(f"taste_{k}" for k in TASTE) + tuple(f"score_{k}" for k in SCORER)
HUMAN_WEIGHT = 5  # a human label counts as much as five synthetic pairs: they are few, and they are the yardstick

# cache keyed by the metric code too: editing the rules, the scorer or the scene analysis they share invalidates it
_SOURCES = [ROOT / "eval" / f for f in ("design_rules.py", "score.py", "judge_fit.py")] + \
    [ROOT / "engine" / "chameleon_layout" / f for f in ("scene.py", "geometry.py", "text_metrics.py", "assets.py")]
_CODE = hashlib.sha1(b"".join(f.read_bytes() for f in _SOURCES)).hexdigest()[:12]
_cache_path = BENCH / f"features_{_CODE}.json"
_cache = json.loads(_cache_path.read_text()) if _cache_path.exists() else {}


_sources: dict = {}  # source digest -> (scene, scorer prep): every comparison scores several designs of one source


def features(source: dict, target: dict, design: dict) -> dict:
    """Every feature of one design (cached).  The source is analysed once, the
    design's scene is shared by the rules and the taste features, and the scorer
    skips JSON-schema validation - every design here is a schema-valid source
    with new geometry, and the gate's own checks (ids, frozen fields, numbers,
    bounds, aspect) still run."""
    from eval.design_rules import _scene
    from eval.score import prepare, score_task

    src = json.dumps(source, sort_keys=True)
    key = hashlib.sha1((src + json.dumps(design, sort_keys=True)).encode()).hexdigest()
    if key not in _cache:
        digest = hashlib.sha1(src.encode()).hexdigest()
        if digest not in _sources:
            _sources[digest] = (_scene(source), prepare(source, False))
        src_scene, src_prep = _sources[digest]
        scene = _scene(design)
        f = {f"rule_{k}": v for k, v in evaluate(source, design, (src_scene, scene)).items()}
        f.update({f"taste_{k}": v for k, v in taste(design, scene, role_groups(src_scene[2], "hero")).items()})
        r = score_task(source, target, design, src_prep, do_render=False, schema=False)
        failed = bool(r.get("gate"))  # a design that breaks the hard rules scores nothing
        f.update({f"score_{k}": 0.0 if failed else float(r["metrics"].get(k, 1.0)) for k in SCORER})
        _cache[key] = f
    return _cache[key]


def save_cache():
    _cache_path.write_text(json.dumps(_cache))


def load(which: str):
    path = BENCH / {"synthetic": "pairs.jsonl", "human": "human_pairs.jsonl", "unseen": "unseen_pairs.jsonl",
                    "unseen2": "unseen2_pairs.jsonl", "unseen3": "unseen3_pairs.jsonl"}[which]
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
    # leakage control: with each pair's good side chosen at random the same audit must read ~50%
    rng = np.random.default_rng(0)
    shuffled = []
    for _ in range(5):
        Xr = Xs * rng.choice([-1.0, 1.0], size=(len(Xs), 1))
        shuffled.append(np.mean([accuracy(Xr[f_of == k], fit(Xr[f_of != k], l2)) for k in range(5)]))
    print(f"    same, labels shuffled (5x):      {np.mean(shuffled):.1%} (should be ~50%)")

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
        accs = [accuracy(Xh[hfo == k], fit(np.vstack([Xs] + [Xh[hfo != k]] * HUMAN_WEIGHT), l2))
                for k in range(5) if (hfo == k).any()]
        print(f"  fit synthetic + other human -> held-out human: {np.mean(accs):.1%}")
    w = fit(np.vstack([Xs] + [Xh] * HUMAN_WEIGHT) if len(hum) else Xs, l2)
    for name, title in (("unseen", "defect kinds never used in fitting (other tasks, newer engine)"),
                        ("unseen2", "a second unseen set, built after the rules were last changed"),
                        ("unseen3", "a third: failures the engine could make (cropped art, text off its card, ...)")):
        unseen, Xu = design_matrix(load(name), vlm)
        if len(unseen):
            print(f"  {title}:")
            u_of = np.array([p["kind"] for p in unseen])
            for k in sorted(set(u_of)):
                print(f"    {k:<18}{accuracy(Xu[u_of == k], w):>7.1%}  (n={int((u_of == k).sum())})")
            print(f"    {'all':<18}{accuracy(Xu, w):>7.1%}")
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


def bootstrap(n: int, l2: float = 0.01, seed: int = 0):
    """Refit on n resamples of whole tasks: the spread of out-of-sample accuracy
    and of each weight.  A model that fits noise swings; this one should not."""
    rng = np.random.default_rng(seed)
    syn = [p for p in load("synthetic") if p["kind"] not in ("same", "invisible")]
    syn, X = design_matrix(syn)
    save_cache()
    tasks = sorted({p["task_id"] for p in syn})
    t_of = np.array([p["task_id"] for p in syn])
    accs, ws = [], []
    for _ in range(n):
        pick = set(rng.choice(tasks, size=len(tasks), replace=True))
        inside = np.array([t in pick for t in t_of])
        w = fit(X[inside], l2)
        accs.append(accuracy(X[~inside], w))
        ws.append(w / max(np.abs(w).sum(), 1e-12))  # compare shapes, not overall scale
    ws = np.array(ws)
    print(f"bootstrap x{n}: out-of-sample accuracy {np.mean(accs):.1%} ± {np.std(accs):.1%} "
          f"(min {np.min(accs):.1%})")
    order = np.argsort(-ws.mean(axis=0))
    print("  weight share (mean ± sd):", ", ".join(f"{FEATURES[i]}={ws[:, i].mean():.3f}±{ws[:, i].std():.3f}"
                                                 for i in order if ws[:, i].mean() > 0.01))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vlm", default="")
    ap.add_argument("--l2", type=float, default=0.01)
    ap.add_argument("--bootstrap", type=int, default=0, help="also refit on this many task resamples")
    a = ap.parse_args()
    audit(a.vlm, a.l2)
    if a.bootstrap:
        bootstrap(a.bootstrap, a.l2)


if __name__ == "__main__":
    main()
