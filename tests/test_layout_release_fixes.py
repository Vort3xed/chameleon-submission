"""Regressions for the three layout defects found during submission review."""
import copy
import json
import random
from pathlib import Path

import pytest
from engine.resize import resize
from engine.chameleon_layout.blocks import Placement
from engine.chameleon_layout.finalize import finalize
from engine.chameleon_layout.geometry import Rect
from engine.chameleon_layout.scene import analyze
from eval.gen_testset import a_product_grid
from eval.score import gate

ROOT = Path(__file__).resolve().parents[1]


def ink(e):
    scene = analyze([e], 1080, 1080)
    return scene.items[0].ink


@pytest.mark.parametrize('seed', [0, 3, 7])
@pytest.mark.parametrize('size', [(300,250),(336,280),(250,250),(970,90)])
def test_product_grid_keeps_products_and_readable_attached_captions(seed, size):
    source = a_product_grid(random.Random(seed), 1080, 1350, 3).to_source()
    before = copy.deepcopy(source)
    target = dict(zip(('width','height'),size))
    output = resize(source,target)
    assert not gate(source,target,output)
    assert source == before
    elements = {e['id']:e for e in output['elements']}
    products = [e for e in source['elements'] if e['id'].startswith('product')]
    for product in products:
        image = elements[product['id']]
        assert image.get('opacity',1) > 0 and min(image['width'],image['height']) >= 2
        suffix = product['id'].removeprefix('product')
        name, price = elements['name'+suffix], elements['price'+suffix]
        for label in (name,price):
            assert label.get('opacity',1) > 0 and label['font_size'] >= 7
        assert name['y'] >= image['y'] + image['height'] - .1
        assert price['y'] >= name['y'] + name['height'] - .1
        assert abs((name['x']+name['width']/2)-(image['x']+image['width']/2)) <= 1


@pytest.mark.parametrize('angle',[45,90,-35,180,270])
@pytest.mark.parametrize('size',[(90,50),(300,90)])
def test_finalizer_fits_rotated_text_and_scales_font(angle,size):
    source={'elements':[{'id':'text','type':'text','content':'A heading','font_family':'Solstice Sans',
                         'color':'#ffffff','font_size':24,'x':0,'y':0,'width':240,'height':35,'rotation':angle}]}
    out=finalize(source,*size,{0:Placement(0,0,240,35,24)})['elements'][0]
    r=Rect(out['x'],out['y'],out['width'],out['height']).rotated_bounds(angle)
    assert r.x >= -.02 and r.y >= -.02 and r.x1 <= size[0]+.02 and r.y1 <= size[1]+.02
    assert 1 <= out['font_size'] <= 24 and out['content']=='A heading'
    item=analyze([out],*size).items[0]
    assert item.text_layout().box_height <= out['height'] + 1
    assert item.text_layout().max_line_width <= out['width'] + 1


def test_rotation_gate_rejects_unrotated_box_false_positive():
    source=json.loads((ROOT/'docs/evidence/rotated-headline-task.json').read_text())['source']
    target={'width':970,'height':90}
    out=resize(source,target)
    assert not gate(source,target,out)
    head=next(e for e in out['elements'] if e['id']=='headline')
    head.update(x=100,y=20,width=200,height=20,rotation=90)
    assert any('rotated footprint' in e for e in gate(source,target,out))


def test_short_banner_cta_is_measured_and_stays_inside_button():
    task=json.loads((ROOT/'input/chameleon_sample_level3_advanced.json').read_text())
    source=task['source'];target={'width':320,'height':50}
    out=resize(source,target)
    assert not gate(source,target,out)
    els={e['id']:e for e in out['elements']}
    label=els['cta_label'];button=els['cta_bg']
    assert label['font_size'] >= 9 and label.get('opacity',1)>0
    box=Rect(button['x'],button['y'],button['width'],button['height'])
    assert box.contains(ink(label),.99)
    for e in out['elements']:
        if e['type']=='text' and e['id'] != 'cta_label' and e.get('opacity',1)>0:
            assert ink(label).intersection(ink(e)) < .1
    assert out == resize(source,target)


def test_dense_grid_cannot_buy_readability_by_hiding_all_products():
    from eval.gen_crazy import c_big_grid
    source=c_big_grid(random.Random(12),1920,1080).to_source()
    target={'width':320,'height':50}
    out=resize(source,target)
    assert not gate(source,target,out)
    products=[e for e in out['elements'] if e['id'].startswith('product')]
    assert len(products)>=9
    assert all(e.get('opacity',1)>0 and min(e['width'],e['height'])>=2 for e in products)
