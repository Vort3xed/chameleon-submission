import {readFileSync, readdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {resolve, relative, extname} from 'node:path';
import {validateBundle} from '../src/model.js';
const root=resolve('..');
const hash=createHash('sha256');
for(const [dir,exts] of [['engine',['.py']],['renderer',['.py']],['brand_kit',['.png','.ttf','.otf']]]){
  const folder=resolve(root,dir);
  for(const rel of readdirSync(folder,{recursive:true}).filter(x=>exts.includes(extname(x))).sort()){
    const path=resolve(folder,rel);hash.update(relative(root,path).replaceAll('\\','/'));hash.update(readFileSync(path));
  }
}
const digest=hash.digest('hex');
const manifest=JSON.parse(readFileSync('src/manifest.json','utf8'));
if(manifest.manifestVersion!==2 || manifest.entryPoints[0].main!=='index.html')throw Error('Invalid viewer manifest');
const catalogue=JSON.parse(readFileSync('src/gallery/index.json','utf8'));
if(!catalogue.length)throw Error('No samples bundled');
for(const item of catalogue){
  if(!/^sample-\d+\.json$/.test(item.file))throw Error('Invalid gallery path');
  const b=validateBundle(JSON.parse(readFileSync('src/gallery/'+item.file,'utf8')));
  if(b.engineDigest!==digest || b.provenance!=='current-engine')throw Error('Samples are stale: run python -m viewer.export before building');
}
console.log(`Validated manifest, ${catalogue.length} bundles, and engine/renderer/asset fingerprint.`);
