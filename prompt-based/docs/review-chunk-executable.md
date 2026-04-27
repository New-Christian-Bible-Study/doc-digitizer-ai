# Review Chunk Executable Builds

This project ships cross-platform reviewer executables with PyInstaller using
`prompt-based/review-chunk.spec`.

## Build targets

- Windows (`windows-latest`) -> `review-chunk.exe`
- macOS (`macos-latest`) -> `review-chunk`
- Linux (`ubuntu-latest`) -> `review-chunk`

Builds are produced in CI by `.github/workflows/review-chunk-executable.yml`.

## Local build command

From repository root:

```bash
python -m pip install -r requirements.txt
python -m pip install pyinstaller
pyinstaller --noconfirm --clean prompt-based/review-chunk.spec
```

Output directory:

- `dist/review-chunk/`

## Runtime dependency strategy (Poppler removal)

The reviewer no longer depends on `pdf2image`/Poppler. Rasterization in
`chunk_lines_model.py` uses `pypdfium2`, so packaged binaries do not require a
separate Poppler install on end-user machines.

PyInstaller bundles `pypdfium2` dynamic libraries through the spec:

- `collect_dynamic_libs('pypdfium2')`

This keeps executable deployment self-contained for PDF rasterization.

## Verification

See `docs/review-chunk-executable-smoke-tests.md` for local smoke-test notes
and CI smoke-test steps.

