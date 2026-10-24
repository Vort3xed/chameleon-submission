"""Contact sheets of source -> output pairs for a run, for eyeballing.

    python -m eval.sheets --run v1 --only official,banner --out /tmp/x.png
    python -m eval.sheets --run v1 --worst 24
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.render import render, side_by_side, vstack_images  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "main"))
    ap.add_argument("--only", default="")
    ap.add_argument("--worst", type=int, default=0)
    ap.add_argument("--limit", type=int, default=24)
    ap.add_argument("--height", type=int, default=260)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    run = ROOT / "eval" / "runs" / a.run
    recs = {json.loads(l)["task_id"]: json.loads(l) for l in (run / "results.jsonl").read_text().splitlines() if l}
    ids = sorted(recs)
    if a.only:
        subs = a.only.split(",")
        ids = [i for i in ids if any(s in i for s in subs)]
    if a.worst:
        ids = sorted(ids, key=lambda i: recs[i]["score"])[: a.worst]
    ids = ids[: a.limit]
    items = []
    for tid in ids:
        task = json.loads((Path(a.tasks) / "tasks" / f"{tid}.json").read_text())
        out_p = run / "outputs" / f"{tid}.json"
        if not out_p.exists():
            continue
        src, _ = render(task["source"], max_size=700)
        out, _ = render(json.loads(out_p.read_text()), max_size=900)
        r = recs[tid]
        label = f"{tid} {r['score']:.1f}  " + "; ".join((r.get("issues") or [])[:2])
        items.append(side_by_side(src, out, h=a.height, label=label[:130]))
    vstack_images(items).save(a.out)
    print(a.out, len(items))


if __name__ == "__main__":
    main()
