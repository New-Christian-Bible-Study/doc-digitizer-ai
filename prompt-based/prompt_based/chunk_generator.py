from __future__ import annotations

from ._script_loader import load_script_module

_module = load_script_module('chunk_generator.py', 'chunk_generator_script')

globals().update(
    {
        name: value
        for name, value in _module.__dict__.items()
        if not name.startswith('__')
    }
)

