from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader, PdfWriter


class ReviewPdfGenerator:
    def __init__(
        self,
        working_dir: Path | None = None,
        state_file_name: str = '.review-chunk-state.json',
        scan_dir_name: str = 'scan-pdfs',
        review_dir_name: str = 'review-pdfs',
    ) -> None:
        self.working_dir = (working_dir or Path.cwd()).resolve()
        self.state_path = self.working_dir / state_file_name
        self.scan_dir = self.working_dir / scan_dir_name
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

    def resolve_scan_pdf(self, filename: str) -> Path:
        if not self.scan_dir.exists():
            raise ValueError(
                f'Missing source directory: {self.scan_dir}. '
                "Create 'scan-pdfs' and add source PDFs first."
            )

        normalized_name = filename.strip()
        if not normalized_name:
            raise ValueError('Scan filename is required.')

        if Path(normalized_name).name != normalized_name:
            raise ValueError('Provide only the filename, not a path.')

        if not normalized_name.lower().endswith('.pdf'):
            raise ValueError("Scan filename must end with '.pdf'.")

        scan_pdf_path = self.scan_dir / normalized_name
        if not scan_pdf_path.exists():
            raise ValueError(f'Scan PDF not found: {scan_pdf_path}')

        return scan_pdf_path

    def build_default_filename(
        self, scan_pdf: Path, start_page: int, end_page: int
    ) -> str:
        return f'{scan_pdf.stem}_{start_page:03d}-{end_page:03d}.pdf'

    def extract_pages(
        self, scan_pdf: Path, start_page: int, end_page: int, output_pdf: Path
    ):
        reader = PdfReader(str(scan_pdf))
        total_pages = len(reader.pages)
        self.validate_page_range(start_page, end_page, total_pages)

        writer = PdfWriter()
        for page_index in range(start_page - 1, end_page):
            writer.add_page(reader.pages[page_index])

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with output_pdf.open('wb') as output_file:
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
                f'End page {end_page} is beyond source PDF page count {total_pages}.'
            )

    def create_review_pdf(
        self,
        scan_filename: str,
        start_page: int,
        end_page: int,
        output_filename: str | None = None,
    ) -> Path:
        scan_pdf = self.resolve_scan_pdf(scan_filename)

        final_output_filename = (output_filename or '').strip()
        if not final_output_filename:
            final_output_filename = self.build_default_filename(
                scan_pdf, start_page, end_page
            )
        if not final_output_filename.lower().endswith('.pdf'):
            final_output_filename = f'{final_output_filename}.pdf'

        output_pdf = self.review_dir / final_output_filename
        self.extract_pages(scan_pdf, start_page, end_page, output_pdf)

        state = self.load_state()
        state['last_scan_filename'] = scan_filename
        state['last_end_page'] = end_page
        state['last_generated_output'] = str(output_pdf)
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        self.save_state(state)

        return output_pdf
