from __future__ import annotations

from ._legacy_loader import load_legacy_module


def main() -> int:
    module = load_legacy_module(
        'build-transcribed-chunk-pdfs.py',
        'build_transcribed_chunk_pdfs_legacy',
    )
    return module.main()

