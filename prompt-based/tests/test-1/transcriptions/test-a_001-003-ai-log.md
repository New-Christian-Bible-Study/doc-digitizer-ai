# AI transcription run log

- Chunk file: `test-a_001-003.pdf`
- Run started at: `2026-04-09 16:22`
- Total pages: `3`
- Total inference time (minutes): `0.30`
- Average time per page (seconds): `6.05`
- Prompt tokens (input): `4106`
- Completion tokens (output): `2084`
- Total tokens: `6190`
- Confidence score: `0.99`
- Confidence label: `high`
- Notes: 
## Transcribe config used

```json
{
  "model": "gemini/gemini-3.1-pro-preview",
  "timeout_seconds": 900,
  "temperature": 1.0,
  "reasoning_effort": "medium",
  "media_resolution": "high",
  "sys_instructions": "Respond with JSON only matching the provided schema. Key order: lines, confidence_score, confidence_label. The \"lines\" array must contain one object per visible text line in reading order; each object has page_number (integer, 1-based within this chunk), text (string), box_2d (four integers [ymin, xmin, ymax, xmax] in 0-1000 normalized coordinates), confidence_label ('low'|'medium'|'high'), and notes (string). When a line confidence_label is 'low', that line's notes must be non-empty and describe the specific ambiguity for that line. For medium/high lines, notes may be empty unless there is useful context. confidence_score must be a number from 0.0 to 1.0. Top-level confidence_label must be one of: 'low', 'medium', 'high'. Strictly avoid general descriptions of the document or praise for formatting."
}
```

## Prompt used

````markdown
# Transcription & Spatial Detection Instructions (Chunk Mode)

**Role:** Archival Transcription Assistant with Spatial Awareness.
**Task:** Literal transcription and line detection of historical text for a specific PDF chunk.

**Context:** You are processing a chunk of a historical PDF (Pages {START_PAGE} to {END_PAGE}). This material is being digitized for academic study. You will provide a structured JSON response to facilitate a human-in-the-loop validation process.

**Output Format:**
Return a single JSON **object** with a key `"lines"` whose value is an array. Every line of text on every page must be its own element in that array. Each element is an object containing:
1. `"page_number"`: The page within **this chunk** where the text appears. Use **1-based** indexing: the first page of the chunk is `1`, the second is `2`, and so on (this matches `images[page_number - 1]` when the chunk is rasterized page-by-page).
2. `"text"`: The transcription of the line following the rules below.
3. `"box_2d"`: `[ymin, xmin, ymax, xmax]` coordinates for the line bounding region, **normalized 0–1000** (integers) relative to that page’s width and height.
4. `"confidence_label"`: One of `low`, `medium`, or `high` for this specific line.
5. `"notes"`: Per-line rationale for uncertainty. Required and non-empty when `"confidence_label"` is `low`; otherwise use an empty string unless there is useful context.

Also include top-level fields `confidence_score` and `confidence_label` exactly as required by the system instructions.

**Transcription Rules (for the "text" field):**
- **Literalness:** Transcribe the text exactly as it appears.
- **Hyphenation:** If a word is split across two lines by a hyphen, remove the hyphen and join the parts of the word together on the line where the word began.
- **Paragraph Numbers:** Prefix paragraph or verse numbers with `{empty}` (e.g., `{empty}123.`).
- **Structure:** - Use AsciiDoc headers (`==`, `===`) for titles/major headings.
    - If a new page starts, ensure the `page_number` increments appropriately. Do NOT insert any synthetic markers like `// Page X`.
- **Preservation:**
    - Preserve archaic spellings and punctuation.
    - **Font Styles:** Use AsciiDoc syntax (`_italic_` and `*bold*`).
    - **Character Conversion:** Convert the historical "long s" (`ſ`) to a standard `s`.
    - **Initial Capitals:** Convert paragraph-starting ALL CAPS words to Sentence case.

**Ignore:** Running heads, ornaments, signature marks, and catchwords.

````
