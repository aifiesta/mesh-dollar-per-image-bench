# Mesh Dollar per Image Bench: pilot benchmark of frontier T2I models (X thread)

*Thread format. Each numbered block is one tweet (≤ 280 chars). Chart placeholders mark where to insert generated PNGs.*

---

**1/16**

New preprint: **Mesh Dollar per Image Bench** — a holistic cost-quality-latency pilot benchmark of five 2026 frontier text-to-image models, all routed through one API gateway (Mesh).

n=5/model, $1.27 total spend, fully reproducible.

paper: github.com/aifiesta/mesh-dollar-per-image-bench

---

**2/16**

Headline result, in one chart:

GPT-Image-1 Mini at **$0.008/image** sits within 0.07 quality-points of Imagen 4 Ultra at $0.060/image — **7.5× cheaper, same neighborhood on quality.**

The premium tier paid for noise.

*[INSERT CHART 1: chart_5_quality_vs_cost.png]*

---

**3/16**

The full headline table (vision-LLM ensemble judge: Claude Opus 4.7 + GPT-5.5, two temps each):

| Model | Quality 1-5 | $/img | $/qpt | p50 latency |
|---|---|---|---|---|
| **GPT-Image-1 Mini** | 4.871 | **$0.008** | **$0.0082** | 37 s |
| Imagen 4 Fast | 4.766 | $0.020 | $0.0210 | **7 s** |
| GPT-Image-1.5 | **4.937** | $0.032 | $0.0324 | 38 s |
| GPT-Image-2 | 4.921 | $0.033 | $0.0335 | 57 s |
| Imagen 4 Ultra | 4.908 | $0.060 | $0.0611 | 16 s |

---

**4/16**

Five hidden taxes the price card doesn't mention.

We surface three from pilot data, two flagged for the full run:

1. **Quality saturation** — 7.5× cost spread, 3.4% quality spread
2. **Latency spread** — 7.8× p50 gap
3. **Retry tax** — GPT-Image-2 retried 20% of calls
4. Refusal rate (full run)
5. Watermark visibility (full run)

---

**5/16**

**Tax 1: quality saturation.**

All 5 models scored 4.77-4.94 on a 1-5 scale. The price spread is 7.5×, the quality spread is **0.17 points** — smaller than the median per-image judge variance.

Buyers paying $0.060 are paying for an effect that's within noise.

---

**6/16**

**Tax 2: latency spread is 7.8×.**

Imagen 4 Fast: 7.3 s p50.
GPT-Image-2: 56.7 s p50.

Two premium-tier models priced within 2× of each other (Imagen 4 Ultra $0.060, GPT-Image-2 $0.033) had a **3.6× latency gap** (15.7 s vs 56.7 s).

For interactive UX: latency is the real differentiator, not cost.

*[INSERT CHART 2: chart_3_latency_p50_p95.png]*

---

**7/16**

**Tax 3: GPT-Image-2 retried 20% of its calls.**

1 of 5 calls hit a transient upstream error and retried, doubling the cost on that call.

None of the other four models retried.

Retry tax shows up in the effective-cost column; never on the price card.

---

**8/16**

Two findings on the rubric axes:

(a) **Text rendering scored 5.0 across every model** on the typography prompt ("OPEN 24 HOURS" diner neon). The 2026 generation has solved in-image text — every glyph correct on every model.

(b) Imagen 4 Fast scored 4.45 on adherence — the only weak spot in the lineup.

---

**9/16**

Visual sanity check.

Both images: T2I-011 ("OPEN 24 HOURS" diner neon, brick exterior, rainy sidewalk).

Left: **GPT-Image-1 Mini ($0.008).**
Right: **Imagen 4 Ultra ($0.060).**

Both scored 5/5 on text fidelity from both judges.

*[INSERT IMAGE PAIR: openai_gpt-image-1-mini__T2I-011.png + google_imagen-4-ultra__T2I-011.png]*

---

**10/16**

Why route through Mesh API (`api.meshapi.ai`)?

One client, one key, one billing surface across every model in the lineup. Per-provider SDK differences, rate-limit dialects, auth-flow drift — all eliminated as confounders.

Switching models = changing a string.

---

**11/16**

Methodology in one paragraph.

Same prompt, same `size=1024x1024`, same `quality=auto`, same `n=1` for every model. Cost from a dated static pricing table (Mesh's catalog exposes `image_usd_per_image`). Quality from a 2-judge × 2-temp vision-LLM ensemble on a 5-axis 1-5 rubric. End-to-end wall-clock latency. Refusal & watermark in their own buckets.

---

**12/16**

Judge ensemble agreement:

GPT-5.5 (Judge B) scores 0.08-0.27 points higher than Claude Opus 4.7 (Judge A) on every model. Claude is the stricter judge.

GPT-5.5 gave GPT-Image-2 a perfect 5.00 — consistent with own-provider preference. We report **both** judge means so the bias is auditable.

---

**13/16**

The cheap-mini result is structural, not coincidental.

The sibling chat benchmark (dollar-per-task-bench) found GPT-4o-mini tied 4/5 frontier chat models at 100% on code.

Today, GPT-Image-1 Mini sits within 0.07 quality-points of the most expensive T2I model in the lineup.

Same shape.

---

**14/16**

The implication: **cost-per-quality is a routing decision, not a model-selection decision.**

Default to the budget workhorse for the broad middle of traffic. Escalate to the premium tier only when a per-call heuristic flags an edge case worth the bill.

Most teams skip step 2 and overpay structurally.

---

**15/16**

Pilot caveats, hold us to all of them:

- n=5/model
- 5 of 12 prompt categories sampled (long-prompt, knowledge, counting, neg-space, edge-case, multilingual, hyper-complex deferred to full run)
- Single region, single time, single seed
- 2-judge ensemble — no human eval yet
- Mesh only routes OpenAI + Google for image; FLUX/Midjourney/Ideogram absent

---

**16/16**

Coming in v1 (n=10/cat × 12 categories × 5-8 models, projected $45-65):

- The seven missing categories (incl. multilingual non-Latin scripts + hyper-complex boss-fight prompts)
- Stretch lineup: Gemini 2.5 Flash Image ("Nano Banana"), Imagen 3, GPT-Image-1
- Third Gemini-vision judge for own-provider-bias triangulation
- Automatic metrics: CLIPScore + VQAScore + LAION aesthetic
- 50-prompt human calibration set

Repo + raw CSVs + paper: github.com/aifiesta/mesh-dollar-per-image-bench

Total pilot cost incl. debugging re-runs: ~$2.50.

If you run it on your own prompts and get different numbers, reply with the CSV.
