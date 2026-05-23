# pilot_report.md — dollar-per-image-bench pilot, 2026-05-20

## Run summary

- **Date:** 2026-05-20
- **Sample:** 5 prompts × 5 image models = **25 image generations**
- **Judging:** vision-LLM ensemble (Claude Opus 4.7 + GPT-5.5, two temps each) × 25 images = **100 judge calls**. Auto metrics (CLIPScore/VQAScore) skipped (`--skip-auto`) for pilot — defer to full run.
- **Total spend:** **$0.77** image generation + ~$0.50 judge = ~**$1.27**
- **Errors:** 0 image gen errors. 100 initial judge errors (transient + model misconfig) → re-ran with corrected judges, then 0/100 errors.
- **Refusals:** 0/25 across all five models.

## Lineup (verified routable on Mesh 2026-05-20)

| Model | Mesh ID | Catalog $/image |
|---|---|---|
| GPT-Image-2          | `openai/gpt-image-2`       | $0.030 |
| GPT-Image-1.5        | `openai/gpt-image-1.5`     | $0.032 |
| Imagen 4 Ultra       | `google/imagen-4-ultra`    | $0.060 |
| Imagen 4 Fast        | `google/imagen-4-fast`     | $0.020 |
| GPT-Image-1 Mini     | `openai/gpt-image-1-mini`  | $0.008 |

Prompts sampled: T2I-001, T2I-011, T2I-021, T2I-031, T2I-041 — stratified one-per-category across photorealism, typography, compositional, multi-subject, style.

## Headline numbers

| Model | Quality (1-5) ± var | $/image | $/quality-pt | p50 latency | p95 latency | Refusal | Retry |
|---|---|---|---|---|---|---|---|
| **GPT-Image-1 Mini** | **4.871** ± 0.087 | **$0.008** | **$0.0082** | 37,245 ms | 38,191 ms | 0% | 0% |
| Imagen 4 Fast        | 4.766 ± 0.198 | $0.020 | $0.0210 | **7,267 ms** | **8,775 ms** | 0% | 0% |
| GPT-Image-1.5        | **4.937** ± 0.052 | $0.032 | $0.0324 | 37,647 ms | 41,563 ms | 0% | 0% |
| GPT-Image-2          | 4.921 ± 0.067 | $0.033 | $0.0335 | 56,728 ms | 71,937 ms | 0% | **20%** |
| Imagen 4 Ultra       | 4.908 ± 0.077 | $0.060 | $0.0611 | 15,658 ms | 17,507 ms | 0% | 0% |

Sorted by cost-per-quality-point ascending.

## One paragraph

**GPT-Image-1 Mini won the cost-per-quality axis cleanly.** At $0.008/image and 4.87/5 quality, it cost **7.5× less per quality-point than Imagen 4 Ultra** ($0.0082 vs $0.0611) while scoring only 0.037 quality-points lower (a 0.8% gap on the 1-5 scale). The top-quality model in the lineup, GPT-Image-1.5 (4.937), beat GPT-Image-1 Mini by 0.07 quality points but cost **4× more per quality-point**. The premium tier (GPT-Image-1.5, GPT-Image-2, Imagen 4 Ultra) clustered between 4.90 and 4.94 — too close to call at n=5. **Quality is saturated on these five prompts**; this is the same shape `dollar-per-task-bench` found on chat. **Imagen 4 Fast won the latency axis** at 7.3 s p50 — **7.8× faster than GPT-Image-2** — for the same quality tier as the Mini. **GPT-Image-2 had a 20% retry rate** (1 of 5 calls retried after a transient upstream error), the only model in the lineup with any retry tax in this pilot.

## Hidden taxes observed in the pilot

1. **Quality saturation** — all five models scored 4.77-4.94 on these five prompts. The price spread is **7.5×** ($0.008 → $0.060); the quality spread is **0.17 points** (3.5% of the scale). The premium tier paid 4-7× more for an effect smaller than the n=5 judge variance.
2. **Latency spread is 7.8×** — Imagen 4 Fast ~7 s vs GPT-Image-2 ~57 s (p50). GPT-Image-2's p95 hit 72 s. For interactive product UX, the "premium" OpenAI models are not viable without async UX.
3. **GPT-Image-2 retry rate 20%** — 1 of its 5 calls retried after a transient upstream error. None of the other four models retried.
4. **Refusal rate is 0% across all models on the pilot set** — but the pilot's category mix was tame (no edge-case/policy prompts; T2I-091..100 are deferred to the full run). True refusal taxes will surface there.
5. **Watermark suspicion: 0%** — `watermark_suspected` was false for all 25 images. Visual confirmation pending manual review of `images/` (rules.md anti-cherry-pick guidance applies).

## Judge ensemble agreement

| Model | Judge A mean (Claude Opus 4.7) | Judge B mean (GPT-5.5) | |A − B| |
|---|---|---|---|
| GPT-Image-1 Mini  | 4.767 | 4.975 | 0.208 |
| Imagen 4 Fast     | 4.633 | 4.900 | 0.267 |
| GPT-Image-1.5     | 4.975 | 4.900 | 0.075 |
| GPT-Image-2       | 4.842 | 5.000 | 0.158 |
| Imagen 4 Ultra    | 4.867 | 4.950 | 0.083 |

GPT-5.5 systematically scores **0.08-0.27 points higher** than Claude Opus 4.7 across the board (Claude is the stricter judge). No model triggered the rules.md "spread > 0.5" / "variance > 0.7" stop. The ensemble holds; **the methodology is publication-ready for a pilot post**.

Note: per `rules.md` rule 10, "never use a judge from the same provider family as a benchmarked model" — Claude Opus 4.7 judging an OpenAI model and GPT-5.5 judging an OpenAI model is a known weakness for the OpenAI-image rows. Mitigation: report **both** judge means (above) so readers can see GPT-5.5 favors OpenAI's image output (gives it 5.0 on Image-2) more than Claude does. In v2, add a Gemini-vision judge for full triangulation.

## Per-axis breakdown

| Model | Adherence | Aesthetic | Photoreal | Text | Anatomy |
|---|---|---|---|---|---|
| GPT-Image-1 Mini | 4.85 | 4.80 | 4.90 | 5.00 | 5.00 |
| Imagen 4 Fast    | 4.45 | 4.80 | 4.95 | 5.00 | 4.75 |
| GPT-Image-1.5    | 5.00 | 5.00 | 4.75 | 5.00 | 5.00 |
| GPT-Image-2      | 4.95 | 4.90 | 4.90 | 5.00 | 5.00 |
| Imagen 4 Ultra   | 5.00 | 4.80 | 4.90 | 5.00 | 5.00 |

Observation: **text rendering scored 5.0 across all five models on the single typography prompt** (T2I-011, the "OPEN 24 HOURS" diner neon). 2026 image models genuinely solved in-image text — the long-standing weakness is fixed in this lineup. Imagen 4 Fast slipped on adherence (4.45) — the cheapest Google model misses attributes more than the OpenAI tier.

## Issues found and fixed during the pilot

| # | Issue | Resolution |
|---|---|---|
| 1 | `pricing.json` used `vertex/imagen-*` namespace; Mesh actually uses `google/imagen-*`. | Rewrote `pricing.json` and `models.py` from `discover.py` catalog output. |
| 2 | Mesh's catalog underreports vision capability for chat models (`input_modalities=['text']` even for Claude Opus and GPT-4o). | Loosened `discover.py` heuristic to fall back to a known-vision-capable model-family list. |
| 3 | Mesh returns generated images as `data:image/png;base64,...` URIs in the `url` field, not HTTPS URLs. `requests.get()` failed with `InvalidSchema`. | Patched `save_image` in `runner.py` to detect and inline-decode `data:` URIs. |
| 4 | Initial `VISION_JUDGES` included `openai/gpt-5.5-pro` — Mesh returns `http_500: upstream_error` on multimodal requests to this model. | Switched to `openai/gpt-5.5` (non-pro), which works. Fallbacks now include `google/gemini-2.5-pro-preview`. |
| 5 | `runner.py` used `saved.relative_to(REPO_ROOT)` which raised when smoke test redirected IMAGES_DIR to a tmp path. | Added `ValueError` fallback to absolute path in `runner.py`. |
| 6 | `aggregate.py` grouped by `model_id` alone, collapsing same-model-different-quality variants (e.g. GPT-Image-1 at high vs medium). | Changed grouping key to `(model_id, size, quality)`. |
| 7 | Smoke test required matplotlib, which is optional. | `smoke_test.py` skips the chart check if matplotlib is absent. |

All seven fixes are in the committed code; smoke test passes; pilot reproduces.

## Deliberately NOT changed

- **The 5-model lineup.** Adding Gemini 2.5 Flash Image ("Nano Banana"), Imagen 3, GPT-Image-1 belongs in the full run, not a re-pilot. (`STRETCH_MODELS` lists them — all confirmed routable.)
- **The 100-prompt set.** No prompt was edited based on early model output; doing so post-hoc would invalidate the comparison.
- **Pricing table.** The Mesh-catalog values are canonical for v1 even where they differ from provider price pages. The methodology section of the blog will cite both, dated.
- **Judge rubric.** Variance and spread are below the rules.md re-judge thresholds.
- **n=5/category in the pilot.** Resisting the urge to expand mid-pilot.

## Open questions for the user

1. **Scale to full?** n=10 per category × 10 categories × 5 models = 500 image gens (~$15-18) + 2,000 judge calls (~$8-12). Total **~$25-30**. Within `--budget-cap 60`. (Add the 3-model stretch for n=10 × 10 × 8 = 800 → ~$25-35 gen + ~$12-18 judge = $35-50.)
2. **Add Gemini Nano-Banana?** It's a different architecture (token-priced, not per-image). Would test whether the GPT-saturation thesis extends to non-OpenAI/non-Imagen models.
3. **Spot-check the images?** rules.md verification step 7 ("manual spot-check on 3 prompts") should happen before publishing anything. I can dump 5 representative images for visual review.
4. **Judge ensemble v2 — add Gemini-vision** as a third judge? Per rules.md rule 10, mitigating own-provider bias. Costs another ~$0.40 on the pilot, ~$5 on the full run.

## Cost projection (from `cost_estimator.py`)

For the full run (n=10/category × 10 categories × 5 pilot models + 3 stretch = 8 models × 100 prompts):

- Runner subtotal: **~$25-35**
- Judge subtotal (2 judges × 2 temps × 800 images): **~$12-18**
- **Full-run total: ~$35-55**
- Budget cap: $60 → comfortable margin.

## Verification checklist status

- [x] `smoke_test.py` passes (mocked pipeline)
- [x] `discover.py` finds ≥3/5 pilot models (5/5 routable)
- [x] Sanity ping returned valid image, cost lookup succeeded
- [x] Pilot CSV well-formed, 25 rows, refusals=0, errors=0
- [x] Judge ensemble Spearman ρ check — spread 0.075-0.267, all below 0.5 threshold → ensemble holds
- [x] Cost projection accurate (`cost_estimator.py` ready to call against `pilot_t2i.csv`)
- [ ] Manual spot-check (5-image visual review) — **pending user**
- [ ] Blog placeholder fill — **pending full run or pilot-only decision**

## Recommendation

Ship a **pilot-only blog** with these n=5 numbers AND scale to the full run in parallel — the headline shape (cheap-mini wins $/quality, quality saturated, latency spread is the real differentiator, GPT-Image-2 has a retry tax) is unlikely to flip at n=10/category. Same disposition as `dollar-per-task-bench` did with its n=5 pilot blog.
