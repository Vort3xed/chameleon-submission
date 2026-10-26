"""One step of the improvement loop: run the engine as it is now on the format
set, the fresh holdout, the stress set, the random designs, banner-shaped
sources (strips) and the extra presets, then judge it against a baseline run
with the discriminator.

A set where nothing changed is neutral; a set blocks the step if it has
gate failures or crashes, too many severe losses, or significantly more
losses than wins.  The step is accepted when no set blocks and at least one
improves significantly (sign test p < 0.05 with a positive mean) - so a fix
aimed at unusual designs can win where it acts without moving the rest.
Every step is appended to eval/runs/loop.jsonl.

    python -m eval.loop --name v37a --baseline v36l
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.discriminator import compare, sign_test  # noqa: E402

SETS = {  # run-name prefix: test set
    "{}_allformats": "formats",
    "h2_{}": "holdout2",
    "c_{}": "crazy",
    "r_{}": "random",
    "s_{}": "strips",
    "x_{}": "formats_extra",
}
SAFETY_ONLY = ("formats_extra",)  # checked for gate failures and crashes, not judged for quality


def run_set(name: str, tset: str, workers: int, note: str) -> dict:
    subprocess.run([sys.executable, "-m", "eval.run_eval", "--name", name, "--tasks",
                    str(ROOT / "eval" / "testsets" / tset), "--workers", str(workers), "--note", note],
                   check=True, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.loads((ROOT / "eval" / "runs" / name / "summary.json").read_text())


def verdict(wins: int, losses: int, mean: float, severe: int, n: int) -> bool:
    """A significant improvement on one set."""
    return sign_test(wins, losses) < 0.05 and wins > losses and mean > 0 and severe <= max(2, n // 100)


def blocks(wins: int, losses: int, severe: int, n: int) -> bool:
    """A set that vetoes the step: too many severe losses, or significantly more losses than wins."""
    return severe > max(2, n // 100) or (losses > wins and sign_test(wins, losses) < 0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="this step, e.g. v37a")
    ap.add_argument("--baseline", required=True, help="an earlier step run through this loop (or by hand)")
    ap.add_argument("--note", default="")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()
    record = {"name": a.name, "baseline": a.baseline, "note": a.note, "sets": {}}
    vetoed, improved = False, False
    for pattern, tset in SETS.items():
        s = run_set(pattern.format(a.name), tset, a.workers, a.note)
        vetoed |= s["gate_fail"] > 0 or s["crashes"] > 0
        entry = {"scorer": s["mean"], "gate_fail": s["gate_fail"], "crashes": s["crashes"]}
        if tset not in SAFETY_ONLY:
            wins, losses, ties, mean, severe = compare(pattern.format(a.baseline), pattern.format(a.name),
                                                       str(ROOT / "eval" / "testsets" / tset))
            n = wins + losses + ties
            better, worse = verdict(wins, losses, mean, severe, n), blocks(wins, losses, severe, n)
            vetoed |= worse
            improved |= better
            entry.update(wins=wins, losses=losses, ties=ties, mean=round(mean, 4), severe=severe,
                         verdict="improved" if better else "blocks" if worse else "neutral")
        record["sets"][tset] = entry
    ok = improved and not vetoed
    record.update(accepted=ok, minutes=round((time.time() - t0) / 60, 1))
    with (ROOT / "eval" / "runs" / "loop.jsonl").open("a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"\n{a.name} vs {a.baseline}: {'ACCEPT' if ok else 'reject'}")
    for tset, e in record["sets"].items():
        print(f"  {tset:<9}", e)


if __name__ == "__main__":
    main()
