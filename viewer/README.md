# Adobe Express viewer

Compare the original and resized design, inspect warnings and hidden element IDs, download the output JSON or PNG, and add the resized PNG to the current Adobe Express page. The three supplied samples are included.

The viewer inserts a **flattened image**, not editable Express layers. It does not execute the Python engine in Express. Other designs are loaded as review bundles containing both designs and their rendered PNGs. No backend service or model key is required.

## Run in Adobe Express

Use Node.js 18+ (tested with Node 24.9.0) and npm. From the repository root:

```bash
cd viewer
npm ci
npm start
```

The Adobe development tool serves the add-on over HTTPS, normally at `https://localhost:5241`. If it reports that no valid SSL certificate exists, run `npx @adobe/ccweb-add-on-ssl setup --hostname localhost`, review the certificate setup prompts yourself, and restart `npm start`. Keep the server running.

1. Sign in to Adobe Express and open a disposable design document.
2. Enable Add-on Development in Express. Review and accept Adobe's developer terms yourself if prompted.
3. Open **Add-ons**, enable **Add-on Development**, and choose **Test your local add-on**. Connect to the HTTPS address printed by the development tool and open **Chameleon Viewer**.
4. Select each sample. Compare the original and resized images, then expand any review notes.
5. Click **Add resized image to Express**. Confirm that the image appears on the current page and matches the preview. The viewer does not resize the Express page.
6. Download JSON and PNG and try opening a custom review bundle.

See Adobe's [local setup guide](https://developer.adobe.com/express/add-ons/docs/guides/getting-started/hello-world) and [local browser limitations](https://developer.adobe.com/express/add-ons/docs/guides/getting-started/local-development/known-issues-limitations). Browser certificate warnings require the user's attention; do not disable certificate verification globally.

## Package for submission

```bash
cd viewer
npm ci
npm test
npm run package
```

This produces `viewer/dist.zip`. Include this archive if the submission form accepts an add-on package; the source, lockfile, manifest and setup instructions also live here. Packaging does not publish or register an add-on, create a private listing, or submit the hackathon entry. Follow the organizers' submission instructions for delivery.

The build checks that bundled previews match the current engine, renderer and brand-kit fingerprint. If it reports stale samples, regenerate them using the command below. No Python environment is needed to view the already bundled samples.

## Export another design

With the repository's Python environment active, install the runtime and development requirements. Each task JSON uses the existing `source` and `target_canvas` structure.

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m viewer.export --tasks input --destination viewer/src/gallery
```

To inspect an existing engine run instead of rerunning the engine:

```bash
python -m viewer.export --tasks input --outputs output --destination /tmp/chameleon-review
```

Open a generated `sample-N.json` using **Open a review bundle**. An engine output JSON alone is not a review bundle. Custom asset IDs must resolve inside `brand_kit/assets/`; the exporter does not fetch remote assets. It uses the real renderer in a separate process and fails if rendering fails. Missing assets retain the renderer's warnings and placeholder behavior; the intentionally missing Level 3 badge is not replaced.

Exports are limited to 32 MB, 2,000 elements, 8,192 pixels per canvas dimension and 32 million canvas pixels. Imported bundles must contain embedded PNGs matching their canvas dimensions. Treat third-party bundles as unverified evidence: validation cannot prove their PNGs were rendered from the accompanying JSON.

## Browser-only preview

```bash
python -m http.server 8771 --bind 127.0.0.1 --directory viewer/src
```

Open `http://127.0.0.1:8771`. Preview, uploads and downloads work; Express insertion is disabled outside the host. This HTTP preview is not the Express sideload server.

## Implementation and verification

`src/app.js` handles selection, decoding, downloads and errors. `src/model.js` validates bundles. `src/express.js` uses Adobe's [`app.document.addImage`](https://developer.adobe.com/express/add-ons/docs/references/addonsdk/app-document) API after SDK readiness. The [manifest](https://developer.adobe.com/express/add-ons/docs/references/manifest/) requests download permission only. Uploaded bundles remain in the panel until the user explicitly adds an image to Express.

Tests cover bundle validation, size limits, PNG identity, hidden-element reporting, and the SDK call/error contract with mocks. The development CLI has reported transitive dependency advisories; its packages are not included in the viewer ZIP or the engine Docker image.
