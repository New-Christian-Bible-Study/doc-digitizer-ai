from __future__ import annotations

import argparse
from pathlib import Path

from PyPDF2 import PdfReader, PdfWriter


def parse_page_range(page_range: str, total_pages: int) -> tuple[int, int]:
    """
    Parse a 1-based inclusive page range string like '5-12' or a single page '7'.

    Returns
    -------
    (start_idx, end_idx)
        Zero-based inclusive start/end indices.
    """
    value = page_range.strip()
    if not value:
        raise ValueError("page range cannot be empty")

    if '-' in value:
        left, right = value.split('-', 1)
        try:
            start = int(left)
            end = int(right)
        except ValueError as e:
            raise ValueError(
                "page range must look like '5-12' or '7'"
            ) from e
    else:
        try:
            start = end = int(value)
        except ValueError as e:
            raise ValueError(
                "page range must look like '5-12' or '7'"
            ) from e

    if start < 1 or end < 1:
        raise ValueError("page numbers must be 1 or greater")
    if start > end:
        raise ValueError("range start cannot be greater than range end")
    if end > total_pages:
        raise ValueError(
            f"page range {start}-{end} exceeds document length ({total_pages} pages)"
        )

    return start - 1, end - 1



def build_default_output_path(input_pdf: Path, start_page: int, end_page: int) -> Path:
    if start_page == end_page:
        suffix = f"_page_{start_page}"
    else:
        suffix = f"_pages_{start_page}-{end_page}"
    return input_pdf.with_name(f"{input_pdf.stem}{suffix}.pdf")



def extract_page_range(
    input_pdf: str | Path,
    output_pdf: str | Path,
    page_range: str,
) -> Path:
    """
    Extract a page range from a PDF into a new PDF.

    Parameters
    ----------
    input_pdf : str | Path
        Source PDF path.
    output_pdf : str | Path
        Destination PDF path.
    page_range : str
        1-based inclusive range such as '1-10' or '3'.
    """
    input_pdf = Path(input_pdf)
    output_pdf = Path(output_pdf)

    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)
    start_idx, end_idx = parse_page_range(page_range, total_pages)

    writer = PdfWriter()
    for i in range(start_idx, end_idx + 1):
        writer.add_page(reader.pages[i])

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f:
        writer.write(f)

    return output_pdf



def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract only a specified page range from a PDF into a new PDF."
    )
    parser.add_argument("input_pdf", help="Path to the source PDF")
    parser.add_argument(
        "page_range",
        help="1-based inclusive page range, e.g. '1-10' or '7'",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Path to the output PDF (default: input_pages_START-END.pdf)",
    )

    args = parser.parse_args()

    input_pdf = Path(args.input_pdf)

    # We need total page count to build a nice default name only after validating range.
    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)
    start_idx, end_idx = parse_page_range(args.page_range, total_pages)
    start_page = start_idx + 1
    end_page = end_idx + 1

    output_pdf = (
        Path(args.output)
        if args.output
        else build_default_output_path(input_pdf, start_page, end_page)
    )

    result = extract_page_range(
        input_pdf=input_pdf,
        output_pdf=output_pdf,
        page_range=args.page_range,
    )
    print(f"Wrote extracted PDF to: {result}")


if __name__ == "__main__":
    main()
