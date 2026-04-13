#!/usr/bin/env python3

import argparse
import json
import re
import sys
from pathlib import Path

import jsonschema

SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = SCRIPT_DIR / 'transcription.schema.json'


def load_schema() -> dict:
    with SCHEMA_PATH.open('r', encoding='utf-8') as schema_file:
        return json.load(schema_file)


def strip_transcription_inline_markup(text: str) -> str:
    '''Remove common inline bold/italic/code markers from one line of text.

    Best-effort for CER-style comparison: ``**bold**``, ``*italic*``, ``__..__``,
    ``_.._``, and `` `mono` `` forms are unwrapped. Odd nesting, unmatched pairs,
    or asterisks used as punctuation may be altered.
    '''
    s = text
    for _ in range(8):
        prev = s
        s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
        s = re.sub(r'__(.+?)__', r'\1', s)
        s = re.sub(r'`([^`]+)`', r'\1', s)
        s = re.sub(r'\*(.+?)\*', r'\1', s)
        s = re.sub(r'_(.+?)_', r'\1', s)
        if s == prev:
            break
    return s


def lines_to_adoc_body(payload: dict, *, strip_inline_markup: bool = False) -> str:
    lines = payload.get('lines')
    if not isinstance(lines, list):
        return ''
    texts = []
    for item in lines:
        if isinstance(item, dict) and 'text' in item:
            t = item.get('text', '')
            if not isinstance(t, str):
                t = ''
            if strip_inline_markup:
                t = strip_transcription_inline_markup(t)
            texts.append(t)
    return '\n'.join(texts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            'Convert a transcription JSON file (*_raw.json or *_final.json) to AsciiDoc '
            'by joining each line\'s "text" field in order with newlines.'
        ),
        epilog=(
            'By default the document is validated against transcription.schema.json '
            'before writing.'
        ),
    )
    parser.add_argument(
        'json_files',
        nargs='+',
        type=Path,
        metavar='JSON',
        help='Path to a transcription JSON file.',
    )
    parser.add_argument(
        '-o',
        '--output',
        type=Path,
        help='Output .adoc path (only when exactly one input JSON is given).',
    )
    parser.add_argument(
        '--skip-schema-validation',
        action='store_true',
        help=(
            'Skip jsonschema validation. For debugging or hand-edited JSON; '
            'normal use should validate.'
        ),
    )
    parser.add_argument(
        '--strip-inline-markup',
        action='store_true',
        help=(
            'Strip common inline **bold**, *italic*, __underline__, _italic_, and '
            '`code` markers from each line before writing (useful for plain CER).'
        ),
    )
    args = parser.parse_args()
    json_paths = [p.resolve() for p in args.json_files]

    if args.output is not None and len(json_paths) != 1:
        print(
            'Error: --output is only allowed when there is exactly one input JSON file.',
            file=sys.stderr,
        )
        return 1

    schema = load_schema() if not args.skip_schema_validation else None

    for json_path in json_paths:
        if not json_path.is_file():
            print(f'Error: file not found: {json_path}', file=sys.stderr)
            return 1

        try:
            text = json_path.read_text(encoding='utf-8')
        except OSError as exc:
            print(f'Error reading {json_path}: {exc}', file=sys.stderr)
            return 1

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f'Error: invalid JSON in {json_path}: {exc}', file=sys.stderr)
            return 1

        if schema is not None:
            try:
                jsonschema.validate(instance=payload, schema=schema)
            except jsonschema.ValidationError as exc:
                path = ' / '.join(str(p) for p in exc.absolute_path) or '(root)'
                print(
                    f'Error: schema validation failed for {json_path} at {path}: {exc.message}',
                    file=sys.stderr,
                )
                return 1

        body = lines_to_adoc_body(
            payload,
            strip_inline_markup=args.strip_inline_markup,
        )
        if args.output is not None:
            out_path = args.output.resolve()
        else:
            out_path = json_path.with_suffix('.adoc')

        try:
            out_path.write_text(body, encoding='utf-8')
        except OSError as exc:
            print(f'Error writing {out_path}: {exc}', file=sys.stderr)
            return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
