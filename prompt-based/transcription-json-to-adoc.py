#!/usr/bin/env python3

import argparse
import json
import re
import sys
from pathlib import Path

import jsonschema

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_SCHEMA_PATH = SCRIPT_DIR / 'raw-transcription.schema.json'
FINAL_SCHEMA_PATH = SCRIPT_DIR / 'final-transcription.schema.json'


def load_schema(schema_path: Path) -> dict:
    with schema_path.open('r', encoding='utf-8') as schema_file:
        return json.load(schema_file)


def schema_path_for_json(json_path: Path) -> Path:
    if json_path.name.endswith('_final.json'):
        return FINAL_SCHEMA_PATH
    return RAW_SCHEMA_PATH


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


def strip_asciidoc_block_from_line(line: str) -> str | None:
    '''Return plain text for one line, or None to drop the line entirely.

    Used when comparing line-joined JSON to pandoc plain ground truth: the
    torture CER test does not render hypothesis text through AsciiDoc3, so
    markers the model copies from the page must be removed heuristically here.

    Removes AsciiDoc-only constructs so transcription text aligns with pandoc
    plain ground truth: document/section heading prefixes (``=`` … ``======``),
    role-only lines (``[.tiny]``), attribute lines (``:foo:``), preprocessor
    conditionals (``ifeval::`` / ``endif::``), and full-line comments (``//``).
    '''
    s = line.strip()
    if not s:
        return ''
    if s.startswith('//'):
        return None
    if re.match(r'^\[\.[^\]]+\]\s*$', s):
        return None
    if re.match(r'^:[-a-zA-Z0-9_]+:', s):
        return None
    if (
        s.startswith('ifeval::')
        or s.startswith('endif::')
        or s.startswith('ifdef::')
        or s.startswith('ifndef::')
    ):
        return None
    m = re.match(r'^\s*(=+)(?:\s+(.*))?$', s)
    if m:
        rest = m.group(2)
        if rest:
            return rest
        return None
    return line.rstrip('\n')


def lines_to_adoc_body(
    payload: dict,
    *,
    strip_inline_markup: bool = False,
    strip_asciidoc_block: bool = False,
) -> str:
    '''Join ``lines[].text`` in order. Optional stripping targets CER-style plain text.

    For torture OCR integration tests both strip flags are True so ``*_raw.txt``
    matches ``ground-truth.txt`` shape before ``normalize_for_cer``. Default
    (both False) preserves model output for normal .adoc export.
    '''
    lines = payload.get('lines')
    if not isinstance(lines, list):
        return ''
    texts = []
    for item in lines:
        if isinstance(item, dict) and 'text' in item:
            t = item.get('text', '')
            if not isinstance(t, str):
                t = ''
            if strip_asciidoc_block:
                block_stripped = strip_asciidoc_block_from_line(t)
                if block_stripped is None:
                    continue
                t = block_stripped
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
            'By default the document is validated against raw-transcription.schema.json '
            'or final-transcription.schema.json based on filename suffix. '
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
            'Strip AsciiDoc block markup (heading = prefixes, [.role] lines, '
            'attributes, ifeval/endif, // comments) and inline **bold**, '
            '*italic*, __underline__, _italic_, and `code` from each line before '
            'writing (for plain-text / CER alignment with pandoc ground truth).'
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

    schema_cache: dict[Path, dict] = {}

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

        if not args.skip_schema_validation:
            schema_path = schema_path_for_json(json_path)
            schema = schema_cache.get(schema_path)
            if schema is None:
                schema = load_schema(schema_path)
                schema_cache[schema_path] = schema
            try:
                jsonschema.validate(instance=payload, schema=schema)
            except jsonschema.ValidationError as exc:
                path = ' / '.join(str(p) for p in exc.absolute_path) or '(root)'
                print(
                    f'Error: schema validation failed for {json_path} '
                    f'(schema {schema_path.name}) at {path}: {exc.message}',
                    file=sys.stderr,
                )
                return 1

        body = lines_to_adoc_body(
            payload,
            strip_inline_markup=args.strip_inline_markup,
            strip_asciidoc_block=args.strip_inline_markup,
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
