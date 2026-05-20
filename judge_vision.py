#!/usr/bin/env python3
"""judge_vision.py — Vision-LLM ensemble judge.

For each (model, prompt) row in a runner CSV, sends the generated image to two
vision-capable LLMs (Claude Opus 4.7-vision + GPT-5.5-vision by default), each
at temperatures 0.0 and 0.3 — four judge passes per image. Writes per-image
score JSON to a sidecar CSV that judge.py merges back onto the main run CSV.

Per rules.md: never publish a single-judge number, never round/fix scores.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

from models import VISION_JUDGES, VISION_JUDGE_FALLBACKS, JUDGE_TEMPS

REPO_ROOT = Path(__file__).resolve().parent

JUDGE_SYSTEM = """You are an expert image evaluator. Rate the generated image against the prompt on a 1-5 integer scale across five axes. Use "N/A" only when an axis is genuinely inapplicable. Return strict JSON in the exact schema below — no commentary, no markdown, no code fence.

Schema: {"adherence": int|"N/A", "aesthetic": int|"N/A", "photoreal": int|"N/A", "text": int|"N/A", "anatomy": int|"N/A", "note": string}

Anchors:
- adherence: 1 = ignores most of prompt; 3 = gets the gist, misses attributes; 5 = every named attribute correct
- aesthetic: 1 = muddy/generic; 3 = competent but bland; 5 = striking, polished
- photoreal: 1 = fails requested style; 3 = approximate, uncanny; 5 = style is convincing
- text: 1 = garbled/missing (only if prompt asks for in-image text); 5 = every word correct
- anatomy: 1 = major errors (extra fingers, melted faces); 3 = minor; 5 = clean
"""

JUDGE_USER_TEMPLATE = """Prompt the image was generated for:
"{prompt}"

Evaluation focus the prompt author flagged:
{eval_focus}

Has in-image text to render: {has_text}

Return only the JSON."""

SIDE_CSV_COLUMNS = [
    "run_id", "model_id", "prompt_id",
    "judge_id", "judge_temp",
    "adherence", "aesthetic", "photoreal", "text", "anatomy",
    "note", "judge_latency_ms", "judge_status", "judge_error",
]


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if not v:
        raise RuntimeError(f"env var {name} required")
    return v


def encode_image_for_judge(local_path: Path) -> str:
    """Base64-encode for inclusion in OpenAI-style messages."""
    return base64.b64encode(local_path.read_bytes()).decode("ascii")


def detect_image_mime(local_path: Path) -> str:
    ext = local_path.suffix.lstrip(".").lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp"}.get(ext, "image/png")


def call_vision_judge(
    *,
    judge_model: str,
    image_path: Path,
    prompt: str,
    eval_focus: list[str],
    has_text: bool,
    temperature: float,
    base_url: str,
    api_key: str,
    timeout_s: int = 120,
) -> dict[str, Any]:
    """OpenAI-compatible vision chat completion. Returns dict with parsed scores
    or {error, latency_ms, status}."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    mime = detect_image_mime(image_path)
    b64 = encode_image_for_judge(image_path)
    data_url = f"data:{mime};base64,{b64}"

    user_text = JUDGE_USER_TEMPLATE.format(
        prompt=prompt,
        eval_focus=", ".join(eval_focus) if eval_focus else "(none specified)",
        has_text="yes" if has_text else "no",
    )
    body = {
        "model": judge_model,
        "temperature": temperature,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
    }

    t0 = time.time()
    try:
        r = requests.post(url, headers=headers, json=body, timeout=timeout_s)
    except requests.RequestException as exc:
        return {"latency_ms": int((time.time() - t0) * 1000),
                "status": None, "error": f"request_exception: {exc}",
                "scores": None}

    latency_ms = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        return {"latency_ms": latency_ms, "status": r.status_code,
                "error": f"http_{r.status_code}: {r.text[:300]}", "scores": None}

    try:
        payload = r.json()
        text = payload["choices"][0]["message"]["content"]
    except Exception as exc:
        return {"latency_ms": latency_ms, "status": 200,
                "error": f"response_parse: {exc}", "scores": None}

    scores = parse_judge_json(text)
    if scores is None:
        # One retry attempt with stricter "return ONLY JSON" suffix could go here;
        # for simplicity, log and return.
        return {"latency_ms": latency_ms, "status": 200,
                "error": f"json_parse_failed: {text[:200]!r}", "scores": None}

    return {"latency_ms": latency_ms, "status": 200, "error": "", "scores": scores}


def parse_judge_json(text: str) -> dict[str, Any] | None:
    """Tolerant JSON extractor — handles minor LLM formatting drift."""
    text = text.strip()
    # Strip code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Try to find first {...} block
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict):
        return None
    # Normalize values
    out = {}
    for k in ("adherence", "aesthetic", "photoreal", "text", "anatomy"):
        v = obj.get(k)
        if v == "N/A" or v is None:
            out[k] = "N/A"
        else:
            try:
                iv = int(v)
                if 1 <= iv <= 5:
                    out[k] = iv
                else:
                    out[k] = "N/A"
            except (TypeError, ValueError):
                out[k] = "N/A"
    out["note"] = str(obj.get("note", ""))[:500]
    return out


def load_runs(runs_path: Path) -> list[dict[str, Any]]:
    with runs_path.open() as f:
        return list(csv.DictReader(f))


def load_tasks_by_id(task_path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(task_path.read_text())
    return {it["id"]: it for it in raw.get("items", [])}


def judge_runs(
    *,
    runs_path: Path,
    task_path: Path,
    out_path: Path,
    judges: list[tuple[str, str]],
    temps: list[float],
    base_url: str,
    api_key: str,
    budget_cap_usd: float = 5.0,
) -> int:
    runs = load_runs(runs_path)
    tasks = load_tasks_by_id(task_path)

    # Only judge OK rows that actually have a local image
    ok_rows = [r for r in runs
               if r.get("refused", "False") in ("False", "false", "0", "") and r.get("local_path")]
    skipped = len(runs) - len(ok_rows)
    print(f"judge_vision.py — {len(ok_rows)} judgeable rows ({skipped} skipped: refused/no-image)")
    print(f"judges: {[j[1] for j in judges]} × temps {temps}")
    n_passes = len(judges) * len(temps)
    total_calls = len(ok_rows) * n_passes
    print(f"total judge calls: {total_calls}  (budget cap ${budget_cap_usd:.2f})")
    print(f"writing to: {out_path}\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out_path.exists() or out_path.stat().st_size == 0
    cumulative_calls = 0
    with out_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SIDE_CSV_COLUMNS)
        if write_header:
            writer.writeheader()

        for row in ok_rows:
            task = tasks.get(row["prompt_id"])
            if not task:
                print(f"  WARN: no task for prompt_id={row['prompt_id']}, skipping")
                continue
            image_path = REPO_ROOT / row["local_path"]
            if not image_path.exists():
                print(f"  WARN: image missing {image_path}, skipping")
                continue

            for judge_id, judge_display in judges:
                for temp in temps:
                    result = call_vision_judge(
                        judge_model=judge_id, image_path=image_path,
                        prompt=task["prompt"],
                        eval_focus=task.get("eval_focus", []),
                        has_text=bool(task.get("has_text_to_render", False)),
                        temperature=temp,
                        base_url=base_url, api_key=api_key,
                    )
                    scores = result["scores"] or {
                        "adherence": "", "aesthetic": "", "photoreal": "",
                        "text": "", "anatomy": "", "note": "",
                    }
                    out_row = {
                        "run_id": row["run_id"],
                        "model_id": row["model_id"],
                        "prompt_id": row["prompt_id"],
                        "judge_id": judge_id,
                        "judge_temp": temp,
                        "adherence": scores["adherence"],
                        "aesthetic": scores["aesthetic"],
                        "photoreal": scores["photoreal"],
                        "text": scores["text"],
                        "anatomy": scores["anatomy"],
                        "note": scores["note"],
                        "judge_latency_ms": result["latency_ms"],
                        "judge_status": result["status"] or "",
                        "judge_error": result["error"],
                    }
                    writer.writerow(out_row)
                    f.flush()
                    cumulative_calls += 1
                    status_label = "OK" if not result["error"] else "ERR"
                    print(f"  [{cumulative_calls:04d}/{total_calls:04d}] {status_label:3s} "
                          f"{judge_display:<24s} t={temp} {row['prompt_id']:>8s} "
                          f"{result['latency_ms']:>5d}ms  scores={[scores[k] for k in ('adherence','aesthetic','photoreal','text','anatomy')]}")

    print(f"\nDONE. {cumulative_calls} judge calls.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", required=True, help="runner output CSV")
    p.add_argument("--task", required=True, help="t2i_prompts.json or edit_prompts.json")
    p.add_argument("--out", required=True, help="judge side-CSV output path")
    p.add_argument("--single-judge", action="store_true",
                   help="use only the primary judge (debug; rules.md forbids for publication)")
    args = p.parse_args()

    base_url = _env("MESH_BASE_URL", "https://api.meshapi.ai/v1")
    api_key = _env("MESH_API_KEY")

    judges = VISION_JUDGES[:1] if args.single_judge else list(VISION_JUDGES)
    return judge_runs(
        runs_path=Path(args.runs),
        task_path=Path(args.task),
        out_path=Path(args.out),
        judges=judges,
        temps=JUDGE_TEMPS,
        base_url=base_url, api_key=api_key,
    )


if __name__ == "__main__":
    sys.exit(main())
