# Developer usage notes

This page is for contributors working on the scripts in this repository.

## Run tests

Run the full test suite:

```bash
pytest -q
```

Run the live transcription integration test subset:

```bash
pytest -q -k transcribe_chunk
```

## Regenerate fixture PDFs

If you edit fixture AsciiDoc files, regenerate fixture PDFs with:

```bash
asciidoctor-pdf prompt-based/tests/test-1/test-a.adoc -o prompt-based/tests/test-1/source-pdfs/test-a.pdf
asciidoctor-pdf prompt-based/tests/test-1/test-b.adoc -o prompt-based/tests/test-1/source-pdfs/test-b.pdf
```

## Transcription config reference

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

The full default `sys_instructions` text is in [`prompt-based/transcribe.config.json`](../../prompt-based/transcribe.config.json) (fallback when the working directory has no `transcribe.config.json`).
