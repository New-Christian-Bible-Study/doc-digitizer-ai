import sys
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

STRATEGY_ROOT = Path(__file__).resolve().parents[1]
if str(STRATEGY_ROOT) not in sys.path:
    sys.path.insert(0, str(STRATEGY_ROOT))

from chunk_generator import ChunkGenerator


def create_pdf_with_pages(path: Path, page_count: int):
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as output_file:
        writer.write(output_file)


def test_build_default_filename_uses_zero_padding(tmp_path: Path):
    generator = ChunkGenerator(working_dir=tmp_path)
    scan_pdf = tmp_path / 'source-pdfs' / 'book-part.pdf'

    result = generator.build_default_filename(scan_pdf, 1, 10)

    assert result == 'book-part_001-010.pdf'


def test_load_state_returns_empty_for_missing_state_file(tmp_path: Path):
    generator = ChunkGenerator(working_dir=tmp_path)

    state = generator.load_state()

    assert state == {}


def test_resolve_source_rejects_path_input(tmp_path: Path):
    generator = ChunkGenerator(working_dir=tmp_path)
    (tmp_path / 'source-pdfs').mkdir(parents=True)

    with pytest.raises(ValueError, match='Provide only the filename'):
        generator.resolve_source('subdir/file.pdf')


def test_create_chunk_extracts_expected_pages_and_updates_state(tmp_path: Path):
    generator = ChunkGenerator(working_dir=tmp_path)
    source_pdf = tmp_path / 'source-pdfs' / 'book-a.pdf'
    create_pdf_with_pages(source_pdf, page_count=5)

    output_pdf = generator.create_chunk(
        source_filename='book-a.pdf',
        start_page=2,
        end_page=4,
    )

    assert output_pdf.exists()
    extracted_reader = PdfReader(str(output_pdf))
    assert len(extracted_reader.pages) == 3

    state = generator.load_state()
    assert state['last_source_filename'] == 'book-a.pdf'
    assert state['last_end_page'] == 4
    assert state['last_generated_output'].endswith('book-a_002-004.pdf')


def test_create_chunk_validates_end_page_within_source(tmp_path: Path):
    generator = ChunkGenerator(working_dir=tmp_path)
    source_pdf = tmp_path / 'source-pdfs' / 'book-a.pdf'
    create_pdf_with_pages(source_pdf, page_count=3)

    with pytest.raises(ValueError, match='beyond source page count'):
        generator.create_chunk(
            source_filename='book-a.pdf',
            start_page=1,
            end_page=4,
        )
