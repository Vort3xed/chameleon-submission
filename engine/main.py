"""
Orchestrator — you shouldn't need to edit this file. It:
  1. Reads every *.json task file from /app/input (source + target_canvas)
  2. Calls your resize() from resize.py
  3. Runs a quick self-check (structural only — NOT the official scoring;
     see RULES.md for what the judge actually checks)
  4. Writes <task>_output.json for every task, then <task>_output.png (each
     preview drawn in its own process, so a renderer crash costs only that
     picture) to /app/output

Mirrors the same input/ -> output/ convention as the earlier India-program
challenges: drop task files in, get one JSON + one PNG out per task, no
manual steps in between.
"""

import json
import sys
import time
from pathlib import Path

from engine.resize import resize

# Relative to the current working directory, which is /app both inside the
# Docker image (WORKDIR /app) and when run locally from this repo's root -
# so this works identically in both "python -m engine.main" (no Docker) and
# the containerized entrypoint.
INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
ASSETS_DIR = Path("brand_kit/assets")

REQUIRED_COMMON = ["id", "type", "x", "y", "width", "height"]
REQUIRED_BY_TYPE = {
    "text": ["content", "font_family", "font_size", "color"],
    "image": ["asset_id"],
    "shape": ["shape_type", "fill_color"],
}


def self_check(source: dict, output: dict) -> list[str]:
    """Quick, non-authoritative sanity check so obvious mistakes are caught
    locally before you submit. This is NOT the official scorer — see
    RULES.md for what actually gates and grades your submission."""
    problems = []

    if "canvas" not in output or "elements" not in output:
        return ["output is missing top-level 'canvas' or 'elements'"]

    src_ids = {el["id"] for el in source["elements"]}
    out_ids = {el.get("id") for el in output["elements"]}
    if src_ids != out_ids:
        problems.append(
            f"element id mismatch — missing {sorted(src_ids - out_ids)}, "
            f"unexpected {sorted(out_ids - src_ids)}"
        )

    cw, ch = output["canvas"].get("width"), output["canvas"].get("height")
    for el in output["elements"]:
        for field in REQUIRED_COMMON:
            if field not in el:
                problems.append(f"element '{el.get('id')}': missing '{field}'")
                continue
        for field in REQUIRED_BY_TYPE.get(el.get("type"), []):
            if field not in el:
                problems.append(f"element '{el.get('id')}' (type={el.get('type')}): missing '{field}'")
        if cw and ch and all(k in el for k in ("x", "y", "width", "height")):
            x1, y1 = el["x"] + el["width"], el["y"] + el["height"]
            if el["x"] < -0.5 or el["y"] < -0.5 or x1 > cw + 0.5 or y1 > ch + 0.5:
                problems.append(f"element '{el.get('id')}' is off-canvas ({cw}x{ch})")

    return problems


def render_to_png(design: dict, assets_dir: Path, png_path: Path) -> None:
    """Renders `design` to a PNG. Prefers the real renderer
    (transformer-convertor, wrapping cr-renderer) if it's vendored into
    ./renderer; falls back to a plain box-and-label preview otherwise so
    this repo is runnable before that's wired in. Swap the fallback out
    once ./renderer is populated — don't ship the fallback's output as a
    real preview."""
    try:
        from renderer.converter.convert import render_design_to_png  # type: ignore
        render_design_to_png(design, assets_dir, str(png_path))
        return
    except ImportError:
        pass

    _fallback_render(design, png_path)


def _fallback_render(design: dict, png_path: Path) -> None:
    """Placeholder only — labeled boxes, not real text/asset rendering.
    Confirms the pipeline runs end-to-end; do not use this to judge your
    actual layout quality. Use transformer-convertor (RULES.md / FAQ Q3)
    for a real preview."""
    from PIL import Image, ImageDraw

    w, h = design["canvas"]["width"], design["canvas"]["height"]
    img = Image.new("RGB", (w, h), "#EDE7DD")
    draw = ImageDraw.Draw(img)
    palette = {"text": "#2B6CB0", "image": "#B7791F", "shape": "#2F855A"}
    for el in sorted(design["elements"], key=lambda e: e.get("z_index", 0)):
        x0, y0 = el["x"], el["y"]
        x1, y1 = x0 + el["width"], y0 + el["height"]
        color = palette.get(el["type"], "#555555")
        draw.rectangle([x0, y0, x1, y1], outline=color, width=3)
        draw.text((x0 + 4, y0 + 4), el["id"], fill=color)
    img.save(png_path)


def render_isolated(design: dict, assets_dir: Path, png_path: Path) -> bool:
    """render_to_png in a child process: a native crash in the renderer then
    costs only this preview (a plain box preview replaces it), never the run."""
    import multiprocessing

    proc = multiprocessing.Process(target=render_to_png, args=(design, assets_dir, png_path))
    proc.start()
    proc.join(timeout=120)
    if proc.is_alive():
        proc.kill()
    if proc.exitcode == 0 and png_path.exists():
        return True
    try:
        _fallback_render(design, png_path)
    except Exception as e:  # a design even the box preview cannot read: no picture, but the run goes on
        print(f"[{png_path.name}] box preview failed: {e!r}", file=sys.stderr)
    return False


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    task_files = [p for p in sorted(INPUT_DIR.glob("*.json")) if not p.name.startswith(".")]  # not ._x.json
    if not task_files:
        print(f"No task files found in {INPUT_DIR}", file=sys.stderr)
        return 1

    exit_code = 0
    done = []
    for task_path in task_files:  # every output JSON first: drawing previews can never cost one
        try:
            task = json.loads(task_path.read_text(encoding="utf-8-sig"))  # a byte-order mark is harmless
            source, target_canvas = task["source"], task.get("target_canvas")  # resize() copes with a missing one
        except Exception as e:  # one malformed task must not stop the others
            print(f"[{task_path.name}] unreadable task: {e}", file=sys.stderr)
            exit_code = 1
            continue

        t0 = time.time()
        output = resize(source, target_canvas)
        elapsed = time.time() - t0

        stem = task_path.stem
        (OUTPUT_DIR / f"{stem}_output.json").write_text(json.dumps(output, indent=2))
        done.append((stem, output))
        try:
            problems = self_check(source, output)
        except Exception as e:  # a malformed source can trip the check itself; its output is written already
            problems = [f"self-check could not run: {e!r}"]

        status = "OK" if not problems else f"{len(problems)} self-check warning(s)"
        print(f"[{task_path.name}] {status} in {elapsed:.2f}s -> {stem}_output.json")
        for p in problems:
            print(f"    - {p}")

    for stem, output in done:  # then the previews, each in its own process
        ok = render_isolated(output, ASSETS_DIR, OUTPUT_DIR / f"{stem}_output.png")
        print(f"[{stem}] preview -> {stem}_output.png" + ("" if ok else " (renderer failed: box preview)"))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
