#!/usr/bin/env python3
"""Diagnose and (optionally) fix pathological line boxes in *_raw.json files.

A pathological line box is one where ≥75% of the box's height is nested inside
an adjacent line's box on the same page.  See ``prompt_based/box_repair.py``
for the detection and repair logic.

Usage
-----
  # Report only (dry run):
  python fix_pathological_boxes.py <raw.json> <chunk.pdf>

  # Apply fix in-place:
  python fix_pathological_boxes.py <raw.json> <chunk.pdf> --fix

  # Apply fix and write to a new file (for diffing):
  python fix_pathological_boxes.py <raw.json> <chunk.pdf> --fix --out fixed.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt_based.box_repair import (
    NESTING_PATHOLOGICAL,
    find_pathological,
    repair_page,
    repair_pathological_boxes,
)
from prompt_based.chunk_lines_model import load_page_images

NESTING_WARN = 0.50


def run(raw_path: Path, chunk_pdf: Path, fix: bool, out_path: Path | None) -> int:
    data = json.loads(raw_path.read_text(encoding='utf-8'))
    lines: list[dict] = data.get('lines', [])
    original_boxes = {i: copy.deepcopy(lines[i].get('line_box')) for i in range(len(lines))}

    pathological_idxs = find_pathological(lines)
    print(f'Found {len(pathological_idxs)} pathological lines (≥{int(NESTING_PATHOLOGICAL*100)}% nested):')
    for idx in pathological_idxs:
        lb = lines[idx].get('line_box', {})
        print(
            f'  [{idx:4d}] pg{lines[idx].get("page_number", "?"):2}  '
            f'h={lb.get("ymax",0)-lb.get("ymin",0):2d}  '
            f'{lines[idx].get("text","")[:60]!r}'
        )

    if not pathological_idxs:
        print('Nothing to fix.')
        return 0

    if not fix:
        print('\n(dry run — pass --fix to apply)')
        return 0

    print('\nLoading page images…')
    total_repairs = repair_pathological_boxes(chunk_pdf, lines)
    print(f'{total_repairs} line(s) repaired')

    # ── verification ─────────────────────────────────────────────────────────
    print('\n── Verification ────────────────────────────────────────────────')

    changed = [
        i for i, line in enumerate(lines)
        if original_boxes[i] != line.get('line_box')
    ]
    path_set = set(pathological_idxs)
    direct_changes = [i for i in changed if i in path_set]
    cascade_changes = [i for i in changed if i not in path_set]
    print(
        f'Lines changed  : {len(changed)} '
        f'({len(direct_changes)} direct + {len(cascade_changes)} cascade)'
    )
    if cascade_changes:
        print(f'  Cascade-displaced indices: {cascade_changes}')
    else:
        print('  No cascade displacements')

    still_bad = find_pathological(lines)
    print(f'Remaining pathological: {len(still_bad)}')
    for idx in still_bad:
        lb = lines[idx].get('line_box', {})
        print(
            f'  [{idx:4d}] pg{lines[idx].get("page_number","?"):2}  '
            f'h={lb.get("ymax",0)-lb.get("ymin",0):2d}  '
            f'{lines[idx].get("text","")[:60]!r}'
        )

    new_bad = set(still_bad) - path_set
    print(f'New pathological introduced: {len(new_bad)}')
    if new_bad:
        print('  REGRESSIONS at indices:', sorted(new_bad))
    else:
        print('  OK — no regressions')

    if out_path is None:
        out_path = raw_path
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'\nWrote: {out_path}')
    return 0 if not new_bad else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('raw_json', type=Path)
    parser.add_argument('chunk_pdf', type=Path)
    parser.add_argument('--fix', action='store_true', help='Apply repairs (default: dry run)')
    parser.add_argument('--out', type=Path, default=None, help='Output path (default: in-place)')
    args = parser.parse_args()
    return run(args.raw_json, args.chunk_pdf, args.fix, args.out)


if __name__ == '__main__':
    raise SystemExit(main())
