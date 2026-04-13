import os
import subprocess
import sys
from pathlib import Path

import pytest


STRATEGY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = STRATEGY_ROOT / 'transcribe-chunk.py'
# Same file the transcribe script uses when the working dir has no *prompt*.md.
STRATEGY_PROMPT_PATH = STRATEGY_ROOT / 'prompt.md'


def skip_if_missing_api_key():
    if not os.environ.get('GEMINI_API_KEY'):
        pytest.skip('GEMINI_API_KEY is not set; skipping live integration test.')


def run_live_transcription(
    working_dir: Path,
    chunk_filename: str,
    prompt_md: Path,
    chunk_dir: Path | None = None,
) -> subprocess.CompletedProcess:
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        '--working-dir',
        str(working_dir),
        '--chunk',
        chunk_filename,
        '--prompt-md',
        str(prompt_md),
    ]
    if chunk_dir is not None:
        command.extend(['--chunk-dir', str(chunk_dir)])
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=dict(os.environ),
        check=False,
    )


def assert_common_ai_summary_fields(ai_summary_text: str, chunk_filename: str):
    assert '# AI transcription summary' in ai_summary_text
    assert f'Chunk file: `{chunk_filename}`' in ai_summary_text
    assert '- Model: `' not in ai_summary_text
    assert '- Configuration: `' not in ai_summary_text
    assert '- Prompt tokens (input): `' not in ai_summary_text
    assert '- Completion tokens (output): `' not in ai_summary_text
    assert '- Total tokens: `' not in ai_summary_text
    assert '## Transcribe config used' in ai_summary_text
    assert '"model": "gemini/gemini-3.1-pro-preview"' in ai_summary_text
    assert '"temperature": 1.0' in ai_summary_text
    assert '"reasoning_effort": "medium"' in ai_summary_text
    assert '"media_resolution": "high"' in ai_summary_text
    assert '"sys_instructions":' in ai_summary_text
    assert '- Confidence score: `' in ai_summary_text
    assert '- Confidence label: `' in ai_summary_text
    assert '## Prompt used' in ai_summary_text
