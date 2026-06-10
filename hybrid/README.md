# NCBS Hybrid


This is a hybrid approach to OCR. It combines the best of prompt based with traditional to yield the best results. Simply put, this project uses PaddleOCR to detect text lines, then passes those line regions to Gemini for the actual OCR and replacement step, and finally opens an editor for review. This allows for the highest accuracy OCR combined with the highest text line region accuracy, as well as the ability to edit the prompts.

PDF Editing tools have also been added and accessible through the streamlit gui (split pages, reading order, page ranges, etc)

See [Editor README](.\EditorREADME.md) for editor-specific details.


- `src\prompts\gemini_system.txt`: base Gemini OCR prompt, change only if issues in the actual OCRing (or change model to a better version).
- `src\prompts\gemini_user.txt`: user-facing prompt, edit for formatting, headers, page numbers, change gemini comments, etc.

## Quick start

1. Create and activate a Python virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Copy and fill out the secrets file:

```bash
copy secrets.env.example secrets.env
```

4. Recommended model:

- Set `GEMINI_MODEL=gemini-3.5-flash` in `secrets.env`.
- This is the recommended free model for this project.

5. Run the app:

```bash
streamlit run src\app.py
```

## Pipeline Technical

- PaddleOCR detects text line regions.
- Extract line data and build the Gemini payload.
- Gemini performs OCR and returns text replacements.
- Merge Gemini output back into the PaddleOCR JSON.
- Open the result in the editor for review.

## Notes

- Do not commit `secrets.env` to version control.
- Edit `secrets.env` with your own API key and settings before running.


## Known Issues

- Scripts with large gaps has trouble detecting whole lines

## Todo

- [ ] Clear GPU support instructions
- [ ] PDF viewer before OCR in GUI
- [ ] Cleaning up GUI options
- [ ] regedit in editor
- [x] fix merge hyphens / line feeds
- [ ] right-to-left reading order
- [ ] Italics
- [x] Serif font option
- [ ] Page feeding system
- [ ] Write simple script to merge gaps in lines