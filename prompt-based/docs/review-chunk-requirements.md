# Review Chunk Requirements (Reverse Engineered)

This document captures the inferred requirements of `prompt_based/review_chunk.py`
based on implementation behavior.

## Purpose

- Provide a desktop review tool to inspect and correct per-line transcription text for chunked PDFs.
- Keep line edits synchronized with page imagery so reviewers can verify text against source regions.
- Persist reviewer decisions to final JSON outputs, including optional reviewer metadata.

## Inputs and Environment

- The tool runs as a GUI app (`PySide6`) launched by `review-chunk.py`.
- CLI description: `Review and correct per-line transcriptions for a chunk.`
- Inputs are sourced from:
  - A working directory containing `chunk-pdfs/` and `transcriptions/`, or
  - Explicit `--chunk-dir` and `--transcriptions-dir`.
- Optional `--raw-json` allows focusing on a specific raw transcription JSON.
- Raw transcription input files (`*_raw.json`) must comply with
  `prompt-based/raw-transcription.schema.json`.
- Final transcription output files (`*_final.json`) must comply with
  `prompt-based/final-transcription.schema.json`.

## CLI Requirements

- The CLI must accept:
  - `--working-dir` (default `.`)
  - `--chunk-dir`
  - `--transcriptions-dir`
  - `--raw-json`
- `--chunk-dir` and `--transcriptions-dir` are a required pair:
  - Passing only one must fail with exit code `2`.
- Relative paths for `--chunk-dir`, `--transcriptions-dir`, and `--raw-json` are resolved from `--working-dir`.

## Transcription Root Discovery

- The transcription root must contain `.chunk-state.json`.
- If both explicit directory flags are omitted and `--working-dir` lacks `.chunk-state.json`:
  - The app may prompt with a directory picker if GUI dialog conditions are safe.
  - If no valid directory is selected, startup must fail with exit code `2`.
- Dialog availability rules:
  - Must not run when both stdin and stdout are non-TTY.
  - On Linux, must require valid `DISPLAY` or `WAYLAND_DISPLAY`.
  - Linux display tokens `$0`, `0`, `false`, `none`, `null` are considered invalid.
  - Non-native Qt file dialog is required to avoid Linux native dialog crashes.

## Startup and Validation Requirements

- Resolved chunk PDF directory must exist; otherwise fail with exit code `1`.
- At least one `*.pdf` must exist in the chunk directory; otherwise fail with exit code `1`.
- App name must be set to `Review chunk`.
- App/window icon should use `icons/review-chunk-lines.png` when present (optional).

## Core UI Requirements

- Main window must default to approximately `1100x750`.
- Layout must include:
  - Top row with chunk selector (`QComboBox`) listing chunk PDFs.
  - Path row showing loaded raw and final JSON filenames.
  - Error/status label area for non-fatal warnings.
  - Horizontal split:
    - Left pane: page image with active line highlight overlay.
    - Right pane: vertically scrollable editable line list.
  - Action row buttons:
    - `Prev flagged`
    - `Next flagged`
    - `Save to final`
    - `Reload from raw`
    - `Mark review complete` (last)
- Zoom shortcuts must be supported:
  - `Ctrl+=` / `Ctrl++` zoom in
  - `Ctrl+-` zoom out
  - `Ctrl+0` reset to fit
- Keyboard navigation shortcuts:
  - `↑` / `↓` in a line field: previous/next editable line (updates scan highlight)
  - `Alt+↑` / `Alt+↓`: previous/next line from anywhere in the window
  - `Page Up` / `Page Down`: previous/next PDF page with editable content; selects the topmost line on that page

## Chunk Loading and Switching

- On startup, the controller must attempt to load the first available valid chunk.
- Switching chunks with unsaved edits must prompt:
  - `Save`, `Discard`, or `Cancel`.
  - `Cancel` keeps current chunk selection.
- If target chunk load fails, UI must revert combo selection to the currently loaded chunk.

## Line Editing Requirements

- Only editable lines from session data are shown.
- Each row must include:
  - Editable text field initialized from line text (rstrip applied),
  - Confidence-driven styling,
  - Optional warning message for non-high confidence lines,
  - Reviewer note controls.
- Edited text must be visually distinguished from original text.
- For medium/low confidence lines, warning text must hide once line text is changed.

## Reviewer Metadata Requirements

- Each line must support optional reviewer metadata:
  - Reviewer confidence (`Unset`, `High`, `Medium`, `Low`)
  - Reviewer note (free text)
- Reviewer panel visibility:
  - Visible when reviewer data exists,
  - Can be forced visible by `Add note`,
  - Hidden and cleared by `Remove note` after confirmation.
- Any reviewer metadata change marks the session dirty.

## Navigation and Focus Requirements

- Focusing a text row sets that row as active review line and updates the scan-pane highlight.
- The active transcription row must have a visible background highlight even when unedited.
- `↑` / `↓` in a line field navigate to the previous/next editable line and update the scan pane.
- `Alt+↑` / `Alt+↓` perform the same line navigation when focus is elsewhere in the window.
- `Page Up` / `Page Down` jump to the previous/next PDF page that has editable lines; the topmost line on that page (smallest `ymin`) is selected. These keys must not scroll the transcription list.
- `Prev flagged` must jump backward to the previous line with AI confidence `low` or `medium`.
- `Next flagged` must jump forward to the next line with AI confidence `low` or `medium`.
- Prev/Next flagged buttons must disable when no matching line exists in that direction.
- Active row should be focused in the right pane; text is not select-all on every navigation (only on initial chunk load).

## Image and Alignment Requirements

- Active line page image is selected by persisted `page_number`.
- Active line overlay box is derived from `box_2d` in normalized coordinates.
- Overlay box must be clamped to image bounds and expanded with display padding.
- Left image pane must align vertically to the active editor row.
- Alignment state must survive zoom, splitter movement, and window resize.
- Scene vertical padding must allow top/bottom lines to align with editor rows.

## Save, Reload, and Completion Requirements

- `Save to final` must:
  - Commit all current line text and reviewer metadata to session records,
  - Force `review_complete=false`,
  - Write final JSON,
  - Clear dirty state.
- `Reload from raw` must confirm before discarding in-memory edits.
- `Mark review complete` must:
  - Commit all edits,
  - Warn when low-confidence lines remain unchanged,
  - On confirmation set `review_complete=true`,
  - Save final JSON and close the window.

## Already-Complete Behavior

- If a loaded final JSON is already marked complete:
  - User must choose `Keep complete`, `Reset and continue`, or `Cancel`.
  - `Reset and continue` sets `review_complete=false` and marks dirty.
  - `Cancel` aborts chunk load.

## Signal and Shutdown Requirements

- Ctrl+C / SIGTERM in terminal should close the app cleanly.
- Qt event loop must be periodically tickled so Python signal handlers run.

## Exit Codes

- `0`: normal GUI exit.
- `1`: invalid chunk directory or no PDFs found.
- `2`: invalid CLI directory pairing or unresolved transcription root.
