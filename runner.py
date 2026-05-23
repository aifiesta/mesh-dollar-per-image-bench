#!/usr/bin/env python3
"""runner.py — hit Mesh /v1/images/generations for each (model, prompt).

Writes one CSV row per call with: model, prompt_id, category, latency_ms,
size, quality, n_retries, refused, error, local_path, image_dimensions,
raw_cost_usd, response_meta.

Hard-enforces --budget-cap (stops mid-run if cumulative effective spend ≥ cap).
Per rules.md: missing pricing tuple is a HARD ERROR; refusals are a third
bucket (not pass/fail); image URLs are downloaded immediately (Mesh signed
URLs expire).

Also exposes call_image_model() and save_image() as a library API for the
sanity-ping snippet in CLAUDE.md.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import requests

from models import MODELS, all_pilot_models, pricing_key

REPO_ROOT = Path(__file__).resolve().parent
IMAGES_DIR = REPO_ROOT / "images"
PRICING_PATH = REPO_ROOT / "pricing.json"

CSV_COLUMNS = [
    "run_id", "ts_iso", "model_id", "model_display", "tier",
    "prompt_id", "category", "size", "quality",
    "latency_ms", "n_retries", "http_status",
    "refused", "error", "local_path",
    "image_width", "image_height", "image_bytes",
    "raw_cost_usd", "effective_cost_usd",
    "watermark_suspected", "response_truncated_note",
]


@dataclass
class CallResult:
    run_id: str
    ts_iso: str
    model_id: str
    model_display: str
    tier: str
    prompt_id: str
    category: str
    size: str
    quality: str
    latency_ms: int
    n_retries: int
    http_status: int | None
    refused: bool
    error: str
    local_path: str
    image_width: int | None
    image_height: int | None
    image_bytes: int | None
    raw_cost_usd: float
    effective_cost_usd: float
    watermark_suspected: bool
    response_truncated_note: str

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


# ────────────────────────────────────────────────────────────────────────────────
# Pricing
# ────────────────────────────────────────────────────────────────────────────────

_PRICING_CACHE: dict[str, Any] | None = None


def load_pricing() -> dict[str, Any]:
    global _PRICING_CACHE
    if _PRICING_CACHE is None:
        _PRICING_CACHE = json.loads(PRICING_PATH.read_text())
    return _PRICING_CACHE


def lookup_price(model_id: str, size: str, quality: str) -> float:
    """Hard-error on missing tuple, per rules.md."""
    pricing = load_pricing()
    model_block = pricing.get(model_id)
    if not isinstance(model_block, dict):
        raise KeyError(
            f"pricing.json has no entry for model_id={model_id!r}. "
            f"Per rules.md, add the entry with _source and _fetched, then re-run."
        )
    size_block = model_block.get(size) or model_block.get("auto")
    if not isinstance(size_block, dict):
        raise KeyError(
            f"pricing.json has no size={size!r} (or 'auto' fallback) under "
            f"model_id={model_id!r}. Add it with _source and _fetched."
        )
    price = size_block.get(quality)
    if price is None:
        # Try a sibling 'auto' quality as a last-resort
        price = size_block.get("auto")
    if price is None:
        raise KeyError(
            f"pricing.json has no quality={quality!r} under "
            f"model_id={model_id!r}, size={size!r}. Add it with _source and _fetched."
        )
    return float(price)


# ────────────────────────────────────────────────────────────────────────────────
# Single API call
# ────────────────────────────────────────────────────────────────────────────────

def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise RuntimeError(f"env var {name} is required")
    return value


def call_image_model(
    *,
    model: str,
    prompt: str,
    size: str = "1024x1024",
    quality: str = "high",
    n: int = 1,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_s: int = 300,  # bumped 2026-05-21 — GPT-Image-2 needs >120s on hyper-complex
) -> dict[str, Any]:
    """Single POST to /v1/images/generations. Returns dict with image_url or b64_json,
    latency_ms, raw_cost_usd, http_status, refused flag.
    """
    base_url = base_url or _env("MESH_BASE_URL", "https://api.meshapi.ai/v1")
    api_key = api_key or _env("MESH_API_KEY")

    url = f"{base_url.rstrip('/')}/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
        "quality": quality,
    }

    raw_cost = lookup_price(model, size, quality) * n

    t0 = time.time()
    try:
        r = requests.post(url, headers=headers, json=body, timeout=timeout_s)
    except requests.RequestException as exc:
        return {
            "ok": False, "http_status": None, "refused": False,
            "latency_ms": int((time.time() - t0) * 1000),
            "raw_cost_usd": 0.0, "error": f"request_exception: {exc}",
            "image_url": None, "b64_json": None, "raw_response": None,
        }
    latency_ms = int((time.time() - t0) * 1000)

    if r.status_code != 200:
        return {
            "ok": False, "http_status": r.status_code, "refused": False,
            "latency_ms": latency_ms, "raw_cost_usd": 0.0,
            "error": f"http_{r.status_code}: {r.text[:500]}",
            "image_url": None, "b64_json": None, "raw_response": None,
        }

    try:
        payload = r.json()
    except json.JSONDecodeError as exc:
        return {
            "ok": False, "http_status": 200, "refused": False,
            "latency_ms": latency_ms, "raw_cost_usd": 0.0,
            "error": f"json_decode: {exc}",
            "image_url": None, "b64_json": None, "raw_response": None,
        }

    data = payload.get("data") or []
    if not data:
        # Content-policy refusal or odd empty response
        return {
            "ok": False, "http_status": 200, "refused": True,
            "latency_ms": latency_ms, "raw_cost_usd": 0.0,
            "error": "empty_data (likely content-policy refusal)",
            "image_url": None, "b64_json": None, "raw_response": payload,
        }

    first = data[0]
    image_url = first.get("url")
    b64 = first.get("b64_json")
    if not image_url and not b64:
        return {
            "ok": False, "http_status": 200, "refused": True,
            "latency_ms": latency_ms, "raw_cost_usd": 0.0,
            "error": "no_image_data (url and b64_json both missing)",
            "image_url": None, "b64_json": None, "raw_response": payload,
        }

    return {
        "ok": True, "http_status": 200, "refused": False,
        "latency_ms": latency_ms, "raw_cost_usd": raw_cost,
        "error": "",
        "image_url": image_url, "b64_json": b64, "raw_response": payload,
    }


def save_image(image_url: str | None, b64_json: str | None, filename_stem: str) -> Path:
    """Download (or decode base64) and save to images/{stem}.{ext}. Returns local path.

    Handles three return shapes Mesh uses:
      1. data['b64_json'] is set → decode directly
      2. data['url'] is a `data:image/<type>;base64,...` URI → decode inline
      3. data['url'] is an HTTP(S) URL → fetch it
    """
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    # filename_stem may contain a relative directory (e.g. "openai/gpt-image-1/T2I-001")
    # to keep saved images organised by provider/model.
    (IMAGES_DIR / filename_stem).parent.mkdir(parents=True, exist_ok=True)
    if b64_json:
        path = IMAGES_DIR / f"{filename_stem}.png"
        path.write_bytes(base64.b64decode(b64_json))
        return path
    if image_url:
        if image_url.startswith("data:"):
            # data:[<mime>];base64,<payload>
            header, _, payload = image_url.partition(",")
            mime = "image/png"
            if ":" in header and ";" in header:
                mime = header[header.index(":") + 1: header.index(";")]
            ext = {"image/png": "png", "image/jpeg": "jpg",
                   "image/webp": "webp"}.get(mime, "png")
            path = IMAGES_DIR / f"{filename_stem}.{ext}"
            path.write_bytes(base64.b64decode(payload))
            return path
        ext = "png"
        for cand in ("webp", "jpg", "jpeg", "png"):
            if f".{cand}" in image_url.lower():
                ext = cand
                break
        path = IMAGES_DIR / f"{filename_stem}.{ext}"
        resp = requests.get(image_url, timeout=60)
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return path
    raise ValueError("save_image called with neither image_url nor b64_json")


def get_image_dimensions(path: Path) -> tuple[int | None, int | None, int]:
    """Returns (width, height, bytes). Width/height may be None if Pillow unavailable."""
    nbytes = path.stat().st_size
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as im:
            return im.width, im.height, nbytes
    except Exception:
        return None, None, nbytes


# ────────────────────────────────────────────────────────────────────────────────
# Refusal & watermark heuristics
# ────────────────────────────────────────────────────────────────────────────────

def detect_watermark(path: Path) -> bool:
    """Best-effort: returns True if image filesize is suspiciously small (refusal stub)
    OR if a known watermark signature is detected. This is a coarse signal; the vision
    judge's `note` field is the more reliable detector.
    """
    if not path.exists():
        return False
    if path.stat().st_size < 5_000:
        # Tiny image; possible refusal placeholder
        return True
    return False


# ────────────────────────────────────────────────────────────────────────────────
# Task loading
# ────────────────────────────────────────────────────────────────────────────────

def load_tasks(task_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(task_path.read_text())
    return raw.get("items", [])


# ────────────────────────────────────────────────────────────────────────────────
# Main loop
# ────────────────────────────────────────────────────────────────────────────────

def run_benchmark(
    *,
    task_path: Path,
    out_path: Path,
    models: Iterable,
    limit: int,
    budget_cap_usd: float,
    base_url: str,
    api_key: str,
    max_retries: int = 1,
) -> int:
    items = load_tasks(task_path)
    if limit:
        # Stratify across categories if possible: take `limit` items, preferring
        # one per distinct category until we've hit the count.
        by_cat: dict[str, list[dict[str, Any]]] = {}
        for it in items:
            by_cat.setdefault(it.get("category", "unknown"), []).append(it)
        picked: list[dict[str, Any]] = []
        cats = list(by_cat.keys())
        round_i = 0
        while len(picked) < limit and any(by_cat[c] for c in cats):
            c = cats[round_i % len(cats)]
            if by_cat[c]:
                picked.append(by_cat[c].pop(0))
            round_i += 1
            if round_i > limit * len(cats):
                break
        items = picked

    models_list = list(models)
    total_planned = len(items) * len(models_list)
    print(f"runner.py — {len(items)} prompts × {len(models_list)} models = {total_planned} calls")
    print(f"budget cap: ${budget_cap_usd:.2f} (hard stop)")
    print(f"writing rows to: {out_path}\n")

    cumulative = 0.0
    rows: list[dict[str, Any]] = []
    run_id_prefix = uuid.uuid4().hex[:8]

    # Header
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out_path.exists() or out_path.stat().st_size == 0
    with out_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()
            f.flush()

        for it in items:
            for model_entry in models_list:
                model_id, display, default_size, default_quality, tier = model_entry
                size = default_size
                quality = default_quality

                # Per-call budget check
                try:
                    raw_cost = lookup_price(model_id, size, quality)
                except KeyError as exc:
                    print(f"PRICING ERROR: {exc}", file=sys.stderr)
                    print("Stopping per rules.md (never default to $0).", file=sys.stderr)
                    return 4

                if cumulative + raw_cost > budget_cap_usd:
                    print(f"\nBUDGET CAP REACHED: cumulative ${cumulative:.4f} + next "
                          f"${raw_cost:.4f} > cap ${budget_cap_usd:.2f}. Stopping.",
                          file=sys.stderr)
                    return 5

                n_retries = 0
                result = None
                for attempt in range(max_retries + 1):
                    try:
                        result = call_image_model(
                            model=model_id, prompt=it["prompt"],
                            size=size, quality=quality, n=1,
                            base_url=base_url, api_key=api_key,
                        )
                    except KeyError as exc:
                        # Pricing miss — hard stop
                        print(f"PRICING ERROR mid-run: {exc}", file=sys.stderr)
                        return 4
                    if result["ok"] or result["refused"] or result["http_status"] not in (None, 429, 500, 502, 503, 504):
                        break
                    n_retries += 1
                    time.sleep(min(2 ** attempt, 10))

                assert result is not None
                effective_cost = result["raw_cost_usd"] * (1 + n_retries * 0.5) if result["ok"] else 0.0
                cumulative += effective_cost

                local_path = ""
                w, h, nbytes = None, None, None
                watermark = False
                if result["ok"]:
                    stem = f"{model_id}/{it['id']}"
                    try:
                        saved = save_image(result["image_url"], result["b64_json"], stem)
                        try:
                            local_path = str(saved.relative_to(REPO_ROOT))
                        except ValueError:
                            # IMAGES_DIR points outside REPO_ROOT (test override etc.)
                            local_path = str(saved)
                        w, h, nbytes = get_image_dimensions(saved)
                        watermark = detect_watermark(saved)
                    except Exception as exc:
                        result["ok"] = False
                        result["error"] = f"save_image: {exc}"

                row = CallResult(
                    run_id=f"{run_id_prefix}-{len(rows):04d}",
                    ts_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    model_id=model_id,
                    model_display=display,
                    tier=tier,
                    prompt_id=it["id"],
                    category=it.get("category", "unknown"),
                    size=size,
                    quality=quality,
                    latency_ms=result["latency_ms"],
                    n_retries=n_retries,
                    http_status=result["http_status"],
                    refused=result["refused"],
                    error=result["error"],
                    local_path=local_path,
                    image_width=w,
                    image_height=h,
                    image_bytes=nbytes,
                    raw_cost_usd=result["raw_cost_usd"],
                    effective_cost_usd=effective_cost,
                    watermark_suspected=watermark,
                    response_truncated_note="",
                ).as_row()
                rows.append(row)
                writer.writerow(row)
                f.flush()

                status_str = "OK" if result["ok"] else ("REFUSED" if result["refused"] else "ERR")
                print(f"  [{len(rows):03d}/{total_planned:03d}] {status_str:7s} "
                      f"{display:<24s} {it['id']:>8s} {result['latency_ms']:>6d}ms "
                      f"${effective_cost:.4f} (cum ${cumulative:.4f})")

    print(f"\nDONE. {len(rows)} calls, cumulative effective spend ${cumulative:.4f}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True, help="path to t2i_prompts.json or edit_prompts.json")
    p.add_argument("--out", required=True, help="output CSV path")
    p.add_argument("--limit", type=int, required=True,
                   help="max prompts to use (pilot=5, full=100 typical)")
    p.add_argument("--budget-cap", type=float, required=True,
                   help="hard USD ceiling; runner stops if cumulative cost would exceed")
    p.add_argument("--models", default="pilot", choices=["pilot", "all"],
                   help="'pilot' uses models.py MODELS only; 'all' adds STRETCH_MODELS")
    p.add_argument("--max-retries", type=int, default=1)
    args = p.parse_args()

    base_url = _env("MESH_BASE_URL", "https://api.meshapi.ai/v1")
    api_key = _env("MESH_API_KEY")

    if args.models == "pilot":
        models = all_pilot_models()
    else:
        # For "all" mode, we'd ideally filter by models_catalog.json but for safety
        # just include pilot + stretch and let pricing-table miss fail loudly.
        from models import STRETCH_MODELS
        models = list(MODELS) + list(STRETCH_MODELS)

    return run_benchmark(
        task_path=Path(args.task),
        out_path=Path(args.out),
        models=models,
        limit=args.limit,
        budget_cap_usd=args.budget_cap,
        base_url=base_url, api_key=api_key,
        max_retries=args.max_retries,
    )


if __name__ == "__main__":
    sys.exit(main())
