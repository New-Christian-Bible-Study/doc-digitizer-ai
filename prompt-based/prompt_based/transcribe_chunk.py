from __future__ import annotations

from ._legacy_loader import load_legacy_module


def main() -> int:
    module = load_legacy_module('transcribe-chunk.py', 'transcribe_chunk_legacy')
    return module.main()

