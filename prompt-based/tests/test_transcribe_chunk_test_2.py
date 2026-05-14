import json
from pathlib import Path

import pytest

from transcribe_integration_helpers import (
    STRATEGY_PROMPT_PATH,
    run_live_transcription,
    skip_if_missing_api_key,
)


STRATEGY_ROOT = Path(__file__).resolve().parents[1]
WORKING_DIR_TEST_2 = STRATEGY_ROOT / 'tests' / 'test-2'
TEST_2_CHUNK_FILENAME = 'test-2.pdf'
TEST_2_OUTPUT_PATH = WORKING_DIR_TEST_2 / 'transcriptions' / 'test-2_raw.json'


@pytest.mark.integration
def test_live_integration_test_2_produces_raw_json_with_lines():
    skip_if_missing_api_key()

    if TEST_2_OUTPUT_PATH.exists():
        TEST_2_OUTPUT_PATH.unlink()

    result = run_live_transcription(
        WORKING_DIR_TEST_2,
        TEST_2_CHUNK_FILENAME,
        STRATEGY_PROMPT_PATH,
    )

    assert result.returncode == 0, result.stderr
    assert TEST_2_OUTPUT_PATH.exists()
    raw_payload = json.loads(TEST_2_OUTPUT_PATH.read_text(encoding='utf-8'))
    assert isinstance(raw_payload.get('lines'), list)
    assert len(raw_payload['lines']) >= 1
    assert raw_payload.get('schema_version') == 2
    for line in raw_payload['lines']:
        assert 'page_number' in line
        assert 'text' in line
        lb = line.get('line_box')
        assert isinstance(lb, dict)
        assert {'ymin', 'xmin', 'ymax', 'xmax'} <= set(lb.keys())


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
