#!/usr/bin/env python3
"""cost_estimator.py — project full-run cost from a pilot/dryrun.

Given one or more dryrun CSVs (typically pilot_t2i.csv), extrapolate to a full
run of N prompts × M models with the pricing table. Prints the projection and
warns if it exceeds the user's budget cap.

Pure-arithmetic; no API calls.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from runner import load_pricing, lookup_price
from models import MODELS, STRETCH_MODELS

REPO_ROOT = Path(__file__).resolve().parent


def load_dryrun(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def estimate(
    *,
    dryruns: list[Path],
    target_n_per_category: int,
    n_categories: int,
    judge_passes_per_image: int,
    judge_cost_per_call_usd: float,
    include_stretch: bool,
    budget_cap_usd: float,
) -> dict[str, Any]:
    pricing = load_pricing()

    rows: list[dict[str, Any]] = []
    for p_ in dryruns:
        rows.extend(load_dryrun(p_))

    # Observed retry rate per model (default 0)
    retry_rates: dict[str, float] = {}
    cost_by_model: dict[str, float] = {}
    for r in rows:
        mid = r["model_id"]
        try:
            retries = int(r.get("n_retries", 0) or 0)
        except ValueError:
            retries = 0
        retry_rates.setdefault(mid, 0.0)
        cost_by_model.setdefault(mid, 0.0)
        retry_rates[mid] = (retry_rates[mid] + retries) / 2  # rough running avg

    models = list(MODELS) + (list(STRETCH_MODELS) if include_stretch else [])
    target_total_prompts = target_n_per_category * n_categories

    rows_out = []
    full_runner_cost = 0.0
    for model_entry in models:
        mid, display, size, quality, tier = model_entry
        try:
            per_image = lookup_price(mid, size, quality)
        except KeyError as exc:
            rows_out.append({"model_id": mid, "display": display,
                             "error": f"pricing miss: {exc}", "subtotal_usd": 0.0,
                             "tier": tier})
            continue
        retry_mult = 1 + (retry_rates.get(mid, 0.0) * 0.5)
        subtotal = per_image * retry_mult * target_total_prompts
        rows_out.append({
            "model_id": mid, "display": display, "tier": tier,
            "per_image_usd": per_image,
            "retry_multiplier": round(retry_mult, 4),
            "calls": target_total_prompts,
            "subtotal_usd": round(subtotal, 4),
            "error": None,
        })
        full_runner_cost += subtotal

    judge_calls_total = len(models) * target_total_prompts * judge_passes_per_image
    judge_cost_total = judge_calls_total * judge_cost_per_call_usd
    total = full_runner_cost + judge_cost_total

    return {
        "per_model": rows_out,
        "runner_subtotal_usd": round(full_runner_cost, 4),
        "judge_calls_total": judge_calls_total,
        "judge_cost_total_usd": round(judge_cost_total, 4),
        "total_usd": round(total, 4),
        "budget_cap_usd": budget_cap_usd,
        "exceeds_cap": total > budget_cap_usd,
        "assumptions": {
            "target_n_per_category": target_n_per_category,
            "n_categories": n_categories,
            "total_prompts": target_total_prompts,
            "judge_passes_per_image": judge_passes_per_image,
            "judge_cost_per_call_usd": judge_cost_per_call_usd,
            "include_stretch": include_stretch,
            "retry_rates_observed": {k: round(v, 4) for k, v in retry_rates.items()},
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dryruns", nargs="+", required=True, help="pilot CSV(s) to extrapolate from")
    p.add_argument("--target-n-per-category", type=int, default=10,
                   help="prompts per category in the full run (default 10)")
    p.add_argument("--n-categories", type=int, default=12,
                   help="number of prompt categories (default 12)")
    p.add_argument("--judge-passes-per-image", type=int, default=4,
                   help="2 judges × 2 temps = 4 default")
    p.add_argument("--judge-cost-per-call-usd", type=float, default=0.005,
                   help="rough per-call vision-LLM cost (default $0.005)")
    p.add_argument("--include-stretch", action="store_true")
    p.add_argument("--budget-cap", type=float, default=60.0)
    args = p.parse_args()

    out = estimate(
        dryruns=[Path(p_) for p_ in args.dryruns],
        target_n_per_category=args.target_n_per_category,
        n_categories=args.n_categories,
        judge_passes_per_image=args.judge_passes_per_image,
        judge_cost_per_call_usd=args.judge_cost_per_call_usd,
        include_stretch=args.include_stretch,
        budget_cap_usd=args.budget_cap,
    )

    print(json.dumps(out, indent=2))

    print("\n" + ("=" * 60))
    print(f"FULL RUN PROJECTION: ${out['total_usd']:.4f}")
    print(f"  - runner subtotal:  ${out['runner_subtotal_usd']:.4f}")
    print(f"  - judge subtotal:   ${out['judge_cost_total_usd']:.4f} "
          f"({out['judge_calls_total']} calls)")
    print(f"  - budget cap:       ${out['budget_cap_usd']:.2f}")
    if out["exceeds_cap"]:
        print(f"  *** PROJECTION EXCEEDS BUDGET CAP. Raise cap or reduce scope. ***")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
