#!/usr/bin/env python3
"""make_tables.py — render headline tables as PNGs for embedding in the blog.

Tables:
  table_1_pricing.png        — pricing.json snapshot in readable form
  table_2_headline.png       — model × quality × $/img × $/qpt × p50 lat × refusal
  table_3_latency.png        — model × p50 × p95 × mean × n_calls
  table_4_hidden_taxes.png   — model × refusal_rate × watermark_rate × retry_rate × quality_tier_inflation
  table_5_judge_agreement.png — model × judge_a × judge_b × spread × ensemble_quality
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent


def _f(v: Any, default=None):
    try:
        if v in (None, "", "N/A"):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _fmt_money(v):
    f = _f(v)
    return f"${f:.4f}" if f is not None else "—"


def _fmt_pct(v):
    f = _f(v)
    return f"{f*100:.1f}%" if f is not None else "—"


def _fmt_num(v, fmt="{:.2f}"):
    f = _f(v)
    return fmt.format(f) if f is not None else "—"


def render_table(rows: list[list[str]], headers: list[str], out: Path, title: str | None = None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig_height = max(1.5, 0.5 * len(rows) + 1.0 + (0.5 if title else 0))
    fig, ax = plt.subplots(figsize=(max(8, 1.5 * len(headers)), fig_height))
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=12, weight="bold", loc="left", pad=12)
    table = ax.table(cellText=rows, colLabels=headers, loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.4)
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)


def render_pricing_table(pricing: dict, out: Path) -> None:
    rows = []
    for model_id, block in pricing.items():
        if not isinstance(block, dict) or model_id.startswith("_"):
            continue
        for size, sblock in block.items():
            if not isinstance(sblock, dict) or size.startswith("_"):
                continue
            for q, price in sblock.items():
                if q.startswith("_"):
                    continue
                rows.append([model_id, size, q, _fmt_money(price)])
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    render_table(rows, ["Model", "Size", "Quality", "$/image"], out, title="Pricing table snapshot")


def render_headline_table(summaries: list[dict], out: Path) -> None:
    rows = []
    for s in summaries:
        rows.append([
            s.get("model_display") or s.get("model_id", "?"),
            _fmt_num(s.get("quality_score")),
            _fmt_money(s.get("cost_per_image_effective")),
            _fmt_money(s.get("cost_per_quality_point")),
            f"{int(_f(s.get('p50_latency_ms'), 0))} ms",
            _fmt_pct(s.get("refusal_rate")),
        ])
    render_table(
        rows,
        ["Model", "Quality (1-5)", "$/image", "$/qpt", "p50 latency", "Refusal"],
        out, title="Headline results",
    )


def render_latency_table(summaries: list[dict], out: Path) -> None:
    rows = []
    for s in summaries:
        rows.append([
            s.get("model_display") or s.get("model_id", "?"),
            f"{int(_f(s.get('p50_latency_ms'), 0))} ms",
            f"{int(_f(s.get('p95_latency_ms'), 0))} ms",
            f"{int(_f(s.get('mean_latency_ms'), 0))} ms",
            str(int(_f(s.get('n_total'), 0))),
        ])
    render_table(rows, ["Model", "p50", "p95", "mean", "n"], out, title="Latency")


def render_hidden_taxes_table(summaries: list[dict], out: Path) -> None:
    rows = []
    for s in summaries:
        rows.append([
            s.get("model_display") or s.get("model_id", "?"),
            _fmt_pct(s.get("refusal_rate")),
            _fmt_pct(s.get("watermark_rate")),
            _fmt_pct(s.get("retry_rate")),
            _fmt_money(s.get("cost_per_unrefused_image")),
        ])
    render_table(
        rows,
        ["Model", "Refusal", "Watermark", "Retry", "$/unrefused-image"],
        out, title="Hidden taxes",
    )


def render_judge_agreement_table(summaries: list[dict], out: Path) -> None:
    rows = []
    for s in summaries:
        rows.append([
            s.get("model_display") or s.get("model_id", "?"),
            _fmt_num(s.get("judge_a_mean")),
            _fmt_num(s.get("judge_b_mean")),
            _fmt_num(s.get("judge_ensemble_spread")),
            _fmt_num(s.get("quality_variance")),
        ])
    render_table(
        rows,
        ["Model", "Judge A mean", "Judge B mean", "|A-B|", "Variance"],
        out, title="Judge ensemble agreement",
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--results", default=str(REPO_ROOT / "pilot_results.csv"))
    p.add_argument("--pricing", default=str(REPO_ROOT / "pricing.json"))
    p.add_argument("--outdir", default=str(REPO_ROOT))
    args = p.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True)

    pricing = json.loads(Path(args.pricing).read_text())
    render_pricing_table(pricing, outdir / "table_1_pricing.png")
    print(f"  wrote {outdir / 'table_1_pricing.png'}")

    results_path = Path(args.results)
    if results_path.exists():
        with results_path.open() as f:
            summaries = list(csv.DictReader(f))
        render_headline_table(summaries, outdir / "table_2_headline.png")
        render_latency_table(summaries, outdir / "table_3_latency.png")
        render_hidden_taxes_table(summaries, outdir / "table_4_hidden_taxes.png")
        render_judge_agreement_table(summaries, outdir / "table_5_judge_agreement.png")
        for n in ("table_2_headline.png", "table_3_latency.png",
                  "table_4_hidden_taxes.png", "table_5_judge_agreement.png"):
            print(f"  wrote {outdir / n}")
    else:
        print(f"  SKIP results tables: {results_path} not found yet")

    return 0


if __name__ == "__main__":
    sys.exit(main())
