"""Docker parity: the submission image (amd64, run as stage one runs it, no
network) must write exactly what native `resize()` returns.  Tasks are a
deterministic sample of every test set plus the official samples.

    docker build --platform linux/amd64 -t chameleon-engine .
    python -m eval.docker_parity --image chameleon-engine --per-set 8
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.resize import resize  # noqa: E402

SETS = ("formats", "holdout2", "crazy", "random", "strips", "tall", "patterns", "skeletons", "wild", "effects",
        "marketing", "offers", "compare", "combos3")


def sample(per_set: int):
    """(name, task) for an evenly spaced sample of each set, and the official samples."""
    out = [(p.name, json.loads(p.read_text())) for p in sorted((ROOT / "input").glob("*.json"))]
    for s in SETS:
        files = sorted((ROOT / "eval" / "testsets" / s / "tasks").glob("*.json"))
        step = max(1, len(files) // per_set)
        out += [(f"{s}__{p.name}", json.loads(p.read_text())) for p in files[::step][:per_set]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="chameleon-engine")
    ap.add_argument("--per-set", type=int, default=8)
    a = ap.parse_args()
    work = ROOT / "eval" / "runs" / "parity"
    shutil.rmtree(work, ignore_errors=True)
    (work / "input").mkdir(parents=True)
    (work / "output").mkdir()
    tasks = sample(a.per_set)
    for name, task in tasks:
        (work / "input" / name).write_text(json.dumps(task))
    subprocess.run(["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
                    "-v", f"{work / 'input'}:/app/input", "-v", f"{work / 'output'}:/app/output", a.image],
                   check=True, stdout=subprocess.DEVNULL)
    bad = []
    for name, task in tasks:
        got = work / "output" / f"{Path(name).stem}_output.json"
        if not got.exists() or json.loads(got.read_text()) != resize(task["source"], task["target_canvas"]):
            bad.append(name)
    print(f"{len(tasks) - len(bad)}/{len(tasks)} identical to native" + (": differ " + ", ".join(bad) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
