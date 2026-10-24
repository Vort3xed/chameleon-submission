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

**v29**: formats 98.30 (scorer v2) · crazy 95.83 · 0 gate failures · 0.06 s/design.
Holdout: v23b beats v12 (start of day 2) **65–20 (35 ties), +0.37**; v27b beats
v23b 27–19 (+0.10).

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

## Objective fits (`eval/collect_prefs.py` + `eval/fit_prefs.py`)

| data | tasks | current weights agree | fitted (5-fold CV) |
|---|---|---|---|
| p1 (v8 candidates, main) | 86 | 57% | 61% |
| p2 (v14 candidates, main) | 323 | 63% | 61% → 67% with family × stretch features |
| p3 (v17 candidates, formats) | 338 | 69% | 68% |

The judge's own ranking agreement (two shuffled rankings) is 75%, which caps
any fit.
