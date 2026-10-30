import {pngBlob} from './model.js';

// The UI SDK inserts a flattened PNG into the current Express page.
export async function addToExpress(sdk, bundle) {
  await sdk.app.document.addImage(pngBlob(bundle.outputPng), {title: `${bundle.name} — resized`});
}
