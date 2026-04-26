from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


def load_legacy_module(legacy_filename: str, module_name: str):
    """Load a sibling legacy script/module from prompt-based/."""
    strategy_root = Path(__file__).resolve().parents[1]
    legacy_path = strategy_root / legacy_filename
    spec = spec_from_file_location(module_name, legacy_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load module from {legacy_path}')
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

