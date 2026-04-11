"""Tests for ``chunk_lines_model`` geometry and line metadata helpers."""

from pathlib import Path

from chunk_lines_model import (
    REVIEW_PDF_RASTER_DPI,
    TranscriptionPaths,
    clamp_box_2d_to_pixels,
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
    assert line_confidence_label({'confidence_label': ' LOW '}) == 'low'
    assert line_confidence_label({'confidence_label': 'unknown'}) is None


def test_line_notes_defaults_to_empty_string():
    assert line_notes({}) == ''
    assert line_notes({'notes': 'hard glyph'}) == 'hard glyph'


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
