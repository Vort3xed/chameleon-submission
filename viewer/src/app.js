import {MAX_BUNDLE_BYTES, parseBundle, hiddenIds, pngBlob, downloadName} from './model.js';
import {addToExpress} from './express.js';
const $ = id => document.getElementById(id);
let current = null, sdk = null, busy = false, generation = 0;
function status(message, error=false) { $('status').textContent=message; $('status').classList.toggle('error',error); }
function actions() { $('add').disabled = !sdk || !current || busy; $('png').disabled = $('json').disabled = !current || busy; }
async function decode(src) { const im = new Image(); im.src=src; await im.decode(); }
async function show(bundle, ticket) {
  // Decode both images before changing the selection, so a corrupt upload cannot replace a good result.
  await Promise.all([decode(bundle.sourcePng),decode(bundle.outputPng)]);
  if (ticket !== generation) return;
  current=bundle;
  $('name').textContent=bundle.name;
  $('source').src=bundle.sourcePng; $('output').src=bundle.outputPng;
  for(const side of ['source','output']) $(''+side+'-size').textContent=`${bundle[side].canvas.width} × ${bundle[side].canvas.height}`;
  const hidden=hiddenIds(bundle);
  $('summary').textContent=`${bundle.output.elements.length} element records retained · ${hidden.length} newly marked hidden`;
  const notes=[...(bundle.warnings || [])];
  if(hidden.length) notes.push(`Marked hidden by the engine: ${hidden.join(', ')}. These records remain in the JSON but are not intended to be visible.`);
  $('notes').replaceChildren(...notes.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
  $('warnings').hidden=!notes.length;
  $('warning-title').textContent=`Review notes (${notes.length})`;
  $('result').hidden=false; actions(); status('Ready to review.');
}
async function load(url) {
  const ticket=++generation; status('Loading design…');
  try {
    const r=await fetch(url); if(!r.ok) throw new Error(`Could not load sample (${r.status}).`);
    const text=await r.text(); await show(parseBundle(text), ticket);
  } catch(e) { if(ticket===generation) status(e.message,true); }
}
$('sample').addEventListener('change',()=>{if($('sample').value)load($('sample').value);});
$('upload').addEventListener('change',async()=>{
  const file=$('upload').files[0]; if(!file)return;
  const ticket=++generation; status('Opening review bundle…');
  try {
    if(file.size>MAX_BUNDLE_BYTES)throw new Error('Review bundles must be under 32 MB.');
    await show(parseBundle(await file.text()),ticket);
    if(ticket===generation)$('sample').value='';
  }catch(e){if(ticket===generation)status(e.message,true);}finally{$('upload').value='';}
});
$('actual').addEventListener('change',()=>{$('previews').classList.toggle('actual',$('actual').checked);});
function download(blob,ext){if(!current)return; const a=document.createElement('a'); const url=URL.createObjectURL(blob);a.href=url;a.download=downloadName(current.name)+ext;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);}
$('json').addEventListener('click',()=>{if(current)download(new Blob([JSON.stringify(current.output,null,2)],{type:'application/json'}),'.json');});
$('png').addEventListener('click',()=>{if(current)download(pngBlob(current.outputPng),'.png');});
$('add').addEventListener('click',async()=>{
  if(!current || !sdk || busy)return;
  const selected=current;busy=true;actions();status('Adding image to the current Express page…');
  try {await addToExpress(sdk,selected);status('Resized image added to the current page.');}
  catch(e){status(`Express could not add the image: ${e.message || 'Please try again.'}`,true);}
  finally {busy=false;actions();}
});
async function connect(){
  if(window.parent===window){$('host').textContent='Browser preview. Open this add-on in Adobe Express to add images to a document.';return;}
  const timer=setTimeout(()=>{$('host').textContent='Express connection is taking longer than expected. Preview and downloads remain available.';},12000);
  try {const m=await import('https://express.adobe.com/static/add-on-sdk/sdk.js');await m.default.ready;sdk=m.default;$('host').textContent='Connected to Adobe Express.';actions();}
  catch{$('host').textContent='Adobe Express is unavailable. Preview and downloads remain available.';}
  finally{clearTimeout(timer);}
}
async function start(){
  connect();
  try{
    const r=await fetch('gallery/index.json');if(!r.ok)throw new Error('Sample gallery is missing. Run the viewer export command first.');
    const items=await r.json();if(!Array.isArray(items)||!items.length)throw new Error('No bundled samples. Open a review bundle to begin.');
    $('sample').replaceChildren(new Option('Choose a sample',''));
    for(const item of items){if(typeof item.name!=='string'||!/^sample-\d+\.json$/.test(item.file))throw new Error('Invalid sample catalogue.');$('sample').add(new Option(item.name,`gallery/${item.file}`));}
    $('sample').disabled=false;$('sample').selectedIndex=1;await load($('sample').value);
  }catch(e){status(e.message,true);}
}
start();
