'''Live integration test that transcribes a torture OCR sample, computes CER
against ground truth, and fails when error rate exceeds the configured cutoff.
'''

import difflib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import Levenshtein
import pytest

from transcribe_integration_helpers import (
    STRATEGY_PROMPT_PATH,
    run_live_transcription,
    skip_if_missing_api_key,
)


# Maximum allowed character error rate (fraction) vs stress-tests/torture/ground-truth.txt.
# Single knob for experimentation; adjust as models and prompts change.
TORTURE_OCR_CER_CUTOFF = 0.05

# Cap word-level unified diff lines so the report stays a reasonable size.
_MAX_DIFF_LINES = 5000

STRATEGY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STRATEGY_ROOT.parent
WORKING_DIR = STRATEGY_ROOT / 'tests' / 'test-torture-ocr'
TORTURE_DIR = REPO_ROOT / 'stress-tests' / 'torture'
CHUNK_FILENAME = 'test-ocr.pdf'
CHUNK_PDF_PATH = TORTURE_DIR / CHUNK_FILENAME
RAW_JSON_PATH = WORKING_DIR / 'transcriptions' / 'test-ocr_raw.json'
PLAIN_TEXT_PATH = RAW_JSON_PATH.with_suffix('.txt')
AI_LOG_PATH = WORKING_DIR / 'transcriptions' / 'test-ocr-ai-log.md'
CER_REPORT_PATH = WORKING_DIR / 'cer-report.txt'
GROUND_TRUTH_PATH = TORTURE_DIR / 'ground-truth.txt'
_COMPUTE_CER_PATH = REPO_ROOT / 'stress-tests' / 'compute-cer.py'

# Match compute-cer.py default (strip-html-emphasis).
_STRIP_HTML_EMPHASIS = True


def _load_compute_cer_module():
    spec = importlib.util.spec_from_file_location(
        'stress_tests_compute_cer',
        _COMPUTE_CER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Cannot load compute-cer from {_COMPUTE_CER_PATH}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_json_to_plain(payload: dict) -> str:
    '''Join transcription line texts like transcription-json-to-adoc (no AsciiDoc).'''
    lines = payload.get('lines')
    if not isinstance(lines, list):
        return ''
    texts = []
    for item in lines:
        if isinstance(item, dict) and 'text' in item:
            t = item.get('text', '')
            texts.append(t if isinstance(t, str) else '')
    return '\n'.join(texts)


def _normalized_truth_and_hypothesis(hypothesis_plain: str, truth_raw: str) -> tuple[str, str]:
    compute_cer = _load_compute_cer_module()
    normalize = compute_cer.normalize_for_cer
    truth = normalize(truth_raw, _STRIP_HTML_EMPHASIS)
    hypothesis = normalize(hypothesis_plain, _STRIP_HTML_EMPHASIS)
    return truth, hypothesis


def _cer_and_distance(truth: str, hypothesis: str) -> tuple[float, int]:
    distance = Levenshtein.distance(truth, hypothesis)
    cer = distance / len(truth) if len(truth) else 0.0
    return cer, distance


def _word_diff_lines(truth: str, hypothesis: str) -> tuple[list[str], bool]:
    diff_iter = difflib.unified_diff(
        truth.split(),
        hypothesis.split(),
        fromfile='ground_truth_normalized_words',
        tofile='transcription_normalized_words',
        lineterm='',
    )
    lines = []
    truncated = False
    for i, line in enumerate(diff_iter):
        if i >= _MAX_DIFF_LINES:
            truncated = True
            break
        lines.append(line)
    return lines, truncated


def _build_cer_report(
    *,
    truth_raw: str,
    hypothesis_plain: str,
    truth_norm: str,
    hypothesis_norm: str,
    cer: float,
    distance: int,
    json_line_count: int,
    seq_similarity: float,
) -> str:
    truth_words = truth_norm.split()
    hyp_words = hypothesis_norm.split()
    diff_lines, diff_truncated = _word_diff_lines(truth_norm, hypothesis_norm)
    preview_len = 800
    blocks = [
        'Torture OCR CER report',
        '======================',
        '',
        f'Generated (UTC): {datetime.now(timezone.utc).isoformat()}',
        '',
        'Paths',
        '-----',
        f'Chunk PDF: {CHUNK_PDF_PATH}',
        f'Ground truth: {GROUND_TRUTH_PATH}',
        f'Raw JSON: {RAW_JSON_PATH}',
        f'Plain transcription (line-joined): {PLAIN_TEXT_PATH}',
        f'AI log: {AI_LOG_PATH}',
        '',
        'Normalization',
        '---------------',
        'Same as stress-tests/compute-cer.py: normalize_for_cer(..., strip_html_emphasis=True).',
        'CER = Levenshtein distance / len(ground truth normalized).',
        '',
        'CER summary',
        '-----------',
        f'Cutoff CER (fraction): {TORTURE_OCR_CER_CUTOFF}',
        f'Cutoff CER (percent): {TORTURE_OCR_CER_CUTOFF:.6%}',
        f'Computed CER (fraction): {cer}',
        f'Computed CER (percent): {cer:.6%}',
        f'Within cutoff: {cer <= TORTURE_OCR_CER_CUTOFF}',
        '',
        'Counts',
        '------',
        f'JSON lines[] entries: {json_line_count}',
        f'Plain transcription newlines: {hypothesis_plain.count(chr(10))}',
        f'Ground truth file newlines: {truth_raw.count(chr(10))}',
        f'Normalized ground truth characters: {len(truth_norm)}',
        f'Normalized transcription characters: {len(hypothesis_norm)}',
        f'Levenshtein edit distance: {distance}',
        f'Normalized ground truth words (whitespace split): {len(truth_words)}',
        f'Normalized transcription words (whitespace split): {len(hyp_words)}',
        (
            'difflib.SequenceMatcher ratio (normalized char strings): '
            f'{seq_similarity:.6f}'
        ),
        '',
        'Normalized previews (first characters)',
        '---------------------------------------',
        f'Ground truth ({min(preview_len, len(truth_norm))} of {len(truth_norm)} chars):',
        truth_norm[:preview_len],
        '',
        f'Transcription ({min(preview_len, len(hypothesis_norm))} of {len(hypothesis_norm)} chars):',
        hypothesis_norm[:preview_len],
        '',
        'Word-level unified diff (normalized)',
        '--------------------------------------',
    ]
    if diff_truncated:
        blocks.append(
            f'(Diff truncated after {_MAX_DIFF_LINES} lines; compare .txt files and full strings locally.)',
        )
        blocks.append('')
    blocks.extend(diff_lines)
    blocks.append('')
    return '\n'.join(blocks)


@pytest.mark.integration
def test_live_integration_torture_ocr_cer_within_cutoff():
    skip_if_missing_api_key()

    for path in (RAW_JSON_PATH, AI_LOG_PATH, PLAIN_TEXT_PATH, CER_REPORT_PATH):
        if path.exists():
            path.unlink()

    transcribe_result = run_live_transcription(
        WORKING_DIR,
        CHUNK_FILENAME,
        STRATEGY_PROMPT_PATH,
        chunk_dir=TORTURE_DIR,
    )
    assert transcribe_result.returncode == 0, transcribe_result.stderr
    assert RAW_JSON_PATH.is_file()

    payload = json.loads(RAW_JSON_PATH.read_text(encoding='utf-8'))
    hypothesis_plain = _raw_json_to_plain(payload)
    PLAIN_TEXT_PATH.write_text(hypothesis_plain, encoding='utf-8')

    truth_raw = GROUND_TRUTH_PATH.read_text(encoding='utf-8')
    truth_norm, hypothesis_norm = _normalized_truth_and_hypothesis(
        hypothesis_plain,
        truth_raw,
    )
    cer, distance = _cer_and_distance(truth_norm, hypothesis_norm)
    lines = payload.get('lines')
    json_line_count = len(lines) if isinstance(lines, list) else 0
    seq_similarity = difflib.SequenceMatcher(
        None,
        truth_norm,
        hypothesis_norm,
    ).ratio()

    CER_REPORT_PATH.write_text(
        _build_cer_report(
            truth_raw=truth_raw,
            hypothesis_plain=hypothesis_plain,
            truth_norm=truth_norm,
            hypothesis_norm=hypothesis_norm,
            cer=cer,
            distance=distance,
            json_line_count=json_line_count,
            seq_similarity=seq_similarity,
        ),
        encoding='utf-8',
    )

    assert cer <= TORTURE_OCR_CER_CUTOFF, (
        f'CER {cer:.4%} exceeds cutoff {TORTURE_OCR_CER_CUTOFF:.4%}; '
        f'see {CER_REPORT_PATH}'
    )


if __name__ == '__main__':
    import sys

    raise SystemExit(pytest.main([__file__, '-v']))
