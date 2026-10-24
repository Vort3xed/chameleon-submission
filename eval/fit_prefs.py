"""Fit the objective's weights to AI-judge rankings (Bradley-Terry / logistic
regression on feature differences), with task-level cross-validation.

    python -m eval.fit_prefs eval/prefs/p1
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.chameleon_layout.objective import WEIGHTS  # noqa: E402


def pairs_from(recs, keys):
    X, groups = [], []
    for g, r in enumerate(recs):
        feats = np.array([[t.get(k, 0.0) for k in keys] for t in r["terms"]])
        for ranking in r["rankings"]:
            for i in range(len(ranking)):
                for j in range(i + 1, len(ranking)):
                    X.append(feats[ranking[i]] - feats[ranking[j]])  # winner - loser
                    groups.append(g)
    return np.array(X), np.array(groups)


def fit(X, l2=0.05, steps=3000, lr=0.5):
    """Logistic regression without intercept: P(win) = sigmoid(w . (f_win - f_lose))."""
    w = np.zeros(X.shape[1])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-X @ w))
        grad = -(X * (1 - p)[:, None]).mean(0) + l2 * w
        w -= lr * grad
    return w


def accuracy(X, w):
    return float(((X @ w) > 0).mean()) if len(X) else float("nan")


def main():
    d = Path(sys.argv[1])
    recs = [json.loads(l) for l in (d / "prefs.jsonl").read_text().splitlines() if l]
    recs = [r for r in recs if r.get("rankings")]
    keys = [k for k in recs[0]["terms"][0] if k != "total"]
    X, groups = pairs_from(recs, keys)
    current = np.array([WEIGHTS.get(k, 0.0) for k in keys])
    print(f"{len(recs)} tasks, {len(X)} pairs; current weights agree with judge on {accuracy(X, current):.3f}")
    folds = 5
    accs = []
    for f in range(folds):
        test = groups % folds == f
        w = fit(X[~test])
        accs.append(accuracy(X[test], w))
    print(f"cross-validated accuracy of fitted weights: {np.mean(accs):.3f} (folds {np.round(accs, 3)})")
    w = fit(X)
    print("fitted weights (sorted):")
    for k, v in sorted(zip(keys, w), key=lambda kv: -abs(kv[1])):
        print(f"  {k:12s} {v:+.3f}   (current {WEIGHTS.get(k, 0.0):+.3f})")


if __name__ == "__main__":
    main()
