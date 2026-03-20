#!/usr/bin/env python3

import argparse
import shutil
import sys
import termios
import tty
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


def list_scan_pdf_filenames(scan_dir: Path) -> list[str]:
    if not scan_dir.exists() or not scan_dir.is_dir():
        return []
    return sorted(
        file_path.name
        for file_path in scan_dir.iterdir()
        if file_path.is_file() and file_path.suffix.lower() == '.pdf'
    )


def prompt_scan_filename(
    label: str,
    default: str,
    scan_filenames: list[str],
) -> str:
    if not scan_filenames:
        return prompt_with_default(label, default)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return prompt_with_default(label, default)

    selected_index = (
        scan_filenames.index(default) if default in scan_filenames else 0
    )

    def truncate_for_terminal(text: str, max_width: int) -> str:
        if max_width <= 0:
            return ''
        if len(text) <= max_width:
            return text
        if max_width <= 3:
            return text[:max_width]
        return f'{text[:max_width - 3]}...'

    def render():
        columns = shutil.get_terminal_size(fallback=(80, 24)).columns
        content_width = max(10, columns - 2)
        sys.stdout.write('\x1b[2J\x1b[H')
        sys.stdout.write('Select scan PDF with up/down arrows and press Enter:\n\n')
        for index, filename in enumerate(scan_filenames):
            prefix = '> ' if index == selected_index else '  '
            display_name = truncate_for_terminal(filename, content_width)
            sys.stdout.write(f'{prefix}{display_name}\n')
        sys.stdout.write('\nPress Ctrl+C to cancel.\n')
        sys.stdout.flush()

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            render()
            key = sys.stdin.read(1)
            if key in ('\r', '\n'):
                sys.stdout.write('\x1b[2J\x1b[H')
                selected = scan_filenames[selected_index]
                sys.stdout.write(f'{label}: {selected}\n')
                sys.stdout.flush()
                return selected
            if key == '\x03':
                raise KeyboardInterrupt
            if key == '\x1b':
                next_one = sys.stdin.read(1)
                next_two = sys.stdin.read(1)
                if next_one == '[':
                    if next_two == 'A':
                        selected_index = (
                            selected_index - 1
                        ) % len(scan_filenames)
                    elif next_two == 'B':
                        selected_index = (
                            selected_index + 1
                        ) % len(scan_filenames)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


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
    scan_filenames = list_scan_pdf_filenames(generator.scan_dir)
    if not scan_filenames:
        print(
            f'No PDF files found in {generator.scan_dir}. '
            'Falling back to manual filename entry.'
        )
    scan_filename = prompt_scan_filename(
        'Scan PDF filename', scan_default, scan_filenames
    )

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
