from __future__ import annotations

from ._legacy_loader import load_legacy_module


def main() -> int:
    module = load_legacy_module('generate-chunk.py', 'generate_chunk_legacy')
    return module.main()

