# Document digitizing using AI

This repository hosts more than one approach to digitizing documents (for example, prompt-based LLM transcription and tooling oriented toward other pipelines).

## Prompt-based transcription

Scripts, tests, and detailed usage for the current prompt/Gemini chunk workflow live under [`prompt-based/`](prompt-based/README.md).

```bash
python -m pip install -r requirements.txt
pytest
```

Run `pytest` from the repository root; see [`pytest.ini`](pytest.ini) for test discovery.

## Shared stress-test PDFs

Challenging source PDFs for comparing strategies (for example, character error rate) live under [`stress-tests/`](stress-tests/README.md).
