#!/usr/bin/env python3
"""discover.py — probe Mesh API for routable image-generation models.

GET /v1/models, filter to entries that produce images, write models_catalog.json,
and print which of our candidate lineup (models.py) are actually routable. Also
attempts a HEAD/OPTIONS on /v1/images/edits to detect editing support.

Read-only. ~1 free API call. Safe to run anytime.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

from models import MODELS, STRETCH_MODELS, VISION_JUDGES, VISION_JUDGE_FALLBACKS

REPO_ROOT = Path(__file__).resolve().parent
CATALOG_PATH = REPO_ROOT / "data" / "models_catalog.json"


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        print(f"ERROR: env var {name} is required.", file=sys.stderr)
        sys.exit(2)
    return value


def fetch_models(base_url: str, api_key: str) -> list[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    payload = r.json()
    # OpenAI-compatible response: {"data": [{...}, ...]} or sometimes a bare list
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    if isinstance(payload, list):
        return payload
    raise RuntimeError(f"Unexpected /models response shape: {type(payload)}")


def is_image_output(model: dict[str, Any]) -> bool:
    """Best-effort detector for image-output models across OpenAI-compatible schemas."""
    # Common fields seen across gateways: modalities, output_modalities, capabilities,
    # type, family, tags. Be permissive — we'd rather over-include and let the user pick.
    bag: list[str] = []
    for key in ("modalities", "output_modalities", "capabilities", "tags", "type"):
        v = model.get(key)
        if isinstance(v, list):
            bag.extend(str(x).lower() for x in v)
        elif isinstance(v, dict):
            bag.extend(str(x).lower() for x in v.keys())
            bag.extend(str(x).lower() for x in v.values() if isinstance(x, str))
        elif isinstance(v, str):
            bag.append(v.lower())

    # Look for image-output signals
    image_signals = {"image", "image_generation", "text-to-image", "t2i", "vision_output"}
    if any(s in bag for s in image_signals):
        # Reject pure vision-input models (input=image, output=text)
        if "image_to_text" in bag or "vision_input_only" in bag:
            return False
        return True

    # Heuristic by model id (last resort)
    mid = model.get("id", "").lower()
    image_id_hints = (
        "image", "imagen", "dall-e", "dalle", "flux", "sdxl",
        "stable-diffusion", "recraft", "ideogram", "seedream", "midjourney",
    )
    return any(h in mid for h in image_id_hints)


def is_vision_input(model: dict[str, Any]) -> bool:
    """Detector for vision-LLM judges (accepts image input, outputs text).

    NOTE: Mesh's catalog under-reports vision support — Claude Opus 4.7 and GPT-4o
    are listed as input_modalities=['text'] but DO accept image_url content blocks
    via the OpenAI-compatible chat endpoint. We fall back to a known-good list
    when the schema-based detector returns nothing.
    """
    bag: list[str] = []
    for key in ("modalities", "input_modalities", "capabilities", "tags"):
        v = model.get(key)
        if isinstance(v, list):
            bag.extend(str(x).lower() for x in v)
        elif isinstance(v, dict):
            bag.extend(str(x).lower() for x in v.keys())
        elif isinstance(v, str):
            bag.append(v.lower())
    vision_signals = {"vision", "image_input", "multimodal", "image-text", "image"}
    if any(s in bag for s in vision_signals):
        return True

    # Fallback to known-good model-family names
    mid = model.get("id", "").lower()
    known_vision_families = (
        "claude-opus-4", "claude-sonnet-4", "claude-haiku-4",
        "gpt-4o", "gpt-5", "gpt-image-1", "gemini-",
    )
    return any(h in mid for h in known_vision_families) and "audio" not in mid


def probe_edit_endpoint(base_url: str, api_key: str) -> dict[str, Any]:
    """Soft-probe /v1/images/edits. Returns {supported, status, note}."""
    url = f"{base_url.rstrip('/')}/images/edits"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        # OPTIONS first; some gateways don't implement OPTIONS, fall back to HEAD
        r = requests.options(url, headers=headers, timeout=15)
        if r.status_code in (200, 204, 405):  # 405 means endpoint exists but doesn't accept OPTIONS
            return {"supported": True, "status": r.status_code, "method": "OPTIONS",
                    "note": "Endpoint responds; edit support likely available."}
        # Try HEAD
        r = requests.head(url, headers=headers, timeout=15)
        if r.status_code in (200, 204, 405):
            return {"supported": True, "status": r.status_code, "method": "HEAD",
                    "note": "Endpoint responds; edit support likely available."}
        return {"supported": False, "status": r.status_code, "method": "HEAD",
                "note": "Endpoint returned a non-success status; assume editing is unavailable."}
    except requests.RequestException as exc:
        return {"supported": False, "status": None, "method": "OPTIONS/HEAD",
                "note": f"Probe failed: {exc}"}


def main() -> int:
    base_url = _env("MESH_BASE_URL", "https://api.meshapi.ai/v1")
    api_key = _env("MESH_API_KEY")

    print(f"discover.py — Mesh API @ {base_url}\n")

    try:
        all_models = fetch_models(base_url, api_key)
    except Exception as exc:
        print(f"ERROR fetching /models: {exc}", file=sys.stderr)
        return 1

    print(f"Mesh exposes {len(all_models)} total models.\n")

    image_output = [m for m in all_models if is_image_output(m)]
    vision_input = [m for m in all_models if is_vision_input(m)]

    print(f"Image-output models: {len(image_output)}")
    for m in image_output:
        print(f"  - {m.get('id', '?')}")
    print()

    print(f"Vision-input (judge-capable) models: {len(vision_input)}")
    for m in vision_input[:20]:  # cap printout
        print(f"  - {m.get('id', '?')}")
    if len(vision_input) > 20:
        print(f"  ... and {len(vision_input) - 20} more")
    print()

    # Coverage check against our candidate lineup
    image_ids = {m.get("id") for m in image_output}
    pilot_ids = {m[0] for m in MODELS}
    stretch_ids = {m[0] for m in STRETCH_MODELS}
    vision_ids = {m.get("id") for m in vision_input}
    judge_primary_ids = {m[0] for m in VISION_JUDGES}
    judge_fallback_ids = {m[0] for m in VISION_JUDGE_FALLBACKS}

    pilot_routable = sorted(pilot_ids & image_ids)
    pilot_missing = sorted(pilot_ids - image_ids)
    stretch_routable = sorted(stretch_ids & image_ids)
    stretch_missing = sorted(stretch_ids - image_ids)
    judge_routable = sorted(judge_primary_ids & vision_ids)
    judge_missing = sorted(judge_primary_ids - vision_ids)
    judge_fallback_routable = sorted(judge_fallback_ids & vision_ids)

    print("=" * 60)
    print("Candidate lineup coverage:")
    print(f"  Pilot routable    ({len(pilot_routable)}/{len(pilot_ids)}): {pilot_routable}")
    print(f"  Pilot missing     ({len(pilot_missing)}/{len(pilot_ids)}): {pilot_missing}")
    print(f"  Stretch routable  ({len(stretch_routable)}/{len(stretch_ids)}): {stretch_routable}")
    print(f"  Stretch missing   ({len(stretch_missing)}/{len(stretch_ids)}): {stretch_missing}")
    print(f"  Judge routable    ({len(judge_routable)}/{len(judge_primary_ids)}): {judge_routable}")
    print(f"  Judge fallbacks   ({len(judge_fallback_routable)}/{len(judge_fallback_ids)}): {judge_fallback_routable}")
    print("=" * 60)

    edit_probe = probe_edit_endpoint(base_url, api_key)
    print(f"\n/v1/images/edits probe: {edit_probe}")

    catalog = {
        "_metadata": {
            "fetched_url": base_url,
            "total_models": len(all_models),
            "image_output_count": len(image_output),
            "vision_input_count": len(vision_input),
            "edit_endpoint_probe": edit_probe,
        },
        "image_output_models": [{"id": m.get("id"), "raw": m} for m in image_output],
        "vision_input_models": [{"id": m.get("id"), "raw": m} for m in vision_input],
        "coverage_against_models_py": {
            "pilot_routable": pilot_routable,
            "pilot_missing": pilot_missing,
            "stretch_routable": stretch_routable,
            "stretch_missing": stretch_missing,
            "judge_routable": judge_routable,
            "judge_missing": judge_missing,
            "judge_fallback_routable": judge_fallback_routable,
        },
    }
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2))
    print(f"\nWrote {CATALOG_PATH}")

    # Stop-and-ask trigger from rules.md: fewer than 3 of 5 pilot models routable
    if len(pilot_routable) < 3:
        print("\n*** STOP-AND-ASK TRIGGER ***", file=sys.stderr)
        print(f"Only {len(pilot_routable)} of 5 pilot models are routable on Mesh.",
              file=sys.stderr)
        print("Missing:", pilot_missing, file=sys.stderr)
        print("Per rules.md, do NOT silently substitute. Re-pick lineup with user.",
              file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
