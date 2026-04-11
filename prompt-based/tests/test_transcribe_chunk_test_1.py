import json
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from transcribe_integration_helpers import (
    STRATEGY_PROMPT_PATH,
    assert_common_ai_log_fields,
    run_live_transcription,
    skip_if_missing_api_key,
)


STRATEGY_ROOT = Path(__file__).resolve().parents[1]
WORKING_DIR = STRATEGY_ROOT / 'tests' / 'test-1'
TEST_1_CHUNK_FILENAME = 'test-a_001-003.pdf'
TEST_1_OUTPUT_PATH = WORKING_DIR / 'transcriptions' / 'test-a_001-003_raw.json'
TEST_1_AI_LOG_PATH = WORKING_DIR / 'transcriptions' / 'test-a_001-003-ai-log.md'


def ensure_review_pdf_exists():
    review_pdf = WORKING_DIR / 'chunk-pdfs' / TEST_1_CHUNK_FILENAME
    if review_pdf.exists():
        return

    scan_pdf = WORKING_DIR / 'source-pdfs' / 'test-a.pdf'
    reader = PdfReader(str(scan_pdf))
    writer = PdfWriter()
    for page_index in range(3):
        writer.add_page(reader.pages[page_index])
    review_pdf.parent.mkdir(parents=True, exist_ok=True)
    with review_pdf.open('wb') as output_file:
        writer.write(output_file)


@pytest.mark.integration
def test_live_integration_test_1_transcribes_and_logs():
    skip_if_missing_api_key()
    ensure_review_pdf_exists()

    if TEST_1_OUTPUT_PATH.exists():
        TEST_1_OUTPUT_PATH.unlink()
    if TEST_1_AI_LOG_PATH.exists():
        TEST_1_AI_LOG_PATH.unlink()

    result = run_live_transcription(
        WORKING_DIR, TEST_1_CHUNK_FILENAME, STRATEGY_PROMPT_PATH
    )

    assert result.returncode == 0, result.stderr
    assert TEST_1_OUTPUT_PATH.exists()
    assert TEST_1_AI_LOG_PATH.exists()
    raw_payload = json.loads(TEST_1_OUTPUT_PATH.read_text(encoding='utf-8'))
    assert isinstance(raw_payload.get('lines'), list)
    assert len(raw_payload['lines']) >= 1
    assert 'box_2d' in raw_payload['lines'][0]
    assert raw_payload['lines'][0]['box_2d'] is not None
    assert len(raw_payload['lines'][0]['box_2d']) == 4
    ai_log_text = TEST_1_AI_LOG_PATH.read_text(encoding='utf-8')
    assert_common_ai_log_fields(ai_log_text, TEST_1_CHUNK_FILENAME)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
