# Document Digitizer AI

This project digitizes scanned documents by first using PaddleOCR to detect text lines, then handing those line regions to Gemini for the actual OCR and replacement step, and finally opening an editor for review.

## Quick start

1. Create and activate a Python virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Install the required Python packages:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Copy and fill out the secrets file:

```bash
copy hybrid\secrets.env.example hybrid\secrets.env
```

Edit `hybrid\secrets.env` with your values.

4. Recommended model:

- Set `GEMINI_MODEL=gemini-3.5-flash` in `hybrid\secrets.env`.
- This is the recommended option because it is free and works well for this project.

5. Run the app:

```bash
streamlit run src\app.py
```

## What this project does

- Uses PaddleOCR to find text lines in documents.
- Sends those line regions to Gemini for OCR and replacement.
- Opens an editor interface for final review and correction.

## Notes

- Make sure `hybrid\secrets.env` is not committed to version control.
- If you need more advanced usage, inspect `hybrid/src/app.py` and the files under `prompt-based/`.
