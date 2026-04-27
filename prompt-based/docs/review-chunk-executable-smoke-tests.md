# Review Chunk Executable Smoke Tests

## Local smoke test (Linux)

Environment:

- OS: Linux 6.8.0-110-generic
- Python: 3.12
- Build command: `pyinstaller --noconfirm --clean prompt-based/review-chunk.spec`

Result:

- Build completed successfully.
- Executable generated at `dist/review-chunk`.
- CLI smoke test passed:
  - Command: `./dist/review-chunk --help`
  - Expected description present: `Review and correct per-line transcriptions for a chunk.`

Notes:

- PyInstaller emitted one non-fatal warning for an optional Qt image plugin dependency
  (`libtiff.so.5` via `libqtiff.so`). The reviewer still builds and `--help` smoke test passes.
- Warning details are recorded in `build/review-chunk/warn-review-chunk.txt`.

## CI smoke tests (Windows/macOS/Linux)

Workflow: `.github/workflows/review-chunk-executable.yml`

Per matrix OS, CI performs:

1. Install dependencies + PyInstaller
2. Build with `prompt-based/review-chunk.spec`
3. Run packaged executable with `--help`
4. Verify expected help text
5. Upload `dist/review-chunk` artifacts

