"""CLI parsing for review-chunk without importing Qt (for ``--help`` on minimal Linux)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(
        description='Review and correct per-line transcriptions for a chunk.',
    )
    parser.add_argument(
        '--working-dir',
        type=Path,
        default=Path('.'),
        help=(
            'Same as transcribe-chunk.py: directory containing '
            'chunk-pdfs/ (or use --chunk-dir) and transcriptions/'
        ),
    )
    parser.add_argument(
        '--chunk-dir',
        type=Path,
        default=None,
        help=(
            'Directory containing chunk PDFs (default: working-dir/chunk-pdfs). '
            'Relative paths are resolved under working-dir.'
        ),
    )
    parser.add_argument(
        '--transcriptions-dir',
        type=Path,
        default=None,
        help=(
            'Directory containing chunk transcription JSON files '
            '(default: working-dir/transcriptions). Relative paths are '
            'resolved under working-dir.'
        ),
    )
    parser.add_argument(
        '--raw-json',
        type=Path,
        default=None,
        help=(
            'Path to *_raw.json; relative paths are under --working-dir '
            '(default: transcriptions/<stem>_raw.json)'
        ),
    )
    return parser.parse_args(argv)
