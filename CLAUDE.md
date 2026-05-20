# Handoff to Claude Code — dollar-per-image-bench

This benchmark kit is the **image-generation sibling** of `dollar-per-task-bench` (which lives one directory up). Same methodology principle (measured > estimated, pilot before scale, honest caveats), different domain.

The whole reason this folder exists: `dollar-per-task-bench` benchmarked five chat LLMs through Mesh API and surfaced four hidden taxes (Opus tokenizer inflation, Gemini hidden reasoning, GPT-5.5 reasoning ratio, quality saturation). The analogous question for image models — "which model is the best fit for which use case across cost, latency, quality, and capability, and what hidden taxes only show up at scale" — has no honest answer yet, and Mesh now routes image generation too.

---

## What's already done

- Folder scaffolding: `CLAUDE.md` (this), `plan.md`, `skill.md`, `rules.md`, stub `README.md`, `.env.example`, `.gitignore`, `LICENSE`
- Datasets:
  - `tasks/t2i_prompts.json` — 100 original text-to-image prompts across 10 HEIM-inspired categories (10 per category)
  - `tasks/edit_prompts.json` — 30 source+instruction pairs (used only if Mesh exposes `/v1/images/edits`)
- Pricing: `pricing.json` — dated table of `(model_id, size, quality) → $/image`, sourced from official provider price pages on 2026-05-20
- Code modules: `discover.py`, `runner.py`, `judge_vision.py`, `judge_auto.py`, `judge.py`, `aggregate.py`, `cost_estimator.py`, `smoke_test.py`, `make_charts.py`, `make_tables.py`
- Models list: `models.py` — candidate 5-model lineup with Mesh model IDs (assumed; confirmed by `discover.py`)
- Blog: `blog_post_draft.md` with `{{PLACEHOLDERS}}` that get filled from pilot/full-run CSVs

**Treat the scaffolding as fixed.** Don't rewrite `runner.py`, the judge rubric, or the aggregator math without checking with Raushan first. The pipeline is intentionally a near-mirror of `dollar-per-task-bench`'s shape so the chat-vs-image narrative stays comparable.

---

## What needs to happen here (run order)

```bash
# 0. Setup (once)
cd /Users/raushan/Documents/Career/AiFiesta/agenticExperiments/benchmarks_onMesh/dollar-per-image-bench
pip install openai pillow matplotlib pandas requests
cp .env.example .env
# Edit .env: set MESH_API_KEY (rotate from previous session — see Security below) and MESH_BASE_URL

# 1. Verify pipeline without spending money (~5s, no API calls)
python3 smoke_test.py

# 2. Discover what image models Mesh actually exposes (~1 free API call)
python3 discover.py
# This writes models_catalog.json and prints which of the 5 candidate models are routable.
# Also probes /v1/images/edits for editing support.

# 3. One-image sanity ping (~$0.01) — auth + pricing-table + image download
python3 -c "
import os
from runner import call_image_model, save_image
out = call_image_model(
    model='openai/gpt-image-1',
    prompt='a single red apple on a white background, photorealistic',
    size='1024x1024', quality='low'
)
print('Latency:', out['latency_ms'], 'ms')
print('Cost:', out['raw_cost_usd'], 'USD')
print('Saved:', save_image(out['image_url'], 'sanity_ping'))
"

# 4. Pilot run — 5 prompts × N models, T2I (~$2-4 total, ~5-10 min)
python3 runner.py --task tasks/t2i_prompts.json --out pilot_t2i.csv \
  --limit 5 --budget-cap 5

# (If Mesh supports /images/edits, also run:)
# python3 runner.py --task tasks/edit_prompts.json --out pilot_edit.csv \
#   --mode edit --limit 5 --budget-cap 3

# 5. Score
python3 judge.py --task tasks/t2i_prompts.json --runs pilot_t2i.csv --out judged_t2i.csv
# This calls judge_vision.py (Claude Opus 4.7 + GPT-5.5, 2 temps each)
# AND judge_auto.py (VQAScore + CLIPScore + aesthetic — local, free)

# 6. Aggregate
python3 aggregate.py --judged judged_t2i.csv --out pilot_results.csv

# 7. Show Raushan
cat pilot_results.csv
python3 cost_estimator.py --dryruns pilot_t2i.csv --target-n-per-category 10 --models-count 8
```

---

## Two open variables to resolve before running

These were guessed during scaffolding; confirm before the pilot:

1. **`MESH_BASE_URL`** — assumed `https://api.meshapi.ai/v1`. Same as the chat benchmark. Confirm with Raushan or Mesh dashboard.
2. **Vision-judge model IDs** — assumed `anthropic/claude-opus-4.7` and `openai/gpt-5.5` are both vision-capable through Mesh. Verify in `models_catalog.json` (look for `modalities.input` containing `"image"`). If GPT-5.5 isn't vision-capable through Mesh, fall back to `openai/gpt-4o` for the second judge slot.
3. **Image model IDs** — assumed `openai/gpt-image-1`, `vertex/imagen-3`, `vertex/imagen-4`. Mesh's docs only explicitly cite the first two. `discover.py` is the source of truth. **If fewer than 3 of the 5 candidates exist, stop and ask** — don't silently swap in alternatives.

---

## Security note

Always get a fresh Mesh API key from the Mesh dashboard. Never reuse a key across sessions, and never commit `.env`.

**One image-specific concern:** Mesh's `POST /v1/images/generations` returns a `url` (or `b64_json`). The signed URL **expires** — download immediately to `images/{model}_{prompt_id}.{ext}` and store the local path in the CSV. `runner.py` does this; don't disable it.

---

## After the pilot completes

Report to Raushan:

1. **Total actual spend** (sum `effective_cost_usd` in `pilot_results.csv`).
2. **Per-model quality score** on the 5 rubric axes, plus the auto-metric baseline (VQAScore + CLIPScore).
3. **Judge ensemble agreement** — Spearman ρ between Claude-vision and GPT-vision scores. If <0.5 on any axis, the rubric is ambiguous and we discuss before scaling.
4. **Hidden taxes observed** — any model that:
   - Refused prompts silently (returned an unrelated image or empty data)
   - Took >2× the median latency
   - Has a quality-tier multiplier that doesn't match the quality jump (e.g. `high` costs 4× `medium` but rates only 0.3 points higher)
   - Stamped a watermark on output (visual judge will mention it)
5. **Full-run projection** from `cost_estimator.py` (n=10/category × 8 models ≈ 800 calls + judge passes).

Then Raushan decides:

- Scale to full run (`--target-n-per-category 10`, hard cap `--budget-cap 60`), OR
- Ship a pilot-only blog with n=5 disclaimer (mirrors the chat benchmark's pilot-only first publish).

---

## When real results land

`blog_post_draft.md` has `{{PLACEHOLDERS}}` like `{{T2I_QUALITY_WINNER}}`, `{{T2I_COST_WINNER}}`, `{{REFUSAL_RATE_RANGE}}`, `{{QUALITY_TIER_INFLATION_PCT}}`, etc. Replace each one from the results CSVs. The structure is intentional — same TL;DR / hidden-tax / honest-caveats shape as the chat blog — so don't rewrite prose, just fill placeholders.

The 6-7 chart specs are inline as `[**Chart N: …**]` blocks. `make_charts.py` produces them. The 4-5 table PNGs come from `make_tables.py`.

---

## Things to flag, not silently fix

- **Mesh doesn't expose one of the 5 candidate models.** Stop and ask. The lineup is a deliberate spread across price/quality tiers.
- **A `(model, size, quality)` tuple is missing from `pricing.json`.** Hard error in `runner.py`. Stop, look up the price on the provider's site, add the entry with a source citation, then re-run. Never default to $0.
- **A model's response has no image data** (neither `url` nor `b64_json`). Could be content-policy refusal (flag in CSV as `refused=true`) or a Mesh bug (flag as `error`). Don't conflate them.
- **Judge variance (`quality_variance` column) > 0.7** on the 1-5 scale for any axis. The rubric is too ambiguous for that axis — discuss before publishing.
- **Pilot quality scores are suspiciously high (>4.5/5) or low (<2/5) across all models.** The judge prompt is probably wrong. Investigate before scaling up.
- **Judge ensemble disagreement (Spearman ρ < 0.5)** on any axis. Means our two vision LLMs see the rubric differently — fix the rubric or call it out in the blog.

---

## Don't do

- **Don't run the full 100-prompt benchmark on first contact.** Pilot first, always. Hard budget cap on the runner.
- **Don't add models that aren't routable through Mesh.** The whole point is that rate-limiting and billing are identical across the lineup. If FLUX isn't on Mesh, we **note that as a Mesh-coverage finding**, not silently fall back to fal.ai. (The chat benchmark made this exact discipline call and it paid off.)
- **Don't change `pricing.json` values without citing the source and date.** Every pricing-table edit gets a `_notes` line with provider URL and fetched date.
- **Don't include generated images in the public repo.** `images/` is gitignored. The blog embeds a hand-curated showcase (3-5 images per model, captioned) plus the chart PNGs.
- **Don't claim a quality finding from a single judge model.** Headline quality numbers always cite ensemble agreement or call out the divergence.

---

## Related files

- Upstream sibling: `../dollar-per-task-bench/` — the chat benchmark whose methodology this borrows.
- Plan file (this session): `/Users/raushan/.claude/plans/users-raushan-documents-career-aifiesta-jolly-hartmanis.md` — the original research/decision log.
