"""Candidate model lineup for dollar-per-image-bench.

Format per entry:
    (mesh_model_id, display_name, default_size, default_quality, tier_label)

tier_label is one of: "premium_high", "premium_mid", "budget_proprietary",
"alt_arch", "legacy".

Model IDs and prices CONFIRMED 2026-05-20 via Mesh `/v1/models` (discover.py).
15 image-output models are routable. The pilot lineup picks 5 that span the
price ladder; STRETCH_MODELS adds 3 more for the full run.

Note: Mesh's catalog reports its single per-image price; the runner sends
quality="auto" by default. Quality-tier behavior is probed in a separate
sub-pilot (see plan.md "Five hidden taxes" → "Quality-tier inflation").
"""

# Pilot lineup (5 models, in priority order)
MODELS = [
    # Premium proprietary OpenAI — latest flagship
    ("openai/gpt-image-2",          "GPT-Image-2",       "1024x1024", "auto", "premium_high"),

    # Premium proprietary OpenAI — current LM Arena #1
    ("openai/gpt-image-1.5",        "GPT-Image-1.5",     "1024x1024", "auto", "premium_high"),

    # Premium proprietary Google
    ("google/imagen-4-ultra",       "Imagen 4 Ultra",    "1024x1024", "auto", "premium_high"),

    # Budget Google
    ("google/imagen-4-fast",        "Imagen 4 Fast",     "1024x1024", "auto", "budget_proprietary"),

    # Budget OpenAI — workhorse, parallels GPT-4o-mini's role in chat benchmark
    ("openai/gpt-image-1-mini",     "GPT-Image-1 Mini",  "1024x1024", "auto", "budget_proprietary"),
]

# Stretch lineup — added for the full run.
# All confirmed routable on Mesh 2026-05-20.
STRETCH_MODELS = [
    # Alternative architecture: Gemini-based image gen ("Nano Banana"), token-priced
    ("google/gemini-2.5-flash-image", "Gemini 2.5 Flash Image (Nano Banana)", "1024x1024", "auto", "alt_arch"),
    # Mid-tier Google
    ("google/imagen-4",             "Imagen 4",          "1024x1024", "auto", "premium_mid"),
    # Older Google baseline
    ("google/imagen-3",             "Imagen 3",          "1024x1024", "auto", "legacy"),
    # Older OpenAI baseline
    ("openai/gpt-image-1",          "GPT-Image-1",       "1024x1024", "auto", "legacy"),
]

# Vision-LLM judges.
# NOTE: Mesh's catalog underreports vision capability — Claude Opus and GPT-4o
# are listed as text-only but DO accept image_url content blocks. We trust the
# known model families and let the API call confirm/reject vision capability.
VISION_JUDGES = [
    ("anthropic/claude-opus-4.7", "Claude Opus 4.7 Vision"),
    ("openai/gpt-5.5",            "GPT-5.5 Vision"),
]

# Probed 2026-05-20: openai/gpt-5.5-pro returns 500 upstream_error on multimodal
# requests via Mesh. claude-sonnet-4.6 returns 200 but content suggests it didn't
# see the image. gpt-4o intermittently disconnects. gemini-2.5-pro-preview works.
VISION_JUDGE_FALLBACKS = [
    ("google/gemini-2.5-pro-preview", "Gemini 2.5 Pro Vision"),
    ("openai/gpt-4o",                 "GPT-4o Vision"),
]

# Judge temperatures — two-pass variance check, mirroring dollar-per-task-bench
JUDGE_TEMPS = [0.0, 0.3]


def all_pilot_models():
    """Returns the pilot lineup."""
    return list(MODELS)


def all_full_run_models(routable_ids):
    """Returns pilot + stretch models filtered to those Mesh actually routes."""
    candidates = list(MODELS) + list(STRETCH_MODELS)
    return [m for m in candidates if m[0] in routable_ids]


def pricing_key(model_entry):
    """Returns the (model_id, size, quality) tuple used for pricing lookup."""
    mesh_id, _, size, quality, _ = model_entry
    return (mesh_id, size, quality)
