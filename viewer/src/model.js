// Review bundles contain data and PNG bytes only; never fetch paths from an imported file.
export const MAX_BUNDLE_BYTES = 32 * 1024 * 1024;
const MAX_ELEMENTS = 2000;
const number = v => typeof v === 'number' && Number.isFinite(v);
export function validateDesign(d) {
  if (!d || !d.canvas || !Array.isArray(d.elements) || !d.elements.length || d.elements.length > MAX_ELEMENTS)
    throw new Error('The design must contain a canvas and 1–2000 elements.');
  for (const k of ['width', 'height']) {
    if (!Number.isInteger(d.canvas[k]) || d.canvas[k] < 1 || d.canvas[k] > 8192)
      throw new Error('Canvas dimensions must be whole numbers from 1 to 8192.');
  }
  const ids = new Set();
  for (const e of d.elements) {
    if (!e || typeof e.id !== 'string' || !e.id || ids.has(e.id) || !['text','image','shape'].includes(e.type))
      throw new Error('Elements must have unique IDs and supported types.');
    ids.add(e.id);
    if (!['x','y','width','height'].every(k => number(e[k])) || e.width < 0 || e.height < 0)
      throw new Error('Element geometry must contain finite numbers and nonnegative sizes.');
    if (e.type === 'text' && (typeof e.content !== 'string' || !number(e.font_size) || e.font_size < 1))
      throw new Error('Text elements need content and a positive font size.');
  }
  return d;
}
function png(value, canvas) {
  if (typeof value !== 'string' || value.length > MAX_BUNDLE_BYTES || !/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(value))
    throw new Error('Previews must be embedded PNG images.');
  const data = value.slice(value.indexOf(',') + 1);
  if (data.length % 4) throw new Error('Invalid PNG encoding.');
  const head = atob(data.slice(0, 44));
  const bytes = Uint8Array.from(head, c => c.charCodeAt(0));
  if (bytes.length < 24 || ![137,80,78,71,13,10,26,10].every((n,i) => bytes[i] === n) || head.slice(12,16) !== 'IHDR')
    throw new Error('Invalid PNG header.');
  const view = new DataView(bytes.buffer);
  const w = view.getUint32(16), h = view.getUint32(20);
  if (w < 1 || h < 1 || w > 8192 || h > 8192 || w * h > 32_000_000)
    throw new Error('Preview image dimensions exceed the viewer limit.');
  if (canvas && (w !== canvas.width || h !== canvas.height))
    throw new Error('Preview dimensions do not match the design canvas.');
  return value;
}
export function validateBundle(b) {
  if (!b || b.version !== 1 || typeof b.name !== 'string' || b.name.length > 200)
    throw new Error('Choose a version 1 Chameleon review bundle exported by viewer.export.');
  validateDesign(b.source); validateDesign(b.output);
  const source = new Map(b.source.elements.map(e => [e.id,e]));
  if (source.size !== b.output.elements.length || b.output.elements.some(e => !source.has(e.id)))
    throw new Error('Source and output must contain the same element IDs.');
  for (const e of b.output.elements) {
    const s = source.get(e.id);
    if (['type','content','font_family','asset_id'].some(k => s[k] !== e[k]))
      throw new Error('Source and output element identities or content differ.');
  }
  png(b.sourcePng, b.source.canvas); png(b.outputPng, b.output.canvas);
  if (b.warnings !== undefined && (!Array.isArray(b.warnings) || b.warnings.length > 100 || b.warnings.some(w => typeof w !== 'string' || w.length > 2000)))
    throw new Error('Invalid warning list.');
  return b;
}
export function parseBundle(text) {
  if (new TextEncoder().encode(text).length > MAX_BUNDLE_BYTES) throw new Error('Review bundles must be under 32 MB.');
  let b;
  try { b = JSON.parse(text); } catch { throw new Error('This file is not valid JSON.'); }
  return validateBundle(b);
}
export function hiddenIds(b) {
  const source = new Map(b.source.elements.map(e => [e.id,e]));
  return b.output.elements.filter(e => e.opacity === 0 && source.get(e.id)?.opacity !== 0).map(e => e.id);
}
export function pngBlob(url) {
  png(url);
  const raw = atob(url.slice(url.indexOf(',') + 1));
  return new Blob([Uint8Array.from(raw, c => c.charCodeAt(0))], {type:'image/png'});
}
export function downloadName(name) {
  return (name.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 100) || 'chameleon') + '_output';
}
