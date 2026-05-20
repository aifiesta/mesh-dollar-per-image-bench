# rules.md — non-negotiable guardrails for dollar-per-image-bench

These are the "stop the line" rules. Violating any of them invalidates a number, a chart, or the entire blog. Read before every run.

---

## Cost rules

1. **Never estimate cost from token counts.** Image endpoints don't return `usage`. Cost is always a lookup in `pricing.json` keyed on `(model_id, size, quality)`.
2. **Never default to $0 on a missing pricing tuple.** Hard error in `runner.py`. Stop, look up the official price, add the entry with a `_source` URL and `_fetched` date, then re-run.
3. **Never change a price in `pricing.json` without citing the source.** Every edit bumps `_fetched` on the affected entry. Old prices remain in git history.
4. **Never run any benchmark without an explicit `--budget-cap`.** The runner enforces a hard ceiling. If the flag is missing, runner exits non-zero with a usage error.
5. **Never silently absorb a retry into cost.** Retries get their own column (`n_retries`) and feed into the retry-tax multiplier. The blog reports `cost_per_image` two ways: raw and effective (with retry tax).

## Routing rules

6. **Never fall back to a direct provider when Mesh doesn't expose a model.** The whole point of routing through Mesh is identical billing and rate-limiting across the lineup. If FLUX isn't on Mesh, it's not in the lineup. That gap becomes a *finding* in the blog ("Mesh-coverage limitation"), not a methodology silently patched.
7. **Never silently swap in an alternative model.** If the candidate lineup loses a model, stop and ask. The lineup is a deliberate price/quality spread.
8. **Never call a model from outside Mesh** unless explicitly approved by the user (and then it's flagged in the CSV with `via=direct`, not Mesh).

## Judging rules

9. **Never publish a quality finding from a single judge model.** Headline quality numbers cite ensemble agreement (Claude + GPT, two temps each = 4 passes). If the two judges disagree (Spearman ρ < 0.5 on an axis), that's a rubric bug — rewrite the rubric, re-judge, don't ship.
10. **Never use a judge from the same provider family as a benchmarked model** for the column scoring that model. (E.g., GPT-vision shouldn't be the *only* judge for GPT-image outputs.) The two-judge ensemble structurally avoids this; don't collapse it back to one.
11. **Never treat judge variance > 0.7 as a signal.** That's noise. Either re-judge with a sharper rubric or drop the axis.
12. **Never round or "fix" judge scores.** If the judge returned a 3 and we think it should be a 4, that's a rubric problem, not a number-fudging problem.

## Content-policy rules

13. **Never count a content-policy refusal as a pass or a fail.** It's a third bucket. Refusal rate is its own headline number.
14. **Never retry a refused prompt with a "softened" version.** That's not the model's real behavior at scale. Refusal is the data point.
15. **Never publish a generated image that violates a model's terms.** The blog gallery is hand-curated; anything sketchy gets cut.

## Image artifact rules

16. **Always download a generated image immediately after the API call.** Mesh signed URLs expire. CSV stores the local path, not the URL.
17. **Never commit generated images to the public repo.** `images/` is in `.gitignore`. The blog embeds a hand-picked gallery (3-5 images per model, captioned).
18. **Always preserve image metadata** — generated file is named `{model}_{prompt_id}_{seed}.{ext}` with no rewriting, no upscaling, no post-processing.
19. **Always detect watermarks** — visual judge flags them in `note`, image hash flags known watermark headers. Watermark presence is a column in `pilot_results.csv`.

## Scaling rules

20. **Never run the full benchmark on first contact.** Pilot first. Always. Hard-coded in the runner: `--limit` flag is required.
21. **Never scale past `--budget-cap 60`** without explicit user approval. The full-run projection is shown to the user before the scale-up call.
22. **Never extend the lineup mid-run.** If a new model gets added, it gets the full prompt set, not just the remaining items. Otherwise the numbers aren't comparable.
23. **Never extend the prompt set mid-run.** Same reason.

## Reporting rules

24. **Always report end-to-end wall-clock latency**, with the disclaimer that it includes network + Mesh routing + provider queue + inference. Don't claim isolated inference time.
25. **Always report p50 and p95 latency separately.** Image-gen tails are fat; mean is misleading.
26. **Always cite the pricing-table `_fetched` date** in the blog's methodology section. Prices move; the reader needs to know when the numbers were captured.
27. **Always list the prompts publicly.** `tasks/t2i_prompts.json` is part of the repo. Other people running the benchmark must be able to reproduce.
28. **Always disclose the model lineup and the candidates that didn't make it.** If FLUX or Midjourney is absent because Mesh doesn't expose them, say so.
29. **Always disclose n.** "n=5 per category, n=10 overall, n=10 per category" — the reader should never guess.

## Anti-cherry-picking rules

30. **Never pick the best of N generations.** One image per (model, prompt, seed). Variance is part of the story.
31. **Never re-run a model after seeing low scores.** That's data laundering.
32. **Always show the median, the worst, and the best** image in the gallery — not three "best" images.

## Code hygiene rules

33. **Never check in `.env`.** It's gitignored; verify before every commit.
34. **Never check in API keys, even rotated ones.** Even in comments. Even in commit messages.
35. **Never check in `images/`, `pilot_*.csv`, `judged_*.csv`** unless they're explicitly part of the published blog. Generated artifacts stay local until publication.
36. **Always run `smoke_test.py` before the pilot.** It's free; it catches the bugs that would burn $30 of judge calls.

---

## Hard "stop and ask the user" triggers

In addition to the never/always list, **these specific situations halt the run and prompt the user**:

- `discover.py` returns fewer than 3 of the 5 candidate models routable on Mesh.
- `pricing.json` is missing a `(model, size, quality)` tuple requested by the runner.
- Vision-judge JSON parse fails after 1 retry on >10% of items.
- Spearman ρ between Claude-vision and GPT-vision < 0.5 on any axis.
- Refusal rate > 50% on any single model in the pilot.
- Cumulative spend reaches 80% of `--budget-cap` (warning, not stop — but reports it).
- Any model's p95 latency > 60 seconds (probably broken, not slow).

When triggered, the runner/judge writes whatever it has, exits non-zero with a clear message, and the next-step decision is the user's.
