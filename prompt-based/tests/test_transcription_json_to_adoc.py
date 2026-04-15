import importlib.util
from pathlib import Path


STRATEGY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = STRATEGY_ROOT / 'transcription-json-to-adoc.py'


def load_module():
    spec = importlib.util.spec_from_file_location('transcription_json_to_adoc', SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load module from {SCRIPT_PATH}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_path_for_json_uses_final_suffix():
    module = load_module()
    raw_path = Path('/tmp/chunk_raw.json')
    final_path = Path('/tmp/chunk_final.json')

    assert module.schema_path_for_json(raw_path).name == 'raw-transcription.schema.json'
    assert module.schema_path_for_json(final_path).name == 'final-transcription.schema.json'
