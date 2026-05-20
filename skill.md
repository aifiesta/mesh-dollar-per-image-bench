---
name: image-bench
description: Build cost-vs-quality benchmarks for image generation models routed through a unified gateway (Mesh API, fal.ai, etc.). Includes a 10-category HEIM-inspired prompt taxonomy, a 5-axis vision-LLM ensemble judge rubric, an automatic-metric stack (VQAScore + CLIPScore + aesthetic), a pricing-table format, and the pilot→scale→publish workflow. Use it when measuring image models head-to-head for cost, latency, prompt adherence, aesthetic quality, photorealism, text rendering, anatomy/artifacts, refusal rates, and watermark presence.
---

# image-bench skill — the reusable playbook

This skill captures the methodology behind `dollar-per-image-bench` so the next image benchmark (different gateway, different model set, different audience) can be assembled fast without re-deriving the rubric or the pricing-table format.

## When to use this skill

- You're comparing two or more text-to-image models head-to-head and want numbers, not vibes.
- You care about cost-per-quality at scale, not single-image curation.
- You're routing through a unified gateway (Mesh, fal.ai, Replicate, OpenRouter) and want apples-to-apples billing and rate-limiting.
- You want the output to be a small, sharp, fully-reproducible blog post in the style of `dollar-per-task-bench`.

## When NOT to use this skill

- You only need 5 generations from each of 3 models — just eyeball them.
- You're doing safety/red-team evaluation — different rubric, different prompt set.
- You're benchmarking video, 3D, or audio generation. Use a different skill.

---

## 1. Prompt taxonomy — 10 categories × 10 prompts each

Each category targets a known failure mode. The full set spans the buyer's actual decision space: not just "is the picture pretty" but "does the model parse my prompt, render the text I asked for, count things correctly, and not stamp a watermark on it."

| # | Category | Tests | Why it earns its own bucket |
|---|---|---|---|
| 1 | Photorealism / portrait | Face anatomy, skin texture, lighting consistency | Anatomy bugs (hands, eyes, teeth) are the canonical failure mode |
| 2 | Typography / in-image text | Glyph fidelity at sentence length | 2026 differentiator — most models still botch ≥5-word phrases |
| 3 | Compositional / spatial | "Red cube left of blue sphere" | Cleanest separator between top models in GenAI-Bench |
| 4 | Multi-subject coherence | Two+ named subjects with distinct attributes | Where prompt parsing falls apart |
| 5 | Style transfer / artistic | "Watercolor", "1970s polaroid", "studio Ghibli" | Cheap models collapse to a generic AI aesthetic here |
| 6 | Long prompt fidelity | 100+ words, 5+ attributes per subject | Tests prompt-parsing depth |
| 7 | Knowledge / world facts | "Trocadéro view of the Eiffel Tower at sunset" | HEIM's knowledge aspect; catches generic-landmark hallucination |
| 8 | Counting / numerical | "Exactly four apples on a wooden table" | Notoriously hard — GenAI-Bench's hardest axis |
| 9 | Negative space / minimalism | "Single black line on white background, lots of empty space" | Catches over-busy aesthetic bias and signature artifacts |
| 10 | Edge cases / policy | Brand-adjacent, copyrighted-character-adjacent, NSFW-boundary | Surfaces content-policy refusal rates as a real product axis |

### Prompt schema

```json
{
  "id": "T2I-008",
  "category": "counting",
  "prompt": "Exactly four red apples arranged in a square on a wooden kitchen table, soft morning light, photorealistic",
  "eval_focus": ["count=4", "color=red", "arrangement=square", "lighting=soft morning"],
  "vqa_questions": [
    "Are there exactly four apples in the image?",
    "Are the apples red?",
    "Are they arranged in a square pattern?",
    "Is there a wooden table?"
  ],
  "negative_prompt": null,
  "has_text_to_render": false
}
```

`vqa_questions` are consumed by `judge_auto.py` for VQAScore.

### Authorship discipline

Write prompts from scratch. Don't lift from PartiPrompts/DrawBench/GenAI-Bench — only borrow the *structure* (one-sentence prompt, multiple attribute axes, one named failure mode per item). Originality matters because training-set contamination is a real worry; the prompts you write today will be in tomorrow's training data.

---

## 2. Quality rubric — 5 axes × 1-5 scale

Two vision LLMs (Claude Opus 4.7-vision + GPT-5.5-vision) rate every generated image on five axes. Each axis is integer 1-5 (no half-points) so JSON parsing doesn't choke and aggregation is straightforward.

| Axis | Score 1 | Score 3 | Score 5 |
|---|---|---|---|
| **Prompt adherence** | Image ignores most of the prompt | Image gets the gist; misses some attributes | Every named attribute is present, correctly placed |
| **Aesthetic quality** | Unappealing, muddy, generic | Acceptable; competent but bland | Striking composition, polished, professional |
| **Photorealism / on-style** | Fails the requested style entirely | Approximate; some uncanny edges | Style is convincing; on-style for photo prompts means no AI tell-tales |
| **Text fidelity** (only if `has_text_to_render`) | Garbled glyphs or missing entirely | Some words readable, others not | Every word rendered correctly, kerning natural |
| **Anatomy & artifacts** | Major errors (extra fingers, melted faces, jpg compression) | Minor visible issues | Anatomically clean, no visible artifacts |

Per-axis "N/A" is allowed (text axis on a prompt with no text, anatomy axis on a pure abstract). N/A axes drop out of the per-image mean.

### Judge JSON output schema

```json
{
  "adherence": 4,
  "aesthetic": 5,
  "photoreal": 5,
  "text": "N/A",
  "anatomy": 4,
  "note": "Strong composition; left hand has slight knuckle blur but not glaring."
}
```

The `note` field is for human auditing only — not used in numeric aggregation.

### Two-temperature variance trick

Run each judge at temperature 0.0 and 0.3. The spread between the two passes is the per-axis judge variance, and it's reported alongside the score so the reader knows whether a 0.2-point gap between models is meaningful.

### Ensemble

Two judges (Claude + GPT) × two temps = four scores per (image, axis). The headline `quality_score` is the mean of all valid axes across all four passes. Disagreement between the two judges (Spearman ρ < 0.5 across the dataset on any axis) is treated as a rubric bug, not a judge bug — we rewrite the rubric and re-run.

---

## 3. Automatic-metric stack

Cheap, deterministic, runs locally. Used as a baseline to sanity-check the vision LLMs.

| Metric | What it measures | How |
|---|---|---|
| **VQAScore** | Prompt alignment (compositional, attribute-binding) | `t2v_metrics` library; generates 5-10 yes/no questions per prompt, runs a VQA model (Gecko or Qwen3-VL backbone), averages the "yes" probabilities |
| **CLIPScore** | Text-image cosine similarity (coarse alignment) | `open_clip` library; encode prompt and image, take cosine similarity. Fast but known to mis-rank compositional prompts |
| **Aesthetic predictor** | Visual appeal (LAION-style) | Regression head over CLIP image embeddings, predicts a 1-10 aesthetic score |

These are reported in `judged_*.csv` as separate columns. **They are not part of the headline quality score** — they serve as a sanity check that the vision LLM judges aren't completely off, and as a free way to extend the benchmark to thousands of prompts later.

---

## 4. Pricing-table format

```json
{
  "openai/gpt-image-1": {
    "1024x1024": { "low": 0.011, "medium": 0.042, "high": 0.167 },
    "1024x1536": { "low": 0.016, "medium": 0.063, "high": 0.250 },
    "1536x1024": { "low": 0.016, "medium": 0.063, "high": 0.250 },
    "_source": "https://openai.com/api/pricing",
    "_fetched": "2026-05-20",
    "_notes": "Token-based hybrid; numbers reflect ~standard token counts for 1024² outputs."
  },
  "vertex/imagen-4": {
    "1024x1024": { "fast": 0.02, "standard": 0.04, "ultra": 0.06 },
    "_source": "https://cloud.google.com/vertex-ai/generative-ai/pricing",
    "_fetched": "2026-05-20"
  },
  "_metadata": {
    "fetched_date": "2026-05-20",
    "currency": "USD",
    "version": 1
  }
}
```

### Rules

- Every model entry has `_source` (URL of the provider's official price page) and `_fetched` (ISO date).
- Missing `(model, size, quality)` tuple = **hard error** in the runner. Never default to $0 or to a sibling tuple.
- When updating pricing, bump `_metadata.version` and `_fetched` on the affected entries. Old prices stay in git history for reproducibility.

---

## 5. Judge prompt template

```text
SYSTEM:
You are an expert image evaluator. Rate the generated image against the prompt on a 1-5 integer scale across five axes. Use "N/A" only when an axis is genuinely inapplicable. Return strict JSON in the exact schema below — no commentary, no markdown, no code fence.

Schema: {"adherence": int|N/A, "aesthetic": int|N/A, "photoreal": int|N/A, "text": int|N/A, "anatomy": int|N/A, "note": string}

Anchors:
- adherence: 1 = ignores most of prompt; 3 = gets the gist, misses attributes; 5 = every named attribute correct
- aesthetic: 1 = muddy/generic; 3 = competent but bland; 5 = striking, polished
- photoreal: 1 = fails requested style; 3 = approximate, uncanny; 5 = style is convincing
- text: 1 = garbled/missing (only if prompt asks for in-image text); 5 = every word correct
- anatomy: 1 = major errors (extra fingers, melted faces); 3 = minor; 5 = clean

USER:
[IMAGE ATTACHED]

Prompt the image was generated for:
"{prompt}"

Evaluation focus the prompt author flagged:
{eval_focus}

Return only the JSON.
```

---

## 6. Failure modes to expect

| Failure | Detection | Handling |
|---|---|---|
| Content-policy refusal | Response has no image data OR has a different image than asked | Mark `refused=true` in CSV; don't count toward pass/fail |
| Mesh signed-URL expiry | Download fails after >5 min | Download immediately after generation; store local path in CSV |
| Malformed judge JSON | Parser raises | Retry once; if still malformed, log and set scores to null (not 0) |
| Rate limit 429 | HTTP status | Exponential backoff, track retries in CSV; retry tax goes into cost |
| Watermark on output | Vision judge mentions "watermark" in note OR image hash matches known-watermark prefix | Flag in CSV `watermark=true`; surfaces in blog hidden-tax section |
| Cold start latency spike | First call to a model is 3-5× the rest | Discard first call from latency aggregates; report it separately |
| Truncated long prompts | Visible in response metadata (some providers expose `prompt_truncated`) | Flag in CSV; affects long-prompt category fairness |

---

## 7. Cost model

```
effective_cost_per_image
  = pricing[model][size][quality]
  × (1 + retry_rate_for_model)
```

Aggregate-level columns in `pilot_results.csv`:

- `raw_cost_usd` — sum of per-image billed costs
- `effective_cost_usd` — raw × (1 + retry_rate) [the retry tax]
- `cost_per_quality_point` — effective_cost / quality_score (headline cross-model number)
- `cost_per_unrefused_image` — effective_cost / (1 − refusal_rate) (content-policy tax)

No `usage` field. No token estimation. The static table is canonical, period.

---

## 8. Pilot-first protocol

Hard rule: never run a full benchmark on first contact.

1. **Smoke test** — pipeline end-to-end with mocked responses. No network.
2. **Discover** — `GET /v1/models`, filter to image-output. Verify candidate models exist.
3. **Sanity ping** — 1 cheap image. Verifies auth + pricing lookup + image download.
4. **Pilot** — n=5/category × N models, budget cap enforced. Surfaces all the bugs.
5. **Cost project** — extrapolate full-run cost from pilot.
6. **User checkpoint** — show pilot results; decide scale or ship pilot-only.
7. **Full run** — n=10/category × N models, higher budget cap, can be parallelized.
8. **Blog** — fill the draft from results CSVs.

Budget caps are enforced inside `runner.py`, not in a wrapper. The runner stops mid-run if cumulative spend hits the cap, writes whatever it has, and exits non-zero.

---

## 9. Output structure (the blog)

A `dollar-per-task-bench`-style write-up:

- Opening caveat (one run, n=5 or n=10, reproducible not universal)
- TL;DR — 4-5 headline numbers with one-line context each
- What we ran — lineup, prompts, gateway
- Headline table (model × cost-per-quality × quality-by-category)
- **5 hidden taxes** section — one paragraph each
- Latency table (p50 / p95)
- Decision rules ("default to X, switch to Y if you need text, never use Z for compositional")
- Deliberate exclusions
- Reproduce-in-5-minutes section

Plus a Twitter/X thread version and a hand-curated showcase gallery (3-5 images per model, captioned).

---

## 10. Anti-patterns (things to avoid)

- **"Best of 4" generation** — never pick the best of N generations. Single seed per (model, prompt). Variance is part of the quality story.
- **Cherry-picked showcase** — the gallery shows representative outputs (median + one bad + one good), not curated highlights.
- **Judge running on its own outputs** — never use a judge whose family/provider also appears in the lineup as a quality-rated model. Avoid via the two-judge ensemble.
- **Token-estimated cost** — image endpoints don't bill on tokens. If a number traces back to a tokenizer, it's wrong.
- **Silent model substitution** — if the gateway doesn't expose your lineup, flag it. Don't swap in alternatives without re-checking with the user.
