#!/usr/bin/env python3
"""smoke_test.py — end-to-end pipeline check with NO API calls.

Mocks Mesh /v1/images/generations and the vision-judge chat endpoint with
canned responses, runs the entire pipeline (runner → judge → aggregate → charts),
and verifies CSV columns, JSON parser, aggregator math, and chart-rendering all
work.

Per rules.md: this must pass before any live pilot. Free; ~5 seconds.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent


# ────────────────────────────────────────────────────────────────────────────────
# Tiny canned image (1x1 PNG)
# ────────────────────────────────────────────────────────────────────────────────

# Single transparent pixel PNG, base64-encoded (smallest valid PNG)
TINY_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


# ────────────────────────────────────────────────────────────────────────────────
# Mock objects
# ────────────────────────────────────────────────────────────────────────────────

class _MockResponse:
    def __init__(self, status_code: int, json_payload=None, content_bytes: bytes = b""):
        self.status_code = status_code
        self._json = json_payload
        self.content = content_bytes
        self.text = json.dumps(json_payload) if json_payload else ""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _make_image_gen_response():
    return _MockResponse(200, json_payload={
        "created": int(time.time()),
        "data": [{"b64_json": TINY_PNG_B64}],
    })


def _make_judge_response(scores: dict | None = None):
    scores = scores or {
        "adherence": 4, "aesthetic": 4, "photoreal": 3,
        "text": "N/A", "anatomy": 5, "note": "smoke test mock",
    }
    return _MockResponse(200, json_payload={
        "choices": [{
            "message": {"content": json.dumps(scores)}
        }]
    })


def mock_requests_post(url, **kwargs):
    if "images/generations" in url:
        return _make_image_gen_response()
    if "chat/completions" in url:
        return _make_judge_response()
    return _MockResponse(404, json_payload={"error": "unmocked"})


def mock_requests_get(url, **kwargs):
    # Image download — return tiny PNG bytes
    import base64
    return _MockResponse(200, content_bytes=base64.b64decode(TINY_PNG_B64))


# ────────────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────────────

def test_pricing_lookup():
    """Pricing table loads and lookups succeed for the pilot lineup."""
    from runner import lookup_price
    from models import MODELS
    print("  - pricing lookups for pilot lineup …", end=" ")
    for model_id, _disp, size, quality, _tier in MODELS:
        price = lookup_price(model_id, size, quality)
        assert price > 0, f"non-positive price for {model_id}"
    print("OK")


def test_pricing_miss_raises():
    """A missing tuple must raise KeyError (rules.md: never default to $0)."""
    from runner import lookup_price
    print("  - pricing miss raises KeyError …", end=" ")
    try:
        lookup_price("nonexistent/model-xyz", "1024x1024", "high")
    except KeyError:
        print("OK")
        return
    raise AssertionError("lookup_price did not raise on missing model")


def test_runner_pipeline_mocked(tmpdir: Path):
    """Run runner.py via mocked requests on 2 prompts × 2 models."""
    from runner import run_benchmark
    from models import MODELS

    # Use only the first 2 pilot models for speed
    sub_models = MODELS[:2]

    # Tiny task set
    task = {
        "items": [
            {"id": "T2I-SMK1", "category": "photoreal_portrait",
             "prompt": "smoke test prompt 1", "eval_focus": ["test"],
             "vqa_questions": ["test?"], "has_text_to_render": False},
            {"id": "T2I-SMK2", "category": "typography",
             "prompt": "smoke test prompt 2", "eval_focus": ["test"],
             "vqa_questions": ["test?"], "has_text_to_render": True},
        ]
    }
    task_path = tmpdir / "smoke_task.json"
    task_path.write_text(json.dumps(task))
    out_path = tmpdir / "smoke_runs.csv"

    print("  - runner.py mocked end-to-end (2×2) …", end=" ")
    with patch("requests.post", side_effect=mock_requests_post), \
         patch("requests.get", side_effect=mock_requests_get):
        rc = run_benchmark(
            task_path=task_path, out_path=out_path,
            models=sub_models, limit=2, budget_cap_usd=10.0,
            base_url="https://mock.test/v1", api_key="mock-key",
            max_retries=0,
        )
    assert rc == 0, f"runner returned {rc}"

    rows = list(csv.DictReader(out_path.open()))
    assert len(rows) == 4, f"expected 4 rows, got {len(rows)}"
    assert all(r["local_path"] for r in rows), "missing local_path"
    print(f"OK ({len(rows)} rows)")


def test_judge_vision_mocked(tmpdir: Path):
    """Run judge_vision.py on the smoke runs via mocked requests."""
    from judge_vision import judge_runs
    from models import VISION_JUDGES, JUDGE_TEMPS

    runs_path = tmpdir / "smoke_runs.csv"
    task_path = tmpdir / "smoke_task.json"
    side_path = tmpdir / "smoke_vision.csv"

    print("  - judge_vision.py mocked …", end=" ")
    with patch("requests.post", side_effect=mock_requests_post):
        rc = judge_runs(
            runs_path=runs_path, task_path=task_path, out_path=side_path,
            judges=list(VISION_JUDGES), temps=list(JUDGE_TEMPS),
            base_url="https://mock.test/v1", api_key="mock-key",
        )
    assert rc == 0
    judge_rows = list(csv.DictReader(side_path.open()))
    # 4 runs × 2 judges × 2 temps = 16 judge rows
    assert len(judge_rows) == 16, f"expected 16 judge rows, got {len(judge_rows)}"
    print(f"OK ({len(judge_rows)} judge rows)")


def test_judge_merge_and_aggregate(tmpdir: Path):
    """Run judge.py merge + aggregate.py on the smoke CSVs."""
    from judge import merge
    from models import VISION_JUDGES
    from aggregate import aggregate

    runs_path = tmpdir / "smoke_runs.csv"
    vision_path = tmpdir / "smoke_vision.csv"
    auto_path = tmpdir / "smoke_auto.csv"  # empty
    judged_path = tmpdir / "smoke_judged.csv"

    # write empty auto sidecar (auto metrics off in smoke test)
    with auto_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "run_id", "model_id", "prompt_id",
            "vqa_score", "clip_score", "aesthetic_score", "auto_backend_notes"
        ])
        writer.writeheader()

    print("  - judge.py merge …", end=" ")
    rc = merge(
        runs_path=runs_path, vision_path=vision_path, auto_path=auto_path,
        out_path=judged_path,
        judges_in_order=[j[0] for j in VISION_JUDGES],
    )
    assert rc == 0
    judged_rows = list(csv.DictReader(judged_path.open()))
    assert len(judged_rows) == 4
    # Verify quality score got computed
    for r in judged_rows:
        assert r["vision_quality_score"], f"missing quality_score in {r}"
    print(f"OK ({len(judged_rows)} judged rows)")

    print("  - aggregate.py …", end=" ")
    summaries = aggregate([judged_path], by_category=False)
    assert len(summaries) == 2, f"expected 2 model summaries, got {len(summaries)}"
    for s in summaries:
        assert s["quality_score"] is not None
        assert s["effective_cost_usd"] > 0
        assert s["cost_per_quality_point"] is not None
    print(f"OK ({len(summaries)} model summaries)")


def test_chart_renderer_optional(tmpdir: Path):
    """If matplotlib is installed, render a chart from the smoke aggregate."""
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        print("  - chart renderer: SKIP (matplotlib not installed)")
        return
    from aggregate import aggregate
    from make_charts import render_chart_quality_vs_cost
    judged_path = tmpdir / "smoke_judged.csv"
    summaries = aggregate([judged_path], by_category=False)
    chart_path = tmpdir / "smoke_chart.png"
    print("  - make_charts.render_chart_quality_vs_cost …", end=" ")
    render_chart_quality_vs_cost(summaries, chart_path)
    assert chart_path.exists() and chart_path.stat().st_size > 1000
    print(f"OK ({chart_path.stat().st_size} bytes)")


def main() -> int:
    print("smoke_test.py — verifying pipeline end-to-end with mocked Mesh\n")

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # Redirect IMAGES_DIR to tmp during the test so we don't pollute the real images/
        import runner
        original_images = runner.IMAGES_DIR
        runner.IMAGES_DIR = tmp / "images"
        runner.IMAGES_DIR.mkdir(exist_ok=True)
        try:
            print("# Pricing")
            test_pricing_lookup()
            test_pricing_miss_raises()

            print("\n# Runner")
            test_runner_pipeline_mocked(tmp)

            # judge_vision expects images at local_path relative to REPO_ROOT.
            # In smoke test we wrote them under tmp/images; rewrite local_path
            # in the CSV to absolute paths so the judge can find them.
            runs_csv = tmp / "smoke_runs.csv"
            rows = list(csv.DictReader(runs_csv.open()))
            with runs_csv.open("w", newline="") as f:
                # local_path in CSV is relative to REPO_ROOT; for the smoke test,
                # we patched runner.IMAGES_DIR, so the saved files live under tmp.
                # Rewrite path to absolute for the judge.
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                for r in rows:
                    if r.get("local_path"):
                        # The original path was REPO_ROOT/images/{stem}.png, but we
                        # patched IMAGES_DIR to tmp/images, so the actual file is there.
                        original_stem = Path(r["local_path"]).name
                        r["local_path"] = str(tmp / "images" / original_stem)
                    writer.writerow(r)

            # Also: judge_vision.py opens REPO_ROOT/local_path; if local_path is
            # absolute, that's fine. Verify.

            print("\n# Judge")
            test_judge_vision_mocked(tmp)
            test_judge_merge_and_aggregate(tmp)

            print("\n# Charts (optional)")
            test_chart_renderer_optional(tmp)
        finally:
            runner.IMAGES_DIR = original_images

    print("\n✓ smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
