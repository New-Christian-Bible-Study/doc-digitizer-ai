"""Tests for Paddle line-box assignment helpers."""

from prompt_based.paddle_line_boxes import (
    _detection_row_to_polygon,
    detect_page_aabbs_px,
)


def test_detection_row_to_polygon_accepts_polygon_only_row():
    polygon = [[49.0, 120.0], [191.0, 120.0], [191.0, 133.0], [49.0, 133.0]]
    assert _detection_row_to_polygon(polygon) == polygon


def test_detection_row_to_polygon_accepts_legacy_text_row():
    polygon = [[51.0, 80.0], [115.0, 80.0], [115.0, 92.0], [51.0, 92.0]]
    row = [polygon, ('THE PREFACE', 0.99)]
    assert _detection_row_to_polygon(row) == polygon


def test_assign_line_boxes_for_page_reading_order_when_counts_match():
    from PIL import Image, ImageDraw

    from prompt_based.paddle_line_boxes import assign_line_boxes_for_page

    img = Image.new('RGB', (400, 120), 'white')
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), 'Line one', fill='black')
    draw.text((20, 60), 'Line two', fill='black')
    lines = [
        (
            0,
            {
                'anchor_box_2d': [900, 0, 1000, 1000],
                'text': 'Line one',
            },
        ),
        (
            1,
            {
                'anchor_box_2d': [900, 0, 1000, 1000],
                'text': 'Line two',
            },
        ),
    ]

    assign_line_boxes_for_page(
        img,
        lines,
        reading_order_when_counts_match=True,
    )
    first = lines[0][1]['line_box']
    second = lines[1][1]['line_box']
    assert first['ymin'] < second['ymin']


def test_detect_page_aabbs_px_parses_polygon_only_rows():
    from PIL import Image, ImageDraw

    img = Image.new('RGB', (800, 200), 'white')
    draw = ImageDraw.Draw(img)
    draw.text((50, 80), 'THE PREFACE', fill='black')
    draw.text((50, 120), 'Some sample text for detection', fill='black')
    boxes = detect_page_aabbs_px(img)
    assert len(boxes) >= 2
