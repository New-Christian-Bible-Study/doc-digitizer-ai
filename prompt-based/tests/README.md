# Tests

## Torture OCR (live integration)

The torture CER test discovers every language directory under `stress-tests/torture/` that contains `test-ocr.pdf` and runs once per language. To run **English only**, set `TORTURE_OCR_LANG` to the directory name:

```bash
# From the repository root; requires GEMINI_API_KEY
TORTURE_OCR_LANG=english pytest prompt-based/tests/test_transcribe_chunk_torture_ocr_cer.py -v
```

See the module docstring in `test_transcribe_chunk_torture_ocr_cer.py` for details.
