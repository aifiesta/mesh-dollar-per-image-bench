#!/usr/bin/env python3
"""aggregate.py — per-model summaries with hidden-tax columns.

Reads judged_*.csv (the output of judge.py) and writes pilot_results.csv +
pilot_results.json with one row per model (or per (model, category) pair when
--by-category is set).

Columns intentionally mirror dollar-per-task-bench/aggregate.py's naming
conventions where applicable.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent

SUMMARY_COLUMNS = [
    "model_id", "model_display", "tier",
    "n_total", "n_ok", "n_refused", "n_error",
    "refusal_rate", "error_rate", "watermark_rate",
    "p50_latency_ms", "p95_latency_ms", "mean_latency_ms",
    "raw_cost_usd", "effective_cost_usd",
    "cost_per_image_raw", "cost_per_image_effective",
    "cost_per_unrefused_image",
    "quality_score", "quality_variance",
    "axis_adherence_mean", "axis_aesthetic_mean", "axis_photoreal_mean",
    "axis_text_mean", "axis_anatomy_mean",
    "auto_vqa_mean", "auto_clip_mean", "auto_aesthetic_mean",
    "cost_per_quality_point",
    "judge_a_mean", "judge_b_mean", "judge_ensemble_spread",
    "retry_rate",
]


def _as_float(v: Any) -> float | None:
    try:
        if v in (None, "", "N/A"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_bool(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1


def aggregate(judged_paths: list[Path], by_category: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in judged_paths:
        with path.open() as f:
            rows.extend(csv.DictReader(f))

    if not rows:
        return []

    # Group key: (model_id, size, quality) — this keeps quality-tier variants
    # separate (e.g., gpt-image-1 @ high vs medium). by_category adds category.
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = (r["model_id"], r.get("size", ""), r.get("quality", ""))
        if by_category:
            key = key + (r.get("category", "unknown"),)
        groups[key].append(r)

    summaries: list[dict[str, Any]] = []
    for key, grp in groups.items():
        model_id = key[0]
        cat = key[-1] if by_category else "_all"
        n_total = len(grp)
        n_refused = sum(1 for r in grp if _as_bool(r.get("refused")))
        n_error = sum(1 for r in grp if r.get("error") and not _as_bool(r.get("refused")))
        n_ok = n_total - n_refused - n_error
        n_watermark = sum(1 for r in grp if _as_bool(r.get("watermark_suspected")))

        latencies = [int(r["latency_ms"]) for r in grp if r.get("latency_ms")]
        latencies_sorted = sorted(latencies)

        raw_cost = sum(_as_float(r.get("raw_cost_usd")) or 0 for r in grp)
        eff_cost = sum(_as_float(r.get("effective_cost_usd")) or 0 for r in grp)

        n_retries_total = sum(int(r.get("n_retries", 0) or 0) for r in grp)
        retry_rate = n_retries_total / n_total if n_total else 0.0

        # Quality scores
        q_scores = [v for r in grp if (v := _as_float(r.get("vision_quality_score"))) is not None]
        q_vars = [v for r in grp if (v := _as_float(r.get("vision_quality_variance"))) is not None]
        q_score_mean = statistics.fmean(q_scores) if q_scores else None
        q_var_mean = statistics.fmean(q_vars) if q_vars else None

        def axis_mean(col: str) -> float | None:
            vals = [v for r in grp if (v := _as_float(r.get(col))) is not None]
            return statistics.fmean(vals) if vals else None

        # Judge ensemble agreement
        judge_a = axis_mean("vision_mean_judge_a")
        judge_b = axis_mean("vision_mean_judge_b")
        ensemble_spread = abs(judge_a - judge_b) if (judge_a is not None and judge_b is not None) else None

        summary = {
            "model_id": model_id,
            "model_display": grp[0].get("model_display", model_id) if not by_category else f"{grp[0].get('model_display', model_id)} [{cat}]",
            "tier": grp[0].get("tier", ""),
            "n_total": n_total, "n_ok": n_ok, "n_refused": n_refused, "n_error": n_error,
            "refusal_rate": round(n_refused / n_total, 4) if n_total else 0,
            "error_rate": round(n_error / n_total, 4) if n_total else 0,
            "watermark_rate": round(n_watermark / n_total, 4) if n_total else 0,
            "p50_latency_ms": int(_percentile(latencies_sorted, 50)),
            "p95_latency_ms": int(_percentile(latencies_sorted, 95)),
            "mean_latency_ms": int(statistics.fmean(latencies)) if latencies else 0,
            "raw_cost_usd": round(raw_cost, 6),
            "effective_cost_usd": round(eff_cost, 6),
            "cost_per_image_raw": round(raw_cost / n_total, 6) if n_total else 0,
            "cost_per_image_effective": round(eff_cost / n_total, 6) if n_total else 0,
            "cost_per_unrefused_image": round(eff_cost / n_ok, 6) if n_ok else None,
            "quality_score": round(q_score_mean, 3) if q_score_mean else None,
            "quality_variance": round(q_var_mean, 3) if q_var_mean else None,
            "axis_adherence_mean": round(axis_mean("vision_adherence_mean") or 0, 3) if axis_mean("vision_adherence_mean") else None,
            "axis_aesthetic_mean": round(axis_mean("vision_aesthetic_mean") or 0, 3) if axis_mean("vision_aesthetic_mean") else None,
            "axis_photoreal_mean": round(axis_mean("vision_photoreal_mean") or 0, 3) if axis_mean("vision_photoreal_mean") else None,
            "axis_text_mean": round(axis_mean("vision_text_mean") or 0, 3) if axis_mean("vision_text_mean") else None,
            "axis_anatomy_mean": round(axis_mean("vision_anatomy_mean") or 0, 3) if axis_mean("vision_anatomy_mean") else None,
            "auto_vqa_mean": round(axis_mean("auto_vqa_score") or 0, 3) if axis_mean("auto_vqa_score") else None,
            "auto_clip_mean": round(axis_mean("auto_clip_score") or 0, 3) if axis_mean("auto_clip_score") else None,
            "auto_aesthetic_mean": round(axis_mean("auto_aesthetic_score") or 0, 3) if axis_mean("auto_aesthetic_score") else None,
            "cost_per_quality_point": round(eff_cost / q_score_mean, 6) if (q_score_mean and q_score_mean > 0) else None,
            "judge_a_mean": round(judge_a, 3) if judge_a is not None else None,
            "judge_b_mean": round(judge_b, 3) if judge_b is not None else None,
            "judge_ensemble_spread": round(ensemble_spread, 3) if ensemble_spread is not None else None,
            "retry_rate": round(retry_rate, 4),
        }
        summaries.append(summary)

    # Sort by cost_per_quality_point (None goes last)
    summaries.sort(key=lambda s: (s.get("cost_per_quality_point") is None,
                                   s.get("cost_per_quality_point") or 0))
    return summaries


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--judged", nargs="+", required=True,
                   help="one or more judged_*.csv files (e.g., judged_t2i.csv judged_edit.csv)")
    p.add_argument("--out", required=True, help="output CSV path (e.g., pilot_results.csv)")
    p.add_argument("--by-category", action="store_true",
                   help="emit per (model, category) rows instead of per-model")
    args = p.parse_args()

    summaries = aggregate([Path(p_) for p_ in args.judged], by_category=args.by_category)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for s in summaries:
            writer.writerow({k: (s.get(k) if s.get(k) is not None else "")
                             for k in SUMMARY_COLUMNS})

    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(summaries, indent=2))

    print(f"wrote {out_path} and {json_path}")
    print(f"{len(summaries)} rows")
    print("\nTop 5 by cost_per_quality_point:")
    for s in summaries[:5]:
        print(f"  {s['model_display']:<30s}  q={s['quality_score']}  "
              f"$/img={s['cost_per_image_effective']}  $/qpt={s['cost_per_quality_point']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
