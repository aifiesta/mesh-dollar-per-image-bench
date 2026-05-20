# dollar-per-image-bench: cost vs quality (and the hidden taxes)

> **STATUS: pilot complete; v1 (n=10/cat × 12 cat × 5-8 models) in progress.** Full paper in [`paper.html`](paper.html) / [`paper.md`](paper.md). Pilot artifacts: `pilot_*.csv`, `judged_*.csv`, `images/`, `chart_*.png`, `table_*.png`.
>
> Sibling chat-LLM benchmark: [`aifiesta/mesh-bench-cost-vs-quality`](https://github.com/aifiesta/mesh-bench-cost-vs-quality).
> Index of public Mesh API benchmarks: [`aifiesta/mesh-benchmarks`](https://github.com/aifiesta/mesh-benchmarks).

A small, sharp, fully-reproducible benchmark across the image generation models routable through [Mesh API](https://meshapi.ai). One task (text-to-image), ten HEIM-inspired prompt categories, a five-axis vision-LLM ensemble rubric plus automatic metrics, and an explicit hunt for five hidden taxes that only show up at scale.

Sibling to [`../dollar-per-task-bench`](../dollar-per-task-bench/), which did the same thing for chat LLMs.

## What we're measuring

For every (model × prompt) pair, we capture:

- **Cost** — from a dated static pricing table (image endpoints don't return `usage`)
- **Latency** — wall-clock end-to-end, p50 and p95
- **Quality** — 5-axis rubric (prompt adherence, aesthetic, photorealism, text rendering, anatomy/artifacts) scored 1-5 by two vision LLMs at two temperatures each
- **Automatic prompt alignment** — VQAScore + CLIPScore + aesthetic predictor as a sanity baseline
- **Hidden taxes** — quality-tier inflation, resolution-multiplier honesty, content-policy refusal rate, watermark presence, retry tax

## The ten prompt categories

| # | Category | What it stresses |
|---|---|---|
| 1 | Photorealism / portrait | Face anatomy, skin, lighting |
| 2 | Typography | Latin-script in-image text glyph fidelity |
| 3 | Compositional / spatial | "Red cube left of blue sphere" |
| 4 | Multi-subject coherence | Two+ named subjects, distinct attributes |
| 5 | Style transfer / artistic | "Watercolor", "polaroid", "Ghibli" |
| 6 | Long prompt fidelity | 100+ words, 5+ attributes |
| 7 | Knowledge / world facts | Specific landmarks, named places |
| 8 | Counting / numerical | "Exactly four apples" |
| 9 | Negative space / minimalism | "Single line, lots of empty space" |
| 10 | Edge cases / policy | Brand-adjacent, NSFW-boundary, watermark-prone |
| 11 | **Multilingual** | Non-Latin script rendering (Devanagari, Chinese, Arabic, Japanese, Cyrillic, Hangul, Greek, Hebrew, Thai, accented Spanish) + cultural context |
| 12 | **Hyper-complex** | Boss-fight prompts: 10+ named entities in named positions, counts, in-image text, scene-knowledge simultaneously |

120 prompts total, 10 per category. Written from scratch (no copy from PartiPrompts/DrawBench/GenAI-Bench/HEIM — only structural inspiration) to limit training-set contamination.

## Pilot results

_Will be filled in from `pilot_results.csv` after the pilot run._

| Model | Quality (1-5) ± var | Auto alignment (VQA) | $/image (effective) | $/quality-point | p50 latency | p95 latency | Refusal rate |
|---|---|---|---|---|---|---|---|
| TBD | | | | | | | |

## The five hidden taxes (the punchline section)

_Will be filled in from real numbers after the pilot._

1. **Quality-tier inflation** — does `quality: "high"` actually look 4× better than `"medium"`, given it costs ~4×? **TBD**
2. **Resolution multiplier honesty** — does `1024×1536` cost 1.5× `1024×1024`, or 2-3× via pixel-count billing? **TBD**
3. **Refusal rate** — fraction of edge-case prompts each model silently refuses or rewrites. **TBD**
4. **Watermark presence** — which providers stamp generations and how visibly. **TBD**
5. **Retry tax** — do retried-after-rate-limit calls still get billed? **TBD**

## What's in this folder

| File | Purpose |
|---|---|
| `CLAUDE.md` | Handoff/work-log for the Claude Code session running this benchmark |
| `plan.md` | Living implementation plan |
| `skill.md` | Reusable image-bench playbook (taxonomy + rubric + pricing format + judge prompt) |
| `rules.md` | Non-negotiable guardrails (never/always list) |
| `tasks/t2i_prompts.json` | 120 prompts × 12 categories (incl. multilingual + hyper-complex) |
| `tasks/edit_prompts.json` | 30 source+instruction pairs (if Mesh exposes /images/edits) |
| `pricing.json` | Dated `(model, size, quality) → $/image` table |
| `models.py` | Candidate MODELS list |
| `discover.py` | GET /v1/models, filter image-output, probe /v1/images/edits |
| `runner.py` | Hits Mesh /v1/images/generations per (model, prompt); downloads image; CSV per call |
| `judge_vision.py` | Claude-vision + GPT-vision ensemble judge (5 axes, 2 temps) |
| `judge_auto.py` | VQAScore + CLIPScore + aesthetic predictor (local, free) |
| `judge.py` | Orchestrator — joins vision + auto scores |
| `aggregate.py` | Per-model summaries with hidden-tax columns |
| `cost_estimator.py` | Dry-run cost projection |
| `smoke_test.py` | Mocked-Mesh end-to-end pipeline check |
| `make_charts.py` | Renders the chart PNGs |
| `make_tables.py` | Pricing / headline / latency table PNGs |
| `pilot_t2i.csv`, `judged_t2i.csv`, `pilot_results.csv` | Pilot artifacts (regenerated by running) |
| `blog_post.md`, `x_article.md` | Public write-ups |

## Reproduce in 5 minutes

```bash
# 1. Install
pip install openai pillow matplotlib pandas requests
# For automatic metrics (optional, slow first install):
# pip install open_clip_torch t2v-metrics

# 2. Configure
cp .env.example .env
# Edit .env: set MESH_API_KEY and MESH_BASE_URL=https://api.meshapi.ai/v1

# 3. Verify (no API calls)
python3 smoke_test.py

# 4. Discover routable image models (~1 free API call)
python3 discover.py

# 5. Sanity ping (~$0.01)
python3 -c "
import os
from runner import call_image_model, save_image
out = call_image_model(model='openai/gpt-image-1',
    prompt='a single red apple on a white background, photorealistic',
    size='1024x1024', quality='low')
print('OK in', out['latency_ms'], 'ms, $', out['raw_cost_usd'])
save_image(out['image_url'], 'sanity_ping')
"

# 6. Pilot (5 prompts × N models, ~$2-4 total)
python3 runner.py --task tasks/t2i_prompts.json --out pilot_t2i.csv \
  --limit 5 --budget-cap 5

# 7. Score and aggregate
python3 judge.py --task tasks/t2i_prompts.json --runs pilot_t2i.csv --out judged_t2i.csv
python3 aggregate.py --judged judged_t2i.csv --out pilot_results.csv
python3 make_charts.py
```

## Cost projection

| Phase | Calls | Estimated $ |
|---|---|---|
| Discover + sanity ping | 2 | <$0.05 |
| Pilot (T2I) | 25 | $2-4 |
| Pilot judging (vision ensemble) | 100 | $0.50-1.50 |
| Full run (T2I, n=10/category × 8 models) | 800 | $15-35 |
| Full judging | 3,200 | $8-18 |
| **Pilot total** | ~125 | **$3-6** |
| **Full total** | ~4,000 | **$25-55** |

Budget enforced by `--budget-cap` on `runner.py` (hard stop mid-run).

## Methodology in one paragraph

Every call uses the same prompt, the same size (`1024x1024` default), the same `n=1`, and the same deterministic seed where the model supports it. Cost comes from `pricing.json` — a static `(model, size, quality) → $/image` table dated 2026-05-20, sourced from each provider's official pricing page (no token-estimation; image endpoints don't return `usage`). Quality is scored by an ensemble of two vision LLMs (Claude Opus 4.7-vision + GPT-5.5-vision), each at temperature 0.0 and 0.3, on five 1-5 axes (prompt adherence, aesthetic, photorealism/on-style, text fidelity, anatomy/artifacts). Variance between the two passes is reported alongside the score. Automatic metrics (VQAScore + CLIPScore + aesthetic predictor) run locally for free as a sanity baseline. Latency is end-to-end wall-clock (includes network + Mesh routing + provider queue + inference), reported as p50 and p95. Content-policy refusals are tracked as a separate bucket from passes/fails. The five hidden taxes (quality-tier inflation, resolution multiplier honesty, refusal rate, watermark presence, retry tax) each get a dedicated column in `pilot_results.csv` and a paragraph in the blog.

## What this benchmark deliberately does not cover

- **Latency is end-to-end wall-clock, not isolated inference time.** Includes network + Mesh routing + provider queue. To break these apart you need server-side telemetry or direct-to-provider calls; neither is in scope.
- **n=5/category in the pilot, n=10/category in the full.** Big enough to surface headline gaps, not big enough for tight confidence intervals.
- **Models that aren't on Mesh aren't in the lineup.** If Mesh doesn't expose FLUX, Midjourney, Recraft, etc., that's a Mesh-coverage finding, not a model gap we paper over with a direct-provider fall-back.
- **Two-judge ensemble, not human eval.** v2 may add a 50-prompt human-rated calibration set if ensemble agreement turns out poor.
- **Single seed per (model, prompt).** No "best of 4" — variance is part of the story.
- **No upscaling, no post-processing, no LoRAs.** Stock model output only.
- **Single region, single time-of-day, single run.** No confidence intervals; provider throttling and queue depth vary by hour.
- **No video, no 3D, no audio.** Separate benchmarks.

## License

**MIT License.** Datasets, scripts, prompts, and raw CSVs are free to use, modify, and republish — including commercially. Copyright © 2026 Fiesta Labs Inc. Attribution appreciated, not required.

## Roadmap

- **v1** — n=10/category × ~8 models, full hidden-tax breakdown, published blog with charts and showcase gallery.
- **v2** — add image editing (if Mesh ships `/v1/images/edits`), add a 50-prompt human calibration set, add p99 latency, add 2-3 more models if Mesh expands its image-output catalog.

## Contributing

If you run this against a different model lineup (different Mesh-routable models, or your own direct-provider configuration) and get different numbers, please open an issue with the CSVs and we'll fold corrections into v2. PRs welcome for: additional models (only if Mesh-routable), additional prompt categories, judge-prompt improvements that boost ensemble agreement, automatic-metric upgrades.
