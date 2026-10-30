"""Reproducible structural stress review; quality flags are not visual pass/fail scores.
Run: python -m tools.adversarial_review --out docs/adversarial-results.json
"""
import argparse, copy, json, math, random, time
from collections import Counter
from pathlib import Path
from engine.resize import resize
from eval.gen_crazy import CRAZY, SOURCES
from eval.gen_random import KINDS
from eval.score import gate

TARGETS = [(300,250),(336,280),(250,250),(970,90),(320,50),(1080,1920),(1920,1080),(1080,1080),(160,600),(1200,628)]

def tasks():
    rng = random.Random(20261030)
    for i, (name, fn) in enumerate(CRAZY.items()):
        src = fn(random.Random(rng.random()), *SOURCES[i % len(SOURCES)]).to_source()
        for w,h in TARGETS:
            yield f'crazy_{name}_{w}x{h}', src, {'width':w,'height':h}
    for name,(fn,_) in KINDS.items():
        for i in range(10):
            src = fn(random.Random(rng.random())).to_source()
            for w,h in rng.sample(TARGETS,2):
                yield f'{name}_{i}_{w}x{h}',src,{'width':w,'height':h}
    for p in sorted(Path('input').glob('*.json')):
        src=json.loads(p.read_text())['source']
        for w,h in TARGETS:
            yield f'{p.stem}_{w}x{h}',src,{'width':w,'height':h}

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    start=time.monotonic();counts=Counter();failures=[];flags=[]
    for i,(name,src,target) in enumerate(tasks()):
        counts['tasks']+=1;before=copy.deepcopy(src)
        try:
            out=resize(src,target)
            errors=gate(src,target,out)
            json.dumps(out,allow_nan=False)
            if src!=before:errors.append('source mutated')
            if i%10==0:
                counts['determinism_checks']+=1
                if out!=resize(copy.deepcopy(before),target):errors.append('nondeterministic')
            if errors:failures.append({'task':name,'errors':errors})
            hidden=[e['id'] for e in out['elements'] if e.get('opacity',1)==0 and next(s for s in src['elements'] if s['id']==e['id']).get('opacity',1)!=0]
            small=[e['id'] for e in out['elements'] if e['type']=='text' and e.get('opacity',1)>0 and e['font_size']<7]
            rotated=[]
            for e in out['elements']:
                if not e.get('rotation') or e.get('opacity',1)==0:continue
                r=math.radians(e['rotation']);w,h=e['width'],e['height'];rw=abs(w*math.cos(r))+abs(h*math.sin(r));rh=abs(w*math.sin(r))+abs(h*math.cos(r));cx,cy=e['x']+w/2,e['y']+h/2
                if cx-rw/2<-.5 or cy-rh/2<-.5 or cx+rw/2>target['width']+.5 or cy+rh/2>target['height']+.5:rotated.append(e['id'])
            for key,items in [('hidden',hidden),('tiny_text',small),('rotated_bounds',rotated)]:
                if items:counts[key+'_tasks']+=1;flags.append({'task':name,'kind':key,'elements':items})
        except Exception as e:failures.append({'task':name,'errors':[f'{type(e).__name__}: {e}']})
        if (i+1)%100==0:print(f'{i+1} tasks checked',flush=True)
    result={'seed':20261030,'counts':dict(counts),'hard_failure_tasks':len(failures),'elapsed_seconds':round(time.monotonic()-start,2),'failures':failures,'quality_flags':flags,'scope':'Structural checks on fresh generated cases; flags require visual review. This is not Adobe scoring.'}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('failures','quality_flags')},indent=2))

if __name__=='__main__':main()
