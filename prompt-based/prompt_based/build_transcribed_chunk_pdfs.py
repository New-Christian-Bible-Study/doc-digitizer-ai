from __future__ import annotations

from ._script_loader import load_script_module


def main() -> int:
    module = load_script_module(
        'build-transcribed-chunk-pdfs.py',
        'build_transcribed_chunk_pdfs_script',
    )
    return module.main()

