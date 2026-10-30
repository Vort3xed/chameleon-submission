"""Readable content must not lose to a layout that simply hides it."""
import copy
import pytest
from tools.adversarial_review import tasks
from engine.resize import resize
from engine.chameleon_layout.scene import analyze
from engine.chameleon_layout.geometry import Rect
from eval.score import gate

CASES = ('crazy_long_words_320x50', 'skeletons_2_300x250',
         'skeletons_3_160x600', 'offers_7_320x50')

@pytest.fixture(scope='module')
def examples():
    return {name:(source,target) for name,source,target in tasks() if name in CASES}

@pytest.mark.parametrize('name',CASES)
@pytest.mark.parametrize('rename_ids',[False,True])
def test_restore_content_without_tiny_text_or_overlap(examples,name,rename_ids):
    source,target=copy.deepcopy(examples[name])
    if rename_ids:
        for n,e in enumerate(source['elements']):
            e['id']=f'element-{n}'
            if e.get('group_id'):e['group_id']='renamed-'+e['group_id']
    before=copy.deepcopy(source)
    output=resize(source,target)
    assert not gate(source,target,output)
    assert source==before
    assert all(e.get('opacity',1)>0 for e in output['elements'])
    assert all(e['font_size']>=7 for e in output['elements'] if e['type']=='text')
    assert output==resize(source,target)
    scene=analyze(output['elements'],target['width'],target['height'])
    texts=[i for i in scene.items if i.type=='text']
    for it in texts:
        layout=it.text_layout()
        assert layout.max_line_width <= it.box.w+1
        assert layout.box_height <= it.box.h+1
        for other in scene.items:
            if other.idx==it.idx or other.alpha==0:continue
            if other.z<it.z and other.type=='shape' and other.box.contains(it.ink,.99):continue
            if other.z<it.z and other.type=='image' and other.box.contains(Rect(0,0,target['width'],target['height']),.99):continue
            # Independent glyph/asset footprints, including within one group.
            assert it.ink.intersection(other.ink) < .5
    for e in output['elements']:
        if e['type']=='text':
            assert Rect(0,0,target['width'],target['height']).contains(Rect(e['x'],e['y'],e['width'],e['height']),.999)
