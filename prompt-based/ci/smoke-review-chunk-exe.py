"""Smoke-test the PyInstaller review-chunk binary (--help). Runs from repo root."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


def main() -> int:
    exe_name = 'review-chunk.exe' if platform.system() == 'Windows' else 'review-chunk'
    exe_path = Path.cwd() / 'dist' / exe_name
    if not exe_path.is_file():
        print(f'Executable not found: {exe_path}', file=sys.stderr)
        return 1
    result = subprocess.run(
        [str(exe_path), '--help'],
        capture_output=True,
        text=True,
        check=True,
    )
    want = 'Review and correct per-line transcriptions for a chunk.'
    if want not in result.stdout:
        print('Unexpected --help output from packaged executable.', file=sys.stderr)
        return 1
    print('Smoke test passed for', exe_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
