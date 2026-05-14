"""
Upgrade legacy transcription JSON (``box_2d``) to schema_version 2 ``line_box``.

CLI entry: ``convert-transcription-boxes.py`` in the ``prompt-based`` directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema

from prompt_based.chunk_lines_model import (
    TRANSCRIPTION_SCHEMA_VERSION_V2,
    line_box_dict_from_normalized_aabb,
    line_aabb_four_ints,
)
from prompt_based.paddle_line_boxes import reassign_line_boxes_from_pdf


SCRIPT_DIR = Path(__file__).resolve().parents[1]
DISK_RAW_SCHEMA_PATH = SCRIPT_DIR / 'raw-transcription.schema.json'
DISK_FINAL_SCHEMA_PATH = SCRIPT_DIR / 'final-transcription.schema.json'


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def is_legacy_payload(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get('schema_version') == TRANSCRIPTION_SCHEMA_VERSION_V2:
        return False
    lines = payload.get('lines')
    if not isinstance(lines, list) or not lines:
        return False
    first = lines[0]
    if not isinstance(first, dict):
        return False
    return 'box_2d' in first and 'line_box' not in first


def migrate_payload_inplace(payload: dict) -> None:
    """Mutate legacy ``box_2d`` rows to ``line_box`` and set ``schema_version``."""
    lines = payload.get('lines')
    if not isinstance(lines, list):
        return
    for line in lines:
        if not isinstance(line, dict):
            continue
        if 'line_box' in line:
            continue
        line_aabb_norm = line_aabb_four_ints(line)
        if line_aabb_norm is None and isinstance(line.get('box_2d'), list):
            b = line['box_2d']
            try:
                line_aabb_norm = [int(b[0]), int(b[1]), int(b[2]), int(b[3])]
            except (TypeError, ValueError):
                line_aabb_norm = None
        if line_aabb_norm is not None:
            line['line_box'] = line_box_dict_from_normalized_aabb(line_aabb_norm)
        line.pop('box_2d', None)
    payload['schema_version'] = TRANSCRIPTION_SCHEMA_VERSION_V2


def convert_file(
    path: Path,
    *,
    chunk_pdf: Path | None,
    in_place: bool,
    dry_run: bool,
) -> tuple[bool, str]:
    raw_schema = load_schema(DISK_RAW_SCHEMA_PATH)
    final_schema = load_schema(DISK_FINAL_SCHEMA_PATH)
    text = path.read_text(encoding='utf-8')
    payload = json.loads(text)
    if not is_legacy_payload(payload):
        return True, f'Skip (already v2 or not legacy): {path}'

    migrate_payload_inplace(payload)
    if chunk_pdf is not None:
        if not chunk_pdf.is_file():
            return False, f'Chunk PDF not found: {chunk_pdf}'
        warn = reassign_line_boxes_from_pdf(chunk_pdf, payload['lines'])
        if warn:
            return True, f'Warning ({path}): {warn}'

    schema = final_schema if path.name.endswith('_final.json') else raw_schema
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        return False, f'Validation failed after migrate ({path}): {exc}'

    if dry_run:
        return True, f'OK (dry-run): {path}'

    out_path = path
    if not in_place:
        out_path = path.with_name(path.stem + '_v2' + path.suffix)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if not in_place:
        return True, f'Wrote: {out_path}'
    return True, f'Updated: {path}'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Convert legacy transcription JSON (box_2d) to schema_version 2 (line_box).',
    )
    parser.add_argument(
        'json_paths',
        nargs='+',
        type=Path,
        help='Paths to *_raw.json or *_final.json files',
    )
    parser.add_argument(
        '--chunk-pdf',
        type=Path,
        default=None,
        help='Chunk PDF used to re-run PaddleOCR and refresh line_box (optional)',
    )
    parser.add_argument(
        '--in-place',
        action='store_true',
        help='Overwrite each input file (default writes *_v2.json beside input)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate only; do not write files',
    )
    args = parser.parse_args(argv)

    any_error = False
    for p in args.json_paths:
        p = p.resolve()
        ok, msg = convert_file(
            p,
            chunk_pdf=args.chunk_pdf.resolve() if args.chunk_pdf else None,
            in_place=args.in_place,
            dry_run=args.dry_run,
        )
        print(msg)
        if not ok:
            any_error = True
    return 1 if any_error else 0


if __name__ == '__main__':
    raise SystemExit(main())
