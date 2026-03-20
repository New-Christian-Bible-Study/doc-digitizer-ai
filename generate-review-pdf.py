#!/usr/bin/env python3

import argparse
from pathlib import Path

from review_pdf_generator import ReviewPdfGenerator


def prompt_with_default(label: str, default: str) -> str:
    prompt = f'{label} [{default}]: ' if default else f'{label}: '
    value = input(prompt).strip()
    return value if value else default


def prompt_int(label: str, default: int) -> int:
    while True:
        raw_value = prompt_with_default(label, str(default))
        try:
            parsed_value = int(raw_value)
        except ValueError:
            print('Please enter a valid integer value.')
            continue

        if parsed_value < 1:
            print('Please enter a value greater than or equal to 1.')
            continue

        return parsed_value


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Create review PDFs from source PDFs in scan-pdfs/.'
    )
    parser.add_argument(
        '--working-dir',
        default='.',
        help='Working directory that contains scan-pdfs/ and review-pdfs/.',
    )
    args = parser.parse_args()

    generator = ReviewPdfGenerator(working_dir=Path(args.working_dir))

    try:
        state = generator.load_state()
    except ValueError as exc:
        print(f'Error reading state file: {exc}')
        return 1

    scan_default = state.get('last_scan_filename', '')
    scan_filename = prompt_with_default('Scan PDF filename', scan_default)

    start_default = generator.get_default_start_page(state)
    start_page = prompt_int('Start PDF page', start_default)

    end_page = prompt_int('End PDF page', start_page)

    try:
        scan_pdf_path = generator.resolve_scan_pdf(scan_filename)
        default_output_name = generator.build_default_filename(
            scan_pdf_path, start_page, end_page
        )
        output_filename = prompt_with_default(
            'Output review PDF filename', default_output_name
        )
        output_pdf = generator.create_review_pdf(
            scan_filename=scan_filename,
            start_page=start_page,
            end_page=end_page,
            output_filename=output_filename,
        )
    except ValueError as exc:
        print(f'Error: {exc}')
        return 1

    print(f'Created review PDF: {output_pdf}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
