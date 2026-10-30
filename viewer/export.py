"""Build portable review bundles using the engine and real renderer, never box previews.

python -m viewer.export --tasks input --destination viewer/src/gallery
python -m viewer.export --tasks input --outputs output --destination /tmp/review

Run from the repository root. --outputs uses existing output JSONs instead of resizing.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT_BYTES = 32 * 1024 * 1024


def engine_digest():
    digest = hashlib.sha256()
    for folder, suffixes in (("engine", {".py"}), ("renderer", {".py"}), ("brand_kit", {".png", ".ttf", ".otf"})):
        for p in sorted((ROOT / folder).rglob('*')):
            if p.suffix in suffixes:
                digest.update(p.relative_to(ROOT).as_posix().encode())
                digest.update(p.read_bytes())
    return digest.hexdigest()


def check_design(d):
    from jsonschema import Draft202012Validator
    Draft202012Validator(json.loads((ROOT / 'chameleon_design_schema_v0.9.json').read_text())).validate(d)
    w, h = d['canvas']['width'], d['canvas']['height']
    if max(w, h) > 8192 or w * h > 32_000_000 or len(d['elements']) > 2000:
        raise ValueError('Viewer limit: 8192 per dimension, 32 million canvas pixels, 2000 elements')
    ids = [e['id'] for e in d['elements']]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate element IDs')
    for e in d['elements']:
        # The converter rasterises shape/image boxes before reducing the whole canvas.
        if e['width'] > 8192 or e['height'] > 8192 or e['width'] * e['height'] > 32_000_000:
            raise ValueError('Element too large for the viewer renderer')
    json.dumps(d, allow_nan=False)


def render_worker(design_path, png_path):
    from renderer.converter.convert import render_design_to_png
    design = json.loads(Path(design_path).read_text())
    check_design(design)
    warnings = render_design_to_png(design, ROOT / 'brand_kit/assets', png_path,
                                   max_size=max(design['canvas'].values()))
    Path(str(png_path) + '.warnings').write_text(json.dumps(warnings))


def render(d, directory, name):
    src, dst = directory / f'{name}.json', directory / f'{name}.png'
    src.write_text(json.dumps(d, allow_nan=False))
    result = subprocess.run([sys.executable, '-m', 'viewer.export', '--render-worker', str(src), str(dst)],
                            cwd=ROOT, capture_output=True, text=True, timeout=90)
    if result.returncode or not dst.exists():
        raise RuntimeError(f'Real renderer failed ({result.returncode}): {result.stderr[-1000:]}')
    return 'data:image/png;base64,' + base64.b64encode(dst.read_bytes()).decode(), json.loads(Path(str(dst) + '.warnings').read_text())


def make_bundle(task, name, output=None):
    from engine.resize import resize
    from eval.score import gate
    source, target = task['source'], task['target_canvas']
    check_design(source)
    if not isinstance(target, dict) or any(type(target.get(k)) is not int or not 1 <= target[k] <= 8192 for k in ('width','height')):
        raise ValueError('Target dimensions must be integers from 1 to 8192')
    output = resize(source, target) if output is None else output
    check_design(output)
    problems = gate(source, target, output)
    if problems:
        raise ValueError('Output failed structural checks: ' + '; '.join(problems))
    with tempfile.TemporaryDirectory(prefix='chameleon-viewer-') as temp:
        a, aw = render(source, Path(temp), 'source')
        b, bw = render(output, Path(temp), 'output')
    bundle = {'version': 1, 'name': name[:200], 'source': source, 'output': output,
              'sourcePng': a, 'outputPng': b, 'warnings': list(dict.fromkeys(aw + bw)),
              'engineDigest': engine_digest(),
              'provenance': 'existing-output' if task.get('_existing_output') else 'current-engine'}
    text = json.dumps(bundle, ensure_ascii=False, allow_nan=False)
    if len(text.encode()) > LIMIT_BYTES:
        raise ValueError('Review bundle exceeds 32 MB')
    return text


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tasks', type=Path, default=ROOT / 'input')
    p.add_argument('--outputs', type=Path, help='Read <task>_output.json from this folder')
    p.add_argument('--destination', type=Path, default=ROOT / 'viewer/src/gallery')
    p.add_argument('--render-worker', nargs=2, metavar=('DESIGN', 'PNG'), help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.render_worker:
        render_worker(*a.render_worker)
        return
    paths = sorted(x for x in a.tasks.glob('*.json') if not x.name.startswith('.'))
    if not paths:
        p.error('No task files found')
    # Prepare every bundle before replacing gallery files, so a failed render leaves the gallery intact.
    prepared = []
    for i, path in enumerate(paths):
        task = json.loads(path.read_text(encoding='utf-8-sig'))
        output = None
        if a.outputs:
            output = json.loads((a.outputs / f'{path.stem}_output.json').read_text())
            task['_existing_output'] = True
        name = path.stem.removeprefix('chameleon_sample_').replace('_', ' ').title()
        prepared.append((f'sample-{i}.json', name, make_bundle(task, name, output)))
        print(f'Rendered {path.name}')
    a.destination.mkdir(parents=True, exist_ok=True)
    for file, _, content in prepared:
        (a.destination / file).write_text(content)
    (a.destination / 'index.json').write_text(json.dumps([{'file': f, 'name': n} for f,n,_ in prepared], indent=2))
    print(f'{len(prepared)} review bundles written to {a.destination}')


if __name__ == '__main__':
    main()
