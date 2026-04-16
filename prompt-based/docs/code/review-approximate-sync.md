# Review Approximate Sync

This document captures implementation details for the `review-chunk.py` rewrite.

## Overview

The reviewer now uses a dual-pane layout:

- Left pane: full-page preview in a `QGraphicsView`.
- Right pane: one editable field per transcription line.

The sync model is approximate: when a line receives focus, the viewer centers near that line's vertical midpoint using normalized `box_2d` coordinates.

## Coordinate Mapping

For a line box `[ymin, xmin, ymax, xmax]` on a 0-1000 grid:

- `line_center = (ymin + ymax) / 2`
- `target_y_px = (line_center / 1000) * page_height_px`

The page view then centers on `target_y_px`.

## Confidence and Notes

Each line can include:

- `confidence_label`: `low`, `medium`, `high`
- `notes`: rationale for uncertainty

UI behavior:

- low-confidence lines render with stronger warning styling
- medium-confidence lines render with mild warning styling
- high/default lines use neutral styling
- per-line notes are shown below the editor row when non-empty

## Schema and Pipeline Compatibility

- `raw-transcription.schema.json` validates Pass 1 (`*_raw.json`).
- `final-transcription.schema.json` extends final output (`*_final.json`) with:
  - top-level `review_complete`
  - per-editable-line `reviewer_changed`
- Low-confidence lines require non-empty `lines[i].notes`.
- Top-level `notes` remains optional metadata but does not drive review triage.

## Save Behavior

Saving writes edited line text into the existing `_final.json` payload while preserving line geometry and metadata fields. Standard Save keeps review in progress (`review_complete=false`). The completion action marks `review_complete=true`, saves, and exits.
