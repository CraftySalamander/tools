"""
PDF Compressor - Reduce the size of PDF files by recompressing embedded images
and rebuilding the document structure.

Works on a single PDF or recursively on a folder of PDFs, mirroring the
relative paths of the input folder into the output folder.

Installation
------------
Option 1 - conda:

    conda create -n compress_pdf python=3.11 -y
    conda activate compress_pdf
    conda install -c conda-forge pymupdf pillow -y

Option 2 - pip:

    pip install pymupdf pillow

Usage
-----
Compress a single PDF:

    python compress_pdf.py -i input.pdf -o output.pdf

Compress every PDF under a folder, recreating its tree under the output folder:

    python compress_pdf.py -i ./input_folder -o ./output_folder

Tuning:

    python compress_pdf.py -i input.pdf -o output.pdf --preset aggressive
    python compress_pdf.py -i input.pdf -o output.pdf --quality 60 --max-dpi 150
    python compress_pdf.py -i ./in -o ./out --grayscale --overwrite
    python compress_pdf.py -i input.pdf -o out.pdf --no-recompress-images

Notes
-----
- Images are only recompressed when it helps: images whose effective DPI is
  already below the target, or that have transparency masks, are kept as-is.
- The destination of a single-file run may be an existing directory, in which
  case the output PDF is created inside it with the same file name.
- Use --overwrite to allow the output to replace the input file in place.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
from dataclasses import dataclass

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
    except ImportError:
        sys.exit("PyMuPDF is not installed.\n" "Install the dependencies with:  pip install pymupdf pillow")

try:
    from PIL import Image  # type: ignore
except ImportError:
    sys.exit("Pillow is not installed.\nInstall the dependencies with:  pip install pymupdf pillow")


PRESETS: dict[str, dict[str, int]] = {
    # max_dpi caps image resolution, quality is the JPEG quality passed to Pillow
    "high": {"max_dpi": 300, "quality": 85},
    "balanced": {"max_dpi": 200, "quality": 70},
    "aggressive": {"max_dpi": 120, "quality": 45},
}

# Images smaller than this (either pixels or bytes) are not worth touching.
MIN_PIXELS = 50 * 50
MIN_BYTES = 2048


@dataclass
class Stats:
    files_ok: int = 0
    files_failed: int = 0
    bytes_in: int = 0
    bytes_out: int = 0


def format_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n:.0f} B"
        n /= 1024
    return f"{n:.1f} GB"


def human_report(name: str, before: int, after: int) -> str:
    pct = (1 - after / before) * 100 if before else 0.0
    return f"{name}: {format_size(before)} -> {format_size(after)} ({pct:+.0f}%)"


def process_image(doc, xref: int, page, quality: int, max_dpi: int, grayscale: bool) -> bytes | None:
    """Return recompressed JPEG bytes for an embedded image, or None to keep it."""
    try:
        info = doc.extract_image(xref)
    except Exception:
        return None
    raw = info.get("image", b"")
    width = info.get("width", 0) or 0
    height = info.get("height", 0) or 0
    ext = info.get("ext", "")
    if not raw or len(raw) < MIN_BYTES or width * height < MIN_PIXELS:
        return None

    # Effective DPI: source pixels divided by displayed width (max over placements).
    try:
        rects = page.get_image_rects(xref)
    except Exception:
        rects = []
    if not rects:
        return None
    shown_w = max(r.width for r in rects)
    if shown_w <= 0:
        return None
    effective_dpi = width / shown_w * 72.0
    scale = min(1.0, max_dpi / effective_dpi)
    if scale >= 1.0 and ext in ("jpeg", "jpg"):
        return None  # already a lossy format at or below the target DPI

    img = None
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode == "CMYK":
            return None  # saving CMYK as RGB would shift colors
        if img.mode in ("RGBA", "LA", "PA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        if grayscale:
            img = img.convert("L")
        if scale < 1.0:
            new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        compressed = out.getvalue()
    except Exception:
        return None
    finally:
        if img is not None:
            try:
                img.close()
            except Exception:
                pass

    return compressed if len(compressed) < len(raw) else None


def recompress_images(doc, quality: int, max_dpi: int, grayscale: bool) -> int:
    """Replace raster images in the open document. Returns how many changed."""
    replaced = 0
    seen: set[int] = set()
    for page in doc.pages():
        try:
            images = page.get_images(full=True)
        except Exception:
            continue
        for entry in images:
            xref = entry[0]
            smask = entry[1]
            if xref in seen or smask != 0:
                continue  # images with soft masks can break if swapped alone
            seen.add(xref)
            new_bits = process_image(doc, xref, page, quality, max_dpi, grayscale)
            if new_bits is None:
                continue
            try:
                page.replace_image(xref, stream=new_bits)
            except Exception:
                continue
            replaced += 1
    return replaced


def compress_pdf(src: str, dst: str, args, quiet: bool) -> tuple[bool, int, int]:
    """Compress one PDF. Returns (ok, size_before, size_after)."""
    size_before = os.path.getsize(src)
    same_path = os.path.abspath(src) == os.path.abspath(dst)
    doc = None
    try:
        doc = pymupdf.open(src)
    except Exception as exc:
        print(f"  [error] cannot open {src}: {exc}", file=sys.stderr)
        return False, size_before, size_before
    try:
        if doc.needs_pass:
            print(f"  [error] {src}: password protected, skipped", file=sys.stderr)
            return False, size_before, size_before

        touched = 0
        if not args.no_recompress_images:
            touched = recompress_images(doc, args.quality, args.max_dpi, args.grayscale)

        if same_path:
            # In-place: write next to the source, then swap only after saving
            # succeeded and the document is fully written.
            fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(os.path.abspath(dst)) or ".")
            os.close(fd)
            try:
                doc.save(tmp, garbage=4, deflate=True, deflate_fonts=True)
                doc.close()
                doc = None
                os.replace(tmp, dst)
                tmp = None
            finally:
                if tmp is not None and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        else:
            doc.save(dst, garbage=4, deflate=True, deflate_fonts=True)
    except Exception as exc:
        print(f"  [error] {src}: {exc}", file=sys.stderr)
        return False, size_before, size_before
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass

    size_after = os.path.getsize(dst) if os.path.exists(dst) else size_before
    if not quiet:
        detail = f", {touched} image(s) recompressed" if touched else ""
        print(f"  {src}{detail}")
        print(f"  -> {dst}")
        print(f"  {human_report(os.path.basename(dst), size_before, size_after)}")
    return True, size_before, size_after


def collect_pdf_files(input_path: str, output_path: str) -> list[tuple[str, str]]:
    """Return (input, output) pairs, one per PDF, with relative paths mirrored."""
    input_path = os.path.abspath(input_path)
    output_path = os.path.abspath(output_path)
    pairs: list[tuple[str, str]] = []
    if os.path.isfile(input_path):
        if os.path.isdir(output_path):
            dst = os.path.join(output_path, os.path.basename(input_path))
        else:
            dst = output_path
        pairs.append((input_path, dst))
        return pairs

    if not os.path.isdir(input_path):
        sys.exit(f"Input path does not exist: {input_path}")

    for root, _dirs, files in os.walk(input_path):
        for name in sorted(files):
            if not name.lower().endswith(".pdf"):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, input_path)
            pairs.append((full, os.path.join(output_path, rel)))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="compress_pdf",
        description="Compress a PDF file or every PDF found recursively in a folder, "
        "recreating the folder tree under the output folder.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-i", "--input", required=True, help="input PDF file, or folder scanned recursively for PDFs")
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="output PDF file, or output folder (tree mirrored from -i); "
        "may be an existing directory for single-file runs",
    )
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default="balanced",
        help="tuning preset; overridden by explicit --quality/--max-dpi",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=None,
        choices=range(10, 96),
        metavar="10-95",
        help="JPEG quality for recompressed images (overrides preset)",
    )
    parser.add_argument(
        "--max-dpi",
        type=int,
        default=None,
        metavar="DPI",
        help="cap on effective image resolution; higher keeps more detail (overrides preset)",
    )
    parser.add_argument("--grayscale", action="store_true", help="convert recompressed images to grayscale")
    parser.add_argument(
        "--no-recompress-images", action="store_true", help="structural optimization only: do not touch embedded images"
    )
    parser.add_argument("--overwrite", action="store_true", help="allow outputs to overwrite the input PDF in place")
    parser.add_argument("--quiet", action="store_true", help="only print errors and the final summary")
    args = parser.parse_args()

    preset = PRESETS[args.preset]
    if args.quality is None:
        args.quality = preset["quality"]
    if args.max_dpi is None:
        args.max_dpi = preset["max_dpi"]

    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    if not os.path.exists(input_path):
        parser.error(f"input path does not exist: {input_path}")

    pairs = collect_pdf_files(input_path, output_path)
    if not pairs:
        sys.exit(f"No PDF files found under {input_path}")

    stats = Stats()
    for src, dst in pairs:
        try:
            same = os.path.samefile(src, dst)
        except OSError:
            same = os.path.abspath(src) == os.path.abspath(dst)
        if same and not args.overwrite:
            print(f"  [skip] {src}: output would overwrite input (use --overwrite)")
            stats.files_failed += 1
            continue
        os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
        ok, before, after = compress_pdf(src, dst, args, quiet=args.quiet)
        if ok:
            stats.files_ok += 1
        else:
            stats.files_failed += 1
        stats.bytes_in += before
        stats.bytes_out += after

    print()
    print(f"Done: {stats.files_ok} file(s) compressed, {stats.files_failed} failed/skipped")
    if stats.files_ok:
        print(human_report("Total", stats.bytes_in, stats.bytes_out))
    return 0 if stats.files_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
