from __future__ import annotations

from ._script_loader import load_script_module


def main() -> int:
    module = load_script_module(
        'transcription-json-to-adoc.py',
        'transcription_json_to_adoc_script',
    )
    return module.main()

