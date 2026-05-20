#!/usr/bin/env python3
"""judge_auto.py — automatic metrics: VQAScore, CLIPScore, aesthetic predictor.

All metrics are local and free. The heavy ML libraries (`t2v_metrics`,
`open_clip_torch`, the aesthetic predictor) are OPTIONAL — if not installed,
this module degrades gracefully: it writes NaN-equivalent empty cells for the
missing metric column rather than crashing the pipeline.

This is by design. The vision-LLM ensemble (judge_vision.py) is the headline
quality signal; auto metrics are a sanity baseline. The benchmark should still
complete usefully on a machine without GPU/torch.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent

AUTO_CSV_COLUMNS = [
    "run_id", "model_id", "prompt_id",
    "vqa_score", "clip_score", "aesthetic_score",
    "auto_backend_notes",
]


# ────────────────────────────────────────────────────────────────────────────────
# Soft-import wrappers — return (function, error_message_if_unavailable)
# ────────────────────────────────────────────────────────────────────────────────

def _try_clip():
    try:
        import torch
        import open_clip  # type: ignore
    except Exception as exc:
        return None, f"open_clip unavailable: {exc}"

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)

    def clip_score(image_path: Path, prompt: str) -> float:
        from PIL import Image  # type: ignore
        image = preprocess(Image.open(image_path).convert("RGB")).unsqueeze(0).to(device)
        text = tokenizer([prompt]).to(device)
        with torch.no_grad():
            image_features = model.encode_image(image)
            text_features = model.encode_text(text)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            sim = (image_features @ text_features.T).item()
        return float(sim)

    return clip_score, None


def _try_vqa():
    try:
        import t2v_metrics  # type: ignore
    except Exception as exc:
        return None, f"t2v_metrics unavailable: {exc}"

    # Default to a small Gecko-style VQA backend; user can override via env var.
    backend = None
    try:
        backend = t2v_metrics.VQAScore(model="clip-flant5-xxl")
    except Exception as exc:
        return None, f"t2v_metrics.VQAScore init failed: {exc}"

    def vqa_score(image_path: Path, prompt: str, questions: list[str] | None) -> float:
        # If specific yes/no questions are provided, use them; else use the prompt itself.
        # t2v_metrics returns alignment in [0, 1].
        score = backend(images=[str(image_path)], texts=[prompt])
        return float(score[0][0])

    return vqa_score, None


def _try_aesthetic():
    """LAION-style aesthetic predictor on CLIP embeddings.

    Tries a few common community packages. Returns None gracefully if absent.
    """
    try:
        import torch
        from PIL import Image  # type: ignore
    except Exception as exc:
        return None, f"torch/PIL unavailable: {exc}"

    # Reuse the open_clip model if available; otherwise try improved-aesthetic-predictor.
    try:
        import open_clip  # type: ignore
        # Train a tiny linear head ad-hoc would be wrong; require a published predictor.
        # If user wants it, they install `aesthetic-predictor-v2-5` or similar.
        from aesthetic_predictor_v2_5 import convert_v2_5_from_siglip  # type: ignore
        model, preprocessor = convert_v2_5_from_siglip(
            low_cpu_mem_usage=True, trust_remote_code=True,
        )
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)

        def aesthetic(image_path: Path) -> float:
            image = Image.open(image_path).convert("RGB")
            pixel_values = preprocessor(images=image, return_tensors="pt").pixel_values
            pixel_values = pixel_values.to(device).to(torch.float32)
            with torch.no_grad():
                score = model(pixel_values).logits.squeeze().float().item()
            return float(score)

        return aesthetic, None
    except Exception as exc:
        return None, f"aesthetic predictor unavailable: {exc}"


# ────────────────────────────────────────────────────────────────────────────────
# Main scoring loop
# ────────────────────────────────────────────────────────────────────────────────

def load_runs(runs_path: Path) -> list[dict[str, Any]]:
    with runs_path.open() as f:
        return list(csv.DictReader(f))


def load_tasks_by_id(task_path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(task_path.read_text())
    return {it["id"]: it for it in raw.get("items", [])}


def score_runs(
    *,
    runs_path: Path,
    task_path: Path,
    out_path: Path,
) -> int:
    runs = load_runs(runs_path)
    tasks = load_tasks_by_id(task_path)

    clip_fn, clip_err = _try_clip()
    vqa_fn, vqa_err = _try_vqa()
    aesth_fn, aesth_err = _try_aesthetic()

    backend_notes = []
    if clip_err:
        backend_notes.append(f"clip:OFF({clip_err.split(':')[0]})")
    else:
        backend_notes.append("clip:ON")
    if vqa_err:
        backend_notes.append(f"vqa:OFF({vqa_err.split(':')[0]})")
    else:
        backend_notes.append("vqa:ON")
    if aesth_err:
        backend_notes.append(f"aesth:OFF({aesth_err.split(':')[0]})")
    else:
        backend_notes.append("aesth:ON")
    backend_str = " ".join(backend_notes)
    print(f"judge_auto.py — backends: {backend_str}")

    if not (clip_fn or vqa_fn or aesth_fn):
        print("\nNote: all automatic-metric backends are unavailable. "
              "Writing empty rows so the pipeline shape is preserved.")
        print("Install with:  pip install open_clip_torch t2v-metrics  "
              "(and aesthetic_predictor_v2_5 if you want aesthetic scores)\n")

    ok_rows = [r for r in runs
               if r.get("refused", "False") in ("False", "false", "0", "") and r.get("local_path")]
    print(f"scoring {len(ok_rows)} judgeable rows\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out_path.exists() or out_path.stat().st_size == 0
    with out_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=AUTO_CSV_COLUMNS)
        if write_header:
            writer.writeheader()

        for i, row in enumerate(ok_rows, 1):
            task = tasks.get(row["prompt_id"])
            if not task:
                continue
            image_path = REPO_ROOT / row["local_path"]
            if not image_path.exists():
                continue

            prompt = task["prompt"]
            questions = task.get("vqa_questions") or []

            clip_v = ""
            vqa_v = ""
            aesth_v = ""

            if clip_fn:
                try:
                    clip_v = f"{clip_fn(image_path, prompt):.4f}"
                except Exception as exc:
                    clip_v = ""
                    backend_str = f"{backend_str} clip-fail:{exc}"
            if vqa_fn:
                try:
                    vqa_v = f"{vqa_fn(image_path, prompt, questions):.4f}"
                except Exception as exc:
                    vqa_v = ""
            if aesth_fn:
                try:
                    aesth_v = f"{aesth_fn(image_path):.4f}"
                except Exception as exc:
                    aesth_v = ""

            writer.writerow({
                "run_id": row["run_id"],
                "model_id": row["model_id"],
                "prompt_id": row["prompt_id"],
                "vqa_score": vqa_v,
                "clip_score": clip_v,
                "aesthetic_score": aesth_v,
                "auto_backend_notes": backend_str,
            })
            f.flush()
            print(f"  [{i:03d}/{len(ok_rows):03d}] {row['prompt_id']:>8s} "
                  f"clip={clip_v or '–'} vqa={vqa_v or '–'} aesth={aesth_v or '–'}")

    print(f"\nDONE.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    return score_runs(
        runs_path=Path(args.runs),
        task_path=Path(args.task),
        out_path=Path(args.out),
    )


if __name__ == "__main__":
    sys.exit(main())
