# Document digitizing using AI

This repository provides script tooling for transcribing handwritten and typewritten PDF content using AI.

## Goals

- Leverage AI as much as possible for transcribing handwritten and typewritten text.
- Make large transcription projects manageable by splitting source PDFs into chunks.
- Improve quality and efficiency by fixing prompts early based on human transcription corrections before generating chunks for later sections.
- Avoid processing too many pages at once, which can hit model token limits.

## Install

From the repository root (parent of this directory):

```bash
python -m pip install -r requirements.txt
```

## Working directory layout

Create one dedicated working directory per work/book/manuscript and run the scripts from there.

### Directories

| Path | Purpose |
| --- | --- |
| `source-pdfs/` | Source PDFs to transcribe. |
| `chunk-pdfs/` | Chunks (PDF files) generated from page ranges in a source PDF. |
| `transcriptions/` | Raw/final JSON transcriptions and AI summaries. Created automatically as needed. |

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

From the **repository root**, invoke scripts under `prompt-based/` and pass working dirs as `prompt-based/tests/...` or your own work folder under `prompt-based/`. Alternatively, `cd prompt-based` and use paths relative to that directory (for example `--working-dir tests/test-1`).

### Chunk directory override (`--chunk-dir`)

By default, chunk PDFs live under `<working-dir>/chunk-pdfs/`. These tools also accept **`--chunk-dir`** so chunks can sit elsewhere (for example under `stress-tests/` in the repo) while `source-pdfs/`, `transcriptions/`, `transcribe.config.json`, and `.chunk-state.json` stay under **`--working-dir`**:

- **`transcribe-chunk.py`** — read chunk PDFs from the given directory.
- **`generate-chunk.py`** — write extracted chunks to the given directory.
- **`review-chunk.py`** — list and load chunk PDFs from the given directory.
- **`tests/chunk-lines-boxes-export.py`** — rasterize the chunk PDF from the given directory (run from `prompt-based/`).

Path rules:

- **Absolute** `--chunk-dir` values are resolved as usual.
- **Relative** values are resolved under **`--working-dir`** (same pattern as `--raw-json`).

## Generate a chunk

`generate-chunk.py` extracts selected pages from a source PDF in `source-pdfs/` and writes a chunk file to `chunk-pdfs/` by default, or to **`--chunk-dir`** when set.

```bash
# from repository root:
python prompt-based/generate-chunk.py --working-dir prompt-based/tests/test-1
# or from prompt-based/:
cd prompt-based && python generate-chunk.py --working-dir tests/test-1
```

To write chunks somewhere other than `working-dir/chunk-pdfs/`:

```bash
python prompt-based/generate-chunk.py --working-dir my-work --chunk-dir /path/to/shared/chunks
# relative to working-dir:
python prompt-based/generate-chunk.py --working-dir my-work --chunk-dir ../other-project/chunk-pdfs
```

The script prompts for:

- Source filename (filename only, chosen from `source-pdfs/`)
- Start page
- End page
- Output chunk filename (editable default)

Default output naming:

- `<scan_chunk_stem>_<start:03d>-<end:03d>.pdf`
- Example: `test-a_001-005.pdf`

## Transcribe a chunk

`transcribe-chunk.py` transcribes a file from `chunk-pdfs/` (or from **`--chunk-dir`**) into:

- `transcriptions/<chunk_stem>_raw.json` — per-line text with `box_2d` coordinates (Pass 1)
- `transcriptions/<chunk_stem>_summary.md`

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
python prompt-based/transcribe-chunk.py --working-dir prompt-based/tests/test-1
```

### Notes

- `transcriptions/` is created automatically if it does not exist.
- `--chunk-dir` is optional. If omitted, chunks are read from `<working-dir>/chunk-pdfs/`.
- `--chunk` is optional. If omitted, you choose from the chunk directory interactively. The default selection uses `.chunk-state.json` (`last_generated_output`) when available.
- `--chunk` must be a filename only (no path).
- `--prompt-md` is optional. If omitted, the script searches for `*prompt*.md` in the working directory:
  - if exactly one file matches, it is used automatically
  - if multiple files match, you can choose interactively
  - if none match, the script exits with an error
- Transcribe config is loaded from `transcribe.config.json` with this precedence:
  - `<working-dir>/transcribe.config.json`
  - `<script-dir>/transcribe.config.json` (fallback)
- The `_summary.md` file includes chunk filename, total pages, confidence score/label, notes, full config JSON used (including `sys_instructions`), and the full prompt used.
- Runtime metrics (`run_started_at`, timing, token usage) are appended to `prompt-based/transcribe-runtime.jsonl`, which is ignored by git.

## Review and correct transcriptions (human pass)

This step does **not** call the model. You still run `transcribe-chunk.py` first (Pass 1) to produce `transcriptions/<stem>_raw.json`. The PySide6 app (`review-chunk.py`) loads that JSON, shows each line’s crop next to editable text, and saves `transcriptions/<stem>_final.json`.

**System dependency:** [Poppler](https://poppler.freedesktop.org/) must be installed so `pdf2image` can rasterize the PDF (on Ubuntu: `sudo apt install poppler-utils`).

The reviewer rasterizes each page at a fixed DPI (see `REVIEW_PDF_RASTER_DPI` in `chunk_lines_model.py`) so line crops are consistent across environments. Pass 1 sends the **PDF** to the model, while the UI uses Poppler — normalized `box_2d` line crops are **best-effort** aligned to the page aspect ratio; Gemini’s internal render may differ slightly.

`--working-dir` is the same as for `transcribe-chunk.py`: the directory that holds `transcriptions/` and usually `source-pdfs/` / config (not those subfolders themselves). Chunk PDFs default to `<working-dir>/chunk-pdfs/` unless you pass **`--chunk-dir`**.

```bash
python review-chunk.py --working-dir .
```

Pick the chunk from the **Chunk** dropdown (PDFs in the chunk directory).

Example using the `tests/test-1` fixture (after the chunk file and `tests/test-1/transcriptions/..._raw.json` exist):

```bash
python prompt-based/review-chunk.py --working-dir prompt-based/tests/test-1
```

- `--raw-json` is optional; defaults to `<working-dir>/transcriptions/<stem>_raw.json`. Relative paths are resolved under `--working-dir`.
- If `_final.json` already exists for that stem, it is loaded so you can resume editing.
- **Quit:** Close the window, or press Ctrl-C in the terminal (the app installs a handler so this works with Qt). If the process is stuck, from another terminal: `pkill -f review-chunk.py` or `kill <pid>` (`kill -9` only as a last resort).

## Transcription JSON to AsciiDoc

To turn a Pass 1 `transcriptions/<stem>_raw.json` or reviewed `transcriptions/<stem>_final.json` into a `.adoc` file, run `transcription-json-to-adoc.py`. It reads the `lines` array and writes each line’s `text` in order, separated by newlines, next to the JSON file (e.g. `chunk_001-003_raw.json` → `chunk_001-003_raw.adoc`).

By default the JSON is validated against `transcription.schema.json` before anything is written. Use `--skip-schema-validation` only for debugging or hand-edited JSON.

```bash
python prompt-based/transcription-json-to-adoc.py \
  prompt-based/tests/test-1/transcriptions/test-a_001-003_raw.json
```

With a single input file you may pass `-o` / `--output` to choose the `.adoc` path.

## Build PDFs from transcriptions (AsciiDoc)

`transcribe-chunk.py` does not emit `.adoc` files; it writes `*_raw.json`. You can convert JSON to `.adoc` with `transcription-json-to-adoc.py` (above), stitch or edit further, or maintain `.adoc` sources under `transcriptions/` by hand.

`build-transcribed-chunk-pdfs.py` walks `--working-dir`, finds every directory named `transcriptions`, and runs [Asciidoctor PDF](https://asciidoctor.org/docs/asciidoctor-pdf/) on each `.adoc` file in that directory. It writes `<stem>-transcription.pdf` beside `<stem>.adoc` (for example `chunk-1.adoc` to `chunk-1-transcription.pdf`).

Prerequisite: the `asciidoctor-pdf` command (Ruby gem) must be installed and on your `PATH`.

```bash
python prompt-based/build-transcribed-chunk-pdfs.py --working-dir prompt-based/tests/test-1
```

## Developer docs

Developer-oriented content (tests, fixtures, implementation notes) is in [`docs/code/`](../docs/code/) at the repository root, starting with [`developer-usage.md`](../docs/code/developer-usage.md).

See also [`tests/README.md`](tests/README.md) for torture OCR integration tests.

The helper script `tests/chunk-lines-boxes-export.py` supports **`--chunk-dir`** the same way as `review-chunk.py` when exporting box overlays for debugging.
