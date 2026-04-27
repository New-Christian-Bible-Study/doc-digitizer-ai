from __future__ import annotations

from ._script_loader import load_script_module


def main() -> int:
    module = load_script_module('generate-chunk.py', 'generate_chunk_script')
    return module.main()

