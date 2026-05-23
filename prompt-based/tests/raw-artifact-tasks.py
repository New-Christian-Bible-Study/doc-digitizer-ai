#!/usr/bin/env python3
'''Makefile helper: clean, regenerate, and review test transcription artifacts.'''

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_STRATEGY_ROOT = _TESTS_DIR.parent
_REPO_ROOT = _STRATEGY_ROOT.parent
_TRANSCRIBE_SCRIPT = _STRATEGY_ROOT / 'transcribe-chunk.py'
_REVIEW_SCRIPT = _STRATEGY_ROOT / 'review-chunk.py'
_PROMPT_MD = _STRATEGY_ROOT / 'prompt.md'
_TORTURE_ROOT = _REPO_ROOT / 'stress-tests' / 'torture'
_TORTURE_CHUNK_FILENAME = 'test-ocr.pdf'
_TORTURE_WORKING_PARENT = _TESTS_DIR / 'test-torture-ocr'


def _discover_raw_json_paths() -> list[Path]:
    paths = sorted(_TESTS_DIR.rglob('transcriptions/*_raw.json'))
    return [p for p in paths if p.is_file()]


def _stem_from_raw_path(raw_path: Path) -> str:
    name = raw_path.name
    suffix = '_raw.json'
    if not name.endswith(suffix):
        raise ValueError(f'Not a *_raw.json path: {raw_path}')
    return name[: -len(suffix)]


def _artifact_paths_for_stem(transcriptions_dir: Path, stem: str) -> list[Path]:
    raw_json = transcriptions_dir / f'{stem}_raw.json'
    paths = [
        raw_json,
        transcriptions_dir / f'{stem}_summary.md',
        transcriptions_dir / f'{stem}_final.json',
        transcriptions_dir / f'{stem}_raw.adoc',
        transcriptions_dir / f'{stem}_final.adoc',
        transcriptions_dir / f'{stem}-transcription.pdf',
        transcriptions_dir / f'{stem}-boxes.pdf',
        raw_json.with_suffix('.txt'),
    ]
    paths.extend(transcriptions_dir.glob(f'{stem}-boxes-p*.png'))
    return paths


def _is_torture_working_dir(working_dir: Path) -> bool:
    try:
        working_dir.relative_to(_TORTURE_WORKING_PARENT)
        return True
    except ValueError:
        return False


def _torture_extra_paths(working_dir: Path) -> list[Path]:
    if not _is_torture_working_dir(working_dir):
        return []
    return [
        working_dir / 'cer-report.txt',
        working_dir / 'transcriptions' / 'test-ocr-ai-log.md',
    ]


def _remove_if_exists(path: Path) -> bool:
    if not path.exists():
        return False
    path.unlink()
    print(f'removed {path}')
    return True


def _discover_torture_working_dirs() -> list[Path]:
    if not _TORTURE_WORKING_PARENT.is_dir():
        return []
    return sorted(
        p
        for p in _TORTURE_WORKING_PARENT.iterdir()
        if p.is_dir()
    )


def cmd_realclean() -> int:
    raw_paths = _discover_raw_json_paths()
    torture_workdirs_cleaned: set[Path] = set()
    removed_count = 0

    for raw_path in raw_paths:
        transcriptions_dir = raw_path.parent
        working_dir = transcriptions_dir.parent
        stem = _stem_from_raw_path(raw_path)
        for artifact in _artifact_paths_for_stem(transcriptions_dir, stem):
            if _remove_if_exists(artifact):
                removed_count += 1

        if working_dir not in torture_workdirs_cleaned:
            torture_workdirs_cleaned.add(working_dir)
            for extra in _torture_extra_paths(working_dir):
                if _remove_if_exists(extra):
                    removed_count += 1

    for working_dir in _discover_torture_working_dirs():
        if working_dir in torture_workdirs_cleaned:
            continue
        for extra in _torture_extra_paths(working_dir):
            if _remove_if_exists(extra):
                removed_count += 1

    if removed_count == 0:
        print('realclean: nothing to remove')
    else:
        print(f'realclean: removed {removed_count} file(s)')
    return 0


def _discover_standard_workdirs() -> list[Path]:
    workdirs = []
    for chunk_dir in sorted(_TESTS_DIR.rglob('chunk-pdfs')):
        if not chunk_dir.is_dir():
            continue
        workdirs.append(chunk_dir.parent)
    return workdirs


def _discover_torture_language_ids() -> list[str]:
    if not _TORTURE_ROOT.is_dir():
        return []
    names = []
    for path in _TORTURE_ROOT.iterdir():
        if path.is_dir() and (path / _TORTURE_CHUNK_FILENAME).is_file():
            names.append(path.name)
    return sorted(names)


def _torture_languages_for_run() -> list[str]:
    discovered = _discover_torture_language_ids()
    only = os.environ.get('TORTURE_OCR_LANG', '').strip()
    if not only:
        return discovered
    if only not in discovered:
        print(
            f'Error: TORTURE_OCR_LANG={only!r} is not a torture language with '
            f'{_TORTURE_CHUNK_FILENAME} under {_TORTURE_ROOT}. '
            f'Available: {discovered!r}',
            file=sys.stderr,
        )
        sys.exit(2)
    return [only]


def _list_chunk_pdfs(chunk_dir: Path) -> list[str]:
    if not chunk_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in chunk_dir.iterdir()
        if p.is_file() and p.suffix.lower() == '.pdf'
    )


def _run_subprocess(command: list[str]) -> int:
    print(' '.join(command), flush=True)
    result = subprocess.run(command, check=False)
    return result.returncode


def _run_transcribe(command: list[str]) -> int:
    return _run_subprocess(command)


def _reviewable_stems(working_dir: Path, chunk_dir: Path) -> list[str]:
    transcriptions_dir = working_dir / 'transcriptions'
    stems = []
    for chunk_name in _list_chunk_pdfs(chunk_dir):
        stem = Path(chunk_name).stem
        if (transcriptions_dir / f'{stem}_raw.json').is_file():
            stems.append(stem)
    return stems


def _build_review_sessions() -> list[tuple[str, list[str]]]:
    '''Return (label, argv) pairs for sequential review-chunk invocations.'''
    sessions: list[tuple[str, list[str]]] = []

    for working_dir in _discover_standard_workdirs():
        chunk_dir = working_dir / 'chunk-pdfs'
        chunk_names = _list_chunk_pdfs(chunk_dir)
        if not chunk_names:
            print(
                f'skip review {working_dir.relative_to(_REPO_ROOT)}: '
                f'no PDFs in {chunk_dir.name}/',
                flush=True,
            )
            continue
        stems = _reviewable_stems(working_dir, chunk_dir)
        if not stems:
            print(
                f'skip review {working_dir.relative_to(_REPO_ROOT)}: '
                f'no *_raw.json for chunk PDFs (run make raw first)',
                flush=True,
            )
            continue
        label = str(working_dir.relative_to(_REPO_ROOT))
        transcriptions_dir = working_dir / 'transcriptions'
        command = [
            sys.executable,
            str(_REVIEW_SCRIPT),
            '--working-dir',
            str(working_dir),
            '--chunk-dir',
            str(chunk_dir),
            '--transcriptions-dir',
            str(transcriptions_dir),
        ]
        sessions.append((label, command))

    for lang in _torture_languages_for_run():
        torture_dir = _TORTURE_ROOT / lang
        working_dir = _TORTURE_WORKING_PARENT / lang
        raw_path = working_dir / 'transcriptions' / 'test-ocr_raw.json'
        if not torture_dir.joinpath(_TORTURE_CHUNK_FILENAME).is_file():
            print(
                f'skip review torture {lang}: missing {_TORTURE_CHUNK_FILENAME}',
                flush=True,
            )
            continue
        if not raw_path.is_file():
            print(
                f'skip review torture {lang}: no {raw_path.name} (run make raw first)',
                flush=True,
            )
            continue
        label = str(working_dir.relative_to(_REPO_ROOT))
        command = [
            sys.executable,
            str(_REVIEW_SCRIPT),
            '--working-dir',
            str(working_dir),
            '--chunk-dir',
            str(torture_dir),
            '--transcriptions-dir',
            str(working_dir / 'transcriptions'),
        ]
        sessions.append((label, command))

    return sessions


def cmd_review() -> int:
    sessions = _build_review_sessions()
    if not sessions:
        print(
            'review: no sessions (need chunk PDFs and matching *_raw.json)',
            file=sys.stderr,
        )
        return 1

    total = len(sessions)
    exit_code = 0
    for index, (label, command) in enumerate(sessions, start=1):
        print(
            f'--- review {index}/{total}: {label} '
            f'(close the window to continue) ---',
            flush=True,
        )
        rc = _run_subprocess(command)
        if rc != 0:
            print(f'review: exited with code {rc} for {label}', file=sys.stderr)
            exit_code = rc

    if exit_code == 0:
        print(f'review: finished {total} session(s)', flush=True)
    return exit_code


def _require_gemini_api_key() -> None:
    if not os.environ.get('GEMINI_API_KEY'):
        print(
            'Error: GEMINI_API_KEY environment variable is not set.',
            file=sys.stderr,
        )
        sys.exit(2)


def _transcribe_standard_workdir(working_dir: Path) -> int:
    chunk_dir = working_dir / 'chunk-pdfs'
    chunk_names = _list_chunk_pdfs(chunk_dir)
    if not chunk_names:
        print(
            f'skip {working_dir}: no PDFs in {chunk_dir} '
            f'(create chunks with generate-chunk.py first)',
            flush=True,
        )
        return 0

    command = [
        sys.executable,
        str(_TRANSCRIBE_SCRIPT),
        '--working-dir',
        str(working_dir),
        '--all',
        '--prompt-md',
        str(_PROMPT_MD),
    ]
    return _run_transcribe(command)


def _transcribe_torture_language(lang: str) -> int:
    torture_dir = _TORTURE_ROOT / lang
    working_dir = _TORTURE_WORKING_PARENT / lang
    command = [
        sys.executable,
        str(_TRANSCRIBE_SCRIPT),
        '--working-dir',
        str(working_dir),
        '--chunk-dir',
        str(torture_dir),
        '--chunk',
        _TORTURE_CHUNK_FILENAME,
        '--prompt-md',
        str(_PROMPT_MD),
    ]
    print(f'--- torture {lang} ---', flush=True)
    return _run_transcribe(command)


def cmd_raw() -> int:
    _require_gemini_api_key()

    exit_code = 0
    for working_dir in _discover_standard_workdirs():
        print(f'--- {working_dir.relative_to(_REPO_ROOT)} ---', flush=True)
        rc = _transcribe_standard_workdir(working_dir)
        if rc != 0:
            exit_code = rc

    for lang in _torture_languages_for_run():
        rc = _transcribe_torture_language(lang)
        if rc != 0:
            exit_code = rc

    if exit_code != 0:
        print('raw: one or more transcribe runs failed', file=sys.stderr)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'command',
        choices=('realclean', 'raw', 'review'),
        help=(
            'realclean: remove raw JSON and dependents; '
            'raw: regenerate raw JSON; '
            'review: open review-chunk.py per fixture (sequential, GUI)'
        ),
    )
    args = parser.parse_args(argv)
    if args.command == 'realclean':
        return cmd_realclean()
    if args.command == 'raw':
        return cmd_raw()
    return cmd_review()


if __name__ == '__main__':
    raise SystemExit(main())
