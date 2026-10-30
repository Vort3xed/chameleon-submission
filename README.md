# Project Chameleon

The engine takes a design and a target canvas size, then rearranges its text, images, and shapes to fit the new format.

It runs locally without model downloads or API calls at runtime.

## Approach

The engine uses layout rules and candidate search:

1. **Identify structure.** Infer headlines, logos, product images, buttons, cards, and related groups from the source’s geometry, typography, and content.
2. **Generate arrangements.** Try preserving the original composition, stacking content, splitting imagery and copy, or arranging elements across a banner.
3. **Measure and score.** Measure text using the bundled fonts and renderer-compatible wrapping. Rank candidates on readability, overlap, hierarchy, spacing, content retention, and similarity to the source.
4. **Finish the layout.** Adjust alignment, decoration, and corner elements, then write the output JSON and render a preview.

Images reuse the supplied assets. Text content and font families are preserved. On constrained canvases, the engine may hide lower-priority content while retaining its element records in the JSON.

## Run with Docker

Build the image:

```bash
docker build --platform linux/amd64 -t chameleon-engine .
```

Process the tasks in `input/`:

```bash
docker run --rm --network none \
  -v "$(pwd)/input:/app/input" \
  -v "$(pwd)/output:/app/output" \
  chameleon-engine
```

Dependencies are installed during the build. The container runs without network access.

## Run locally

Use Python 3.11:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m engine.main
```

Each input file contains a `source` design and a `target_canvas`. The three supplied examples are in `input/`.

For each task, the engine writes:

- `<task>_output.json` — the resized design.
- `<task>_output.png` — a rendered preview.

If preview rendering fails, the engine retains the JSON and attempts a simplified box preview. Check the console output for rendering warnings.

## Adobe Express viewer

The add-on in `viewer/` includes the three samples, original/resized comparisons, JSON and PNG downloads, and an action to insert the resized image into Express. It inserts a flattened PNG; it does not reconstruct editable layers or run the engine inside Express.

```bash
cd viewer
npm ci
npm start
```

See [viewer setup and packaging](viewer/README.md) for Express installation, custom review bundles, and building `viewer/dist.zip`.

## Repository structure

| Path | Purpose |
|---|---|
| `engine/resize.py` | Main `resize(source, target_canvas)` interface |
| `engine/chameleon_layout/` | Structure inference, layout search, scoring, and finishing |
| `engine/main.py` | Batch input, output, and preview rendering |
| `renderer/` | Conversion and rendering through `cr-renderer` |
| `brand_kit/` | Bundled images and fonts |
| `input/` | Sample tasks |
| `viewer/` | Adobe Express viewer, bundled previews, and export utility |
| `tests/` | Structural, rendering, and regression tests |
| `eval/` | Design generators, quality metrics, and comparison tools |

## Testing and evaluation

Install the development dependencies and run the tests:

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

The tests cover element preservation, geometry, rendering, determinism, malformed inputs, and layout relationships such as button labels and card contents.

Development evaluation uses generated designs, structural checks, and visual comparisons. AI-assisted and human/reviewer preferences informed parts of the scoring approach. These evaluation tools are separate from the runtime engine and are not included in the Docker image.
