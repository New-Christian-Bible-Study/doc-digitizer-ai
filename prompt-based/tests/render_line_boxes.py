#!/usr/bin/env python3
"""Render line boxes on page images for automated visual inspection.

Produces one PNG per page with every line's box drawn and labelled with
its JSON index.  Colour coding:

  blue   — normal-height box (h ≥ 12 px in normalised space)
  orange — small-height box  (h < 12) that is still pathological
  green  — was pathological in raw.json but is now fixed (box changed)

Usage
-----
  python render_line_boxes.py <fixed.json> <chunk.pdf> [out_dir]

Compare with raw.json by passing a second JSON as the fourth argument:

  python render_line_boxes.py <fixed.json> <chunk.pdf> [out_dir] [raw.json]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from prompt_based.chunk_lines_model import BOX_2D_NORMALIZED_MAX, load_page_images


def _lb(line: dict) -> dict | None:
    lb = line.get('line_box')
    return lb if isinstance(lb, dict) else None


def _nesting(a: dict, b: dict) -> float:
    la, lb = _lb(a), _lb(b)
    if la is None or lb is None:
        return 0.0
    overlap = min(la['ymax'], lb['ymax']) - max(la['ymin'], lb['ymin'])
    if overlap <= 0:
        return 0.0
    return overlap / max(1, la['ymax'] - la['ymin'])


def find_pathological_set(lines: list[dict]) -> set[int]:
    bad: set[int] = set()
    n = len(lines)
    for i in range(n):
        a = lines[i]
        if not isinstance(a, dict):
            continue
        for delta in range(1, 3):
            for j in (i - delta, i + delta):
                if not (0 <= j < n):
                    continue
                b = lines[j]
                if not isinstance(b, dict):
                    continue
                if a.get('page_number') != b.get('page_number'):
                    continue
                if _nesting(a, b) >= 0.75:
                    bad.add(i)
    return bad


def render_boxes(
    fixed_json: Path,
    chunk_pdf: Path,
    out_dir: Path,
    raw_json: Path | None = None,
) -> None:
    fixed_data = json.loads(fixed_json.read_text(encoding='utf-8'))
    fixed_lines: list[dict] = fixed_data.get('lines', [])

    raw_lines: list[dict] | None = None
    if raw_json is not None:
        raw_data = json.loads(raw_json.read_text(encoding='utf-8'))
        raw_lines = raw_data.get('lines', [])

    page_images = load_page_images(chunk_pdf)
    g = float(BOX_2D_NORMALIZED_MAX)
    out_dir.mkdir(parents=True, exist_ok=True)

    pathological = find_pathological_set(fixed_lines)

    by_page: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    for i, line in enumerate(fixed_lines):
        pn = line.get('page_number')
        if isinstance(pn, int) and 1 <= pn <= len(page_images):
            by_page[pn].append((i, line))

    for pn, pg_lines in sorted(by_page.items()):
        img = page_images[pn - 1].convert('RGB')
        draw = ImageDraw.Draw(img, 'RGBA')
        w, h = img.size

        for idx, line in pg_lines:
            lb = _lb(line)
            if lb is None:
                continue

            left = int(round(lb['xmin'] / g * w))
            right = int(round(lb['xmax'] / g * w))
            top = int(round(lb['ymin'] / g * h))
            bottom = int(round(lb['ymax'] / g * h))

            box_h = lb['ymax'] - lb['ymin']

            changed = False
            if raw_lines is not None and idx < len(raw_lines):
                raw_lb = _lb(raw_lines[idx])
                changed = raw_lb != lb

            if idx in pathological:
                # Red: still pathological after fix
                outline = (220, 40, 40, 230)
                fill = (220, 40, 40, 30)
            elif changed:
                # Green: was pathological, now fixed
                outline = (30, 160, 30, 230)
                fill = (30, 160, 30, 30)
            elif box_h < 12:
                # Orange: small but not detected as pathological
                outline = (200, 100, 0, 200)
                fill = (200, 100, 0, 20)
            else:
                # Blue: normal
                outline = (40, 100, 220, 180)
                fill = (40, 100, 220, 15)

            draw.rectangle([left, top, right, bottom], outline=outline, fill=fill, width=2)
            # Label at top-left of box
            label = str(idx)
            draw.text((left + 2, max(0, top - 14)), label, fill=outline[:3])

        out_path = out_dir / f'page_{pn:02d}.png'
        img.save(out_path)
        print(f'  page {pn:2d} → {out_path}')


def main() -> None:
    if len(sys.argv) < 3:
        print('Usage: render_line_boxes.py <fixed.json> <chunk.pdf> [out_dir] [raw.json]')
        sys.exit(1)
    fixed_json = Path(sys.argv[1])
    chunk_pdf = Path(sys.argv[2])
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path('box-renders')
    raw_json = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    print(f'Rendering boxes from {fixed_json.name}…')
    render_boxes(fixed_json, chunk_pdf, out_dir, raw_json)
    print('Done.')


if __name__ == '__main__':
    main()
