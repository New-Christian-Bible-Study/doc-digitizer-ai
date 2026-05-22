"""Tests for Paddle line-box assignment helpers."""

from unittest.mock import patch

from PIL import Image, ImageDraw

from prompt_based.paddle_line_boxes import (
    _detection_row_to_polygon,
    _filter_detections_for_matching,
    _pick_best_unused_detection,
    assign_line_boxes_for_page,
    detect_page_aabbs_px,
)


def test_detection_row_to_polygon_accepts_polygon_only_row():
    polygon = [[49.0, 120.0], [191.0, 120.0], [191.0, 133.0], [49.0, 133.0]]
    assert _detection_row_to_polygon(polygon) == polygon


def test_detection_row_to_polygon_accepts_legacy_text_row():
    polygon = [[51.0, 80.0], [115.0, 80.0], [115.0, 92.0], [51.0, 92.0]]
    row = [polygon, ('THE PREFACE', 0.99)]
    assert _detection_row_to_polygon(row) == polygon


def test_filter_detections_drops_bottom_catchword():
    page_w, page_h = 800, 1000
    body = (50, 200, 700, 230)
    catchword = (650, 920, 720, 945)
    filtered = _filter_detections_for_matching(page_w, page_h, [body, catchword])
    assert filtered == [body]


def test_pick_detection_requires_minimum_iou():
    anchor = (50, 100, 350, 130)
    far = (600, 900, 720, 930)
    assert _pick_best_unused_detection(anchor, [far], set()) is None


def test_pick_detection_accepts_overlapping_box():
    anchor = (50, 100, 350, 130)
    overlap = (55, 98, 340, 132)
    assert _pick_best_unused_detection(anchor, [overlap], set()) == 0


def test_assign_line_boxes_hybrid_uses_paddle_when_iou_confident():
    img = Image.new('RGB', (400, 400), 'white')
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 100, 350, 120], fill='black')

    body_line = (50, 95, 350, 125)
    catchword = (320, 370, 350, 390)
    lines = [
        (
            0,
            {
                'anchor_box_2d': [240, 120, 290, 880],
                'text': 'Hello',
            },
        ),
    ]

    with patch(
        'prompt_based.paddle_line_boxes.detect_page_aabbs_px',
        return_value=[catchword, body_line],
    ):
        assign_line_boxes_for_page(img, lines)

    lb = lines[0][1]['line_box']
    assert 230 <= lb['ymin'] <= 260
    assert lb['ymax'] <= 320


def test_assign_line_boxes_hybrid_falls_back_to_anchor_when_iou_weak():
    img = Image.new('RGB', (400, 400), 'white')
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 100, 350, 120], fill='black')

    far = (300, 370, 350, 390)
    anchor = [240, 120, 290, 880]
    lines = [(0, {'anchor_box_2d': anchor, 'text': 'Hello'})]

    with patch(
        'prompt_based.paddle_line_boxes.detect_page_aabbs_px',
        return_value=[far],
    ):
        assign_line_boxes_for_page(img, lines)

    lb = lines[0][1]['line_box']
    assert lb['ymin'] >= anchor[0] - 40
    assert lb['ymax'] <= anchor[2] + 40


def test_detect_page_aabbs_px_parses_polygon_only_rows():
    img = Image.new('RGB', (800, 200), 'white')
    draw = ImageDraw.Draw(img)
    draw.text((50, 80), 'THE PREFACE', fill='black')
    draw.text((50, 120), 'Some sample text for detection', fill='black')
    boxes = detect_page_aabbs_px(img)
    assert len(boxes) >= 2
