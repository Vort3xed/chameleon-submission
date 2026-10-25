"""Robustness tests: the engine must never crash, never lose or invent
elements, never leave the canvas and always produce JSON the official
renderer accepts - whatever it is fed.

    .venv/bin/python -m pytest tests -q
"""

import copy
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.resize import resize  # noqa: E402
from eval.score import gate  # noqa: E402

SAMPLES = sorted((ROOT / "input").glob("chameleon_sample_*.json"))
TARGETS = [(1080, 1080), (1080, 1920), (1920, 1080), (728, 90), (160, 600), (320, 50), (300, 250), (2480, 3508),
           (1, 1), (7, 3000)]


def load(p):
    return json.loads(Path(p).read_text())


def assert_valid(source, target, out):
    """Structural invariants that must hold for ANY input."""
    json.dumps(out, allow_nan=False)  # serialisable, no NaN/inf
    assert set(out) == {"canvas", "elements"}
    W, H = out["canvas"]["width"], out["canvas"]["height"]
    assert isinstance(W, int) and isinstance(H, int) and W >= 1 and H >= 1
    src = source.get("elements") if isinstance(source, dict) and isinstance(source.get("elements"), list) else []
    assert len(out["elements"]) == len(src)
    src_ids = sorted(str(e.get("id")) for e in src if isinstance(e, dict))
    out_ids = sorted(str(e.get("id")) for e in out["elements"] if isinstance(e, dict))
    assert src_ids == out_ids
    for e in out["elements"]:
        if not isinstance(e, dict):
            continue
        x, y, w, h = (float(e[k]) for k in ("x", "y", "width", "height"))
        assert all(math.isfinite(v) for v in (x, y, w, h))
        assert x >= -0.5 and y >= -0.5 and x + w <= W + 0.5 and y + h <= H + 0.5, e.get("id")
        if e.get("type") == "text":
            assert w > 0 and h > 0  # the renderer's pydantic model requires > 0
            assert isinstance(e.get("font_size"), int) and e["font_size"] >= 1


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
@pytest.mark.parametrize("target", TARGETS[:8])
def test_samples_pass_gate(sample, target):
    task = load(sample)
    tc = {"width": target[0], "height": target[1]}
    out = resize(copy.deepcopy(task["source"]), tc)
    assert_valid(task["source"], tc, out)
    assert gate(task["source"], tc, out) == []


def test_official_targets_render():
    from eval.render import render

    for sample in SAMPLES:
        task = load(sample)
        out = resize(copy.deepcopy(task["source"]), task["target_canvas"])
        img, _ = render(out)
        assert img.size[0] > 0


def test_input_not_mutated_and_deterministic():
    task = load(SAMPLES[-1])
    src = copy.deepcopy(task["source"])
    a = resize(src, task["target_canvas"])
    assert src == task["source"]
    b = resize(copy.deepcopy(task["source"]), task["target_canvas"])
    assert a == b


def test_deterministic_across_processes():
    """Same input, same output in fresh interpreters with different hash seeds
    (no dependence on set/dict ordering of strings, nor on machine speed)."""
    code = ("import sys, json, glob, hashlib; sys.path.insert(0, %r); from engine.resize import resize; "
            "h = hashlib.sha256(); "
            "[h.update(json.dumps(resize(t['source'], t['target_canvas']), sort_keys=True).encode()) "
            "for t in (json.load(open(p)) for p in sorted(glob.glob(%r)))]; print(h.hexdigest())"
            % (str(ROOT), str(ROOT / "input" / "*.json")))
    digests = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300,
                              env={**os.environ, "PYTHONHASHSEED": seed}).stdout.strip() for seed in ("0", "4242")}
    assert len(digests) == 1 and "" not in digests


# ---------------------------------------------------------------------------
# fuzzing


def _mutate(el: dict, rng: random.Random) -> dict:
    el = copy.deepcopy(el)
    junk = [None, "", "abc", float("nan"), float("inf"), -float("inf"), -50, 0, 1e9, [], {}, True, "12"]
    for _ in range(rng.randint(1, 3)):
        key = rng.choice(["x", "y", "width", "height", "font_size", "rotation", "opacity", "z_index", "color",
                          "fill_color", "content", "font_family", "text_align", "line_height", "letter_spacing",
                          "style_runs", "asset_id", "fit", "shape_type", "group_id", "font_weight", "type", "id"])
        if rng.random() < 0.3:
            el.pop(key, None)
        else:
            el[key] = rng.choice(junk)
    return el


def _fuzz_sources(n=60, seed=0):
    rng = random.Random(seed)
    base = [load(p)["source"] for p in SAMPLES]
    out = []
    for i in range(n):
        src = copy.deepcopy(rng.choice(base))
        els = src["elements"]
        mode = i % 6
        if mode == 0:  # mutate some elements
            src["elements"] = [_mutate(e, rng) if rng.random() < 0.4 else e for e in els]
        elif mode == 1:  # garbage canvas
            src["canvas"] = rng.choice([None, {}, {"width": "x"}, {"width": 0, "height": -5}, {"width": 1e9, "height": 2}])
        elif mode == 2:  # non-dict elements and duplicates
            src["elements"] = els + [None, 7, "text", copy.deepcopy(els[0])]
        elif mode == 3:  # many random elements
            src["elements"] = els + [copy.deepcopy(rng.choice(els)) | {"id": f"clone{k}", "x": rng.uniform(-500, 1500),
                                                                     "y": rng.uniform(-500, 1500)} for k in range(80)]
        elif mode == 4:  # empty / single element
            src["elements"] = rng.choice([[], els[:1]])
        else:  # zero-sized and huge elements
            for e in src["elements"]:
                if rng.random() < 0.3:
                    e["width"], e["height"] = rng.choice([(0, 0), (1e6, 1e6), (5, 0)])
        out.append(src)
    return out


@pytest.mark.parametrize("idx", range(60))
def test_fuzz_never_crashes(idx):
    src = _fuzz_sources()[idx]
    rng = random.Random(idx)
    tw, th = rng.choice(TARGETS)
    tc = {"width": tw, "height": th}
    out = resize(copy.deepcopy(src), tc)
    assert out["canvas"] == {"width": tw, "height": th}
    assert_valid(src, tc, out)


@pytest.mark.parametrize("idx", range(0, 60, 3))
def test_fuzz_main_pipeline_handles_junk(idx):
    """Junk must be absorbed by the real layout engine, not just by the fallback."""
    from engine.chameleon_layout.pipeline import retarget

    src = _fuzz_sources()[idx]
    tw, th = random.Random(idx).choice(TARGETS)
    tc = {"width": tw, "height": th}
    assert_valid(src, tc, retarget(copy.deepcopy(src), tc))


def _adversarial_sources():
    base = load(SAMPLES[1])["source"]

    def text(i, content, x=100, y=100, w=800, size=40):
        return {"id": f"adv_t{i}", "type": "text", "x": x, "y": y, "width": w, "height": size * 1.4, "content": content,
                "font_family": "Solstice Sans", "font_size": size, "color": "rgba(255,255,255,1)", "z_index": 50 + i}

    cases = {}
    d = copy.deepcopy(base)
    d["elements"] = d["elements"][:1] + [
        {"id": f"dot{i}", "type": "shape", "x": (i * 37) % 1000, "y": (i * 53) % 1000, "width": 20, "height": 20,
         "shape_type": "ellipse", "fill_color": "rgba(255,255,255,0.3)", "z_index": 2} for i in range(150)] + [
        text(i, f"Item {i}", 50 + (i % 5) * 200, 100 + (i // 5) * 80, 180, 20) for i in range(50)]
    cases["200 elements"] = d
    d = copy.deepcopy(base)
    d["elements"].append(text(99, "Lorem ipsum dolor sit amet " * 200, 60, 60, 960, 18))
    cases["5000-char text"] = d
    d = copy.deepcopy(base)
    d["elements"].append(text(98, "\u0645\u0631\u062d\u0628\u0627 \u05e9\u05dc\u05d5\u05dd e\u0301\u0301 \u200b\u200b"))
    cases["rtl and combining marks"] = d
    d = copy.deepcopy(base)
    for e in d["elements"]:
        e["opacity"] = 0
    cases["everything at opacity 0"] = d
    d = copy.deepcopy(base)
    d["elements"] = d["elements"][:1] + [e for e in d["elements"] if e.get("group_id") == "badge"]
    cases["only a corner badge"] = d
    return cases


@pytest.mark.parametrize("name", sorted(_adversarial_sources()))
@pytest.mark.parametrize("target", [(1080, 1920), (728, 90), (1, 1)])
def test_adversarial_inputs_main_pipeline(name, target):
    """Odd but legal inputs must be handled by the real engine, not by the fallback."""
    from engine.chameleon_layout.pipeline import retarget

    src = _adversarial_sources()[name]
    tc = {"width": target[0], "height": target[1]}
    assert_valid(src, tc, retarget(copy.deepcopy(src), tc))


@pytest.mark.parametrize("idx", range(0, 60, 3))
def test_fallback_always_valid(idx):
    from engine.chameleon_layout.fallback import letterbox

    src = _fuzz_sources()[idx]
    tw, th = random.Random(idx).choice(TARGETS)
    tc = {"width": tw, "height": th}
    assert_valid(src, tc, letterbox(copy.deepcopy(src), tc))


@pytest.mark.parametrize("target", [None, {}, {"width": "100", "height": "50"}, {"width": 0, "height": 0},
                                    {"width": float("nan"), "height": 10}, {"width": 333.7, "height": 91.2}])
def test_garbage_target_canvas(target):
    src = load(SAMPLES[1])["source"]
    out = resize(copy.deepcopy(src), target)
    assert_valid(src, target, out)


def test_garbage_source_objects():
    for src in (None, {}, {"elements": None}, {"elements": "nope"}, {"canvas": {"width": 10, "height": 10}}):
        out = resize(src, {"width": 300, "height": 250})
        assert out["canvas"] == {"width": 300, "height": 250}
        assert isinstance(out["elements"], list)


def test_fuzzed_valid_outputs_render():
    """Fuzzed inputs whose source renders must also render after resizing."""
    from eval.render import render

    def renderable(src):  # never rasterise absurd sizes (the renderer allocates per element)
        try:
            c = src["canvas"]
            sizes = [float(c["width"]), float(c["height"])]
            sizes += [float(e.get(k, 0)) for e in src["elements"] if isinstance(e, dict) for k in ("width", "height")]
            return all(math.isfinite(v) and 0 <= v <= 4000 for v in sizes)
        except Exception:
            return False

    rendered = 0
    for src in filter(renderable, _fuzz_sources(30, seed=3)):
        try:
            render(src)
        except Exception:
            continue  # the source itself is unrenderable; nothing to compare
        out = resize(copy.deepcopy(src), {"width": 728, "height": 90})
        render(out)
        rendered += 1
    assert rendered > 5


# ---------------------------------------------------------------------------
# environment robustness


def test_without_assets_or_fonts(monkeypatch):
    from engine.chameleon_layout import assets, text_metrics

    for f in (assets.assets_dir, assets.content_bounds, assets.pixel_size, assets.is_opaque, text_metrics._font_table):
        f.cache_clear()
    monkeypatch.setattr(assets, "assets_dir", lambda: None)
    monkeypatch.setattr(text_metrics, "_font_table", lambda: {})
    try:
        for sample in SAMPLES:
            task = load(sample)
            out = resize(copy.deepcopy(task["source"]), task["target_canvas"])
            assert_valid(task["source"], task["target_canvas"], out)
    finally:
        for f in (assets.content_bounds, assets.pixel_size, assets.is_opaque):
            f.cache_clear()


def test_import_from_other_cwd(tmp_path):
    code = ("import sys, json; sys.path.insert(0, %r); from engine.resize import resize; "
            "t = json.load(open(%r)); print(len(resize(t['source'], t['target_canvas'])['elements']))"
            % (str(ROOT), str(SAMPLES[0])))
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "4"


def test_import_as_top_level_module(tmp_path):
    code = ("import sys, json; sys.path.insert(0, %r); import resize as R; "
            "t = json.load(open(%r)); print(len(R.resize(t['source'], t['target_canvas'])['elements']))"
            % (str(ROOT / "engine"), str(SAMPLES[2])))
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "17"


def test_main_end_to_end(tmp_path):
    """`python -m engine.main` from a copy of the repo layout writes JSON + PNG per task."""
    import shutil

    for d in ("engine", "renderer", "brand_kit"):
        shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "input").mkdir()
    for s in SAMPLES:
        shutil.copy(s, tmp_path / "input" / s.name)
    r = subprocess.run([sys.executable, "-m", "engine.main"], cwd=tmp_path, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    for s in SAMPLES:
        assert (tmp_path / "output" / f"{s.stem}_output.json").exists()
        assert (tmp_path / "output" / f"{s.stem}_output.png").stat().st_size > 1000


# ---------------------------------------------------------------------------
# stress designs (eval/gen_crazy.py): walls of text, 3x3 grids, vertical and
# rotated type, non-Latin scripts, unbreakable words, nested cards, ...


def _crazy(arch):
    from eval.gen_crazy import CRAZY, SOURCES

    W, H = SOURCES[list(CRAZY).index(arch) % len(SOURCES)]
    return CRAZY[arch](random.Random(arch), W, H).to_source()


def _crazy_names():
    from eval.gen_crazy import CRAZY

    return list(CRAZY)


@pytest.mark.parametrize("arch", _crazy_names())
@pytest.mark.parametrize("target", [(1080, 1080), (728, 90), (160, 600), (64, 64), (200, 2000)])
def test_crazy_designs_pass_gate(arch, target):
    src = _crazy(arch)
    tc = {"width": target[0], "height": target[1]}
    out = resize(copy.deepcopy(src), tc)
    assert_valid(src, tc, out)
    assert gate(src, tc, out) == []
    shown = {e["id"] for e in out["elements"] if (1 if e.get("opacity") is None else e["opacity"]) > 0.01}
    assert set(_headlines(src)) <= shown, "the headline is never hidden"


def _headlines(src):
    from engine.chameleon_layout.scene import analyze

    def walk(blocks):
        for b in blocks:
            if b.role == "headline":
                yield from (i.el["id"] for i in b.items)
            yield from walk(b.children)

    return list(walk(analyze(src["elements"], src["canvas"]["width"], src["canvas"]["height"]).blocks))


@pytest.mark.parametrize("arch", _crazy_names())
def test_crazy_designs_render(arch):
    from eval.render import render

    render(resize(_crazy(arch), {"width": 1200, "height": 628}), max_size=600)
