"""Release checks for concrete failures found in the submission review."""
import builtins
import copy
import json
from pathlib import Path
import pytest
from engine.main import self_check, render_to_png
from engine.chameleon_layout import assets
from renderer.converter.assets import asset_path
from viewer.export import check_design

ROOT = Path(__file__).resolve().parents[1]


def source():
    return json.loads((ROOT / 'input/chameleon_sample_level1_warmup.json').read_text())['source']


def test_self_check_detects_duplicate_record():
    src = source()
    out = copy.deepcopy(src)
    out['elements'].append(copy.deepcopy(out['elements'][0]))
    assert any('id mismatch' in e for e in self_check(src, out))


def test_renderer_import_failure_cannot_report_success(monkeypatch, tmp_path):
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == 'renderer.converter.convert':
            raise ImportError('simulated missing renderer')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', unavailable)
    dest = tmp_path / 'preview.png'
    with pytest.raises(ImportError):
        render_to_png(source(), ROOT / 'brand_kit/assets', dest)
    assert not dest.exists()


@pytest.mark.parametrize('name', ['../outside.png', '/tmp/outside.png', 'link.png', None])
def test_asset_paths_cannot_escape_brand_kit(tmp_path, monkeypatch, name):
    root = tmp_path / 'assets'
    root.mkdir()
    outside = tmp_path / 'outside.png'
    outside.write_bytes(b'not an image')
    (root / 'link.png').symlink_to(outside)
    monkeypatch.setattr(assets, 'assets_dir', lambda: root)
    assert asset_path(root, name) is None
    assert assets.asset_path(name) is None


def test_asset_paths_accept_bundled_file():
    name = 'solstice_bottle.png'
    assert asset_path(ROOT / 'brand_kit/assets', name).is_file()
    assert assets.asset_path(name).is_file()


def test_viewer_rejects_resource_exhaustion_and_duplicate_ids():
    d = source()
    d['elements'][0]['width'] = 1_000_000
    with pytest.raises(ValueError):
        check_design(d)
    d = source()
    d['elements'].append(d['elements'][0])
    with pytest.raises(ValueError):
        check_design(d)
