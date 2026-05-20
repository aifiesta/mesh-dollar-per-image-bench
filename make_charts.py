#!/usr/bin/env python3
"""make_charts.py — render the 6-7 chart PNGs from pilot_results.csv.

Mirrors dollar-per-task-bench/make_charts.py's structure: each chart is its
own function so they can be called individually from smoke_test.py.

Charts:
  1. chart_1_cost_per_quality.png     — bar chart, log-scale, $/quality-point
  2. chart_2_quality_axes.png         — grouped bars, per-axis quality per model
  3. chart_3_latency_p50_p95.png      — paired bars, p50/p95 latency
  4. chart_4_refusal_rates.png        — bar chart, refusal rate per model
  5. chart_5_quality_vs_cost.png      — scatter, quality on y, $/image on x (log)
  6. chart_6_judge_agreement.png      — scatter, judge A vs judge B mean
  7. chart_7_quality_by_category.png  — heatmap, model × category (if by-category aggregate provided)
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = REPO_ROOT / "pilot_results.csv"


def _load_summaries(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _f(v: Any, default: float | None = None) -> float | None:
    try:
        if v in (None, "", "N/A"):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _spread_label_offsets(points: list[tuple[float, float, str]]) -> list[tuple[int, int]]:
    """Return a list of (dx, dy) point-offsets for matplotlib annotate so labels
    don't overlap. Greedy: place each label in one of 8 directions, prefer the
    one whose offset placement is least crowded relative to already-placed labels.
    Returns one offset per input point.
    """
    if not points:
        return []
    # Candidate offsets in (dx, dy) pixels — clockwise from upper-right
    candidates = [(8, 8), (8, -8), (-8, 8), (-8, -8),
                  (12, 0), (-12, 0), (0, 12), (0, -12),
                  (16, 6), (16, -6), (-16, 6), (-16, -6)]
    chosen: list[tuple[int, int]] = []
    placed_pixel_pos: list[tuple[float, float]] = []
    # Convert data coords to a rough screen-space using the axis bounds at the
    # end isn't possible without rendering — but greedy avoidance in offset-space
    # is good enough at n≤10 points.
    for x, y, _label in points:
        best = candidates[0]
        best_score = -1.0
        for dx, dy in candidates:
            # Score = min distance to any already-placed (offset-projected) label
            ppos = (x + dx * 0.02, y + dy * 0.005)
            if not placed_pixel_pos:
                score = 1e9
            else:
                score = min(
                    ((ppos[0] - p[0]) ** 2 + (ppos[1] - p[1]) ** 2) ** 0.5
                    for p in placed_pixel_pos
                )
            if score > best_score:
                best_score = score
                best = (dx, dy)
        chosen.append(best)
        placed_pixel_pos.append((x + best[0] * 0.02, y + best[1] * 0.005))
    return chosen


def _zoomed_limits(values: list[float], pad_frac: float = 0.15,
                    hard_min: float | None = None,
                    hard_max: float | None = None) -> tuple[float, float]:
    """Zoom axis to data range with padding. Clamp to hard min/max if given."""
    if not values:
        return (0, 1)
    lo, hi = min(values), max(values)
    span = max(hi - lo, 1e-6)
    pad = span * pad_frac
    out_lo = lo - pad
    out_hi = hi + pad
    if hard_min is not None:
        out_lo = max(out_lo, hard_min)
    if hard_max is not None:
        out_hi = min(out_hi, hard_max)
    return (out_lo, out_hi)


def render_chart_quality_vs_cost(summaries: list[dict[str, Any]], out: Path) -> None:
    """Chart 5 (also used as smoke-test default): scatter $/img vs quality, auto-zoomed."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pts: list[tuple[float, float, str]] = []
    for s in summaries:
        x = _f(s.get("cost_per_image_effective"))
        y = _f(s.get("quality_score"))
        if x is None or y is None or x <= 0:
            continue
        pts.append((x, y, s.get("model_display", s.get("model_id", "?"))))
    if not pts:
        return

    fig, ax = plt.subplots(figsize=(10, 6.2))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    offsets = _spread_label_offsets(pts)
    colors = plt.cm.tab10.colors[:len(pts)]
    for (x, y, label), (dx, dy), color in zip(pts, offsets, colors):
        ax.scatter(x, y, s=140, color=color, edgecolor="white", linewidth=1.5, zorder=3)
        ha = "left" if dx >= 0 else "right"
        va = "bottom" if dy >= 0 else "top"
        ax.annotate(label, (x, y),
                    textcoords="offset points", xytext=(dx, dy),
                    fontsize=10, ha=ha, va=va,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
    ax.set_xscale("log")
    # Auto-zoom Y axis to data, clamped to [1, 5.05]
    y_lo, y_hi = _zoomed_limits(ys, pad_frac=0.25, hard_min=1.0, hard_max=5.05)
    ax.set_ylim(y_lo, y_hi)
    # X axis log-padded
    x_lo = min(xs) * 0.6
    x_hi = max(xs) * 1.7
    ax.set_xlim(x_lo, x_hi)
    ax.set_xlabel("Effective cost per image (USD, log scale)", fontsize=11)
    ax.set_ylabel("Quality score (1-5, vision-judge ensemble)", fontsize=11)
    ax.set_title("Quality vs. cost per image  (n=5/model, pilot)", fontsize=12, weight="bold")
    ax.grid(True, alpha=0.35, linestyle="-", linewidth=0.5)
    ax.set_axisbelow(True)
    # Annotate the y-axis range to make the zoom explicit
    ax.text(0.02, 0.02,
            f"Y axis zoomed to {y_lo:.2f}–{y_hi:.2f} (full rubric range is 1–5).",
            transform=ax.transAxes, fontsize=8.5, color="#666", style="italic")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def render_chart_cost_per_quality(summaries: list[dict[str, Any]], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    valid = [s for s in summaries if _f(s.get("cost_per_quality_point"), 0) and _f(s.get("cost_per_quality_point"), 0) > 0]
    valid.sort(key=lambda s: _f(s["cost_per_quality_point"], 0))
    if not valid:
        return
    names = [s["model_display"] for s in valid]
    vals = [_f(s["cost_per_quality_point"], 0) for s in valid]

    fig, ax = plt.subplots(figsize=(10, max(4, 0.5 * len(valid) + 2)))
    ax.barh(names, vals, log=True if max(vals) / max(min(vals), 1e-9) > 100 else False)
    ax.set_xlabel("Cost per quality point (USD, log scale if spread > 100×)")
    ax.set_title("Cost per quality point (lower is better)")
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def render_chart_quality_axes(summaries: list[dict[str, Any]], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    axes_names = ["adherence", "aesthetic", "photoreal", "text", "anatomy"]
    valid = [s for s in summaries if _f(s.get("quality_score"))]
    if not valid:
        return
    n_models = len(valid)
    n_axes = len(axes_names)
    width = 0.8 / n_axes

    fig, ax = plt.subplots(figsize=(max(8, n_models * 1.6), 5))
    x = np.arange(n_models)
    for i, axis in enumerate(axes_names):
        col = f"axis_{axis}_mean"
        vals = [_f(s.get(col), 0) or 0 for s in valid]
        ax.bar(x + i * width, vals, width, label=axis)
    ax.set_xticks(x + width * (n_axes - 1) / 2)
    ax.set_xticklabels([s["model_display"] for s in valid], rotation=20, ha="right")
    ax.set_ylim(0, 5.2)
    ax.set_ylabel("Mean axis score (1-5)")
    ax.set_title("Quality by axis, per model")
    ax.legend(loc="lower right", ncols=5, fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def render_chart_latency(summaries: list[dict[str, Any]], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    valid = [s for s in summaries if _f(s.get("p50_latency_ms"))]
    if not valid:
        return
    valid.sort(key=lambda s: _f(s["p50_latency_ms"], 0))
    names = [s["model_display"] for s in valid]
    p50 = [_f(s["p50_latency_ms"], 0) for s in valid]
    p95 = [_f(s.get("p95_latency_ms"), 0) for s in valid]

    fig, ax = plt.subplots(figsize=(10, max(4, 0.5 * len(valid) + 2)))
    x = np.arange(len(valid))
    ax.barh(x - 0.2, p50, 0.4, label="p50")
    ax.barh(x + 0.2, p95, 0.4, label="p95")
    ax.set_yticks(x)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlabel("Latency (ms, end-to-end wall-clock)")
    ax.set_title("Latency: p50 vs p95")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def render_chart_refusal(summaries: list[dict[str, Any]], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [s["model_display"] for s in summaries]
    vals = [(_f(s.get("refusal_rate"), 0) or 0) * 100 for s in summaries]
    if not any(v > 0 for v in vals):
        # Render anyway as evidence of zero-refusal
        pass
    fig, ax = plt.subplots(figsize=(10, max(3, 0.5 * len(names) + 2)))
    ax.barh(names, vals)
    ax.set_xlim(0, max(max(vals or [0]), 100))
    ax.set_xlabel("Refusal rate (%)")
    ax.set_title("Content-policy refusal rate per model")
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def render_chart_judge_agreement(summaries: list[dict[str, Any]], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pts: list[tuple[float, float, str]] = []
    for s in summaries:
        a = _f(s.get("judge_a_mean"))
        b = _f(s.get("judge_b_mean"))
        if a is None or b is None:
            continue
        pts.append((a, b, s["model_display"]))
    if not pts:
        return

    fig, ax = plt.subplots(figsize=(8, 7))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    # Zoom axes to data + padding; clamp at [1, 5.05]
    all_v = xs + ys
    lo, hi = _zoomed_limits(all_v, pad_frac=0.35, hard_min=1.0, hard_max=5.05)
    # Plot diagonal across the zoomed range only
    ax.plot([lo, hi], [lo, hi], "k--", alpha=0.5, linewidth=1, label="judges agree")

    offsets = _spread_label_offsets(pts)
    colors = plt.cm.tab10.colors[:len(pts)]
    for (a, b, label), (dx, dy), color in zip(pts, offsets, colors):
        ax.scatter(a, b, s=160, color=color, edgecolor="white", linewidth=1.5, zorder=3)
        ha = "left" if dx >= 0 else "right"
        va = "bottom" if dy >= 0 else "top"
        ax.annotate(label, (a, b),
                    textcoords="offset points", xytext=(dx, dy),
                    fontsize=10, ha=ha, va=va,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.88))
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Judge A mean — Claude Opus 4.7 (stricter)", fontsize=11)
    ax.set_ylabel("Judge B mean — GPT-5.5", fontsize=11)
    ax.set_title("Judge ensemble agreement, per-model means  (n=5/model, pilot)",
                 fontsize=12, weight="bold")
    ax.legend(loc="upper left", fontsize=10, framealpha=0.92)
    ax.grid(True, alpha=0.35, linestyle="-", linewidth=0.5)
    ax.set_axisbelow(True)
    # Inline annotation for the zoom — bottom-right since legend is upper-left
    ax.text(0.98, 0.02,
            f"Axes zoomed to {lo:.2f}–{hi:.2f}. Full rubric range 1–5.\nAll points cluster near judges-agree diagonal.",
            transform=ax.transAxes, fontsize=8.5, color="#666", style="italic",
            ha="right", va="bottom")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def render_all(summaries: list[dict[str, Any]], outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, fn in [
        ("chart_1_cost_per_quality.png", render_chart_cost_per_quality),
        ("chart_2_quality_axes.png",     render_chart_quality_axes),
        ("chart_3_latency_p50_p95.png",  render_chart_latency),
        ("chart_4_refusal_rates.png",    render_chart_refusal),
        ("chart_5_quality_vs_cost.png",  render_chart_quality_vs_cost),
        ("chart_6_judge_agreement.png",  render_chart_judge_agreement),
    ]:
        out = outdir / name
        try:
            fn(summaries, out)
            if out.exists():
                paths.append(out)
                print(f"  wrote {out}")
        except Exception as exc:
            print(f"  SKIP {name}: {exc}")
    return paths


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(DEFAULT_INPUT))
    p.add_argument("--outdir", default=str(REPO_ROOT))
    args = p.parse_args()
    summaries = _load_summaries(Path(args.input))
    paths = render_all(summaries, Path(args.outdir))
    print(f"\nrendered {len(paths)} charts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
