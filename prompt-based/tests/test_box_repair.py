"""Tests for box_repair — regression-guard behaviour."""

from PIL import Image

from prompt_based.box_repair import repair_pathological_boxes, find_pathological

# Helpers ─────────────────────────────────────────────────────────────────────

def _lb(ymin, xmin, ymax, xmax):
    return {'ymin': ymin, 'xmin': xmin, 'ymax': ymax, 'xmax': xmax}


def _line(page, ymin, xmin, ymax, xmax, text=''):
    return {'page_number': page, 'line_box': _lb(ymin, xmin, ymax, xmax), 'text': text}


def _gray_page(width=1000, height=1200):
    """Solid white page — snap-to-ink will find no ink and leave boxes unchanged."""
    return Image.new('RGB', (width, height), color=(255, 255, 255))


def _gray_page_with_stripe(y0, y1, width=1000, height=1200, dark=50):
    """Page with a single horizontal dark stripe between y0 and y1 (pixels)."""
    img = Image.new('RGB', (width, height), color=(255, 255, 255))
    for y in range(y0, min(y1, height)):
        for x in range(0, width):
            img.putpixel((x, y), (dark, dark, dark))
    return img


# ── find_pathological ─────────────────────────────────────────────────────────

def test_find_pathological_detects_fully_nested_box():
    lines = [
        _line(1, 100, 50, 200, 800, 'A'),
        _line(1, 110, 50, 190, 800, 'B'),  # nested inside A
    ]
    bad = find_pathological(lines)
    assert 1 in bad


def test_find_pathological_skips_clean_lines():
    lines = [
        _line(1, 100, 50, 150, 800, 'A'),
        _line(1, 200, 50, 250, 800, 'B'),  # non-overlapping
    ]
    assert find_pathological(lines) == []


# ── regression guard: no regressions introduced ───────────────────────────────

def _make_tmp_pdf(tmp_path, page_image: Image.Image) -> object:
    """Write a single-page PDF containing page_image and return its path."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    pdf_page = pdf.new_page(page_image.width, page_image.height)
    # Embed image as a bitmap object
    bm = pdfium.PdfBitmap.from_pil(page_image)
    img_obj = pdfium.PdfImage.new(pdf)
    img_obj.set_bitmap(bm)
    img_obj.set_matrix(pdfium.PdfMatrix(page_image.width, 0, 0, page_image.height, 0, 0))
    pdf_page.insert_obj(img_obj)
    pdf_page.gen_content()
    out = tmp_path / 'test.pdf'
    pdf.save(str(out))
    return out


def test_repair_introduces_no_nesting_regressions(tmp_path):
    """repair_pathological_boxes must not make non-pathological lines pathological."""
    # Page has ink at rows 300-330 and 600-630 (normalized: ~250-275 and ~500-525 on 1200px)
    page_h = 1200
    img = _gray_page_with_stripe(300, 330, height=page_h)

    # Draw second stripe
    for y in range(600, 630):
        for x in range(0, 1000):
            img.putpixel((x, y), (50, 50, 50))

    pdf_path = _make_tmp_pdf(tmp_path, img)

    g = 1000
    # Line A: correctly placed at first stripe (~y 250-275 in normalised space)
    # Line B: tiny pathological box, nested deeply inside A
    # Line C: correctly placed at second stripe
    lines = [
        _line(1, 245, 50, 278, 800, 'A'),       # clean, ~row 294-334px
        _line(1, 250, 50, 260, 800, 'B'),       # pathological (nested in A)
        _line(1, 495, 50, 528, 800, 'C'),       # clean, ~row 594-634px
    ]

    orig_c_box = dict(lines[2]['line_box'])
    repair_pathological_boxes(pdf_path, lines)

    # B was pathological → repair attempted it; C was clean → must stay unchanged
    assert lines[2]['line_box'] == orig_c_box, \
        f'Regression: clean line C box changed to {lines[2]["line_box"]}'
    assert find_pathological(lines) == [] or all(
        lines[i]['text'] != 'C' for i in find_pathological(lines)
    ), 'Regression: line C became pathological after repair'
