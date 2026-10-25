# Run log

Every engine change is measured three ways:

* **scorer** – `eval/score.py` mean (0–100) over the main set (`main`, 363 tasks)
  and over every design × every format (`formats`, 1,638 tasks). A run with any
  gate failure or crash is not kept.
* **VLM A/B** – `eval/vlm_pairwise.py`: the local Qwen3.8-27B judge compares the
  two versions on tasks whose outputs differ, twice with the order swapped.
  Reported as *new wins – old wins (ties)*, net preference in [-1, 1]. This is
  the deciding signal; the judge agrees with itself ~75% of the time, so small
  margins (< ~0.1 net) are noise.
* **holdout** – a test set generated with another seed (`--seed 2026`), never
  used for tuning, to check that gains generalise.

**Taste policy.** The discriminator vetoes defects; it has no calibration on
bigger-vs-faithful (see the attack notes).  A change on that axis whose
severe losses are within the limit is decided by the VLM judge, on the format
set and confirmed on the fresh holdout.  Human labels, when they exist, will
replace this.

`python -m eval.loop --name <step> --baseline <step>` does a whole step
(engine on formats + fresh holdout + stress set, gate/crash check,
discriminator verdict on both quality sets) in ~3 minutes and logs it to
`eval/runs/loop.jsonl`.  A change that fails only on the sign test but has a
positive mean and no severe losses may still be kept on visual review - the
log row says so.

Runs live in `eval/runs/<name>/` (outputs, `results.jsonl`, `summary.json`,
pairwise logs); `eval/runs/history.jsonl` has every scorer run.

## Current best

**v36r**: formats 98.52 · fresh holdout2 98.16 · crazy 96.81 (28 designs) · extra presets 97.55 · 0 gate failures · 0.08 s/design.
Discriminator vs v34: formats 1134–291 (p 10⁻¹¹⁷, 1 severe), fresh holdout2 145–45 (2 severe).
Holdout (never tuned on): v31-era engine beats v12 (start of day 2) 55–19 (+0.29);
v33 ties v27 18–17 over all 233 differing tasks; v34 vs v33 16–13.

## Kept changes

| version | change | scorer main | scorer formats | VLM A/B (vs previous kept) | commit |
|---|---|---|---|---|---|
| baseline | starter's uniform stretch | 10.42 | – | – | – |
| v1 | first engine | 95.76 | – | – | |
| v2b | recursive panels, slot fitting for split/row | 96.12 | – | – | |
| v5b | drop levels, hidden text under the background, element-level overlap | 97.30 | – | 47–29, +0.14 vs v2b | |
| v7 | strict fit tolerance (rows had silently failed) | 97.54 | 98.30¹ | 16–10, +0.17 vs v5b | `077b7a3` |
| v12 | preference-fitted direction, words-per-line wrap term | 97.76 | 98.41¹ | – | `254a29b` |
| v13 | text-scale cap leans to the long side (banners keep short text large) | 98.10 | – | 25–18, +0.08 vs v12 | |
| v14 | banner logo: padding-aware on-canvas sizing, ≤ ½ height, ≤ 1.5× text proportion | 98.24 | 98.55 | 35–23, +0.12 vs v12 | |
| v16 | product rows recognised as the visual; large faint frames stretch to the canvas; drops inside cards; price never headline | 98.25 | 98.55 | 21–3, +0.58 vs v15 | `95e449f` |
| v17 | family × canvas-stretch features, weights refit to 320 tasks of judge rankings | 97.94 | 98.35 | 52–29 +0.24 (main), 57–19 +0.38 (formats) | `95e449f` |
| v18 | guard weights (wrap, legibility, overlap) restored | 97.98 | 98.38 | 50–21, +0.29 vs v16 (formats) | `2c0a68d` |
| v19 | split layouts may give the product 62% of the width | 98.01 | 98.40 | 40–8 +0.40 (formats), 7–3 +0.22 (main) | `d31e428` |
| v20b | decorative shapes move to a clear spot (tiny ones hide) | 98.01 | 98.39 | 14–13, ±0 | `5f63563` |
| v22 | hardened against junk input (tiny canvases, junk type/group_id, fallback text boxes) | 98.01 | – | outputs identical | `39cf0b2` |
| v23b | one-line CTA/badge labels shrink (to the legibility floor) before wrapping | – | 98.40 | 10–9, ±0 | `dede079` |
| v26 | "keep the composition" may enlarge everything 1.5× (was 1.3×) | – | 98.40 | **51–3, +0.59** (formats) | |
| v26b | …while keeping the usual margin from the canvas edge | – | 98.38 | 23–19, +0.09 | |
| v27 | …up to 2× (beyond 2× never fits) | 97.98 | 98.38 | **24–1, +0.68** (formats); 31–23 +0.09 (main); 25–20 +0.09 (holdout) | |
| v27b | …and elements that were apart must keep a gap (no touching) | – | 98.38 | 11–13 vs v27 (formats); 27–19 +0.10 vs v23b (holdout) | `8ca3c99` |
| v29 | fixes from the stress set: rigid groups sized by visible words (3×3 grids no longer dropped), nested cards stack (3.6 s → 0.4 s), a group spanning the design is broken up, rotated elements fit by footprint and box, preserve never pushes a box off-canvas | – | 98.30² | 17–11 +0.06 (formats); 5–11 −0.06 (holdout) | |
| v30 | wall-clock time budget replaced by a candidate cap (output no longer depends on machine speed; under x86 emulation the old budget changed 2/30 outputs) | – | 98.30² | outputs identical | `6ef0c83` |
| v31 | stacked rows of like tiles form one grid; wrapped lines are evened out (9 tiles: 3×3 or 5+4) | – | 98.31² | 7–1 +0.60 (formats); 4–1 +0.38 (holdout) | |
| v33 | regression fix: grouped labels keep the font the full box allowed, *then* the box tightens around the measured lines (v29 had sized tight boxes from scaled glyph widths, which run short at small sizes, so labels lost a pixel: holdout 11–27 vs v23b) | – | – | holdout: 12–10 vs v23b; 18–17 (198 ties) vs v27 on all differing tasks | |
| v34 | logo floor 18 → 28 px visible height (the wordmark was ~5 px in 300×250 / 250×250) | – | 98.23 | **90–40, +0.16** (formats, 310 tasks); 16–13 +0.03 (holdout) | |
| v35a | corner badges stay in their corner (shrink to 0.7 before sliding away) | – | 98.22 | 11–7 (VLM) | |
| v35c | one alignment per stacked column; mixed columns centre | – | 98.24 | 27–3 (VLM, 44 of 208 judged before the server died) | |
| v35f | preserve: blocks whose drawn content overlaps move as a band, gaps scale and share the slack equally; stacked columns stretch gaps in proportion; banner rows centred by visible ink | – | 98.24 | (v1 of the band rule lost 72–93 on VLM: it kept text and button "cramped") | |
| v35g | alignment snapping: near-misses (< 1.5%) moved onto the shared line unless that collides, crams a neighbour or unbalances margins | – | 98.24 | discriminator 309–203 (p 3·10⁻⁶) | |
| v35h | strip ends get wider margins (up to ~15% of the short side; a 320×50 button sat 2 px from the edge) | – | 98.24 | discriminator 568–290 | |
| v35j | banner text may grow until the headline fills two lines of the row (logo and button keep the old cap) | – | 98.30 | discriminator 200–145 | |
| v35k | objective: the headline must lead (1.15× any other text, weight 0.08); the logo is never dropped (brand) | – | 98.34 | discriminator 36–19 | |
| v35m | sparse designs (little drawn on their canvas) may scale up to 2× more | – | 98.41 | discriminator 152–159 (neutral); kept on visual review: sparse stories and squares stop looking empty | |
| v35o | preserve: margins measured on drawn content, not boxes (a wide box around short text pushed it to x = 0); corner ornaments no longer shape the bands (a corner ribbon put all the slack on one side) | – | 98.43 | discriminator 225–30, 0 severe (formats); 84–55 (holdout) | |
| v35q | decoration that sat on a card moves with the card (dots were left behind when a card moved); scorer: a dot leaving its card weighs by its importance | – | – | discriminator 33–0 | |
| v35r | preserve bands keep the outer horizontal margin when compressing (a clamp had jammed text against a product panel) | – | – | discriminator 17–25, mean −0.003, 0 severe (neutral); kept: principled | |
| v35s | banner rows: after shifting, leftover margin imbalance is taken from the padding-side gap (a logo's transparent padding no longer leaves the button end tight) | – | – | discriminator 82–18, 0 severe | |
| v35t | alignment snapping also inside cards (against the card's centre) | – | – | ties (offsets were below the visible threshold) | |
| v35v | an inset border frame is the canvas the content lives in (preserve maps into the frame's new box; reflowed layouts use its inside) | – | – | neutral (34–39, 0 severe) | |
| v35w | side-by-side and banner columns share one drawn centre line (boxes include line spacing and padding, so centred boxes left visible centres a few px apart) | – | 98.48 | discriminator 255–100, 0 severe; holdout2 45–8 | |
| v35z | wrapped centred headlines/subheads get balanced lines (narrowest box with the same line count, like CSS text-wrap: balance) - no lone word on the last line (v35y's version almost never fired: the renderer needs a few px past the widest line) | – | – | discriminator 52–54, 0 severe (neutral: it has no widow rule); kept: typography | |
| v36b | side-by-side layouts centred by drawn content too (a 4:3 slide had 14% more margin on one side) | – | – | discriminator 191–43, 0 severe | |
| v36c | a corner badge keeps its corner: product art there shrinks (≤15%, about its far corner) to make way; text is never pushed aside | – | – | 14–12, mean +0.31, 0 severe on the 29 tasks it touches (too few for the sign test); kept: badges back in their corners, a ribbon no longer overlapping the product | |
| v36f | the same shape (aspect within 8%) keeps the designer's composition (scaled, enlarged where it fits), unless that is not legible - found by resizing every design to its own size: 8/75 got worse, one was rebuilt as a side-by-side layout | – | – | discriminator 7–22, mean −0.17, 0 severe (small margin shifts on near-identical outputs); kept: a design asked for at its own size should not be rearranged | |
| v36i | the logo's legibility floor is capped at 25% of the canvas height (in 320×100 rows the 28 px floor made the logo a space hog) | – | – | discriminator 87–10, 0 severe; one subhead now outgrows its headline (poster_center_00 320×100) | |
| v36k | a banner row must give its copy at least 25% of the width - otherwise something is dropped or another layout used (a 320×100 headline had a 36 px column) | – | 98.53 | discriminator 20–6, 0 severe; fixes v36i's inverted subhead | |
| v36l | short titles (3–6 words) keep at least two words a line: the widest word pair, not the widest word, is what must fit (found by the new wrap rule: "Taste / the / Sunset" in a 600×200 header) | – | 98.52 | discriminator 61–42 (p 0.076), mean +0.12, 1 severe (looks fine: an alignment shift); kept: typography | |
| v36r | keep-the-composition tightens lone text boxes around their lines before enlarging (a full-width box around short lines no longer caps the growth), and refuses any boost that eats more than 40% of an element's breathing room (capped at two margins) - the fix that made tightening safe after v35u/v36h/v36o | – | 98.52 | discriminator neutral, defect veto passed (formats 95–86, 0 severe; holdout 14–16, 1 severe); **VLM 124–50 (formats), 17–12 (holdout)** - accepted under the taste policy | |
| v36w | banner rows take even end margins when they cost nothing visible: a logo's transparent padding pinned at the edge (ink 52 px in from the left on 320x100) used to leave the far end at the usual margin; the row now reserves the same drawn margin at both ends whenever every text keeps its line breaks and the type keeps >=90% of its size | – | 98.51 | discriminator formats 183–45, holdout2 26–8, 0 severe; content hidden on 2 tasks, shown on 4 more; VLM 21–32 (67 ties) is uninformative here: on the bench it prefers the lopsided copy (lopsided 0.04: 7% right, 43% wrong) | |
| v37b | from a human label note ("the text at the top should be centered"): a left- or right-aligned text in a centred column used a box ~0.6 em wider than its lines, all of the slack on one side, so the words sat off the centre line; such boxes now shrink to the narrowest width that wraps identically and stay centred | – | 98.52 | discriminator formats 66–3, holdout2 14–5 (p 0.06), 0 severe - kept on visual review (titles in tall formats now on the centre line) | |
| v37i | edge bands, from the stress-set audit (quality, not just crashes): a full-width bar on the top or bottom edge (header, footer, photo scrim) is a panel even with one thing inside, keeps its edge, the full width and its share of the height, with its content laid out inside; the rest flows between the bars, and runs under a bar as deep as the source let it (product art beneath a scrim). Bars stay bars whenever that layout is legible, else they flow as before (thin strips) | – | 98.51 | discriminator formats 42–41, holdout2 5–4, 0 severe (neutral); crazy 96.80 -> 96.86; header/footer bars no longer float as boxes, the footer is no longer read as a button - kept on visual review for the structural fix; tests/test_structure.py fails without it | |

**Lesson (v29–v31):** a chain of small A/B wins (+0.06, +0.06, +0.38 on 8
tasks) hid a real regression. Every few versions, compare against a fixed
baseline on *all* differing holdout tasks.

² scorer v2: group integrity compares visible extents, not boxes (v27b rescored: 98.34).

¹ official samples × 42 formats only (126 tasks).

The scorer drops at v17 because it penalises small text harder than the judge
does; the judge consistently prefers keeping content and bigger product art.

## Rejected experiments

| experiment | VLM A/B | note |
|---|---|---|
| v3: drop levels without scaled hidden fonts | 20–33, −0.12 | fixed in v4b/v5 |
| v6: kept weight 0.24, hero dropped last | 7–15, −0.20 | |
| v6a: hero dropped last (couples logo) | 0–4 | |
| v15 alone: drops inside panels | 2–4, −0.18 | judge wants subtitles kept; kept term reweighted in v17 |
| v19a: keep composition for aspect change up to 0.6 (was 0.45) | 23–48, −0.31 | |
| v19c: split image fraction 0.72 | 6–9, −0.06 | |
| v19d: stack image ratio k = 2.8 | 17–16, ±0 | slower, no gain |
| v21: banner rows grouped toward the centre (mid-wide canvases) | 1–6, −0.20 | judge prefers logo left / CTA right |
| v24: button padding compresses in tight slots | 13–7, +0.08 | tiny labels went *up* (43 → 46); reverted |
| v25: same aspect ratio → return the source layout scaled exactly | **1–76, −0.93** | the judge prefers our larger text even to the designer's own sizing |
| v28: preserve boosts 2.5× / 3× | 0 differing | never fit |
| v35n: banner rows mirror the logo's padding inset on the button side | discriminator 277–47 but 4 severe losses | the mirrored inset starved the headline (Twitch banner headline shrank to a few px); a case of the generator gaming the margin rule - comparisons now also require a positive mean and no severe losses |
| v35p: preserve bands keep the outer margins when compressing (both axes / x only) | discriminator 50–95 / 17–25 | x-only turned the jammed split layouts into stacks, which look cleaner but lose on the scorer's group-integrity metric: the discriminator may be biased toward keeping the composition (its training defects never include a good re-layout); needs human labels |
| v35u: preserve tightens lone text boxes around their lines before scaling (lets sparse/list designs grow) | discriminator 77–115 (p 0.007); VLM **173–31 for it** | bigger text, but tighter edges; first version re-wrapped text (integer fonts) - fixed by verifying lines; still rejected; revisit with human labels (bigger vs faithful is the axis the discriminator has no calibration for) |
| v35x: stacks also offered with the headline alone grown further (emphasis; the brief's own example grows the headline 56 → 150 px for a story) | discriminator 42–70 | engine 30% slower; with the presence rule, growth past each element's source share earns nothing and costs margins. VLM and the brief favour bigger; the discriminator does not - the open question for human labels |
| v36a: the tight preserve (v35u) offered as an extra candidate beside the normal one | discriminator 36–44 | the objective seldom picks it; no gain |
| v36d: columns at the optical centre (45% of the outer slack above) | discriminator 55–76, mean −0.004 | trades against vertical margin symmetry; no measurable gain |
| v36g: unreadable text (< 70% of legible size) no longer counts as kept in the objective | discriminator 17–17, 1 severe | badges and subheads got dropped but the headline did not grow: in 320×100 rows the text column is narrow because logo, product and button keep their width |
| v36h: tight preserve again on the current engine (+ margins growing with the boost) | discriminator 94–134, 3 severe | the composition grows until the widest full-line paragraph reaches its margin; body copy then crowds an inset frame. Parked until human labels settle bigger vs faithful |
| v36j: in a column, text other than the headline is capped 1.15× below it | 4–5 on 12 tasks | the inversions left are at the legibility floor (both 8 px in a 36 px column): the row itself is wrong for that much content at 320×100 |
| v36m: headline emphasis again (stacks may grow the headline alone, up to 2.5×) | discriminator 31–72 (2 severe, within limit); **VLM 21–41** | both judges against: the bigger headline cost dropped content (a card lost its wordmark and subhead) and off-axis left-aligned titles |
| v36n: a text whose id names the brand (logo / wordmark / brand) is the logo (never dropped) | discriminator 18–53 | in tiny typographic banners dropping the wordmark was the better trade |
| v36o: tight preserve + every element keeps ≥ 60% of its scaled edge distance | discriminator 39–219, 96 severe | the proportional floor can exceed the room there is and pushes blocks into impossible positions; tightening stays parked for human labels (VLM was 173–31 for it) |
| v36p: a minor ornament with no spot clear of content is hidden instead of overlapping | loop: formats 2–7, holdout 1–1 | rare; dropping the badge costs more presence than the overlap |
| v36q: preserve also offers the next calmer boost | loop: formats 50–50, holdout 5–0 | no gain for the extra candidates |
| v36s: 9:16 stories keep content inside the platform-safe band (12% top, 18% bottom clear; 78/117 story CTAs sat in the bottom 20%) | loop: formats 11–132, 4 severe (veto) | the narrower band shrinks everything; the AI evaluator judges the image, not a phone UI over it - noted for the finale (a 'safe zones' toggle) |
| v36t: the headline term saturates at 64 px viewed (was 44), so rankings prefer bigger headlines | loop: formats 82–129, holdout2 8–25, 0 severe; VLM 39–44 (37 ties) on formats | neither judge wants it; the brief's "bigger" is already met where room allows |
| v36u: banner rows always reserve the padded end's drawn margin at both ends | loop: formats 290–62, holdout2 42–12 | by eye: 'Sip Slowly' broke into one word per line, content dropped, orphans - balance must not cost line breaks (v36w) |
| v36v: v36u offered as an extra candidate, plus a margins term (0.07) in the objective | loop: formats 369–73 | the term reshaped choices inside cards and between families (cramped button rows in scrim cards, smaller posters) |
| v36x / v36y: banner groups at least 0.5 / 0.35 em of the largest text apart (the warmup sample's wordmark sat 6 px from its 61 px headline) | loop: v36x formats 207–104, 3 severe; v36y 191–82, 4 severe (over the limit), holdout2 22–16 | the air comes out of the type: buttons drift back to the edge (even ends no longer fit) and extra copy returns tiny; the first human labels prefer bigger type, so the cramming is left to a fix that does not shrink text |
| v37a: every left/right-aligned text box snug | loop: formats 76–27, holdout2 16–7 | in banner rows a column takes the block's source anchor (often 'right'), so snug headlines slid against the button; narrowed to centred columns (v37b) |
| v37f: layout-tree family - each design parsed by recursive XY-cut (widest whitespace first, so what sits close ends up in the same subtree: the advanced sample parses as [[logo, product], [[headline, subhead, badges], button]], legal), re-solved with up to two stacks flipped the way the canvas went | loop: formats 57–140, 25 severe | the parse is right and role-free, the naive solver is not: rows share width by source width (tiny logos and buttons), no image-fills-height or button caps, and it sometimes wins the ranking because it has no family prior; next use of the parse: group-aware spacing inside the existing families. Code kept outside the repo |
| v37g / v37h: edge bands always / as an extra option, band height from the narrower canvas scale | loop: v37g formats 24–76, 5 severe; v37h 16–11, 3 severe | scrims shrank to ~80 px on skyscrapers; as an option the ranking had no reason to keep a header a header; fixed by the height share, preferring bands when legible, and letting content run under them (v37i) |
| v37j: v37i + a split needs text beside the product | loop: formats 43–40, scorer 98.51 -> 98.47 | hurts elsewhere |
| v36z: banner logo never outgrows the text relative to the source (1.0x, was 1.5x) | loop: formats 230–88, holdout2 35–16, 0 severe; **VLM 12–39** | the wordmark becomes illegible on 728x90 / 320x50 (VLM: 'logo larger and more readable' x20) |
| v36z2: banner logo at most 40% of the row height (was 50%) | loop: formats 65–13, holdout2 13–3; VLM 14–21 (62 ties) | parked (patch kept): the headline also loses ~10% when even ends become affordable - waiting on human labels for logo size and balance-vs-size (pairs p080–p109) |
| v35l: banner rows also offered with a 0.75× button | discriminator 22–41 (p 0.02), engine 60% slower | the objective picked small buttons where they hurt; reverted |
| edge bands (full-width header/footer bars) | not built | they scale rigidly and get dropped in banners; needs a band concept — deferred, the official samples have none |

## The discriminator (`eval/judge_bench.py`, `eval/judge_fit.py`, `eval/discriminator.py`)

A benchmark of 590 known-answer pairs (40 tasks): a real output against a
copy with one design defect at graded severity (block off its alignment,
neighbours crammed, lopsided margins, element on the edge, product shrunk,
headline no longer leading, jitter, smaller text, collision), plus controls
that must tie (identical, and a block moved 1 px / 0.15%).

| judge | accuracy on defects | on ties |
|---|---|---|
| VLM, JSON answer (`vlm_pairwise` prompt) | 65% | flips with order 67% |
| VLM, one question per rubric item | 62% | flips 100% |
| VLM, answer token probabilities | 54% | flips 80% |
| VLM, both candidates in one image | 54% | flips 84% |
| VLM, thinking | – | ~4 min per call; dropped |
| design rules alone (`eval/design_rules.py`) | 78% | – |
| structural scorer alone | 72% | – |
| **fitted discriminator** (non-negative logistic on rules + scorer metrics) | **82% held-out tasks** | invisible-change sensitivity 0.02 |

Anti-overfitting audit (current): held-out tasks 85.2% vs 85.3% train; seven
defect kinds never used in fitting, on other tasks and a newer engine: 90.4%;
a second unseen set built after the rules were last changed (widow, stranded
button, drifting logo, badge on headline, tilted headline, squeezed layout):
97.2%; bootstrap over 20 task resamples (`--bootstrap 20`): out-of-sample
85.0% ± 1.5% (worst 81.3%), weight shares stable (top three ±0.01; spacing
and edge ±0.02 are the least pinned down);
adding the VLM vote does not help (81.9 → 81.2%).  Fixes found by auditing it:
hidden (opacity 0) elements were counted; a design failing the hard gate got
perfect scorer features (the starter's stretch went undetected); the spacing
rule flagged good grouping (now: pairs newly closer than 1.2% that were apart
in the source - 288 flags on v35o fell to 8, mostly real); alignment inside
cards was invisible; the naive letterbox beat real layouts on wide sources
(now a training defect, from the brief: "rearrange, not simply shrink").
Rules are relative to the source (a designer's original scores 1.0 against
itself), and alignment is perceptual (aligned within max(0.3%, 1.5 px),
0 at 1.5%), so pixel nudges cannot move the verdict.  Speed: ~1 ms per design;
a whole 1,638-task run compares in ~6 s.  Human labels (`eval/label_app.py`)
are the remaining check that it agrees with taste.

**Taste features (human labels, 51 decided pairs):** the discriminator agreed with
people on only 43% of them; the one thing they consistently reward is size - the
headline relative to the canvas (24 right / 8 wrong as a lone feature) and the
product's share (16 / 7); padding, by contrast, loses to size when they compete
(11 / 17), although the notes ask for it.  Two absolute features (`taste()` in
design_rules.py: headline at 12% of the short side, product at 25% of the area,
both saturating) plus human pairs weighted x5: held-out synthetic 84.7 -> 90.1%,
held-out human 42.7 -> 71.4%, unseen defect sets 92.2% / 96.8%, invisible-change
sensitivity unchanged (0.01).  Gradient-boosted trees (xgboost, depth 2-4, also
with monotone constraints) on the same features fit the familiar defects a little
better (91.5%) but generalise worse (unseen 89-90%, human 63-73%): with ~600
pairs the linear model stays.

**Attack (`eval/attack.py`):** hill-climbing engine outputs on the
discriminator's score found one hole - it bought margin balance by breaking
button labels onto two lines ("Learn / More"), because text re-wrapping
weighed 0.09.  A `wrap` rule (one-line labels stay one line; short phrases
are not broken one word per line) closed it: refit weight 1.50, held-out
85.1%, unseen sets 90.8% / 98.2%.  What the climb can still buy is tidiness
at the cost of size (a slightly smaller product for exact alignment): the
discriminator penalises falling below an element's source share but never
rewards more - the bigger-vs-faithful axis only human labels can calibrate.
Two of six engine outputs were already local optima for it.  A second
attack on six fresh-holdout tasks: four were local optima; it found a card
stretched to the canvas edges unpenalised (the edge rule exempted every panel;
now only panels that already bled in the source), and two genuine
improvements (slightly bigger text) the engine leaves on the table.

**The brief's own example** (1080×1920: logo 320×120, product 432×720
"kept in proportion", headline 150 px on two lines, button 600×120) as an
organiser-made calibration point: literally it fails our gate (box aspect of
logo and product changed - so the official check probably judges rendered
proportions of contain-fit images, not box aspect; ours is the safe side).
Made valid, it scores 12.7 against our 14.4 - mostly logo/presence and a
collision from the subhead the example leaves out.  Its taste is clear
though: a far bigger headline (150 px vs our 85) and a smaller product than
ours - more evidence for the bigger-headline side of the open question.

**Extra presets** (`eval/testsets/formats_extra`, 546 tasks: 14 real presets
not in the main catalogue, incl. 120×600, 300×1050, 468×60, 234×60,
1128×191): v36l 0 gate failures, 0 crashes, scorer 97.54, max 1.3 s.

**Submission check (v36l):** the official amd64 image builds (920 MB) and
`resize()` inside it, under emulation, is byte-identical to native on the 3
official samples and on 40 random format / fresh-holdout tasks.  The engine
imports nothing from `eval/`.

**Selection audit:** among the engine's top-6 candidates, the discriminator
would pick differently in 10 of 80 fresh-holdout tasks; by eye the engine's
objective was right in about 3 of the top 5 (bigger legible text, dropped
clutter), the discriminator in 1 (a title broken one word per line).  So the
discriminator referees changes but does not choose layouts: it leans toward
completeness and the source's proportions.  `python -m eval.label_app
questions` builds human-label pairs for exactly these disagreements and for
the two bigger-vs-faithful experiments.

## How far the judge can be trusted (`eval/vlm_sanity.py`)

80 main-set tasks: the v33 output against a copy with a known defect, and
against itself; both orders, same prompt as the A/B. Share of the 160 verdicts:

| defect | clean wins | tie | damaged wins | verdict flips with order |
|---|---|---|---|---|
| identical copy | 10% | 79% | 11% | 21% |
| all text 10% smaller | 54% | 22% | 24% | 48% |
| all text 25% smaller | 84% | 1% | 15% | 22% |
| all text 50% smaller | 100% | 0% | 0% | 0% |
| headline moved onto the product | 99% | 0% | 1% | 3% |
| headline half off the canvas | 99% | 0% | 1% | 1% |
| headline deleted | 96% | 1% | 4% | 9% |
| starter's naive stretch | 84% | 1% | 14% | 15% |
| product squashed 1.6× wide | **42%** | 4% | **54%** | 39% |

* Gross defects (collisions, cut-off, missing headline, halved text) are
  caught almost always.
* Subtle ones are near chance per pair: 10% smaller text is a 54/24 call that
  flips with order half the time. Single close A/B results mean little; only
  totals over many tasks count (a sign test on decisive pairs: 90–40 is
  p ≈ 10⁻⁵, 16–13 is noise).
* It does not see distortion and prefers the squashed (wider) product. The
  engine never distorts (hard gate), but anything that just makes art bigger
  will look like a win to this judge.
* Slight position bias toward the second candidate (55%), cancelled by
  judging both orders.

## Objective fits (`eval/collect_prefs.py` + `eval/fit_prefs.py`)

| data | tasks | current weights agree | fitted (5-fold CV) |
|---|---|---|---|
| p1 (v8 candidates, main) | 86 | 57% | 61% |
| p2 (v14 candidates, main) | 323 | 63% | 61% → 67% with family × stretch features |
| p3 (v17 candidates, formats) | 338 | 69% | 68% |

The judge's own ranking agreement (two shuffled rankings) is 75%, which caps
any fit.
