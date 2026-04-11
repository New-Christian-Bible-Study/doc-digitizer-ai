#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

import questionary

from chunk_generator import ChunkGenerator
from chunk_lines_model import resolve_chunk_pdf_dir


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


def list_source_filenames(source_dir: Path) -> list[str]:
    if not source_dir.exists() or not source_dir.is_dir():
        return []
    return sorted(
        file_path.name
        for file_path in source_dir.iterdir()
        if file_path.is_file() and file_path.suffix.lower() == '.pdf'
    )


def prompt_source_filename(
    label: str,
    default: str,
    source_filenames: list[str],
) -> str:
    if not source_filenames:
        return prompt_with_default(label, default)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return prompt_with_default(label, default)

    default_choice = (
        default if default in source_filenames else source_filenames[0]
    )
    selected = questionary.select(
        f'{label}:',
        choices=source_filenames,
        default=default_choice,
        qmark='>',
    ).ask()
    if selected is None:
        raise KeyboardInterrupt
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Create chunks from sources in source-pdfs/.'
    )
    parser.add_argument(
        '--working-dir',
        default='.',
        help='Working directory that contains source-pdfs/ and chunk-pdfs/.',
    )
    parser.add_argument(
        '--chunk-dir',
        type=Path,
        default=None,
        help=(
            'Directory for extracted chunk PDFs (default: working-dir/chunk-pdfs). '
            'Relative paths are resolved under working-dir.'
        ),
    )
    args = parser.parse_args()

    working_path = Path(args.working_dir).resolve()
    chunk_pdf_kw = {}
    if args.chunk_dir is not None:
        chunk_pdf_kw['chunk_pdf_dir'] = resolve_chunk_pdf_dir(working_path, args.chunk_dir)
    generator = ChunkGenerator(working_dir=working_path, **chunk_pdf_kw)

    try:
        state = generator.load_state()
    except ValueError as exc:
        print(f'Error reading state file: {exc}')
        return 1

    source_default = state.get('last_source_filename', '')
    source_filenames = list_source_filenames(generator.scan_dir)
    if not source_filenames:
        print(
            f'No PDF files found in {generator.scan_dir}. '
            'Falling back to manual filename entry.'
        )
    source_filename = prompt_source_filename(
        'Source filename', source_default, source_filenames
    )

    start_default = generator.get_default_start_page(state)
    start_page = prompt_int('Start page', start_default)

    end_page = prompt_int('End page', start_page)

    try:
        source_path = generator.resolve_source(source_filename)
        default_output_name = generator.build_default_filename(
            source_path, start_page, end_page
        )
        output_filename = prompt_with_default(
            'Output chunk filename', default_output_name
        )
        output = generator.create_chunk(
            source_filename=source_filename,
            start_page=start_page,
            end_page=end_page,
            output_filename=output_filename,
        )
    except ValueError as exc:
        print(f'Error: {exc}')
        return 1

    print(f'Created chunk: {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
