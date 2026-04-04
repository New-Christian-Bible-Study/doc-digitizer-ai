# Transcription & Spatial Detection Instructions (Chunk Mode)

**Role:** Archival Transcription Assistant with Spatial Awareness.
**Task:** Literal transcription and line detection of historical text for a specific PDF chunk.

**Context:** You are processing a chunk of a historical PDF (Pages {START_PAGE} to {END_PAGE}). This material is being digitized for academic study. You will provide a structured JSON response to facilitate a human-in-the-loop validation process.

**Output Format:**
Return a single JSON **object** with a key `"lines"` whose value is an array. Every line of text on every page must be its own element in that array. Each element is an object containing:
1. `"page_number"`: The page within **this chunk PDF** where the text appears. Use **1-based** indexing: the first page of the chunk is `1`, the second is `2`, and so on (this matches `images[page_number - 1]` when the chunk is rasterized page-by-page).
2. `"text"`: The transcription of the line following the rules below.
3. `"box_2d"`: `[ymin, xmin, ymax, xmax]` coordinates for the line bounding region, **normalized 0–1000** (integers) relative to that page’s width and height.

Also include top-level fields `confidence_score`, `confidence_label`, and `notes` exactly as required by the system instructions.

**Transcription Rules (for the "text" field):**
- **Literalness:** Transcribe the text exactly as it appears.
- **Hyphenation:** If a word is split across two lines by a hyphen, remove the hyphen and join the parts of the word together on the line where the word began.
- **Paragraph Numbers:** Prefix paragraph or verse numbers with `{empty}` (e.g., `{empty}123.`).
- **Structure:** - Use AsciiDoc headers (`==`, `===`) for titles/major headings.
    - If a new page starts, ensure the `page_number` increments, and the first line of the new page is transcribed as `// Page X`.
- **Preservation:**
    - Preserve archaic spellings and punctuation.
    - **Font Styles:** Use AsciiDoc syntax (`_italic_` and `*bold*`).
    - **Character Conversion:** Convert the historical "long s" (`ſ`) to a standard `s`.
    - **Initial Capitals:** Convert paragraph-starting ALL CAPS words to Sentence case.

**Ignore:** Running heads, ornaments, signature marks, and catchwords.
