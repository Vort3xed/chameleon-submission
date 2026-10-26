# CHAMELEON — design retargeting engine

`engine/resize.py::resize(source, target_canvas)` re-lays-out a design for a new
canvas instead of stretching it. It moves the furniture: it works out what
each element *is* (no labels are given), picks a layout that suits the new
shape, sizes text so it renders legibly with the real renderer, and checks
every hard rule before it returns.

```
source design + target canvas
  └─ scene.py      structure inference  (backgrounds, decor, groups, containers, rows, roles)
  └─ arrange.py    candidate layouts    (every family, per drop level; bands kept at their edges)
       └─ families.py preserve / stack / split / row
       └─ blocks.py   measure + place    (exact renderer text wrapping, aspect-locked images)
       └─ finishing.py decoration, corner ornaments, alignment snapping
  └─ objective.py  rank candidates      (legibility, headline & product size, coverage, overlap…)
  └─ finalize.py   enforce hard rules   (ids, order, bounds, aspect, ints, finite numbers)
```

## Approach

**1. Understand the design (`scene.py`).** Elements are classified without
semantic labels:

* *backgrounds* – images/shapes covering ≥90% of the canvas → re-fitted full-bleed;
* *decor* – faint, tiny or off-canvas shapes holding no content, and faint
  texture type (a huge 8%-opacity word behind everything) → kept, re-anchored
  proportionally (large faint frames instead keep their distance to each canvas edge);
* *hidden* – invisible elements, elements wholly off the source canvas (never
  seen, so never revealed) and small images whose asset is missing (the
  intentional `holiday_watermark` case) → skipped gracefully (opacity 0); a
  large image we cannot find is laid out as usual - only the logo is a fixed
  asset, so the scorer's bundle may hold product art we have never seen;
* *effects* – copies of one text stacked on each other (drop shadows,
  outlines) echo the topmost copy, wrapping as it does; a shape just beneath a
  card or button of nearly its box is its shadow or outline and stays with it,
  whatever its opacity; a small icon beside a one-line label is one unit with
  it, and list items (icons with labels, lines opening with a bullet or a
  number) keep one left edge when stacked;
* *bands* – full-width bars on the top or bottom edge (header, footer, photo
  scrim) → stay bars on that edge with their content inside; the rest flows
  between them (and under them, as far as the source let it).  A full-height
  panel on a side edge (a colour block bleeding off half the canvas) does the
  same on a canvas relatively as wide as the source or wider; on a narrower
  one it flows like any block (a bare bar - a two-tone background, a colour
  strip - keeps its edge on any canvas).  A bar too thin to hold its content stays a
  stripe on its edge while its logo or small print flows with the rest - if
  that content stays legible off it (the bar is close in tone to the
  background); else the bar grows to hold it.  A thin bar holding the message
  flows as a card behind it;
* *blocks* – the units that get laid out: single texts and images, **rigid
  groups** (shared `group_id`, e.g. button shape + label, rotated ribbons,
  product tiles), **panels** (a container shape such as a card or scrim whose
  children are re-laid out *inside* it, recursively), **rows**
  (side-by-side runs like a badge strip), **tables** (three or more
  stacked rows of aligned text cells - a menu, a price list - which keep
  their columns, each aligned as in the source; four columns fold to two
  over two when the canvas is narrow) and **column units** (a row of pieces
  each set over its caption - a stat over its label, a numbered step over its
  text, a feature title over its detail: each column travels as one, wrapping
  as a row of tiles, and a big stat never takes the headline role);
* *ornaments* – rotated or corner-pinned small blocks, placed last in free corner space.

Roles come from cues a designer would use: largest type → headline (a price
like "From $24" is never the headline, even when it is the biggest), verbs like
"Shop/Buy/Learn" or the biggest pill → CTA, wide image near an edge or an
asset named *logo* → logo, the block carrying the most product imagery → hero,
smallest long text near the bottom → legal. Each role has an importance used
when space is tight.

**2. Measure exactly what the renderer will draw (`text_metrics.py`).** The
official converter wraps greedily at spaces using skia glyph advances and
cr-renderer draws top-aligned at `int(font_size)`. We replicate that wrap
verbatim (verified identical), so line counts, box heights and
centring inside buttons are exact. Letter spacing is scaled with font size.
Fallbacks: Pillow/FreeType advances, then a per-font heuristic — the engine
still works with no fonts or assets present.

**3. Generate candidate layouts (`arrange.py`, `families.py`).**

* **preserve** – nearby aspect ratios: uniform scale; blocks whose drawn content
  overlaps move together and only the space between them stretches (corner
  pieces stay by their corner; an inset border frame is the canvas the content
  lives in). The same shape (aspect within 8%) always keeps the composition;
* **stack** – a single column in reading order (tall/square canvases); groups stay compact and the spare height goes to the margins and the gaps between groups, drawn halfway to how the source spaced them (a headline the designer centred does not sink to the bottom of a tall canvas);
* **split** – product imagery in one column, everything else stacked beside it;
* **row** – banners: logo | product | text columns | CTA, with text partitioned into 1–3 columns; beside product art on a banner (not a strip), a logo that headed the copy stays at the head of the headline's column when that costs the type under 20% (set apart by the product, it reads as a stray); copy columns narrow to their lines and the spare width is shared between the row's items, so the gaps are even.

Each arrangement binary-searches the largest text scale that fits (and a
calmer 0.82× variant), for several image-to-text ratios. Text never drops
below a legibility floor tuned to how a judge views the canvas (≈10.5 px at
1024 px viewing size, less for legal/badges, never more than the source had).
When even that cannot fit — e.g. a 17-element poster into 728×90 — whole
low-importance blocks (also inside cards) are dropped progressively (legal →
badges/ribbons → body → secondary text → product), never the headline or CTA;
never the logo.  In banner rows, images fill the height while their
transparent padding stays on the canvas, the logo never outgrows the text by
more than 1.5× its original proportion, the text may grow until a headline
fills two lines of the row, copy keeps at least a third of an em from the
product, logo or button beside it, and the button never outshines the
headline. Long copy may re-wrap to a comfortable ~40-character line even when
its source box was narrow.
Strips get wider end margins (a 320×50 button no longer sits 2 px from the
edge); sparse designs may scale up to 2× more into a bigger canvas.

**3b. Finish like a designer (`finishing.py`).** One alignment per column (mixed columns
centre); a column keeps its groups compact - the widest gaps of the original
separate groups, a gap inside a group stays between half and 1.2 em of the
text beside it, and spare height goes only between groups and to the margins; side-by-side columns and
banner rows share one *drawn* centre line and equal drawn outer margins
(transparent padding in product art or a logo does not count); near-misses
within 1.5% are snapped onto the shared line (also inside cards) unless that
collides, crams a neighbour or unbalances the margins; a corner badge keeps
its corner (product art there shrinks a little to make way, text never);
decoration on a card moves with the card; wrapped centred titles get
balanced lines instead of a lone last word.

**4. Rank them (`objective.py`).** Terms in [0, 1]: legibility, headline size,
product size, visible coverage, fill, kept content, overlap beyond what the
source layered, short phrases not shattered into one-word lines, faithfulness
of position, the headline still leading the other text, visual mass centred -
plus which arrangement family suits how stretched the canvas is
(near-square → keep the composition, wide → product beside text, very wide →
banner row). The weights started as a logistic fit to an AI judge's rankings
of the engine's own candidates on ~320 tasks (`eval/collect_prefs.py` +
`eval/fit_prefs.py`); human labels then moved them: headline size and
legibility count more, content kept more (size must not be bought by
dropping content), and two terms reward using the canvas - the headline's
share of the short side and the product's share of the area.  The family
priors are kept small (a quarter of the fit): they are the judge's taste in
arrangements and must not outvote the quality terms.  A family's prior
follows the less stretched of the canvas and the region it laid out: beside
a side panel a stack sits in a near-square space whatever the canvas, but a
scrim along the bottom of a square ad does not make its content a banner.  A layout that collides never
outranks a clean one.

**5. Enforce the rules (`finalize.py`).** Same elements in the same order,
only geometry / `font_size` / `opacity` (and, for hidden text, `z_index`) change;
images keep their exact source aspect (full-bleed backgrounds excepted);
every box lies on the canvas (rotated footprints too where possible); text
boxes are strictly positive (cr-renderer rejects zero); font sizes are
integers; NaN/inf anywhere is replaced. `resize()` never raises: on any
internal error it falls back to a letterboxed copy of the design.

**Hidden elements.** Dropped images/shapes get `opacity: 0`. cr-renderer
ignores opacity on text, so dropped text gets `opacity: 0` *and* a `z_index`
just below the opaque full-canvas background, which hides it in the
reference renderer as well. Without such a background, a dropped text is
squeezed to 1 px in the middle of its own opaque card - or else the design's
biggest opaque button - with a `z_index` just beneath it. With nothing opaque
to hide behind, text is never dropped.

## Run it

Python 3.10+ (developed on 3.11). With [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m engine.main          # every input/*.json -> output/<task>_output.{json,png}
```

(or `python -m venv .venv && .venv/bin/pip install -r requirements.txt`).

Docker — exactly how stage one runs it:

```bash
docker build --platform linux/amd64 -t my-chameleon-engine .
docker run --rm --network none \
  -v $(pwd)/input:/app/input -v $(pwd)/output:/app/output my-chameleon-engine
```

Everything is installed at build time (versions pinned in `requirements.txt`);
nothing is fetched at run time and no model is used. Typical latency is
~0.1 s per design; the slowest (cards inside narrow banners, where every
candidate re-solves the card's interior) take ~3 s.

## Evaluation harness (`eval/`, `tests/`)

Development-only tooling, not copied into the image
(`uv pip install -r requirements-dev.txt` for `jsonschema`/`pytest`).

* `gen_testset.py` – procedural Solstice-brand designs from 12 archetypes
  (posters, split heroes, banners, typographic flyers, cards with contained-but-
  ungrouped content, scrims, product grids, event flyers, sale promos, minimal,
  story stacks, adversarial messes with junk fields, rotation, missing assets,
  off-canvas and zero-size elements), each paired with near / far / extreme
  targets from a 42-format catalogue; `--formats` builds every design × every
  format (1,638 tasks); `--extra-formats` the same idea over 14 more presets
  kept apart (120×600, 300×1050, 468×60, 234×60, 1128×191, 3000×3000, menus,
  invitations, book covers…); `--seed 2026` and `--seed 4242` give holdout sets
  never used for tuning.
* `gen_crazy.py` – 35 stress designs (walls of text, 3×3 grids, giant type,
  two CTAs, photo + scrim, no background, vertical and rotated type, collages,
  CJK/Arabic/emoji, unbreakable words, hard line breaks, nested cards, one
  group holding everything, edge bars, price lists, lone elements, a faint
  watermark word, imagery with no text, a sidebar, art bleeding off an edge,
  feature cards, the eyebrow-to-legal stack, copy on a bare background) × 10
  targets including 10:1 strips, 64 px squares and 4K.
* `gen_random.py` – random plausible designs (the pieces real designs are made
  of, combined at random in four skeletons) × random catalogue targets, plus
  kinds (`--kind`) for banner and skyscraper sources (`strips`, `tall`) and
  further skeletons (`patterns`: Z-pattern, product grid, half-bleed panel;
  `skeletons`: copy in a colour block, scrim, feature columns, partner
  footer, card overlap; `wild`: full-bleed photo, menu, grouped offers,
  badge ring, testimonial; `effects`: card and text shadows, outlined type,
  two-tone backgrounds, bare colour strips; `marketing`: stats row, numbered
  steps, coupon code, star rating, QR corner); `hunt.py` ranks the engine's outputs on any set by the source-relative part
  of the discriminator and shows the worst - where new weaknesses come from.
* `score.py` – a hard structural gate (schema, ids, frozen content/fonts/assets,
  bounds, aspect, renderability) plus 17 rubric metrics computed from real font
  metrics and actual renders (collisions, cut-off, readability, contrast,
  hierarchy, group integrity, margins, balance, completeness, …).
* `run_eval.py` – parallel engine + scorer over a test set (`--vlm` adds AI-judge scores).
* `vlm_judge.py`, `vlm_pairwise.py` – a local multimodal LLM as a stand-in for
  the AI evaluator: absolute rubric scores, and A/B preference between engine versions.
* `vlm_sanity.py` – how far the judge can be trusted: a resize against copies
  with known defects (smaller text, collisions, squashed product, text cut off,
  dropped headline, naive stretch) and against itself, in both orders.
* `design_rules.py` – exact design-rule metrics, each relative to the source
  (alignment incl. inside cards, edge crowding, margin balance, newly crammed
  neighbours, headline lead, product and logo share - nested in panels too -,
  fill, corner pieces, header and footer bars kept on their edges, captions
  kept under the piece they caption). Roles are
  read in the source and followed into the resize by element id (analysed
  afresh, a resize could merge a side panel with its content into 'product
  art'); thresholds ramp in over a band and specks under 3 px are not seen, so
  a nudge too small to see cannot flip a verdict.
* `judge_bench.py` – known-answer pairs for judges: an output against a copy
  with one defect at graded severity, tie controls (identical, 1 px moves),
  the brief's anti-examples (shrunk, stretched), and three sets of held-out
  defect kinds (`--set unseen3`: failures the engine could make - cropped art,
  text off its card, overflowing text, a bar slipped off its edge).
* `judge_fit.py`, `discriminator.py` – the fitted discriminator (non-negative
  logistic on rules + scorer metrics, a floor on every rule) with an
  overfitting audit (held-out tasks, unseen defect kinds, held-out human
  labels, invisible-change sensitivity, a shuffled-label leakage control), and
  run-vs-run comparison: sign test, mean, severe losses.
* `loop.py` – one step of the improvement loop in one command (~20 min): run
  the engine on the format set, the fresh holdout, the stress set, every
  random-design set and the extra presets, judge each against a baseline with the
  discriminator (sign test, mean, severe losses); accepted when no set blocks
  and at least one improves significantly; logged to `eval/runs/loop.jsonl`.
* `attack.py` – hill-climbs outputs on the discriminator's score to expose
  what it over-rewards (found the label-wrapping hole).
* `judges.py` – VLM judge variants measured on the bench; `label_app.py` – a
  local page for human A/B labels, the yardstick for every judge.
* `docker_parity.py` – runs a fixed sample of every test set in the amd64
  image exactly as stage one does (`--network none`) and checks each output is
  byte-identical to native `resize()`.
* `sheets.py`, `format_sheet.py` – contact sheets for eyeballing results.
* `tests/test_robustness.py` – the bulk of the suite: samples pass the gate at many sizes,
  fuzzed/malformed inputs never crash or break invariants (and are absorbed
  by the main engine, not just the fallback), outputs render,
  determinism, no-fonts/no-assets operation, import from any cwd or as a
  top-level module, `python -m engine.main` end to end, every stress
  design at five targets and 20 random designs at three - each passing the
  gate with its headline shown.
* `tests/test_structure.py` – structure survives any canvas: header and footer
  bars stay full-width on their edges with their content inside (as stripes
  when too thin for it), a side panel
  stays a full-height bar holding the product with the copy beside it in
  reading order; a price list keeps each price with its item; grouped offers
  never outgrow the headline; faint texture type stays decoration, never the
  headline; the logo that headed the copy keeps heading it beside product art;
  a centred headline stays near the middle of a tall canvas; each stat and
  numbered step keeps its caption.
* `tests/test_discriminator.py` – the discriminator's invariants: a designer's
  original scores 1.0 on every rule against itself, a 1 px move is a tie,
  collisions / shrunk headlines / edge-crowding / a header bar floating loose
  from its logo or slipped off its edge score lower, the naive
  shrink loses to a real layout when the shape changes, product art is the
  source's, and a sub-pixel nudge of every element barely moves the verdict.
* `RUNS.md` – log of every kept change and rejected experiment with scorer
  and AI-judge results.

```bash
.venv/bin/python -m eval.gen_testset --out eval/testsets/main
.venv/bin/python -m eval.run_eval --name mine
.venv/bin/python -m pytest tests -q
```
