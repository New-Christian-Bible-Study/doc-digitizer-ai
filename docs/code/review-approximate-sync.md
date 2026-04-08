# Review Approximate Sync

This document captures implementation details for the `review-chunk-lines.py` rewrite.

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

- `transcription.schema.json` now supports line-level `confidence_label` and `notes`.
- Low-confidence lines require non-empty `lines[i].notes`.
- Top-level `notes` is retained as optional backward-compatible metadata but no longer drives line review triage.

## Save Behavior

Saving writes edited line text into the existing `_final.json` payload while preserving line geometry and metadata fields.
