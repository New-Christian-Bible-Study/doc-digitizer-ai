"""Tests for ``chunk_lines_model`` box geometry (no PDF rasterization)."""

from chunk_lines_model import REVIEW_PDF_RASTER_DPI, clamp_box_2d_to_pixels


def test_clamp_box_2d_to_pixels_center_square():
    # 10%–20% of a 1000×1000 page; padding applied from named constants.
    assert clamp_box_2d_to_pixels([100, 100, 200, 200], 1000, 1000) == (
        97,
        93,
        203,
        212,
    )


def test_clamp_box_2d_to_pixels_degenerate_box_non_empty():
    # Model noise at a corner → clamped to a 1×1 box, then padded within page.
    assert clamp_box_2d_to_pixels([0, 0, 0, 0], 100, 100) == (0, 0, 2, 3)


def test_clamp_box_2d_to_pixels_wide_short_strip():
    assert clamp_box_2d_to_pixels([400, 100, 450, 900], 1000, 1000) == (
        83,
        397,
        917,
        457,
    )


def test_review_pdf_raster_dpi_is_pinned():
    assert REVIEW_PDF_RASTER_DPI == 200
