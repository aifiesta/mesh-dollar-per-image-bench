#!/usr/bin/env python3
"""judge.py — orchestrator.

Runs judge_vision.py and judge_auto.py back-to-back, then merges their sidecar
CSVs onto the runner CSV producing one judged_*.csv per task.

The vision sidecar has up to 4 rows per (run_id, prompt) (2 judges × 2 temps);
those are aggregated to a single per-image quality score, then joined onto the
main row. The auto sidecar is one row per (run_id, prompt) and joins directly.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent

OUTPUT_COLUMNS_BASE = [
    "run_id", "ts_iso", "model_id", "model_display", "tier",
    "prompt_id", "category", "size", "quality",
    "latency_ms", "n_retries", "http_status",
    "refused", "error", "local_path",
    "image_width", "image_height", "image_bytes",
    "raw_cost_usd", "effective_cost_usd",
    "watermark_suspected", "response_truncated_note",
]
OUTPUT_COLUMNS_JUDGED = OUTPUT_COLUMNS_BASE + [
    # Per-axis means across the 4 vision-judge passes
    "vision_adherence_mean", "vision_aesthetic_mean", "vision_photoreal_mean",
    "vision_text_mean", "vision_anatomy_mean",
    # Per-axis variance across passes
    "vision_adherence_var", "vision_aesthetic_var", "vision_photoreal_var",
    "vision_text_var", "vision_anatomy_var",
    # Per-judge means (useful for ensemble agreement)
    "vision_mean_judge_a", "vision_mean_judge_b",
    # Overall quality score and variance
    "vision_quality_score", "vision_quality_variance",
    "vision_judge_notes",
    # Auto metrics
    "auto_vqa_score", "auto_clip_score", "auto_aesthetic_score",
    "auto_backend_notes",
]


def run_subprocess(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.call(cmd)


def load_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def _to_int_or_none(v: Any) -> int | None:
    if v in (None, "", "N/A"):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def aggregate_vision_for_image(
    judge_rows: list[dict[str, Any]],
    judges_in_order: list[str],
) -> dict[str, Any]:
    """Reduce up-to-4 judge passes for one image into per-axis stats + headline score."""
    axes = ["adherence", "aesthetic", "photoreal", "text", "anatomy"]
    per_axis: dict[str, list[int]] = {a: [] for a in axes}
    per_judge_axis_values: dict[str, list[int]] = {jid: [] for jid in judges_in_order}
    notes: list[str] = []

    for row in judge_rows:
        for a in axes:
            v = _to_int_or_none(row.get(a))
            if v is not None:
                per_axis[a].append(v)
        for jid in judges_in_order:
            if row.get("judge_id") == jid:
                # Concatenate this judge's valid axis values for ensemble agreement
                for a in axes:
                    v = _to_int_or_none(row.get(a))
                    if v is not None:
                        per_judge_axis_values[jid].append(v)
        if row.get("note"):
            notes.append(f"[{row.get('judge_id', '?')}@t{row.get('judge_temp', '?')}]: "
                         f"{row['note']}")

    result: dict[str, Any] = {}
    flat: list[int] = []
    for a in axes:
        vals = per_axis[a]
        if vals:
            mean = sum(vals) / len(vals)
            var = statistics.pvariance(vals) if len(vals) > 1 else 0.0
            result[f"vision_{a}_mean"] = round(mean, 3)
            result[f"vision_{a}_var"] = round(var, 3)
            flat.extend(vals)
        else:
            result[f"vision_{a}_mean"] = ""
            result[f"vision_{a}_var"] = ""

    if flat:
        result["vision_quality_score"] = round(sum(flat) / len(flat), 3)
        result["vision_quality_variance"] = round(
            statistics.pvariance(flat) if len(flat) > 1 else 0.0, 3
        )
    else:
        result["vision_quality_score"] = ""
        result["vision_quality_variance"] = ""

    judge_a_vals = per_judge_axis_values.get(judges_in_order[0], []) if judges_in_order else []
    judge_b_vals = per_judge_axis_values.get(judges_in_order[1], []) if len(judges_in_order) > 1 else []
    result["vision_mean_judge_a"] = round(sum(judge_a_vals) / len(judge_a_vals), 3) if judge_a_vals else ""
    result["vision_mean_judge_b"] = round(sum(judge_b_vals) / len(judge_b_vals), 3) if judge_b_vals else ""
    result["vision_judge_notes"] = " | ".join(notes)[:1000]
    return result


def merge(
    *,
    runs_path: Path,
    vision_path: Path,
    auto_path: Path,
    out_path: Path,
    judges_in_order: list[str],
) -> int:
    runs = load_csv(runs_path)
    vision = load_csv(vision_path)
    auto = load_csv(auto_path)

    vision_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in vision:
        k = (r["run_id"], r["model_id"], r["prompt_id"])
        vision_by_key.setdefault(k, []).append(r)

    auto_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in auto:
        k = (r["run_id"], r["model_id"], r["prompt_id"])
        auto_by_key[k] = r

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS_JUDGED)
        writer.writeheader()
        for row in runs:
            k = (row["run_id"], row["model_id"], row["prompt_id"])
            out = {col: row.get(col, "") for col in OUTPUT_COLUMNS_BASE}
            v_rows = vision_by_key.get(k, [])
            v_agg = aggregate_vision_for_image(v_rows, judges_in_order)
            out.update(v_agg)
            a_row = auto_by_key.get(k, {})
            out["auto_vqa_score"] = a_row.get("vqa_score", "")
            out["auto_clip_score"] = a_row.get("clip_score", "")
            out["auto_aesthetic_score"] = a_row.get("aesthetic_score", "")
            out["auto_backend_notes"] = a_row.get("auto_backend_notes", "")
            writer.writerow(out)

    print(f"merged → {out_path}  ({len(runs)} rows)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--runs", required=True)
    p.add_argument("--out", required=True, help="final judged CSV (merged)")
    p.add_argument("--skip-vision", action="store_true",
                   help="don't run judge_vision.py (use existing sidecar)")
    p.add_argument("--skip-auto", action="store_true",
                   help="don't run judge_auto.py (use existing sidecar)")
    p.add_argument("--vision-sidecar", default=None,
                   help="path for vision judge sidecar CSV (default: <out>.vision.csv)")
    p.add_argument("--auto-sidecar", default=None,
                   help="path for auto judge sidecar CSV (default: <out>.auto.csv)")
    args = p.parse_args()

    out_path = Path(args.out)
    vision_path = Path(args.vision_sidecar) if args.vision_sidecar else out_path.with_suffix(".vision.csv")
    auto_path = Path(args.auto_sidecar) if args.auto_sidecar else out_path.with_suffix(".auto.csv")

    if not args.skip_vision:
        rc = run_subprocess([
            sys.executable, str(REPO_ROOT / "judge_vision.py"),
            "--runs", args.runs, "--task", args.task, "--out", str(vision_path),
        ])
        if rc != 0:
            print(f"judge_vision.py exited with {rc}; continuing to merge what we have.",
                  file=sys.stderr)

    if not args.skip_auto:
        rc = run_subprocess([
            sys.executable, str(REPO_ROOT / "judge_auto.py"),
            "--runs", args.runs, "--task", args.task, "--out", str(auto_path),
        ])
        if rc != 0:
            print(f"judge_auto.py exited with {rc}; continuing.", file=sys.stderr)

    from models import VISION_JUDGES
    judges_in_order = [j[0] for j in VISION_JUDGES]

    return merge(
        runs_path=Path(args.runs),
        vision_path=vision_path,
        auto_path=auto_path,
        out_path=out_path,
        judges_in_order=judges_in_order,
    )


if __name__ == "__main__":
    sys.exit(main())
