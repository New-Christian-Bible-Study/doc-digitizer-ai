#!/usr/bin/env python3
"""Headless verifier for line box alignment — two complementary checks.

**Ink-density check** — for each line, measures the dark-pixel fraction within
the ``line_box`` region and in equal-height strips immediately above and below
it.  Flags lines where the box has significantly less ink than an adjacent
strip (box landing in whitespace while the real text band is nearby).

**Nesting check** — flags lines whose ``line_box`` is ≥75 % vertically nested
inside a neighbouring line's box on the same page (snap-to-ink locked onto the
wrong text band, or two lines sharing the same Paddle detection).

Either failure causes the script to exit 1.

Exit code 0 = all lines pass; exit code 1 = at least one flagged.

Usage
-----
  # Check raw or final JSON against its source PDF:
  python check_box_ink.py <transcription.json> <chunk.pdf>

  # Adjust ink-density sensitivity (default 0.5 = box must have ≥50 % of adjacent ink):
  python check_box_ink.py <json> <pdf> --threshold 0.4

  # Print ink values for every line (not just flagged ones):
  python check_box_ink.py <json> <pdf> --verbose

  # Skip the ink-density check (nesting check only, faster):
  python check_box_ink.py <json> <pdf> --no-ink
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from prompt_based.box_repair import NESTING_PATHOLOGICAL, find_pathological
from prompt_based.chunk_lines_model import (
    BOX_2D_NORMALIZED_MAX,
    SNAP_DARK_PIXEL_THRESHOLD,
    line_aabb_four_ints,
    load_page_images,
)

DEFAULT_THRESHOLD = 0.5


def _ink_frac(img: Image.Image, x0: int, y0: int, x1: int, y1: int) -> float:
    iw, ih = img.size
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(iw, x1), min(ih, y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    data = img.crop((x0, y0, x1, y1)).getdata()
    n = len(data)
    if n == 0:
        return 0.0
    return sum(1 for p in data if p < SNAP_DARK_PIXEL_THRESHOLD) / n


def _check_nesting(lines: list[dict]) -> list[int]:
    bad = find_pathological(lines)
    if bad:
        print(f'Nesting check — {len(bad)} pathological line(s) '
              f'(≥{int(NESTING_PATHOLOGICAL * 100)}% nested):')
        for idx in bad:
            lb = lines[idx].get('line_box', {})
            print(
                f'  [{idx:4d}] pg{lines[idx].get("page_number","?"):2}  '
                f'h={lb.get("ymax", 0) - lb.get("ymin", 0):2d}  '
                f'{lines[idx].get("text", "")[:60]!r}'
            )
    else:
        print('Nesting check — OK')
    return bad


def _check_ink(
    lines: list[dict],
    page_images: list,
    threshold: float,
    verbose: bool,
) -> list[dict]:
    gray_cache: dict[int, Image.Image] = {}
    g = BOX_2D_NORMALIZED_MAX

    def gray(pg: int) -> Image.Image:
        if pg not in gray_cache:
            gray_cache[pg] = page_images[pg - 1].convert('L')
        return gray_cache[pg]

    flagged: list[dict] = []
    for idx, line in enumerate(lines):
        aabb = line_aabb_four_ints(line)
        if aabb is None:
            continue
        pg = line.get('page_number')
        if not isinstance(pg, int) or pg < 1 or pg > len(page_images):
            continue

        img = gray(pg)
        iw, ih = img.size
        ymin, xmin, ymax, xmax = aabb
        left = int(round(xmin / g * iw))
        top = int(round(ymin / g * ih))
        right = int(round(xmax / g * iw))
        bottom = int(round(ymax / g * ih))
        box_h = max(1, bottom - top)

        ink_box = _ink_frac(img, left, top, right, bottom)
        ink_above = _ink_frac(img, left, top - box_h, right, top)
        ink_below = _ink_frac(img, left, bottom, right, bottom + box_h)
        best_adj = max(ink_above, ink_below)

        is_flagged = best_adj > 0 and ink_box < threshold * best_adj

        if verbose or is_flagged:
            tag = 'FAIL' if is_flagged else 'ok  '
            print(
                f'[{idx:4d}] {tag} pg{pg:2d}  '
                f'box={ink_box:.3f}  above={ink_above:.3f}  below={ink_below:.3f}  '
                f'h={box_h:3d}px  {line.get("text", "")[:50]!r}'
            )

        if is_flagged:
            flagged.append({'idx': idx, 'page': pg, 'ink_box': ink_box,
                            'ink_above': ink_above, 'ink_below': ink_below,
                            'text': line.get('text', '')[:60]})

    if flagged:
        print(f'Ink-density check — {len(flagged)} line(s) flagged '
              f'(ink_box < {threshold} * best_adjacent)')
    else:
        print('Ink-density check — OK')
    return flagged


def run(json_path: Path, chunk_pdf: Path, threshold: float, verbose: bool, no_ink: bool) -> int:
    data = json.loads(json_path.read_text(encoding='utf-8'))
    lines: list[dict] = data.get('lines', [])

    bad_nesting = _check_nesting(lines)

    if not no_ink:
        print(f'\nLoading page images from {chunk_pdf.name}…')
        page_images = load_page_images(chunk_pdf)
        bad_ink = _check_ink(lines, page_images, threshold, verbose)
    else:
        bad_ink = []

    print()
    any_fail = bool(bad_nesting) or bool(bad_ink)
    if any_fail:
        parts = []
        if bad_nesting:
            parts.append(f'{len(bad_nesting)} nesting failure(s)')
        if bad_ink:
            parts.append(f'{len(bad_ink)} ink-density failure(s)')
        print('FAIL:', ', '.join(parts))
        return 1
    print(f'OK: {len(lines)} lines, all checks passed')
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('json_path', type=Path)
    p.add_argument('chunk_pdf', type=Path)
    p.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD,
                   help=f'Ink ratio floor (default {DEFAULT_THRESHOLD})')
    p.add_argument('--verbose', action='store_true',
                   help='Print ink values for every line, not just failures')
    p.add_argument('--no-ink', action='store_true',
                   help='Skip ink-density check (nesting only, faster, no PDF render needed)')
    args = p.parse_args()
    return run(args.json_path, args.chunk_pdf, args.threshold, args.verbose, args.no_ink)


if __name__ == '__main__':
    raise SystemExit(main())
