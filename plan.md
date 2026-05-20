# plan.md — dollar-per-image-bench implementation plan

> Living plan, scoped to this folder. The original research+decision log is at `/Users/raushan/.claude/plans/users-raushan-documents-career-aifiesta-jolly-hartmanis.md`. This file is the actionable checklist.

## One-paragraph summary

Build a `dollar-per-task-bench`-shaped benchmark for image generation models routed through Mesh API. Mirror the chat benchmark's pipeline (tasks → runs → judge → aggregate → charts → blog) and discipline (pilot-first, measured numbers, hard budget caps, honest caveats). Differ from the chat benchmark in three places: (1) no `usage` field in image responses, so cost comes from a dated static pricing table; (2) two judge models instead of one (vision LLM ensemble) plus automatic metrics (VQAScore / CLIPScore / aesthetic) from day 1; (3) prompt taxonomy spans 10 HEIM-inspired categories instead of two task domains.

## Goal

Answer, with measured numbers: **which image model is the best fit for which use case across cost, latency, quality, and capability — and what hidden taxes (quality-tier inflation, resolution multipliers, content-policy refusals, watermarks, retries) only show up at scale?**

## Non-goals

- Comparing models that aren't routable through Mesh (no fall-back to fal.ai / Replicate / direct providers).
- Video generation. Out of scope for v1.
- Fine-tuning, LoRA, or any custom-checkpoint comparison.
- Time-to-first-byte streaming latency unless Mesh exposes SSE for image gen (the docs note `stream: true` is supported).
- Confidence intervals from a single run — pilot is n=5/category, full is n=10/category, neither is a 1000-prompt random sample.

---

## Execution checklist

### Phase 0 — Scaffolding (no API calls, free)

- [x] Create folder `dollar-per-image-bench/` with `tasks/`, `images/` subdirs
- [x] Write `CLAUDE.md` — handoff/work-log
- [x] Write `plan.md` — this file
- [ ] Write `skill.md` — reusable image-bench playbook (taxonomy + rubric + pricing format + judge prompt)
- [ ] Write `rules.md` — guardrails (never/always list)
- [ ] Write stub `README.md` — fill in after pilot lands
- [ ] Write `.env.example`, `.gitignore`, `LICENSE` (MIT)

### Phase 1 — Datasets (no API calls)

- [ ] `tasks/t2i_prompts.json` — 100 prompts (10 per category × 10 categories)
  - Categories: photorealism/portrait, typography, compositional/spatial, multi-subject, style, long-prompt, knowledge, counting, negative-space, edge-case
  - Schema per item: `{id, category, prompt, eval_focus, vqa_questions, optional_negative_prompt, has_text_to_render}`
- [ ] `tasks/edit_prompts.json` — 30 pairs (only used if `discover.py` confirms `/v1/images/edits`)
  - 3 sub-buckets: object insertion/removal (10), style edit (10), region inpainting (10)
- [ ] `pricing.json` — dated table, sourced from official provider price pages on 2026-05-20
  - At minimum: `openai/gpt-image-1` (low/medium/high × 3 sizes), `vertex/imagen-3` and `vertex/imagen-4` (fast/standard/ultra × 1024²)
  - Each entry: `{$/image, _source, _fetched_date}`. Missing tuple = hard error in runner.
- [ ] `models.py` — `MODELS` list, 5 candidates, format `(mesh_id, display_name, default_size, default_quality)`

### Phase 2 — Code modules (no API calls)

- [ ] `discover.py` — GET `/v1/models` → filter image-output → write `models_catalog.json`. Probe `/v1/images/edits` with a HEAD/OPTIONS to detect edit support.
- [ ] `runner.py` — POST `/v1/images/generations` per (model, prompt), wall-clock, download image, lookup cost, write CSV row. Hard budget cap. Detects content-policy refusal as a third category beside success/error.
- [ ] `judge_vision.py` — Claude-vision + GPT-vision, 2 temps each, 5-axis 1-5 rubric, strict JSON output.
- [ ] `judge_auto.py` — VQAScore (`t2v_metrics`), CLIPScore (`open_clip`), aesthetic predictor (LAION). All local, no API cost.
- [ ] `judge.py` — orchestrator. Joins vision + auto scores onto one judged CSV.
- [ ] `aggregate.py` — per-model summary with the 5 hidden-tax columns.
- [ ] `cost_estimator.py` — dry-run projection (n_pilot × multiplier → full-run cost).
- [ ] `smoke_test.py` — replays mocked Mesh responses through the entire pipeline. No network.
- [ ] `make_charts.py` — 6-7 chart PNGs from `pilot_results.csv`.
- [ ] `make_tables.py` — 4-5 table PNGs (pricing, headline, latency, refusal rates, hidden taxes).

### Phase 3 — Validation (mostly free)

- [ ] Run `smoke_test.py` — verify pipeline end-to-end with no API calls.
- [ ] Run `discover.py` — verify Mesh exposes ≥3 of 5 candidate models. List the rest.
- [ ] Sanity ping — 1 cheap image (~$0.01), confirms auth + pricing lookup + image download.

### Phase 4 — Pilot ($2-10)

- [ ] `runner.py --limit 5 --budget-cap 5` on `t2i_prompts.json` (5 prompts × N models)
- [ ] If edit support: same command on `edit_prompts.json`
- [ ] `judge.py` on the pilot CSVs (vision ensemble + auto metrics)
- [ ] `aggregate.py` → `pilot_results.csv`
- [ ] Write `pilot_report.md` (issues found, decisions made, what was flagged)
- [ ] `cost_estimator.py` → full-run projection
- [ ] **User decision point**: scale to full or ship pilot-only

### Phase 5 — Full run (if approved, $25-60)

- [ ] `runner.py --limit 10 --budget-cap 60` — 100 prompts × N models
- [ ] Same judge + aggregate
- [ ] `make_charts.py`, `make_tables.py`
- [ ] Fill `blog_post_draft.md` → `blog_post.md`
- [ ] Render `blog_post.html`
- [ ] Write `x_article.md`

---

## Key design decisions (locked in)

1. **Mesh API as the single routing layer.** No fallback to direct providers or other gateways. If a model isn't on Mesh, it's not in the lineup — that's a Mesh-coverage finding, not a methodology gap.
2. **Static pricing table, not response-based cost.** Image endpoints don't return `usage`. Cost lookup keyed on `(model_id, size, quality)`. Missing tuple = hard error.
3. **Two-judge ensemble from day 1.** Claude Opus 4.7-vision + GPT-5.5-vision, two temperatures each (0.0 and 0.3). Addresses own-output bias up front.
4. **Automatic metrics alongside, not instead of.** VQAScore + CLIPScore + aesthetic as a cheap sanity baseline; vision LLM rubric for the subjective axes.
5. **HEIM-inspired 10-category prompt taxonomy.** Not a copy of any single benchmark — original prompts modeled on PartiPrompts / DrawBench / GenAI-Bench structure.
6. **5 hidden taxes hunted explicitly.** Quality-tier inflation, resolution multiplier honesty, refusal rate, watermark presence, retry tax. Each gets its own column in `pilot_results.csv` and its own paragraph in the blog.
7. **Pilot-first.** n=5/category pilot before any scale decision. Hard budget cap on runner.
8. **Images are not committed.** `images/` is gitignored. Blog embeds a hand-curated showcase only.

---

## Where we mirror dollar-per-task-bench vs. where we diverge

| Aspect | Chat benchmark | Image benchmark | Why diverge |
|---|---|---|---|
| Routing | Mesh API | Mesh API | Same |
| Cost source | `usage` field | static `pricing.json` | Image APIs don't return usage |
| Judge | 1 model (Opus), 2 temps | 2 models (Opus + GPT-5.5), 2 temps each | Image quality is more subjective; ensemble up front |
| Automatic metric | None (programmatic test runner only) | VQAScore, CLIPScore, aesthetic | Programmatic tests don't exist for images |
| Tasks | 2 (code, support) | 1 (T2I) + optional (edit) | Image gen is one task with 10 sub-categories |
| Prompts | 30 each (5 in pilot) | 100 total (50 in pilot) | More categories require more breadth |
| Hidden taxes | 4 (tokenizer, reasoning, accuracy, saturation) | 5 (quality-tier, resolution, refusal, watermark, retry) | Different domain, different leaks |
| Latency metric | wall-clock | wall-clock + p95 | Image gen has fatter tail |
| Lineup size | 5 | 5 in pilot, 8 in full | Image landscape has more meaningful tiers |
| Output | blog + x thread | blog + x thread + showcase gallery | Visual benchmark warrants a gallery |

---

## Verification checklist (from the approved plan)

- [ ] `smoke_test.py` passes — mocked pipeline end-to-end without network.
- [ ] `discover.py` finds ≥3 of 5 candidate models. If fewer, re-pick lineup with user.
- [ ] Sanity ping returns a valid image, downloads, costs as expected.
- [ ] Pilot CSV is well-formed: 25-50 rows, required columns non-null, refusals flagged.
- [ ] Judge ensemble Spearman ρ > 0.5 across all 5 axes. If lower, rewrite rubric.
- [ ] Cost projection accurate within ~30% when re-checked against pilot.
- [ ] Manual spot-check on 3 prompts — judge scores defensible.
- [ ] `grep "{{" blog_post.md` returns nothing before publishing.

---

## Budget envelope

| Phase | Calls | $ |
|---|---|---|
| Discover + sanity ping | 2 | <$0.05 |
| T2I pilot (5 prompts × ~5 models) | 25 | $2-4 |
| T2I pilot judging | 100 | $0.50-1.50 |
| Edit pilot (if available) | 25 | $1-3 |
| Edit judging | 100 | $0.50-1.50 |
| **Pilot total** | ~250 | **$4-10** |
| T2I full (100 prompts × 8 models) | 800 | $15-35 |
| T2I full judging | 3,200 | $8-18 |
| **Full total** | ~4,000 | **$25-55** |

Hard caps: `--budget-cap 15` for pilot, `--budget-cap 60` for full. The runner stops mid-run if cumulative spend hits the cap.

---

## Open questions (deferred to in-line decisions)

- Should the editing pilot run in the same pass as the T2I pilot, or as a follow-up? **Default: same pass, gated on `discover.py` confirming `/v1/images/edits`.**
- Add a 20-prompt human-rated calibration set? **Default: defer to v2 unless judge ensemble agreement is poor (Spearman ρ < 0.5).**
- Lineup size for full run? **Default: 5 in pilot, 8 in full if Mesh exposes enough.**
