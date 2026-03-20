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

## Transcribe a review PDF

Use Gemini through LiteLLM to transcribe a file from `review-pdfs/` into
`transcriptions/<review_pdf_stem>.md`.

```bash
export GEMINI_API_KEY=...
python transcribe-review-pdf.py \
  --working-dir tests/test-1 \
  --review-pdf test-a_001-003.pdf \
  --prompt-md tests/test-1/prompt.md
```

Notes:
- `transcriptions/` is created automatically if it does not exist.
- `--review-pdf` must be a filename only (no path).
- `--out-json <path>` optionally saves validated full JSON response.

Live integration test:

```bash
pytest -q -k transcribe_review_pdf
```
