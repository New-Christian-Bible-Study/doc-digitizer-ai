'''Live integration test that transcribes a torture OCR sample, computes CER
against ground truth, and fails when error rate exceeds the configured cutoff.

Each immediate subdirectory of ``stress-tests/torture/`` that contains
``test-ocr.pdf`` is treated as one language fixture (names are directory names,
e.g. ``english``, ``italian``). New languages only require adding that tree; no
edit to this file.

To run CER for a single language, set ``TORTURE_OCR_LANG`` to that directory
name, for example::

    TORTURE_OCR_LANG=italian pytest prompt-based/tests/test_transcribe_chunk_torture_ocr_cer.py -v
'''

import difflib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import Levenshtein
import pytest

from transcribe_integration_helpers import (
    STRATEGY_PROMPT_PATH,
    run_live_transcription,
    skip_if_missing_api_key,
)


# Maximum allowed character error rate (fraction) vs stress-tests/torture/<lang>/ground-truth.txt.
# Single knob for experimentation; adjust as models and prompts change.
TORTURE_OCR_CER_CUTOFF = 0.05

# Cap word-level unified diff lines so the report stays a reasonable size.
_MAX_DIFF_LINES = 5000

STRATEGY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STRATEGY_ROOT.parent
TORTURE_ROOT = REPO_ROOT / 'stress-tests' / 'torture'
CHUNK_FILENAME = 'test-ocr.pdf'


def _discover_torture_language_ids():
    '''Directory names under TORTURE_ROOT that are language fixtures (have chunk PDF).'''
    if not TORTURE_ROOT.is_dir():
        return []
    names = []
    for path in TORTURE_ROOT.iterdir():
        if path.is_dir() and (path / CHUNK_FILENAME).is_file():
            names.append(path.name)
    return sorted(names)


def _torture_lang_params_for_parametrize():
    '''Languages to parametrize; honor TORTURE_OCR_LANG for a single-language run.'''
    discovered = _discover_torture_language_ids()
    only = os.environ.get('TORTURE_OCR_LANG', '').strip()
    if only:
        if only not in discovered:
            raise pytest.UsageError(
                f'TORTURE_OCR_LANG={only!r} is not a torture language directory '
                f'with {CHUNK_FILENAME} under {TORTURE_ROOT}. '
                f'Available: {discovered!r}',
            )
        return [only]
    return discovered


TORTURE_LANG_PARAMS = _torture_lang_params_for_parametrize()
_RAW_JSON_NAME = 'test-ocr_raw.json'
_COMPUTE_CER_PATH = REPO_ROOT / 'stress-tests' / 'compute-cer.py'
_TRANSCRIPTION_JSON_TO_ADOC_PATH = STRATEGY_ROOT / 'transcription-json-to-adoc.py'

# Match compute-cer.py default (strip-html-emphasis).
_STRIP_HTML_EMPHASIS = True

# CER vocabulary (same as speech/ASR and OCR metrics): the **reference** is the
# known-correct text (here, ground-truth.txt). The **hypothesis** is the system's
# transcription—the model output we score. Variables named hypothesis_* are the
# hypothesis side at different stages (raw line-joined text vs after normalize_for_cer).


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


def _load_transcription_json_to_adoc_module():
    spec = importlib.util.spec_from_file_location(
        'transcription_json_to_adoc',
        _TRANSCRIPTION_JSON_TO_ADOC_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f'Cannot load transcription-json-to-adoc from {_TRANSCRIPTION_JSON_TO_ADOC_PATH}',
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hypothesis_plain_from_payload(payload: dict) -> str:
    '''Build the hypothesis string from Pass 1 JSON before CER normalization.

    **hypothesis_plain** is the model transcription as a single document: each
    line's ``text`` joined with newlines, with AsciiDoc block markup (heading
    ``=`` prefixes, role lines, etc.) removed and inline ``**bold**`` /
    ``*italic*`` markers stripped so the ``*_raw.txt`` side matches plain
    ``ground-truth.txt`` before ``normalize_for_cer``.
    '''
    mod = _load_transcription_json_to_adoc_module()
    return mod.lines_to_adoc_body(
        payload,
        strip_inline_markup=True,
        strip_asciidoc_block=True,
    )


def _normalized_truth_and_hypothesis(hypothesis_plain: str, truth_raw: str) -> tuple[str, str]:
    '''Return (reference, hypothesis) both passed through ``normalize_for_cer``.

    ``hypothesis_plain`` is the line-joined hypothesis; the returned second
    value is that same hypothesis after normalization, ready for Levenshtein.
    '''
    compute_cer = _load_compute_cer_module()
    normalize = compute_cer.normalize_for_cer
    truth = normalize(truth_raw, _STRIP_HTML_EMPHASIS)
    hypothesis = normalize(hypothesis_plain, _STRIP_HTML_EMPHASIS)
    return truth, hypothesis


def _cer_and_distance(truth: str, hypothesis: str) -> tuple[float, int]:
    '''``truth`` and ``hypothesis`` are normalized reference and hypothesis strings.'''
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
    chunk_pdf_path: Path,
    ground_truth_path: Path,
    raw_json_path: Path,
    plain_text_path: Path,
    ai_log_path: Path,
    cer_report_path: Path,
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
        f'Chunk PDF: {chunk_pdf_path}',
        f'Ground truth: {ground_truth_path}',
        f'Raw JSON: {raw_json_path}',
        f'Plain transcription (line-joined): {plain_text_path}',
        f'AI log: {ai_log_path}',
        '',
        'Normalization',
        '---------------',
        'Same as stress-tests/compute-cer.py: normalize_for_cer(..., strip_html_emphasis=True).',
        'Hypothesis text: lines_to_adoc_body(..., strip_inline_markup=True, '
        'strip_asciidoc_block=True) from transcription-json-to-adoc.py.',
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
@pytest.mark.skipif(
    not TORTURE_LANG_PARAMS,
    reason=(
        f'No torture language directories with {CHUNK_FILENAME} under {TORTURE_ROOT}'
    ),
)
@pytest.mark.parametrize('torture_lang', TORTURE_LANG_PARAMS)
def test_live_integration_torture_ocr_cer_within_cutoff(torture_lang):
    skip_if_missing_api_key()

    torture_dir = TORTURE_ROOT / torture_lang
    chunk_pdf_path = torture_dir / CHUNK_FILENAME
    ground_truth_path = torture_dir / 'ground-truth.txt'
    working_dir = STRATEGY_ROOT / 'tests' / 'test-torture-ocr' / torture_lang
    raw_json_path = working_dir / 'transcriptions' / _RAW_JSON_NAME
    plain_text_path = raw_json_path.with_suffix('.txt')
    ai_log_path = working_dir / 'transcriptions' / 'test-ocr-ai-log.md'
    cer_report_path = working_dir / 'cer-report.txt'

    for path in (raw_json_path, ai_log_path, plain_text_path, cer_report_path):
        if path.exists():
            path.unlink()

    transcribe_result = run_live_transcription(
        working_dir,
        CHUNK_FILENAME,
        STRATEGY_PROMPT_PATH,
        chunk_dir=torture_dir,
    )
    assert transcribe_result.returncode == 0, transcribe_result.stderr
    assert raw_json_path.is_file()

    payload = json.loads(raw_json_path.read_text(encoding='utf-8'))
    # Hypothesis (model output) before shared CER normalization; saved for debugging.
    hypothesis_plain = _hypothesis_plain_from_payload(payload)
    plain_text_path.write_text(hypothesis_plain, encoding='utf-8')

    truth_raw = ground_truth_path.read_text(encoding='utf-8')
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

    cer_report_path.write_text(
        _build_cer_report(
            chunk_pdf_path=chunk_pdf_path,
            ground_truth_path=ground_truth_path,
            raw_json_path=raw_json_path,
            plain_text_path=plain_text_path,
            ai_log_path=ai_log_path,
            cer_report_path=cer_report_path,
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
        f'see {cer_report_path}'
    )


if __name__ == '__main__':
    import sys

    raise SystemExit(pytest.main([__file__, '-v']))
