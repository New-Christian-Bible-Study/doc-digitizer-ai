# Stress-test PDFs

Place **source PDFs** here that are intentionally difficult for transcription (poor scans, unusual fonts, damage, etc.). They are **shared** across digitization strategies in this repository so you can compare outputs—for example with **character error rate (CER)**—on the same inputs.

## How strategies use these files

Nothing in this folder is consumed automatically. Each pipeline uses its own working-directory layout (typically `source-pdfs/`, `chunk-pdfs/`, `transcriptions/`). To run a strategy on a stress PDF:

1. Copy or symlink the PDF from `stress-tests/` into that work directory’s `source-pdfs/`, **or**
2. Point your strategy’s preparation step at an absolute path under `stress-tests/`, if your tooling supports it.

For the **prompt-based** flow, see [`prompt-based/README.md`](../prompt-based/README.md): run `generate-chunk-pdf.py` (or equivalent) with `--working-dir` set to a directory that contains `source-pdfs/` where you placed the file.

Optional: set an environment variable in your own scripts (for example `STRESS_TESTS_DIR` pointing at this directory) and resolve paths from there when batching comparisons.
