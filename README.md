# Review PDF Generator

Interactive tooling to split source PDFs into smaller review PDFs for transcription and human QA workflows.

## Install

```bash
python -m pip install -r requirements.txt
```

## Directory layout

Run the script from a transcription working directory that contains:

- `scan-pdfs/`: source PDFs to split
- `review-pdfs/`: generated review PDFs
- `.review-chunk-state.json`: created automatically to store defaults

Example fixture working directory:

- `tests/test-1/scan-pdfs/test-a.pdf`
- `tests/test-1/scan-pdfs/test-b.pdf`
- `tests/test-1/review-pdfs/`

## Generate a review PDF

```bash
python generate-review-pdf.py --working-dir tests/test-1
```

Prompts:

- Scan PDF filename (filename only, from `scan-pdfs/`)
- Start PDF page
- End PDF page
- Output review PDF filename (editable default)

Default output naming:

- `<scan_chunk_stem>_<start:03d>-<end:03d>.pdf`
- Example: `test-a_001-005.pdf`

## Fixture PDF regeneration

If you edit fixture AsciiDoc files, regenerate PDFs with:

```bash
asciidoctor-pdf tests/test-1/test-a.adoc -o tests/test-1/scan-pdfs/test-a.pdf
asciidoctor-pdf tests/test-1/test-b.adoc -o tests/test-1/scan-pdfs/test-b.pdf
```

## Run tests

```bash
pytest -q
```
