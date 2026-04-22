"""Tests for ``chunk_lines_model`` geometry and line metadata helpers."""

from pathlib import Path

from chunk_lines_model import (
    LineRecord,
    REVIEW_COMPLETE_KEY,
    REVIEWER_CHANGED_KEY,
    REVIEW_PDF_RASTER_DPI,
    ChunkLinesSession,
    TranscriptionPaths,
    clamp_box_2d_to_pixels,
    line_text,
    line_confidence_label,
    line_notes,
    normalized_center_y_for_line,
    resolve_chunk_pdf_dir,
    resolve_transcription_paths_for_chunk,
)


def test_clamp_box_2d_to_pixels_center_square():
    # 10%–20% of a 1000×1000 page; padding applied from named constants.
    assert clamp_box_2d_to_pixels([100, 100, 200, 200], 1000, 1000) == (
        97,
        93,
        203,
        212,
    )


def test_clamp_box_2d_to_pixels_degenerate_box_non_empty():
    # Model noise at a corner → clamped to a 1×1 box, then padded within page.
    assert clamp_box_2d_to_pixels([0, 0, 0, 0], 100, 100) == (0, 0, 2, 3)


def test_clamp_box_2d_to_pixels_wide_short_strip():
    assert clamp_box_2d_to_pixels([400, 100, 450, 900], 1000, 1000) == (
        83,
        397,
        917,
        457,
    )


def test_review_pdf_raster_dpi_is_pinned():
    assert REVIEW_PDF_RASTER_DPI == 200


def test_normalized_center_y_for_line_returns_midpoint():
    assert normalized_center_y_for_line({'box_2d': [120, 10, 220, 80]}) == 170.0


def test_line_confidence_label_normalizes_and_validates():
    assert line_confidence_label({'ai_confidence_label': ' LOW '}) == 'low'
    assert line_confidence_label({'ai_confidence_label': 'unknown'}) is None


def test_line_notes_defaults_to_empty_string():
    assert line_notes({}) == ''
    assert line_notes({'ai_notes': 'hard glyph'}) == 'hard glyph'


def test_line_record_reviewer_metadata_round_trip():
    record = LineRecord.from_object({})
    assert record.reviewer_confidence_label() is None
    assert record.reviewer_notes() == ''

    record.set_reviewer_confidence_label('Medium')
    record.set_reviewer_notes('reviewer note')
    assert record.reviewer_confidence_label() == 'medium'
    assert record.reviewer_notes() == 'reviewer note'

    record.set_reviewer_confidence_label(None)
    assert record.reviewer_confidence_label() is None


def test_line_text_returns_rstripped_string():
    assert line_text({'text': 'abc   '}) == 'abc'
    assert line_text({'text': None}) == ''


def test_resolve_chunk_pdf_dir_default_is_chunk_pdfs_under_working(tmp_path: Path):
    wd = tmp_path / 'proj'
    wd.mkdir()
    assert resolve_chunk_pdf_dir(wd, None) == wd.resolve() / 'chunk-pdfs'


def test_resolve_chunk_pdf_dir_relative_under_working(tmp_path: Path):
    wd = tmp_path / 'proj'
    wd.mkdir()
    ext = tmp_path / 'external'
    ext.mkdir()
    assert resolve_chunk_pdf_dir(wd, Path('../external')) == ext.resolve()


def test_resolve_transcription_paths_uses_chunk_pdf_dir(tmp_path: Path):
    wd = tmp_path / 'w'
    chunks = tmp_path / 'c'
    trans = wd / 'transcriptions'
    wd.mkdir()
    chunks.mkdir()
    trans.mkdir(parents=True)
    (chunks / 'x.pdf').write_bytes(b'%PDF-1.4')
    (trans / 'x_raw.json').write_text('{"lines":[]}', encoding='utf-8')
    r = resolve_transcription_paths_for_chunk(
        wd, 'x.pdf', None, chunk_pdf_dir=chunks
    )
    assert isinstance(r, TranscriptionPaths)
    assert r.chunk_path == chunks / 'x.pdf'
    assert r.raw_path == trans / 'x_raw.json'


def test_review_flags_compare_against_raw_baseline():
    session = ChunkLinesSession()
    session.payload = {'lines': [{'text': 'raw one'}, {'text': 'raw two'}]}
    session.lines = session.payload['lines']
    session.line_records = [LineRecord.from_object(line) for line in session.lines]
    session.editable_indices = [0, 1]
    session._init_review_metadata({'lines': [{'text': 'raw one'}, {'text': 'raw two'}]})

    assert session.payload[REVIEW_COMPLETE_KEY] is False
    assert session.lines[0][REVIEWER_CHANGED_KEY] is False
    assert session.lines[1][REVIEWER_CHANGED_KEY] is False

    session.lines[1]['text'] = 'edited two'
    session.refresh_reviewer_changed_flags()
    assert session.lines[0][REVIEWER_CHANGED_KEY] is False
    assert session.lines[1][REVIEWER_CHANGED_KEY] is True


def test_low_confidence_unchanged_stats_counts_only_low():
    session = ChunkLinesSession()
    session.payload = {'lines': [{'text': 'a'}, {'text': 'b'}, {'text': 'c'}]}
    session.lines = session.payload['lines']
    session.line_records = [LineRecord.from_object(line) for line in session.lines]
    session.editable_indices = [0, 1, 2]
    session.lines[0]['ai_confidence_label'] = 'low'
    session.lines[1]['ai_confidence_label'] = 'medium'
    session.lines[2]['ai_confidence_label'] = 'low'
    session.lines[0][REVIEWER_CHANGED_KEY] = False
    session.lines[1][REVIEWER_CHANGED_KEY] = False
    session.lines[2][REVIEWER_CHANGED_KEY] = True

    unchanged_low, total_low = session.low_confidence_unchanged_stats()
    assert unchanged_low == 1
    assert total_low == 2


def test_reload_from_raw_restores_missing_confidence_metadata(tmp_path: Path):
    raw_path = tmp_path / 'chunk_raw.json'
    raw_path.write_text(
        '{"lines":[{"page_number":1,"text":"line one","box_2d":[0,0,10,10]}]}',
        encoding='utf-8',
    )

    session = ChunkLinesSession()
    session.source_raw_path = str(raw_path)
    session.lines = [
        {
            'page_number': 1,
            'text': 'line one',
            'box_2d': [0, 0, 10, 10],
            'ai_confidence_label': 'medium',
            'ai_notes': 'faded text',
        }
    ]
    session.line_records = [LineRecord.from_object(line) for line in session.lines]
    session.payload = {'lines': session.lines}

    err = session.reload_from_raw_disk()

    assert err is None
    assert session.lines[0]['ai_confidence_label'] == 'medium'
    assert session.lines[0]['ai_notes'] == 'faded text'


def test_reload_from_raw_preserves_existing_confidence_metadata_when_raw_conflicts(tmp_path: Path):
    raw_path = tmp_path / 'chunk_raw.json'
    raw_path.write_text(
        (
            '{"lines":[{"page_number":1,"text":"line one","box_2d":[0,0,10,10],'
            '"ai_confidence_label":"high","ai_notes":""}]}'
        ),
        encoding='utf-8',
    )

    session = ChunkLinesSession()
    session.source_raw_path = str(raw_path)
    session.lines = [
        {
            'page_number': 1,
            'text': 'line one',
            'box_2d': [0, 0, 10, 10],
            'ai_confidence_label': 'medium',
            'ai_notes': 'faded text',
        }
    ]
    session.line_records = [LineRecord.from_object(line) for line in session.lines]
    session.payload = {'lines': session.lines}

    err = session.reload_from_raw_disk()

    assert err is None
    assert session.lines[0]['ai_confidence_label'] == 'medium'
    assert session.lines[0]['ai_notes'] == 'faded text'


def test_reload_from_raw_restores_confidence_when_indices_shift():
    session = ChunkLinesSession()
    previous_lines = [
        {'text': '// Page 1'},
        {
            'page_number': 1,
            'text': 'line one',
            'box_2d': [0, 0, 10, 10],
            'ai_confidence_label': 'medium',
            'ai_notes': 'faded text',
        },
    ]
    session.payload = {
        'lines': [
            {'page_number': 1, 'text': 'line one', 'box_2d': [0, 0, 10, 10]},
        ]
    }
    session.lines = session.payload['lines']
    session.line_records = [LineRecord.from_object(line) for line in session.lines]
    session._restore_confidence_metadata_from_previous(
        [LineRecord.from_object(line) for line in previous_lines]
    )

    assert session.payload['lines'][0]['ai_confidence_label'] == 'medium'
    assert session.payload['lines'][0]['ai_notes'] == 'faded text'
