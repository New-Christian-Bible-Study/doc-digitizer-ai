# Tests

## Paddle / raw fixture refresh

When Paddle line-box logic or Pass 1 output changes, wipe raw artifacts and regenerate them before manual review:

```bash
# From the repository root
make -C prompt-based/tests realclean
export GEMINI_API_KEY=...
make -C prompt-based/tests raw
```

Prerequisites for `raw`:

- `GEMINI_API_KEY` set (same as `transcribe-chunk.py`)
- Install [`requirements.txt`](../../requirements.txt) and [`requirements-paddleocr.txt`](../../requirements-paddleocr.txt) for real `line_box` geometry

`realclean` removes every `transcriptions/*_raw.json` under this tree plus downstream artifacts (`*_summary.md`, `*_final.json`, exported `.adoc`/PDF/box debug files, torture CER outputs). It does **not** remove `chunk-pdfs/`, `source-pdfs/`, or hand-maintained files such as `test-2.adoc`.

`raw` transcribes all chunk PDFs in each fixture workdir that has a `chunk-pdfs/` subdirectory with at least one `.pdf`, then regenerates torture OCR raw JSON using chunk PDFs from `stress-tests/torture/<lang>/`. Limit torture to one language:

```bash
TORTURE_OCR_LANG=english make -C prompt-based/tests raw
```

If `test-1/chunk-pdfs/` has no PDFs yet, create chunks first (for example with `generate-chunk.py` or the slice helper in `test_transcribe_chunk_test_1.py`).

After `raw`, review fixtures in order (one GUI session per workdir; use the Chunk dropdown when a workdir has multiple chunk PDFs):

```bash
make -C prompt-based/tests review
```

`review` needs a display (PySide6). It passes `--chunk-dir` and `--transcriptions-dir` for each workdir (like torture), so `.chunk-state.json` is not required. It skips workdirs with no chunk PDFs or no matching `*_raw.json`. Limit torture languages with `TORTURE_OCR_LANG=english`.

Commit updated `*_raw.json` / summaries only after you are satisfied with review. Optional smoke test (re-runs transcribe; may overwrite `*_raw.json` if `GEMINI_API_KEY` is set):

```bash
pytest -q -k transcribe_chunk
```

For Paddle-only box refresh without re-running the VLM, use `convert-transcription-boxes.py --chunk-pdf` instead of `make raw`.

## Torture OCR (live integration)

The torture CER test discovers every language directory under `stress-tests/torture/` that contains `test-ocr.pdf` and runs once per language. To run **English only**, set `TORTURE_OCR_LANG` to the directory name:

```bash
# From the repository root; requires GEMINI_API_KEY
TORTURE_OCR_LANG=english pytest prompt-based/tests/test_transcribe_chunk_torture_ocr_cer.py -v
```

See the module docstring in `test_transcribe_chunk_torture_ocr_cer.py` for details.
