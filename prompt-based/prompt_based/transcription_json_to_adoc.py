from __future__ import annotations

from ._legacy_loader import load_legacy_module


def main() -> int:
    module = load_legacy_module(
        'transcription-json-to-adoc.py',
        'transcription_json_to_adoc_legacy',
    )
    return module.main()

