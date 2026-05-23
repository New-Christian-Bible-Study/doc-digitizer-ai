import importlib.util
from pathlib import Path


STRATEGY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = STRATEGY_ROOT / 'prompt_based' / 'transcription_json_to_adoc.py'


def load_module():
    spec = importlib.util.spec_from_file_location('transcription_json_to_adoc', MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load module from {MODULE_PATH}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_path_for_json_uses_final_suffix():
    module = load_module()
    raw_path = Path('/tmp/chunk_raw.json')
    final_path = Path('/tmp/chunk_final.json')

    assert module.schema_path_for_json(raw_path).name == 'raw-transcription.schema.json'
    assert module.schema_path_for_json(final_path).name == 'final-transcription.schema.json'


def test_lines_to_adoc_body_skips_excluded_lines():
    module = load_module()
    payload = {
        'lines': [
            {'text': 'keep me'},
            {'text': '23181', 'excluded': True},
            {'text': 'also keep'},
        ],
    }

    assert module.lines_to_adoc_body(payload) == 'keep me\nalso keep'
