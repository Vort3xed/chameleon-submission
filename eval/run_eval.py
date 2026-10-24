"""Run an engine over a test set, score every output, and summarise.

    python -m eval.run_eval --name v1                 # full main set
    python -m eval.run_eval --name v1 --quick         # stratified ~1/3 subset
    python -m eval.run_eval --engine-root path/to/snapshot --name old

`--engine-root` must contain an `engine/` package exposing `engine.resize.resize`,
so archived snapshots can be compared against the working tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval" / "runs"

_resize = None
_src_cache = {}


def _init(engine_root: str):
    global _resize
    import resource

    # a runaway render must fail in this worker, not exhaust the machine
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024 ** 3, resource.getrlimit(resource.RLIMIT_AS)[1]))
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    sys.path.insert(0, str(ROOT))
    if engine_root and Path(engine_root).resolve() != ROOT:
        sys.path.insert(0, str(Path(engine_root).resolve()))
    import logging

    logging.disable(logging.WARNING)
    from engine.resize import resize  # noqa

    _resize = resize


def _one(args):
    task_path, out_dir, do_render = args
    from eval import score as S

    task = json.loads(Path(task_path).read_text())
    tid = task.get("task_id", Path(task_path).stem)
    rec = {"task_id": tid}
    t0 = time.time()
    try:
        import copy

        output = _resize(copy.deepcopy(task["source"]), copy.deepcopy(task["target_canvas"]))
        rec["crash"] = None
    except Exception as e:
        output = None
        rec["crash"] = f"{type(e).__name__}: {e}"
        rec["trace"] = traceback.format_exc()[-1500:]
    rec["time"] = round(time.time() - t0, 4)
    try:
        json_ok = json.loads(json.dumps(output, allow_nan=False)) if output is not None else None
    except Exception as e:
        json_ok = None
        rec["crash"] = rec["crash"] or f"not JSON-serialisable: {e}"
    if json_ok is None:
        rec.update(score=0.0, gate=[rec["crash"] or "no output"], metrics={}, issues=[rec["crash"]])
        return rec
    Path(out_dir, f"{tid}.json").write_text(json.dumps(output, indent=1, ensure_ascii=False))
    key = hashlib.md5(json.dumps(task["source"], sort_keys=True).encode()).hexdigest()
    try:
        if key not in _src_cache:
            _src_cache.clear() if len(_src_cache) > 64 else None
            _src_cache[key] = S.prepare(task["source"], do_render)
        res = S.score_task(task["source"], task["target_canvas"], json_ok, _src_cache[key], do_render)
    except Exception as e:
        res = {"score": 0.0, "gate": [f"scorer error: {e!r}"], "metrics": {}, "issues": [traceback.format_exc()[-800:]]}
    rec.update(res)
    return rec


def quick_subset(manifest, frac=3):
    """Every `frac`-th design per archetype, all three targets, + officials."""
    keep = []
    for m in manifest:
        arch = m["archetype"]
        digits = [int(t) for t in m["task_id"].replace("__", "_").split("_") if t.isdigit()]
        idx = digits[0] if digits and arch != "official" else 0
        if arch == "official" or idx % frac == 0:
            keep.append(m["task_id"])
    return set(keep)


def summarise(recs, manifest_by_id):
    def mean(xs):
        xs = list(xs)
        return round(float(sum(xs)) / len(xs), 3) if xs else None

    out = {"n": len(recs), "mean": mean(r["score"] for r in recs)}
    out["gate_fail"] = sum(1 for r in recs if r.get("gate"))
    out["crashes"] = sum(1 for r in recs if r.get("crash"))
    out["time_mean"] = mean(r.get("time", 0) for r in recs)
    out["time_max"] = max((r.get("time", 0) for r in recs), default=0)
    for key in ("difficulty", "archetype", "ratio_level"):
        groups = defaultdict(list)
        for r in recs:
            m = manifest_by_id.get(r["task_id"], {})
            groups[str(m.get(key, "?"))].append(r["score"])
        out[f"by_{key}"] = {k: mean(v) for k, v in sorted(groups.items())}
    mets = defaultdict(list)
    for r in recs:
        for k, v in (r.get("metrics") or {}).items():
            mets[k].append(v)
    out["metrics"] = {k: mean(v) for k, v in sorted(mets.items())}
    worst = sorted(recs, key=lambda r: r["score"])[:15]
    out["worst"] = [(r["task_id"], r["score"], (r.get("issues") or [])[:3]) for r in worst]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "main"))
    ap.add_argument("--engine-root", default=str(ROOT))
    ap.add_argument("--workers", type=int, default=max(1, min(16, (os.cpu_count() or 4) - 2)))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-render", action="store_true", help="skip render-based metrics (contrast)")
    ap.add_argument("--only", default="", help="comma-separated substrings of task ids")
    ap.add_argument("--note", default="")
    ap.add_argument("--vlm", action="store_true", help="also AI-judge the quick subset with the local VLM")
    a = ap.parse_args()

    tset = Path(a.tasks)
    manifest = json.loads((tset / "manifest.json").read_text())
    by_id = {m["task_id"]: m for m in manifest}
    files = sorted((tset / "tasks").glob("*.json"))
    if a.quick:
        keep = quick_subset(manifest)
        files = [f for f in files if f.stem in keep]
    if a.only:
        subs = [s for s in a.only.split(",") if s]
        files = [f for f in files if any(s in f.stem for s in subs)]
    run_dir = RUNS / a.name
    out_dir = run_dir / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    jobs = [(str(f), str(out_dir), not a.no_render) for f in files]
    ctx = mp.get_context("fork")
    with ctx.Pool(a.workers, initializer=_init, initargs=(a.engine_root,)) as pool:
        recs = list(pool.imap_unordered(_one, jobs, chunksize=2))
    recs.sort(key=lambda r: r["task_id"])
    summ = summarise(recs, by_id)
    summ["wall"] = round(time.time() - t0, 1)
    summ["name"] = a.name
    summ["note"] = a.note
    summ["quick"] = a.quick
    (run_dir / "results.jsonl").write_text("\n".join(json.dumps(r) for r in recs))
    if a.vlm:
        from eval.vlm_judge import judge_run

        sub = quick_subset(manifest)
        summ["vlm"] = judge_run(a.name, sorted(r["task_id"] for r in recs if r["task_id"] in sub), tset / "tasks",
                                "http://127.0.0.1:8000/v1", "qwen3.8-27b-abliterated")
    (run_dir / "summary.json").write_text(json.dumps(summ, indent=1))
    with open(RUNS / "history.jsonl", "a") as f:
        f.write(json.dumps({"name": a.name, "time": time.strftime("%Y-%m-%d %H:%M"), "n": summ["n"], "mean": summ["mean"],
                            "quick": a.quick, "by_difficulty": summ["by_difficulty"], "vlm": summ.get("vlm"),
                            "note": a.note}) + "\n")

    print(f"\n== {a.name}: mean {summ['mean']} over {summ['n']} tasks  (gate fails {summ['gate_fail']}, crashes "
          f"{summ['crashes']}, {summ['wall']}s wall, engine {summ['time_mean']}s avg / {summ['time_max']}s max)")
    print("by difficulty:", summ["by_difficulty"])
    print("by ratio    :", summ["by_ratio_level"])
    print("by archetype:", summ["by_archetype"])
    print("metrics     :", summ["metrics"])
    if "vlm" in summ:
        print("VLM (quick subset):", summ["vlm"])
    print("worst:")
    for tid, sc, iss in summ["worst"][:10]:
        print(f"  {sc:6.1f} {tid}: {iss}")


if __name__ == "__main__":
    main()
