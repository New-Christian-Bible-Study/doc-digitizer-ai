# Document digitizing using AI

This repository provides script tooling for transcribing handwritten and typewritten PDF content using AI.

## Goals

- Leverage AI as much as possible for transcribing handwritten and typewritten text.
- Make large transcription projects manageable by splitting source PDFs into chunk PDFs.
- Improve quality and efficiency by fixing prompts early based on human transcription corrections before generating chunks for later sections.
- Avoid processing too many pages at once, which can hit model token limits.

## Install

```bash
python -m pip install -r requirements.txt
```

## Working directory layout

Create one dedicated working directory per work/book/manuscript and run the scripts from there.

### Directories

| Path | Purpose |
| --- | --- |
| `source-pdfs/` | Source PDFs to transcribe. |
| `chunk-pdfs/` | Chunk PDFs generated from page ranges in a source PDF. |
| `transcriptions/` | Transcription outputs and AI run logs. Created automatically as needed. |

### Files

| Path | Purpose |
| --- | --- |
| `prompt.md` | Prompt used during transcription (`--prompt-md` can override). |
| `.chunk-state.json` | Created automatically to store defaults such as last selected source and generated output. |
| `transcribe.config.json` | Optional per-work config to override the repository default model/settings. |

### Example layout

```text
my-work/
├── source-pdfs/
│   ├── volume-1.pdf
│   └── volume-2.pdf
├── chunk-pdfs/
├── transcriptions/
├── prompt.md
├── transcribe.config.json
└── .chunk-state.json
```

Run commands from the repository root and point to your working directory with `--working-dir`, or `cd` into your working directory and pass `--working-dir .`.

## Generate a chunk PDF

`generate-chunk-pdf.py` extracts selected pages from a source PDF in `source-pdfs/` and writes a chunk PDF to `chunk-pdfs/`.

```bash
python generate-chunk-pdf.py --working-dir tests/test-1
```

The script prompts for:

- Source PDF filename (filename only, chosen from `source-pdfs/`)
- Start PDF page
- End PDF page
- Output chunk PDF filename (editable default)

Default output naming:

- `<scan_chunk_stem>_<start:03d>-<end:03d>.pdf`
- Example: `test-a_001-005.pdf`

## Transcribe a chunk PDF

`transcribe-chunk-pdf.py` transcribes a file from `chunk-pdfs/` into:

- `transcriptions/<chunk_pdf_stem>.adoc`
- `transcriptions/<chunk_pdf_stem>-ai-log.md`

By default a Gemini model is used to do the transcription. 
To create a Gemini API key: [Google AI Studio - Get API key](https://ai.google.dev/gemini-api/docs/api-key)

### Specifying the API key to use

The environment variable `GEMINI_API_KEY` is used for storing the API key to use.

```bash
export GEMINI_API_KEY=...
```

### Example run

```bash
export GEMINI_API_KEY=...
python transcribe-chunk-pdf.py --working-dir tests/test-1
```

### Notes

- `transcriptions/` is created automatically if it does not exist.
- `--chunk-pdf` is optional. If omitted, you choose from `chunk-pdfs/` interactively. The default selection uses `.chunk-state.json` (`last_generated_output`) when available.
- `--chunk-pdf` must be a filename only (no path).
- `--prompt-md` is optional. If omitted, the script searches for `*prompt*.md` in the working directory:
  - if exactly one file matches, it is used automatically
  - if multiple files match, you can choose interactively
  - if none match, the script exits with an error
- Transcribe config is loaded from `transcribe.config.json` with this precedence:
  - `<working-dir>/transcribe.config.json`
  - `<script-dir>/transcribe.config.json` (fallback)
- The `-ai-log.md` file includes chunk filename, run timing, confidence score/label, notes, full config JSON used (including `sys_instructions`), and the full prompt used.

## Developer docs

Developer-oriented content (tests, fixtures, implementation notes) is in `docs/code/`, starting with `docs/code/developer-usage.md`.
