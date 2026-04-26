from __future__ import annotations

from ._legacy_loader import load_legacy_module

_legacy = load_legacy_module('chunk_lines_model.py', 'chunk_lines_model_legacy')

globals().update(
    {
        name: value
        for name, value in _legacy.__dict__.items()
        if not name.startswith('__')
    }
)

