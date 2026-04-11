from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader, PdfWriter


class ChunkGenerator:
    def __init__(
        self,
        working_dir: Path | None = None,
        state_file_name: str = '.chunk-state.json',
        scan_dir_name: str = 'source-pdfs',
        review_dir_name: str = 'chunk-pdfs',
        chunk_pdf_dir: Path | None = None,
    ) -> None:
        self.working_dir = (working_dir or Path.cwd()).resolve()
        self.state_path = self.working_dir / state_file_name
        self.scan_dir = self.working_dir / scan_dir_name
        if chunk_pdf_dir is not None:
            self.review_dir = Path(chunk_pdf_dir).resolve()
        else:
            self.review_dir = self.working_dir / review_dir_name

    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {}

        with self.state_path.open('r', encoding='utf-8') as state_file:
            data = json.load(state_file)

        if not isinstance(data, dict):
            raise ValueError('State file content must be a JSON object.')

        return data

    def save_state(self, state: dict):
        with self.state_path.open('w', encoding='utf-8') as state_file:
            json.dump(state, state_file, indent=2, sort_keys=True)
            state_file.write('\n')

    def get_default_start_page(self, state: dict) -> int:
        last_end_page = state.get('last_end_page')
        if isinstance(last_end_page, int) and last_end_page >= 1:
            return last_end_page + 1
        return 1

    def resolve_source(self, filename: str) -> Path:
        if not self.scan_dir.exists():
            raise ValueError(
                f'Missing source directory: {self.scan_dir}. '
                "Create 'source-pdfs' and add sources first."
            )

        normalized_name = filename.strip()
        if not normalized_name:
            raise ValueError('Source filename is required.')

        if Path(normalized_name).name != normalized_name:
            raise ValueError('Provide only the filename, not a path.')

        if not normalized_name.lower().endswith('.pdf'):
            raise ValueError("Source filename must end with '.pdf'.")

        source_path = self.scan_dir / normalized_name
        if not source_path.exists():
            raise ValueError(f'Source file not found: {source_path}')

        return source_path

    def build_default_filename(
        self, source: Path, start_page: int, end_page: int
    ) -> str:
        return f'{source.stem}_{start_page:03d}-{end_page:03d}.pdf'

    def extract_pages(
        self, source: Path, start_page: int, end_page: int, output: Path
    ):
        reader = PdfReader(str(source))
        total_pages = len(reader.pages)
        self.validate_page_range(start_page, end_page, total_pages)

        writer = PdfWriter()
        for page_index in range(start_page - 1, end_page):
            writer.add_page(reader.pages[page_index])

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('wb') as output_file:
            writer.write(output_file)

    def validate_page_range(self, start_page: int, end_page: int, total_pages: int):
        if start_page < 1:
            raise ValueError('Start page must be at least 1.')
        if end_page < 1:
            raise ValueError('End page must be at least 1.')
        if end_page < start_page:
            raise ValueError('End page must be greater than or equal to start page.')
        if end_page > total_pages:
            raise ValueError(
                f'End page {end_page} is beyond source page count {total_pages}.'
            )

    def create_chunk(
        self,
        source_filename: str,
        start_page: int,
        end_page: int,
        output_filename: str | None = None,
    ) -> Path:
        source = self.resolve_source(source_filename)

        final_output_filename = (output_filename or '').strip()
        if not final_output_filename:
            final_output_filename = self.build_default_filename(
                source, start_page, end_page
            )
        if not final_output_filename.lower().endswith('.pdf'):
            final_output_filename = f'{final_output_filename}.pdf'

        output = self.review_dir / final_output_filename
        self.extract_pages(source, start_page, end_page, output)

        state = self.load_state()
        state['last_source_filename'] = source_filename
        state['last_end_page'] = end_page
        state['last_generated_output'] = str(output)
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        self.save_state(state)

        return output
