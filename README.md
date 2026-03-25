# Chunk PDF Generator

Interactive tooling to split source PDFs into smaller chunk PDFs for transcription and human QA workflows.

## Install

```bash
python -m pip install -r requirements.txt
```

## Directory layout

Run the script from a transcription working directory that contains:

- `source-pdfs/`: source PDFs to split
- `chunk-pdfs/`: generated chunk PDFs
- `.chunk-pdf-state.json`: created automatically to store defaults

Example fixture working directory:

- `tests/test-1/source-pdfs/test-a.pdf`
- `tests/test-1/source-pdfs/test-b.pdf`
- `tests/test-1/chunk-pdfs/`

## Generate a chunk PDF

```bash
python generate-chunk-pdf.py --working-dir tests/test-1
```

Prompts:

- Source PDF filename (filename only, from `source-pdfs/`)
- Start PDF page
- End PDF page
- Output chunk PDF filename (editable default)

Default output naming:

- `<scan_chunk_stem>_<start:03d>-<end:03d>.pdf`
- Example: `test-a_001-005.pdf`

## Fixture PDF regeneration

If you edit fixture AsciiDoc files, regenerate PDFs with:

```bash
asciidoctor-pdf tests/test-1/test-a.adoc -o tests/test-1/source-pdfs/test-a.pdf
asciidoctor-pdf tests/test-1/test-b.adoc -o tests/test-1/source-pdfs/test-b.pdf
```

## Run tests

```bash
pytest -q
```

## Transcribe a chunk PDF

Use Gemini through LiteLLM to transcribe a file from `chunk-pdfs/` into
`transcriptions/<chunk_pdf_stem>.md`, and write a reproducibility log to
`transcriptions/<chunk_pdf_stem>-ai-log.md`.

```bash
export GEMINI_API_KEY=...
python transcribe-chunk-pdf.py \
  --working-dir tests/test-1
```

Notes:
- `transcriptions/` is created automatically if it does not exist.
- Model settings and the system prompt string (`sys_instructions`) are read from `transcribe.config.json` with this precedence:
  - `<working-dir>/transcribe.config.json`
  - `<script-dir>/transcribe.config.json` (fallback)
- `--config` is not required.
- `--chunk-pdf` is optional. If omitted, the script prompts you to choose from `chunk-pdfs/` with up/down arrows. The default selection comes from `.chunk-pdf-state.json` (`last_generated_output`) when available.
- `--chunk-pdf` must be a filename only (no path) when provided.
- `--prompt-md` is optional. If omitted, the script looks for files matching `*prompt*.md` in the working directory:
  - if exactly one file matches, it is used automatically
  - if multiple files match, you can choose interactively with up/down arrows
  - if none match, the script exits with an error
- `<chunk_pdf_stem>-ai-log.md` includes: chunk PDF filename, confidence score, confidence label, notes, full transcribe config JSON used (including `sys_instructions`), and full prompt used.

Example `-ai-log.md`:

```markdown
# AI transcription run log

- Chunk PDF file: `test-a_001-003.pdf`
- Confidence score: `0.93`
- Confidence label: `high`
- Notes: Clear text with minor uncertainty around one table heading.

## Transcribe config used

```json
{
  "model": "gemini/gemini-2.5-flash",
  "temperature": 0.0,
  "reasoning_effort": "medium",
  "media_resolution": "high",
  "sys_instructions": "Transcribe this chunk PDF …"
}
```

(`sys_instructions` is abbreviated in this example; the repository file contains the full string.)

## Prompt used

````markdown
<!-- full prompt text captured verbatim -->
````
```

Live integration test:

```bash
pytest -q -k transcribe_review_pdf
```

Example `transcribe.config.json`:

```json
{
  "model": "gemini/gemini-2.5-flash",
  "temperature": 0.0,
  "reasoning_effort": "medium",
  "media_resolution": "high",
  "sys_instructions": "Transcribe this chunk PDF …"
}
```

The full default `sys_instructions` text is in the repository’s `transcribe.config.json`.
