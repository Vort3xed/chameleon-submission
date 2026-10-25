"""The fitted discriminator: a design's quality as a weighted sum of exact
features (design rules + structural scorer), weights from eval/judge_fit.py.
Milliseconds per design, so whole runs compare in seconds.

    python -m eval.discriminator --a v35f_allformats --b v35g_allformats
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.judge_fit import WEIGHTS, features, save_cache  # noqa: E402


def _weights():
    w = json.loads(WEIGHTS.read_text())
    return {n: v for n, v in zip(w["features"], w["weights"]) if n != "vlm"}


def quality(source: dict, target: dict, design: dict, w=None) -> float:
    w = w or _weights()
    f = features(source, target, design)
    return sum(f[k] * v for k, v in w.items())


SEVERE = 1.0  # a quality drop this large is a visible regression, whatever the tally says


def sign_test(wins: int, losses: int) -> float:
    """Two-sided p-value that wins and losses are a fair coin."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def compare(a: str, b: str, tasks: str, eps: float = 1e-4):
    from eval.vlm_pairwise import differs

    w = _weights()
    ra, rb = ROOT / "eval" / "runs" / a / "outputs", ROOT / "eval" / "runs" / b / "outputs"
    wins = losses = ties = 0
    deltas = []
    for pa in sorted(ra.glob("*.json")):
        pb = rb / pa.name
        if not pb.exists():
            continue
        da, db = json.loads(pa.read_text()), json.loads(pb.read_text())
        if not differs(da, db):
            continue
        task = json.loads((Path(tasks) / "tasks" / pa.name).read_text())
        d = quality(task["source"], task["target_canvas"], db, w) - quality(task["source"], task["target_canvas"], da, w)
        deltas.append((d, pa.stem))
        wins += d > eps
        losses += d < -eps
        ties += abs(d) <= eps
    save_cache()
    deltas.sort()
    mean = sum(d for d, _ in deltas) / max(1, len(deltas))
    severe = sum(d < -SEVERE for d, _ in deltas)
    p = sign_test(wins, losses)
    verdict = "ACCEPT" if p < 0.05 and wins > losses and mean > 0 and severe <= max(2, len(deltas) // 100) else "reject"
    print(f"{b} vs {a}: {len(deltas)} differing tasks -> B better {wins}, A better {losses}, ties {ties}; "
          f"sign test p={p:.3g}; mean {mean:+.3f}; severe losses {severe} -> {verdict}")
    for d, t in deltas[:5]:
        print(f"  A better {d:+.3f} {t}")
    for d, t in deltas[-5:][::-1]:
        print(f"  B better {d:+.3f} {t}")
    return wins, losses, ties, mean, severe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "formats"))
    a = ap.parse_args()
    compare(a.a, a.b, a.tasks)


if __name__ == "__main__":
    main()
