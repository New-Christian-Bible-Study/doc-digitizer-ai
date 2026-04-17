#!/usr/bin/env python3

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import jsonschema
import questionary
import structlog
from jsonargparse import ArgumentParser as JsonArgParser
from litellm import completion
from pypdf import PdfReader

from chunk_generator import ChunkGenerator
from chunk_lines_model import (
    list_chunk_filenames,
    load_page_images,
    resolve_chunk_pdf_dir,
    snap_box_2d_to_ink,
)

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_SCHEMA_PATH = SCRIPT_DIR / 'raw-transcription.schema.json'
TRANSCRIBE_CONFIG_FILENAME = 'transcribe.config.json'
VALID_REASONING_EFFORTS = ('none', 'disable', 'low', 'medium', 'high', 'minimal')
VALID_MEDIA_RESOLUTIONS = ('low', 'medium', 'high', 'ultra_high', 'auto')
DEFAULT_TIMEOUT_SECONDS = 900.0
RUNTIME_LOG_FILENAME = 'transcribe-runtime.jsonl'
RUNTIME_LOG_JSON_KEY_ORDER = (
    'run_started_at',
    'event',
    'chunk_file',
    'total_pages',
    'confidence_label',
    'confidence_score',
    'total_inference_time_minutes',
    'average_time_per_page_seconds',
    'prompt_tokens',
    'completion_tokens',
    'total_tokens',
)


def reorder_runtime_log_event_dict(_logger, _method_name, event_dict):
    """Put known runtime-log keys first; append any extras (e.g. future structlog fields)."""
    event_dict.pop('logged_at', None)
    ordered = {key: event_dict[key] for key in RUNTIME_LOG_JSON_KEY_ORDER if key in event_dict}
    for key, value in event_dict.items():
        if key not in ordered:
            ordered[key] = value
    event_dict.clear()
    event_dict.update(ordered)
    return event_dict


def load_schema() -> dict:
    with RAW_SCHEMA_PATH.open('r', encoding='utf-8') as schema_file:
        return json.load(schema_file)


def build_response_format(schema: dict) -> dict:
    return {
        'type': 'json_schema',
        'json_schema': {
            'name': 'idp_line_transcription_response',
            'schema': schema,
            'strict': True,
        },
    }


def strip_json_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith('```'):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
    return text


def resolve_chunk(chunk_pdf_dir: Path, chunk_filename: str) -> Path:
    if not chunk_pdf_dir.is_dir():
        raise ValueError(
            f'Missing chunk PDF directory: {chunk_pdf_dir}. '
            'Create it and place chunk files there, or pass --chunk-dir.'
        )

    filename = chunk_filename.strip()
    if not filename:
        raise ValueError('Chunk filename is required.')
    if Path(filename).name != filename:
        raise ValueError('Provide only the chunk filename, not a path.')
    if not filename.lower().endswith('.pdf'):
        raise ValueError("Chunk filename must end with '.pdf'.")

    chunk_path = chunk_pdf_dir / filename
    if not chunk_path.exists():
        raise ValueError(f'Chunk not found: {chunk_path}')

    return chunk_path


def prompt_with_default(label: str, default: str) -> str:
    prompt = f'{label} [{default}]: ' if default else f'{label}: '
    value = input(prompt).strip()
    return value if value else default


def prompt_select_filename(label: str, default: str, options: list[str]) -> str:
    if not options:
        return prompt_with_default(label, default)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        while True:
            selected = prompt_with_default(label, default)
            if selected in options:
                return selected
            print(f"Please choose one of: {', '.join(options)}")

    default_choice = default if default in options else options[0]
    selected = questionary.select(
        f'{label}:',
        choices=options,
        default=default_choice,
        qmark='>',
    ).ask()
    if selected is None:
        raise KeyboardInterrupt
    return selected


def resolve_chunk_filename(working_dir: Path, chunk_pdf_dir: Path) -> str:
    filenames = list_chunk_filenames(chunk_pdf_dir)

    state = {}
    try:
        state = ChunkGenerator(working_dir=working_dir).load_state()
    except ValueError:
        state = {}

    last_generated = state.get('last_chunk_generated')
    default_filename = ''
    if isinstance(last_generated, str) and last_generated.strip():
        default_filename = Path(last_generated).name
    if default_filename not in filenames:
        default_filename = filenames[0] if filenames else default_filename

    if not filenames:
        print(
            f'No PDF files found in {chunk_pdf_dir}. '
            'Falling back to manual filename entry.'
        )

    return prompt_select_filename(
        label='Chunk filename',
        default=default_filename,
        options=filenames,
    )


def resolve_prompt_md(working_dir: Path) -> Path:
    prompt_candidates = sorted(
        path for path in working_dir.glob('*prompt*.md') if path.is_file()
    )
    if not prompt_candidates:
        default_prompt = SCRIPT_DIR / 'prompt.md'
        if default_prompt.exists():
            return default_prompt
        raise ValueError(
            f'No prompt markdown files found in {working_dir} matching *prompt*.md '
            f'and fallback prompt not found: {default_prompt}'
        )

    if len(prompt_candidates) == 1:
        return prompt_candidates[0]

    prompt_names = [path.name for path in prompt_candidates]
    default_name = 'prompt.md' if 'prompt.md' in prompt_names else prompt_names[0]
    selected_name = prompt_select_filename(
        label='Prompt markdown file',
        default=default_name,
        options=prompt_names,
    )
    return working_dir / selected_name


def resolve_prompt_md_auto(working_dir: Path) -> Path:
    prompt_candidates = sorted(
        path for path in working_dir.glob('*prompt*.md') if path.is_file()
    )
    if not prompt_candidates:
        default_prompt = SCRIPT_DIR / 'prompt.md'
        if default_prompt.exists():
            return default_prompt
        raise ValueError(
            f'No prompt markdown files found in {working_dir} matching *prompt*.md '
            f'and fallback prompt not found: {default_prompt}'
        )

    if len(prompt_candidates) == 1:
        return prompt_candidates[0]

    prompt_names = [path.name for path in prompt_candidates]
    default_name = 'prompt.md' if 'prompt.md' in prompt_names else prompt_names[0]
    return working_dir / default_name


def build_messages(
    sys_instructions: str,
    prompt_text: str,
    base64_url: str,
    media_resolution: str,
) -> list[dict]:
    return [
        {'role': 'system', 'content': sys_instructions},
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': prompt_text},
                # LiteLLM/OpenAI-style multimodal content uses the field name `detail`.
                # We expose this as `media_resolution` in config for clarity.
                {
                    'type': 'file',
                    'file': {'file_data': base64_url, 'detail': media_resolution},
                },
            ],
        },
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Transcribe chunk(s) via Gemini/LiteLLM.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--chunk',
        required=False,
        default=None,
        help='Chunk PDF filename only (resolved under --chunk-dir, default working-dir/chunk-pdfs).',
    )
    parser.add_argument(
        '--prompt-md',
        type=Path,
        default=None,
        help='Optional path to prompt markdown file.',
    )
    parser.add_argument(
        '--working-dir',
        type=Path,
        default=Path('.'),
        help='Optional working directory containing chunk-pdfs/ and transcriptions/.',
    )
    parser.add_argument(
        '--chunk-dir',
        type=Path,
        default=None,
        help=(
            'Directory containing chunk PDFs (default: working-dir/chunk-pdfs). '
            'Relative paths are resolved under working-dir.'
        ),
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help=(
            'Transcribe every .pdf in the chunk directory without prompting '
            '(non-interactive).'
        ),
    )
    args = parser.parse_args()
    if args.all and args.chunk is not None:
        parser.error('cannot combine --all with --chunk')
    return args


def resolve_transcribe_config_path(working_dir: Path) -> Path:
    working_dir_config = working_dir / TRANSCRIBE_CONFIG_FILENAME
    if working_dir_config.exists():
        return working_dir_config

    script_dir_config = SCRIPT_DIR / TRANSCRIBE_CONFIG_FILENAME
    if script_dir_config.exists():
        return script_dir_config

    raise ValueError(
        f'Missing transcribe config file: expected {working_dir_config} '
        f'or {script_dir_config}'
    )


def load_transcribe_config(config_path: Path) -> dict:
    parser = JsonArgParser(exit_on_error=False)
    parser.add_argument('--model', type=str, required=True)
    parser.add_argument('--temperature', type=float, required=True)
    parser.add_argument(
        '--reasoning_effort',
        type=str,
        choices=VALID_REASONING_EFFORTS,
        required=True,
    )
    parser.add_argument(
        '--media_resolution',
        type=str,
        choices=VALID_MEDIA_RESOLUTIONS,
        required=True,
    )
    parser.add_argument('--sys_instructions', type=str, required=True)
    parser.add_argument(
        '--timeout_seconds',
        type=float,
        required=False,
        default=DEFAULT_TIMEOUT_SECONDS,
    )

    try:
        config_data = json.loads(config_path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise ValueError(f'Could not read config file {config_path}: {exc}') from exc

    try:
        parsed = parser.parse_object(config_data)
    except Exception as exc:
        raise ValueError(f'Invalid config file {config_path}: {exc}') from exc

    return {
        'model': parsed.model,
        'temperature': parsed.temperature,
        'reasoning_effort': parsed.reasoning_effort,
        'media_resolution': parsed.media_resolution,
        'sys_instructions': parsed.sys_instructions,
        'timeout_seconds': parsed.timeout_seconds,
    }


def normalize_transcription_newlines(transcription: object) -> str:
    if not isinstance(transcription, str):
        return ''

    normalized = transcription.replace('\r\n', '\n')
    if '\\n' in normalized or '\\r' in normalized:
        normalized = (
            normalized.replace('\\r\\n', '\n')
            .replace('\\n', '\n')
            .replace('\\r', '\n')
        )
    return normalized


def normalize_lines_from_model(raw_lines: object) -> list[dict]:
    if not isinstance(raw_lines, list):
        return []

    normalized: list[dict] = []
    for item in raw_lines:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                'page_number': item.get('page_number'),
                'text': normalize_transcription_newlines(item.get('text', '')),
                'box_2d': item.get('box_2d'),
                'confidence_label': item.get('confidence_label'),
                'notes': item.get('notes', ''),
            }
        )
    return normalized


def build_llm_payload_for_validation(raw: dict) -> dict:
    return {
        'lines': normalize_lines_from_model(raw.get('lines')),
        'confidence_score': raw.get('confidence_score'),
        'confidence_label': raw.get('confidence_label'),
    }


def build_full_transcription_payload(
    llm_payload: dict,
    transcribe_config: dict,
) -> dict:
    return {
        'lines': llm_payload['lines'],
        'confidence_score': llm_payload['confidence_score'],
        'confidence_label': llm_payload['confidence_label'],
        'model': transcribe_config['model'],
        'configuration': (
            f'temperature={transcribe_config["temperature"]}, '
            f'media_resolution={transcribe_config["media_resolution"]}, '
            f'reasoning_effort={transcribe_config["reasoning_effort"]}'
        ),
    }


def snap_line_boxes_to_ink(chunk_path: Path, lines: list[dict]) -> str | None:
    """Replace each line's ``box_2d`` with snap-to-ink bounds when detection succeeds."""
    # Only automated step that mutates ``box_2d`` before review (aside from manual
    # JSON edits). Reviewer UI reads boxes as-is from ``*_raw.json`` / ``*_final.json``.
    try:
        # Raster once per chunk so --all mode does not re-render per line.
        page_images = load_page_images(chunk_path)
    except Exception as exc:
        return f'Could not rasterize pages for snap-to-ink: {exc}'

    for line in lines:
        page_number = line.get('page_number')
        box_2d = line.get('box_2d')
        if not isinstance(page_number, int) or page_number < 1:
            continue
        if page_number > len(page_images):
            continue
        snapped = snap_box_2d_to_ink(page_images[page_number - 1], box_2d)
        if snapped is None:
            # Keep original model coordinates when snap confidence is weak.
            continue
        # In early-dev mode, ``box_2d`` is authoritative and stores snapped output.
        line['box_2d'] = snapped
    return None


def is_notes_min_length_validation_error(exc: jsonschema.ValidationError) -> bool:
    validator_is_min_length = exc.validator == 'minLength'
    validator_value_is_one = exc.validator_value == 1
    path = list(exc.absolute_path)
    field_is_notes = path and path[-1] == 'notes'
    schema_path = list(exc.absolute_schema_path)
    schema_points_to_notes = schema_path and schema_path[-1] == 'minLength'
    return (
        validator_is_min_length
        and validator_value_is_one
        and field_is_notes
        and schema_points_to_notes
    )


def get_page_count(path: Path) -> int:
    try:
        reader = PdfReader(str(path))
        return len(reader.pages)
    except Exception as exc:
        raise ValueError(f'Could not read page count from {path}: {exc}') from exc


def extract_usage_tokens(response) -> tuple[object, object, object]:
    """Return (prompt_tokens, completion_tokens, total_tokens) from a LiteLLM response."""
    usage = getattr(response, 'usage', None)
    if usage is None:
        return (None, None, None)
    return (
        getattr(usage, 'prompt_tokens', None),
        getattr(usage, 'completion_tokens', None),
        getattr(usage, 'total_tokens', None),
    )


def format_token_log_value(value: object) -> str:
    if value is None:
        return '(not reported)'
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def log_runtime_event(
    chunk_filename: str,
    run_started_at: str,
    total_pages: int,
    inference_time_seconds: object,
    average_time_per_page_seconds: object,
    prompt_tokens: object,
    completion_tokens: object,
    total_tokens: object,
    confidence_score: object,
    confidence_label: object,
) -> Path:
    runtime_log_path = SCRIPT_DIR / RUNTIME_LOG_FILENAME
    runtime_log_path.parent.mkdir(parents=True, exist_ok=True)

    with runtime_log_path.open('a', encoding='utf-8') as runtime_log_file:
        logger = structlog.wrap_logger(
            structlog.WriteLogger(runtime_log_file),
            processors=[
                reorder_runtime_log_event_dict,
                structlog.processors.JSONRenderer(sort_keys=False),
            ],
        )
        logger.info(
            'transcription_run',
            run_started_at=run_started_at,
            chunk_file=chunk_filename,
            total_pages=total_pages,
            confidence_label=confidence_label,
            confidence_score=confidence_score,
            total_inference_time_minutes=(
                None
                if inference_time_seconds is None
                else round(float(inference_time_seconds) / 60.0, 2)
            ),
            average_time_per_page_seconds=(
                None
                if average_time_per_page_seconds is None
                else round(float(average_time_per_page_seconds), 2)
            ),
            prompt_tokens=format_token_log_value(prompt_tokens),
            completion_tokens=format_token_log_value(completion_tokens),
            total_tokens=format_token_log_value(total_tokens),
        )
    return runtime_log_path


def build_ai_summary_markdown(
    chunk_filename: str,
    total_pages: int,
    transcribe_config_text: str,
    confidence_score: object,
    confidence_label: object,
    prompt_text: str,
) -> str:
    confidence_score_text = '' if confidence_score is None else str(confidence_score)
    confidence_label_text = '' if confidence_label is None else str(confidence_label)

    return (
        '# AI transcription summary\n\n'
        f'- Chunk file: `{chunk_filename}`\n'
        f'- Total pages: `{total_pages}`\n'
        f'- Confidence score: `{confidence_score_text}`\n'
        f'- Confidence label: `{confidence_label_text}`\n'
        '## Transcribe config used\n\n'
        '```json\n'
        f'{transcribe_config_text}\n'
        '```\n\n'
        '## Prompt used\n\n'
        '````markdown\n'
        f'{prompt_text}\n'
        '````\n'
    )


def write_raw_response_debug_file(
    transcriptions_dir: Path,
    chunk_stem: str,
    content: object,
) -> Path:
    transcriptions_dir.mkdir(parents=True, exist_ok=True)
    raw_response_path = transcriptions_dir / f'{chunk_stem}-raw-response.txt'
    response_text = '' if content is None else str(content)
    raw_response_path.write_text(response_text + '\n', encoding='utf-8')
    return raw_response_path


def build_json_error_excerpt(
    text: str,
    exc: Exception,
    context_lines: int = 2,
) -> str:
    if not isinstance(exc, json.JSONDecodeError):
        return ''

    lines = text.splitlines()
    if not lines:
        return ''

    line_index = max(exc.lineno - 1, 0)
    start = max(line_index - context_lines, 0)
    end = min(line_index + context_lines + 1, len(lines))
    width = len(str(end))

    excerpt_lines: list[str] = []
    for idx in range(start, end):
        line_no = idx + 1
        prefix = '>>' if idx == line_index else '  '
        excerpt_lines.append(f'{prefix} {line_no:>{width}} | {lines[idx]}')
        if idx == line_index:
            col = max(exc.colno, 1)
            caret_padding = ' ' * (width + 5 + col - 1)
            excerpt_lines.append(f'   {caret_padding}^')

    return '\n'.join(excerpt_lines)


def transcribe_single_chunk(
    working_dir: Path,
    prompt_md: Path,
    transcribe_config: dict,
    config_path: Path,
    schema: dict,
    chunk_filename: str,
    chunk_pdf_dir: Path,
) -> int:
    run_started_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    try:
        chunk_path = resolve_chunk(chunk_pdf_dir, chunk_filename)
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    try:
        total_pages = get_page_count(chunk_path)
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2

    prompt_text = prompt_md.read_text(encoding='utf-8')
    transcribe_config_text = config_path.read_text(encoding='utf-8').strip()
    encoded_pdf = base64.b64encode(chunk_path.read_bytes()).decode('utf-8')
    pdf_data_url = f'data:application/pdf;base64,{encoded_pdf}'
    print(f'Using prompt file: {prompt_md}')
    print(
        f'Transcribing {chunk_path.name} with {transcribe_config["model"]} '
        f'(timeout={transcribe_config["timeout_seconds"]:.0f}s); '
        'this can take a while...',
        flush=True,
    )

    try:
        inference_start = time.perf_counter()
        response = completion(
            model=transcribe_config['model'],
            messages=build_messages(
                transcribe_config['sys_instructions'],
                prompt_text,
                pdf_data_url,
                transcribe_config['media_resolution'],
            ),
            temperature=transcribe_config['temperature'],
            reasoning_effort=transcribe_config['reasoning_effort'],
            response_format=build_response_format(schema),
            timeout=transcribe_config['timeout_seconds'],
        )
        inference_time_seconds = time.perf_counter() - inference_start
    except Exception as exc:
        print(f'LiteLLM request failed: {exc}', file=sys.stderr)
        return 1

    prompt_tokens, completion_tokens, total_tokens = extract_usage_tokens(response)

    average_time_per_page_seconds = (
        inference_time_seconds / total_pages if total_pages > 0 else None
    )

    content = None
    try:
        content = response.choices[0].message.content
        raw = json.loads(strip_json_code_fence(content))
    except Exception as exc:
        transcriptions_dir = working_dir / 'transcriptions'
        raw_response_path = write_raw_response_debug_file(
            transcriptions_dir=transcriptions_dir,
            chunk_stem=chunk_path.stem,
            content=content,
        )
        print(f'Error parsing model response JSON: {exc}', file=sys.stderr)
        excerpt = build_json_error_excerpt(
            text='' if content is None else str(content),
            exc=exc,
        )
        if excerpt:
            print('JSON parse error context:', file=sys.stderr)
            print(excerpt, file=sys.stderr)
        print(
            f'Wrote raw model response to: {raw_response_path}',
            file=sys.stderr,
        )
        return 1

    llm_payload = build_llm_payload_for_validation(raw)

    try:
        jsonschema.validate(instance=llm_payload, schema=schema)
    except jsonschema.ValidationError as exc:
        if is_notes_min_length_validation_error(exc):
            print(
                'Warning: notes failed schema minLength validation; continuing '
                "because empty notes are allowed when confidence_score is 1.0.",
                file=sys.stderr,
            )
        else:
            print(f'Schema validation failed: {exc}', file=sys.stderr)
            return 1

    if not llm_payload['lines']:
        print(
            'Error: model returned no lines (empty "lines" array).',
            file=sys.stderr,
        )
        return 1

    # Run snap-to-ink after schema validation so we only post-process well-formed data.
    # This step corrects the VLM's natural "coordinate drift" by adjusting the raw
    # `box_2d` coordinates to perfectly wrap the physical ink printed on the page.
    snap_err = snap_line_boxes_to_ink(chunk_path, llm_payload['lines'])
    if snap_err is not None:
        print(f'Warning: {snap_err}', file=sys.stderr)

    payload = build_full_transcription_payload(llm_payload, transcribe_config)

    transcriptions_dir = working_dir / 'transcriptions'
    transcriptions_dir.mkdir(parents=True, exist_ok=True)
    output_raw_json = transcriptions_dir / f'{chunk_path.stem}_raw.json'
    output_ai_summary_md = transcriptions_dir / f'{chunk_path.stem}_summary.md'
    output_raw_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    output_ai_summary_md.write_text(
        build_ai_summary_markdown(
            chunk_filename=chunk_path.name,
            total_pages=total_pages,
            transcribe_config_text=transcribe_config_text,
            confidence_score=payload['confidence_score'],
            confidence_label=payload['confidence_label'],
            prompt_text=prompt_text,
        ),
        encoding='utf-8',
    )
    runtime_log_path = log_runtime_event(
        chunk_filename=chunk_path.name,
        run_started_at=run_started_at,
        total_pages=total_pages,
        inference_time_seconds=inference_time_seconds,
        average_time_per_page_seconds=average_time_per_page_seconds,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        confidence_score=payload['confidence_score'],
        confidence_label=payload['confidence_label'],
    )

    print(f'Created raw transcription JSON: {output_raw_json}')
    print(f'Created AI summary: {output_ai_summary_md}')
    print(f'Appended runtime log: {runtime_log_path}')
    return 0


def main() -> int:
    args = parse_args()
    working_dir = args.working_dir.resolve()
    chunk_pdf_dir = resolve_chunk_pdf_dir(working_dir, args.chunk_dir)
    schema = load_schema()

    try:
        config_path = resolve_transcribe_config_path(working_dir)
        transcribe_config = load_transcribe_config(config_path)
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2

    if not os.environ.get('GEMINI_API_KEY'):
        print('Error: GEMINI_API_KEY environment variable is not set.', file=sys.stderr)
        return 2

    if args.prompt_md is not None:
        prompt_md = args.prompt_md.resolve()
    else:
        try:
            if args.all:
                prompt_md = resolve_prompt_md_auto(working_dir)
            else:
                prompt_md = resolve_prompt_md(working_dir)
        except ValueError as exc:
            print(f'Error: {exc}', file=sys.stderr)
            return 2

    if not prompt_md.exists():
        print(f'Error: Prompt file not found: {prompt_md}', file=sys.stderr)
        return 2

    if args.all:
        chunk_filenames = list_chunk_filenames(chunk_pdf_dir)
        if not chunk_filenames:
            print(
                f'Error: No PDF files in {chunk_pdf_dir}. Nothing to transcribe.',
                file=sys.stderr,
            )
            return 2
        print(f'--all: transcribing {len(chunk_filenames)} chunk(s).', flush=True)
        for chunk_filename in chunk_filenames:
            print(f'--- {chunk_filename} ---', flush=True)
            rc = transcribe_single_chunk(
                working_dir,
                prompt_md,
                transcribe_config,
                config_path,
                schema,
                chunk_filename,
                chunk_pdf_dir,
            )
            if rc != 0:
                return rc
        return 0

    chunk_filename = args.chunk
    if chunk_filename is None:
        chunk_filename = resolve_chunk_filename(working_dir, chunk_pdf_dir)

    return transcribe_single_chunk(
        working_dir,
        prompt_md,
        transcribe_config,
        config_path,
        schema,
        chunk_filename,
        chunk_pdf_dir,
    )


if __name__ == '__main__':
    raise SystemExit(main())
