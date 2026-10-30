import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseBundle,validateBundle,hiddenIds,pngBlob,downloadName,MAX_BUNDLE_BYTES} from '../src/model.js';
const fixture=()=>JSON.parse(readFileSync(new URL('../src/gallery/sample-0.json',import.meta.url),'utf8'));
test('real export round trips, PNG bytes have correct type',()=>{const b=fixture();assert.deepEqual(parseBundle(JSON.stringify(b)),b);assert.equal(pngBlob(b.outputPng).type,'image/png');assert.ok(pngBlob(b.outputPng).size>1000);});
for(const [name,edit] of [
  ['duplicate IDs', b=>b.output.elements.push(b.output.elements[0])],
  ['missing IDs', b=>b.output.elements.pop()],
  ['rewritten content', b=>b.output.elements.find(e=>e.type==='text').content='changed'],
  ['NaN geometry', b=>b.output.elements[0].width=NaN],
  ['infinite canvas', b=>b.output.canvas.width=Infinity],
  ['mismatched PNG canvas', b=>b.output.canvas.width+=1],
  ['negative canvas', b=>b.source.canvas.height=-1],
  ['external image URL', b=>b.outputPng='https://example.org/track.png'],
  ['script image URL', b=>b.outputPng='javascript:alert(1)'],
  ['SVG in place of PNG', b=>b.outputPng='data:image/svg+xml;base64,PHN2Zz4='],
  ['invalid PNG bytes', b=>b.outputPng='data:image/png;base64,AAAA'],
  ['unsupported version', b=>b.version=2],
  ['invalid notes', b=>b.warnings=[{}]],
  ['giant PNG header', b=>{const bytes=Buffer.from(b.outputPng.split(',')[1],'base64');bytes.writeUInt32BE(100000,16);b.outputPng='data:image/png;base64,'+bytes.toString('base64');}],
])test(`rejects ${name}`,()=>{const b=fixture();edit(b);assert.throws(()=>validateBundle(b));});
test('rejects malformed or oversized JSON',()=>{assert.throws(()=>parseBundle('{'));assert.throws(()=>parseBundle(' '.repeat(MAX_BUNDLE_BYTES+1)));});
test('hidden report excludes elements already hidden in the source',()=>{const b=fixture();b.source.elements[0].opacity=0;b.output.elements[0].opacity=0;b.output.elements[1].opacity=0;assert.deepEqual(hiddenIds(b),[b.output.elements[1].id]);});
test('download filenames cannot contain paths',()=>{assert.equal(downloadName('../../x<script>'),'______x_script__output');});
test('the gallery includes all three real samples',()=>{const index=JSON.parse(readFileSync(new URL('../src/gallery/index.json',import.meta.url)));assert.equal(index.length,3);for(const i of index)validateBundle(JSON.parse(readFileSync(new URL('../src/gallery/'+i.file,import.meta.url))));});

// These mocks verify the API contract and error propagation, not Adobe hosting.
import {addToExpress} from '../src/express.js';
test('Express receives the exact output PNG and title',async()=>{const b=fixture();let call;await addToExpress({app:{document:{addImage:async(...args)=>{call=args;}}}},b);assert.deepEqual(Buffer.from(await call[0].arrayBuffer()),Buffer.from(b.outputPng.split(',')[1],'base64'));assert.deepEqual(call[1],{title:`${b.name} — resized`});});
test('Express import errors propagate to the UI',async()=>{await assert.rejects(addToExpress({app:{document:{addImage:async()=>{throw new Error('Host refused');}}}},fixture()),/Host refused/);});
