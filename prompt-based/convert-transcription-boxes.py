#!/usr/bin/env python3
"""Convert legacy transcription JSON (box_2d) to schema_version 2 (line_box)."""

from prompt_based.convert_transcription_boxes import main

if __name__ == '__main__':
    raise SystemExit(main())
