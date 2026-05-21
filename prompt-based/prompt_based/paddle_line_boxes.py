"""
PaddleOCR detection for per-line axis-aligned boxes (schema_version 2 ``line_box``).

We use **detection only** (text regions as polygons), then collapse each polygon to an
axis-aligned bounding box (AABB) in **pixels**, match those boxes to VLM transcript lines
using the coarse ``anchor_box_2d``, and write normalized ``line_box`` dicts.

This module is imported only from transcribe and the legacy upgrade CLI so the
reviewer executable does not depend on Paddle.

**PaddleOCR documentation (APIs change across major versions — verify against your pin):**

- Project: https://github.com/PaddlePaddle/PaddleOCR
- English README (features, models): https://github.com/PaddlePaddle/PaddleOCR/blob/main/README_en.md
- Quick start / install: https://paddlepaddle.github.io/PaddleOCR/main/en/quick_start.html
- ``PaddleOCR`` class / ``ocr()`` parameters: read the docstring of ``paddleocr.PaddleOCR``
  and ``ocr()`` in your installed tree (``site-packages/paddleocr/``), or browse the repo
  tag matching your ``paddleocr`` version on GitHub.

**Maintainer notes:**

- If you upgrade ``paddleocr``, re-check ``ocr()`` return shape in ``detect_page_aabbs_px``
  (list nesting and whether each detection is ``[polygon, (text, score)]`` vs polygon-only).
- ``rec=False`` avoids loading the recognition model; we only need detector polygons.
- Reading-order sort is intentionally simple (single-column); multi-column pages may need
  column clustering or PP-Structure / layout models (see PaddleOCR docs).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from prompt_based.chunk_lines_model import (
    BOX_2D_NORMALIZED_MAX,
    line_box_dict_from_normalized_aabb,
    load_page_images,
    snap_box_2d_to_ink,
)

if TYPE_CHECKING:
    pass

# --- Matching heuristics (tune here; document changes in review-line-syncing.md if UX shifts) ---

# If best IoU is below this, treat geometry overlap as unreliable and fall back to
# nearest-center distance between anchor and detections (see ``_pick_best_unused_detection``).
IOU_MIN_CONFIDENT_MATCH = 0.01

_OCR_SINGLETON = None


def _get_ocr():
    """Lazy singleton ``PaddleOCR`` (detector only at inference time via ``ocr(..., rec=False)``).

    Constructor flags follow PaddleOCR defaults for English text; adjust if you add
    non-Latin scripts (``lang=``) or enable angle classifiers for heavily rotated scans.
    """
    global _OCR_SINGLETON
    if _OCR_SINGLETON is not None:
        return _OCR_SINGLETON
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        import sys

        raise RuntimeError(
            'Could not import paddleocr (ImportError: '
            f'{exc}). Install with the same Python that runs this script: '
            f'{sys.executable} -m pip install -r requirements-paddleocr.txt'
        ) from exc
    _OCR_SINGLETON = PaddleOCR(
        use_angle_cls=False,
        lang='en',
        show_log=False,
        use_gpu=False,
    )
    return _OCR_SINGLETON


def _looks_like_point(item: object) -> bool:
    if not isinstance(item, (list, tuple)) or len(item) < 2:
        return False
    try:
        float(item[0])
        float(item[1])
    except (TypeError, ValueError):
        return False
    return not isinstance(item[0], (list, tuple))


def _looks_like_polygon(item: object) -> bool:
    if not isinstance(item, (list, tuple)) or len(item) < 3:
        return False
    return _looks_like_point(item[0])


def _detection_row_to_polygon(row: object) -> object | None:
    """Extract a detection polygon from one ``ocr()`` row.

    Paddle 2.7 often returns ``[polygon, (text, score)]``; newer builds with
    ``rec=False`` may return the polygon list directly.
    """
    if not isinstance(row, (list, tuple)) or not row:
        return None
    if _looks_like_polygon(row):
        return row
    if len(row) >= 1 and _looks_like_polygon(row[0]):
        return row[0]
    return None


def polygon_to_pixel_aabb(poly: object) -> tuple[int, int, int, int] | None:
    """Tight axis-aligned rectangle around a Paddle **detection polygon** (pixel coords).

    Paddle's text detector returns each region as a quadrilateral (typically 4 points,
    often clockwise). We only need the outer AABB for ``line_box`` and for IoU matching.

    ``poly`` is usually ``[[x0,y0], [x1,y1], ...]``; see ``detect_page_aabbs_px`` for where
    it is taken from the ``ocr()`` output line.
    """
    if poly is None:
        return None
    try:
        points = list(poly)
    except TypeError:
        return None
    if len(points) < 3:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        xs.append(float(point[0]))
        ys.append(float(point[1]))
    left = int(math.floor(min(xs)))
    upper = int(math.floor(min(ys)))
    right = int(math.ceil(max(xs)))
    lower = int(math.ceil(max(ys)))
    if right <= left:
        right = left + 1
    if lower <= upper:
        lower = upper + 1
    return left, upper, right, lower


def pixel_aabb_to_line_box(
    left: int,
    upper: int,
    right: int,
    lower: int,
    width: int,
    height: int,
) -> dict:
    """Map pixel-space AABB to normalized ``line_box`` integers (0–1000 grid).

    Same convention as ``chunk_lines_model``: ``[ymin, xmin, ymax, xmax]`` on the
    ``BOX_2D_NORMALIZED_MAX`` grid. ``right``/``lower`` here are **exclusive** upper bounds
    in pixel space (consistent with ``polygon_to_pixel_aabb`` output).
    """
    g = float(BOX_2D_NORMALIZED_MAX)
    w = max(1, width)
    h = max(1, height)
    ymin = int(round(max(0.0, min(g, upper / float(h) * g))))
    xmin = int(round(max(0.0, min(g, left / float(w) * g))))
    ymax = int(round(max(0.0, min(g, lower / float(h) * g))))
    xmax = int(round(max(0.0, min(g, right / float(w) * g))))
    if ymax <= ymin:
        ymax = min(int(g), ymin + 1)
    if xmax <= xmin:
        xmax = min(int(g), xmin + 1)
    return line_box_dict_from_normalized_aabb([ymin, xmin, ymax, xmax])


def _iou_pixel_boxes(
    box_a: tuple[int, int, int, int],
    box_b: tuple[int, int, int, int],
) -> float:
    """Intersection-over-union of two axis-aligned boxes in **pixel** coordinates.

    Each tuple is ``(left, upper, right, lower)`` with **positive** width ``right - left``
    and height ``lower - upper`` (``right``/``lower`` treated as exclusive edges for area,
    same style as Pillow crop rects).

    IoU is used only to score **anchor** (VLM coarse box) vs **Paddle detection** overlap;
    it is not a Paddle API — standard 2D vision geometry.
    """
    left_a, upper_a, right_a, lower_a = box_a
    left_b, upper_b, right_b, lower_b = box_b
    inter_left = max(left_a, left_b)
    inter_upper = max(upper_a, upper_b)
    inter_right = min(right_a, right_b)
    inter_lower = min(lower_a, lower_b)
    inter_w = max(0, inter_right - inter_left)
    inter_h = max(0, inter_lower - inter_upper)
    intersection = float(inter_w * inter_h)
    area_a = float(max(0, right_a - left_a) * max(0, lower_a - upper_a))
    area_b = float(max(0, right_b - left_b) * max(0, lower_b - upper_b))
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _center_distance_px(
    box_a: tuple[int, int, int, int],
    box_b: tuple[int, int, int, int],
) -> float:
    """Euclidean distance between the **pixel centers** of two ``(left, upper, right, lower)`` boxes."""
    cx_a = (box_a[0] + box_a[2]) / 2.0
    cy_a = (box_a[1] + box_a[3]) / 2.0
    cx_b = (box_b[0] + box_b[2]) / 2.0
    cy_b = (box_b[1] + box_b[3]) / 2.0
    return math.hypot(cx_a - cx_b, cy_a - cy_b)


def detect_page_aabbs_px(page_image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Run Paddle text **detection**; return pixel-space AABBs, sorted for single-column reading.

    ``ocr()`` typically returns ``[page_results]`` where ``page_results`` is a list of
    lines; each line is commonly ``[polygon, (recognized_text, score)]`` when recognition
    is enabled. With ``rec=False``, the second element may be ``None`` — we only read
    ``polygon`` at index ``0``. If Paddle changes this layout, update this loop and add a
    regression test with a tiny fixture image.

    Sort key ``(upper, left)`` is a simple top-to-bottom, left-to-right ordering for one
    text column; replace with smarter layout if you add multi-column support.
    """
    ocr = _get_ocr()
    rgb = page_image.convert('RGB')
    import numpy as np

    arr = np.asarray(rgb)
    result = ocr.ocr(arr, det=True, rec=False, cls=False)
    boxes: list[tuple[int, int, int, int]] = []
    if not result or not result[0]:
        return boxes
    for row in result[0]:
        polygon = _detection_row_to_polygon(row)
        aabb = polygon_to_pixel_aabb(polygon)
        if aabb is not None:
            boxes.append(aabb)
    page_w, page_h = page_image.size
    boxes.sort(key=lambda b: (b[1], b[0]))
    clamped: list[tuple[int, int, int, int]] = []
    for left, upper, right, lower in boxes:
        left = max(0, min(left, page_w - 1))
        right = max(left + 1, min(right, page_w))
        upper = max(0, min(upper, page_h - 1))
        lower = max(upper + 1, min(lower, page_h))
        clamped.append((left, upper, right, lower))
    return clamped


def _anchor_norm_to_pixel_rect(
    anchor_norm: list[int],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """Map VLM ``anchor_box_2d`` (0–1000 ``[ymin,xmin,ymax,xmax]``) to pixel ``(l,u,r,lo)``."""
    g = float(BOX_2D_NORMALIZED_MAX)
    ymin, xmin, ymax, xmax = anchor_norm
    left = int(round(xmin / g * width))
    upper = int(round(ymin / g * height))
    right = int(round(xmax / g * width))
    lower = int(round(ymax / g * height))
    left = max(0, min(left, width - 1))
    right = max(left + 1, min(right, width))
    upper = max(0, min(upper, height - 1))
    lower = max(upper + 1, min(lower, height))
    return left, upper, right, lower


def _pick_best_unused_detection(
    anchor_px: tuple[int, int, int, int],
    detections_px: list[tuple[int, int, int, int]],
    used_indices: set[int],
) -> int | None:
    """Pick the best unused Paddle detection index for one transcript line.

    Primary score: IoU between anchor (VLM coarse rect in pixels) and detection AABB.
    Tie-break: prefer larger IoU, then smaller center-distance (``key = (iou, -dist)``).

    If the best IoU is still tiny (``< IOU_MIN_CONFIDENT_MATCH``), overlap is ambiguous
    (e.g. anchor drift); fall back to **nearest center** among unused boxes so we still
    pick something stable when the VLM y-position is roughly right but width/height differ.

    **Future change:** replace greedy per-line with Hungarian assignment if line/det
    counts diverge often; pass cost matrix ``1 - iou`` or center distance.
    """
    best_index: int | None = None
    best_key: tuple[float, float] | None = None
    for j, det_box in enumerate(detections_px):
        if j in used_indices:
            continue
        iou = _iou_pixel_boxes(anchor_px, det_box)
        dist = _center_distance_px(anchor_px, det_box)
        key = (iou, -dist)
        if best_key is None or key > best_key:
            best_key = key
            best_index = j
    if best_index is None:
        return None
    assert best_key is not None
    if best_key[0] >= IOU_MIN_CONFIDENT_MATCH:
        return best_index
    nearest_index: int | None = None
    nearest_dist = 1e18
    for j, det_box in enumerate(detections_px):
        if j in used_indices:
            continue
        d = _center_distance_px(anchor_px, det_box)
        if d < nearest_dist:
            nearest_dist = d
            nearest_index = j
    return nearest_index


def assign_line_boxes_for_page(
    page_image: Image.Image,
    page_lines: list[tuple[int, dict]],
    *,
    reading_order_when_counts_match: bool = False,
) -> None:
    """For one page, set ``line_box`` on each line dict and remove ``anchor_box_2d``.

    ``page_lines`` is ``(ignored_index, line_dict)`` pairs in **transcript order**; that
    order is preserved so the greedy matcher does not reorder VLM lines (only picks
    which detection to attach to each line).

    When ``reading_order_when_counts_match`` is true and transcript line count equals
    Paddle detection count on this page, pair lines to detections in reading order
    (transcript order to detections sorted by ``(upper, left)``).
    """
    page_w, page_h = page_image.size
    detections_px = detect_page_aabbs_px(page_image)
    if (
        reading_order_when_counts_match
        and detections_px
        and len(page_lines) == len(detections_px)
    ):
        for (_idx, line), det in zip(page_lines, detections_px):
            line['line_box'] = pixel_aabb_to_line_box(
                det[0], det[1], det[2], det[3], page_w, page_h,
            )
            line.pop('anchor_box_2d', None)
        return

    used_detection_indices: set[int] = set()
    for _idx, line in page_lines:
        anchor = line.get('anchor_box_2d')
        if not isinstance(anchor, list) or len(anchor) != 4:
            anchor = [0, 0, int(BOX_2D_NORMALIZED_MAX), int(BOX_2D_NORMALIZED_MAX)]
        try:
            anchor_norm = [int(anchor[0]), int(anchor[1]), int(anchor[2]), int(anchor[3])]
        except (TypeError, ValueError):
            anchor_norm = [0, 0, 1000, 1000]
        anchor_px = _anchor_norm_to_pixel_rect(anchor_norm, page_w, page_h)
        chosen: int | None = None
        if detections_px:
            chosen = _pick_best_unused_detection(anchor_px, detections_px, used_detection_indices)
        if chosen is not None:
            used_detection_indices.add(chosen)
            det = detections_px[chosen]
            line['line_box'] = pixel_aabb_to_line_box(det[0], det[1], det[2], det[3], page_w, page_h)
        else:
            snapped = snap_box_2d_to_ink(page_image, anchor_norm)
            line_aabb_norm = snapped if snapped is not None else anchor_norm
            line['line_box'] = line_box_dict_from_normalized_aabb(
                [
                    int(line_aabb_norm[0]),
                    int(line_aabb_norm[1]),
                    int(line_aabb_norm[2]),
                    int(line_aabb_norm[3]),
                ],
            )
        line.pop('anchor_box_2d', None)


def assign_paddle_line_boxes(
    chunk_path: Path,
    lines: list[dict],
    *,
    reading_order_when_counts_match: bool = False,
) -> str | None:
    """Fill ``line_box`` from Paddle (or snap/anchor fallback). Returns warning or ``None``."""
    warn: str | None = None
    try:
        page_images = load_page_images(chunk_path)
    except Exception as exc:
        return f'Could not rasterize pages for line boxes: {exc}'
    try:
        _get_ocr()
    except RuntimeError as exc:
        warn = str(exc)
        for line in lines:
            if not isinstance(line, dict):
                continue
            anchor = line.get('anchor_box_2d')
            if not isinstance(anchor, list) or len(anchor) != 4:
                anchor = [0, 0, 1000, 1000]
            page_number = line.get('page_number')
            if not isinstance(page_number, int) or page_number < 1 or page_number > len(page_images):
                line.pop('anchor_box_2d', None)
                line.setdefault(
                    'line_box',
                    line_box_dict_from_normalized_aabb(
                        [0, 0, int(BOX_2D_NORMALIZED_MAX), int(BOX_2D_NORMALIZED_MAX)],
                    ),
                )
                continue
            img = page_images[page_number - 1]
            snapped = snap_box_2d_to_ink(img, anchor)
            line_aabb_norm = snapped if snapped is not None else anchor
            line['line_box'] = line_box_dict_from_normalized_aabb(
                [
                    int(line_aabb_norm[0]),
                    int(line_aabb_norm[1]),
                    int(line_aabb_norm[2]),
                    int(line_aabb_norm[3]),
                ],
            )
            line.pop('anchor_box_2d', None)
        return warn

    # Group lines by PDF page so each Paddle ``ocr()`` call processes one raster once.
    by_page: dict[int, list[tuple[int, dict]]] = {}
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        pn = line.get('page_number')
        if not isinstance(pn, int) or pn < 1:
            continue
        by_page.setdefault(pn, []).append((i, line))

    for pn in sorted(by_page.keys()):
        if pn > len(page_images):
            continue
        assign_line_boxes_for_page(
            page_images[pn - 1],
            by_page[pn],
            reading_order_when_counts_match=reading_order_when_counts_match,
        )
    # Lines skipped above (bad ``page_number``) never entered ``by_page``; finish them here.
    for line in lines:
        if not isinstance(line, dict):
            continue
        if 'anchor_box_2d' not in line:
            continue
        page_number = line.get('page_number')
        if not isinstance(page_number, int) or page_number < 1 or page_number > len(page_images):
            line.pop('anchor_box_2d', None)
            line.setdefault(
                'line_box',
                line_box_dict_from_normalized_aabb(
                    [0, 0, int(BOX_2D_NORMALIZED_MAX), int(BOX_2D_NORMALIZED_MAX)],
                ),
            )
            continue
        anchor = line.get('anchor_box_2d')
        if not isinstance(anchor, list) or len(anchor) != 4:
            anchor = [0, 0, 1000, 1000]
        img = page_images[page_number - 1]
        snapped = snap_box_2d_to_ink(img, anchor)
        line_aabb_norm = snapped if snapped is not None else anchor
        line['line_box'] = line_box_dict_from_normalized_aabb(
            [
                int(line_aabb_norm[0]),
                int(line_aabb_norm[1]),
                int(line_aabb_norm[2]),
                int(line_aabb_norm[3]),
            ],
        )
        line.pop('anchor_box_2d', None)
    return warn


def reassign_line_boxes_from_pdf(chunk_path: Path, lines: list[dict]) -> str | None:
    """Recompute ``line_box`` for existing v2 lines using Paddle (expects no ``anchor_box_2d``).

    Builds ephemeral ``anchor_box_2d`` from current ``line_box`` so the same matcher as
    transcribe runs without re-querying the VLM.
    """
    for line in lines:
        if not isinstance(line, dict):
            continue
        lb = line.get('line_box')
        if isinstance(lb, dict):
            try:
                line['anchor_box_2d'] = [
                    int(lb['ymin']),
                    int(lb['xmin']),
                    int(lb['ymax']),
                    int(lb['xmax']),
                ]
            except (KeyError, TypeError, ValueError):
                line['anchor_box_2d'] = [0, 0, 1000, 1000]
        else:
            line['anchor_box_2d'] = [0, 0, 1000, 1000]
    return assign_paddle_line_boxes(
        chunk_path,
        lines,
        reading_order_when_counts_match=True,
    )
