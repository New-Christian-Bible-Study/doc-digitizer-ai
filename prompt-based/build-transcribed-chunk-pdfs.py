#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
from pathlib import Path


def iter_transcriptions_dirs(root: Path):
    for dirpath, _, _ in os.walk(root):
        if Path(dirpath).name == 'transcriptions':
            yield Path(dirpath)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            'Run asciidoctor-pdf on every .adoc file in each transcriptions/ directory '
            'under the working directory. Writes <stem>-transcription.pdf next to each <stem>.adoc.'
        ),
        epilog=(
            'Requires asciidoctor-pdf on PATH. Finds directories named transcriptions '
            'anywhere under --working-dir and processes direct .adoc children only.'
        ),
    )
    parser.add_argument(
        '--working-dir',
        default='.',
        help='Root directory to walk (default: current directory).',
    )
    args = parser.parse_args()
    working_dir = Path(args.working_dir).resolve()
    if not working_dir.is_dir():
        print(f'Error: working directory does not exist: {working_dir}', file=sys.stderr)
        return 1

    transcriptions_dirs = sorted(iter_transcriptions_dirs(working_dir), key=str)
    if not transcriptions_dirs:
        print(
            f'No transcriptions/ directories under {working_dir}.',
            file=sys.stderr,
        )
        return 0

    for trans_dir in transcriptions_dirs:
        adoc_paths = sorted(
            p
            for p in trans_dir.iterdir()
            if p.is_file() and p.suffix.lower() == '.adoc'
        )
        for adoc_path in adoc_paths:
            out_pdf = trans_dir / f'{adoc_path.stem}-transcription.pdf'
            try:
                subprocess.run(
                    ['asciidoctor-pdf', '-o', str(out_pdf), str(adoc_path)],
                    check=True,
                )
            except FileNotFoundError:
                print(
                    'Error: asciidoctor-pdf not found. Install the asciidoctor-pdf gem '
                    'and ensure it is on PATH.',
                    file=sys.stderr,
                )
                return 1
            except subprocess.CalledProcessError as exc:
                return exc.returncode

    return 0


if __name__ == '__main__':
    sys.exit(main())
