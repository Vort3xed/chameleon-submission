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

Runs live in `eval/runs/<name>/` (outputs, `results.jsonl`, `summary.json`,
pairwise logs); `eval/runs/history.jsonl` has every scorer run.

## Current best

**v35w**: formats 98.48 · holdout 98.09 · fresh holdout2 98.11 · crazy 96.85 (28 designs) · 0 gate failures · 0.07 s/design.
Fresh holdout2 (seed 4242, never inspected before this run): v35w vs v34 132–47, 0 severe; vs v35r 45–8.
Discriminator (below) vs v34: formats 907–398 (p 10⁻⁴⁶), holdout 218–70 (p 10⁻¹⁹).
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
97.2%;
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

**Attack (`eval/attack.py`):** hill-climbing engine outputs on the
discriminator's score found one hole - it bought margin balance by breaking
button labels onto two lines ("Learn / More"), because text re-wrapping
weighed 0.09.  A `wrap` rule (one-line labels stay one line; short phrases
are not broken one word per line) closed it: refit weight 1.50, held-out
85.1%, unseen sets 90.8% / 98.2%.  What the climb can still buy is tidiness
at the cost of size (a slightly smaller product for exact alignment): the
discriminator penalises falling below an element's source share but never
rewards more - the bigger-vs-faithful axis only human labels can calibrate.
Two of six engine outputs were already local optima for it.

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
