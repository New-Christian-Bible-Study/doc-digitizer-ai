from __future__ import annotations

import argparse
import copy
from pathlib import Path

from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import RectangleObject


def crop_page_half(page, left: bool, split_ratio: float = 0.5):
    """
    Return a deep-copied page cropped to the left or right half.

    split_ratio=0.5 means split exactly down the middle.
    """
    new_page = copy.deepcopy(page)

    box = page.mediabox
    x0 = float(box.left)
    y0 = float(box.bottom)
    x1 = float(box.right)
    y1 = float(box.top)

    width = x1 - x0
    split_x = x0 + width * split_ratio

    if left:
        new_rect = RectangleObject([x0, y0, split_x, y1])
    else:
        new_rect = RectangleObject([split_x, y0, x1, y1])

    # Keep the visible/cropped area consistent across viewers.
    new_page.mediabox = new_rect
    new_page.cropbox = new_rect

    # Update other boxes if present.
    try:
        new_page.trimbox = RectangleObject(new_rect)
    except Exception:
        pass
    try:
        new_page.bleedbox = RectangleObject(new_rect)
    except Exception:
        pass
    try:
        new_page.artbox = RectangleObject(new_rect)
    except Exception:
        pass

    return new_page


def split_double_page_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    split_ratio: float = 0.5,
    rtl: bool = False,
) -> Path:
    """
    Split each page of a double-page PDF into two single pages.

    Parameters
    ----------
    input_pdf : str | Path
        Path to the source PDF containing double-page spreads.
    output_pdf : str | Path
        Path to the output PDF with single pages.
    split_ratio : float
        Horizontal split location as a fraction of page width.
        0.5 = exact middle, 0.48 = slightly left of center, etc.
    rtl : bool
        If True, output right page first, then left page.
        Useful for right-to-left books.
    """
    input_pdf = Path(input_pdf)
    output_pdf = Path(output_pdf)

    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")
    if not (0.0 < split_ratio < 1.0):
        raise ValueError("split_ratio must be between 0 and 1 (exclusive).")

    reader = PdfReader(str(input_pdf))
    writer = PdfWriter()

    for page in reader.pages:
        left_page = crop_page_half(page, left=True, split_ratio=split_ratio)
        right_page = crop_page_half(page, left=False, split_ratio=split_ratio)

        if rtl:
            writer.add_page(right_page)
            writer.add_page(left_page)
        else:
            writer.add_page(left_page)
            writer.add_page(right_page)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f:
        writer.write(f)

    return output_pdf


def build_default_output_path(input_pdf: Path) -> Path:
    return input_pdf.with_name(f"{input_pdf.stem}_split.pdf")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split each double-page PDF page down the middle into two single pages."
    )
    parser.add_argument("input_pdf", help="Path to the input double-page PDF")
    parser.add_argument(
        "-o",
        "--output",
        help="Path to the output PDF (default: INPUTNAME_split.pdf)",
        default=None,
    )
    parser.add_argument(
        "--split-ratio",
        type=float,
        default=0.5,
        help="Where to split across the page width (default: 0.5 = center)",
    )
    parser.add_argument(
        "--rtl",
        action="store_true",
        help="Output right page first, then left page",
    )

    args = parser.parse_args()

    input_pdf = Path(args.input_pdf)
    output_pdf = Path(args.output) if args.output else build_default_output_path(input_pdf)

    result = split_double_page_pdf(
        input_pdf=input_pdf,
        output_pdf=output_pdf,
        split_ratio=args.split_ratio,
        rtl=args.rtl,
    )
    print(f"Wrote split PDF to: {result}")


if __name__ == "__main__":
    main()
