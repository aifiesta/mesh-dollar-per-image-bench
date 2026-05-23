#!/usr/bin/env python3
"""build_pdf.py — regenerate paper.pdf from paper.html.

The paper references ~56 PNGs at full 1024×1024 resolution. Chrome's
default PDF embedder would produce a ~90 MB file. We compress images to
JPEG (600 px max dim, quality 80) into a temp dir, swap the references
in a temp HTML, render to PDF, and clean up.

Requires:
  - Pillow (`pip install pillow`)
  - Google Chrome (or Chromium) at the path below
"""
from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow required: pip install pillow")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SRC_IMAGES = REPO / "images"
PDF_IMAGES = HERE / "images_pdf"
PAPER_HTML = HERE / "paper.html"
PAPER_PDF_HTML = HERE / "paper_pdf.html"
PAPER_PDF = HERE / "mesh-dollar-per-image-bench.pdf"

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]
MAX_DIM = 600
QUALITY = 80


def _find_chrome() -> str:
    for p in CHROME_PATHS:
        if Path(p).exists():
            return p
    raise SystemExit("No Chrome/Chromium found. Install one or edit CHROME_PATHS.")


def compress_images() -> tuple[int, int]:
    if PDF_IMAGES.exists():
        shutil.rmtree(PDF_IMAGES)
    PDF_IMAGES.mkdir()
    total_src = total_dst = 0
    n = 0
    for p in sorted(SRC_IMAGES.rglob("*.png")):
        if p.name.startswith("sanity_"):
            continue
        with Image.open(p) as im:
            im.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
            if im.mode != "RGB":
                im = im.convert("RGB")
            # Compose flat name from provider/model/stem so it matches rewrite_paths.
            rel = p.relative_to(SRC_IMAGES).with_suffix("")
            parts = rel.parts
            if len(parts) == 3:
                flat = f"{parts[0]}_{parts[1]}__{parts[2]}.jpg"
            else:
                flat = "_".join(parts) + ".jpg"
            out = PDF_IMAGES / flat
            im.save(out, "JPEG", quality=QUALITY, optimize=True)
        total_src += p.stat().st_size
        total_dst += out.stat().st_size
        n += 1
    return n, total_dst


def rewrite_paths() -> None:
    html = PAPER_HTML.read_text()
    # Flatten ../images/<provider>/<model>/<id>.png → images_pdf/<provider>_<model>__<id>.jpg
    def _flat(m: "re.Match[str]") -> str:
        provider, model, stem = m.group(1), m.group(2), m.group(3)
        return f"images_pdf/{provider}_{model}__{stem}.jpg"
    out = re.sub(r"\.\./images/([^/]+)/([^/]+)/([^./\"]+)\.(png|webp)", _flat, html)
    # Rewrite chart/table refs to point at sibling dirs (kept absolute via ../)
    PAPER_PDF_HTML.write_text(out)


def render_pdf() -> int:
    chrome = _find_chrome()
    cmd = [
        chrome,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--no-margins",
        "--virtual-time-budget=30000",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={PAPER_PDF}",
        "--print-to-pdf-no-header",
        f"file://{PAPER_PDF_HTML.resolve()}",
    ]
    return subprocess.call(cmd)


def cleanup() -> None:
    if PAPER_PDF_HTML.exists():
        PAPER_PDF_HTML.unlink()
    if PDF_IMAGES.exists():
        shutil.rmtree(PDF_IMAGES)


def main() -> int:
    print("compressing images for PDF ...")
    n, dst_bytes = compress_images()
    print(f"  {n} images → {dst_bytes / 1024 / 1024:.1f} MB")
    print("rewriting image paths in paper_pdf.html ...")
    rewrite_paths()
    print("rendering PDF via Chrome headless ...")
    rc = render_pdf()
    if rc != 0:
        print(f"chrome exited {rc}; leaving temp files for debugging")
        return rc
    pdf_mb = PAPER_PDF.stat().st_size / 1024 / 1024
    print(f"wrote {PAPER_PDF} ({pdf_mb:.1f} MB)")
    cleanup()
    print("cleaned temp files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
