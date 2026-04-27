from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


def load_script_module(script_filename: str, module_name: str):
    """Load a sibling script/module from prompt-based/."""
    strategy_root = Path(__file__).resolve().parents[1]
    script_path = strategy_root / script_filename
    spec = spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load module from {script_path}')
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

