#!/usr/bin/env python3
'''Raster stress strips for OCR PDF (gradient, vignette shading, speckle).'''

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SEED = 42
WIDTH = 880
MARGIN_X = 36
MARGIN_Y = 32
LINE_GAP = 6
FONT_SIZE = 22

FONT_CANDIDATES = (
    '/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf',
)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'noise-assets')

TEXT_UNIFORM = (
    'Uniform mid-grey panel (~#A8A8A8). OCR should read this line despite '
    'a flat non-white backing similar to tinted copier paper.'
)

TEXT_GRADIENT = (
    'Subtle vertical gradient from ~#909090 to ~#C8C8C8. Tests thresholding '
    'when background luminance drifts smoothly across the line.'
)

TEXT_SHADING = (
    'Low-frequency shading and vignette mimic uneven platen lighting or mild '
    'drum wear; strokes should still decode cleanly.'
)

TEXT_SPECKLE = (
    'High-frequency speckle and salt-and-pepper noise mimic print soot, dust, '
    'and coarse halftone; text must separate from background grain.'
)


def load_font():
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, FONT_SIZE)
    return ImageFont.load_default()


def wrap_lines(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = []
    for w in words:
        trial = ' '.join(current + [w])
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(w)
        else:
            if current:
                lines.append(' '.join(current))
            current = [w]
    if current:
        lines.append(' '.join(current))
    return lines


def line_block_height(lines, font, draw):
    h = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        h += (bbox[3] - bbox[1]) + LINE_GAP
    return h - LINE_GAP if lines else 0


def fill_vertical_gradient(img, rgb_top, rgb_bottom):
    w, h = img.size
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(rgb_top[0] * (1 - t) + rgb_bottom[0] * t)
        g = int(rgb_top[1] * (1 - t) + rgb_bottom[1] * t)
        b = int(rgb_top[2] * (1 - t) + rgb_bottom[2] * t)
        for x in range(w):
            px[x, y] = (r, g, b)


def add_low_frequency_shading(base, rng):
    w, h = base.size
    small_w = max(48, w // 14)
    small_h = max(32, h // 6)
    n = Image.new('L', (small_w, small_h))
    spx = n.load()
    for y in range(small_h):
        for x in range(small_w):
            spx[x, y] = int(110 + rng.random() * 80)
    n = n.resize((w, h), Image.Resampling.BILINEAR)
    n = n.filter(ImageFilter.GaussianBlur(radius=min(w, h) * 0.04))
    out = base.copy()
    opx = out.load()
    npix = n.load()
    for y in range(h):
        for x in range(w):
            r, g, b = opx[x, y]
            lift = (npix[x, y] - 128) / 128.0 * 28
            opx[x, y] = (
                max(0, min(255, int(r + lift))),
                max(0, min(255, int(g + lift))),
                max(0, min(255, int(b + lift))),
            )
    return out


def add_vignette(img):
    w, h = img.size
    px = img.load()
    cx, cy = w * 0.5, h * 0.5
    max_d = math.hypot(cx, cy)
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy) / max_d
            factor = 1.0 - 0.22 * (d ** 1.35)
            r, g, b = px[x, y]
            px[x, y] = (
                max(0, min(255, int(r * factor))),
                max(0, min(255, int(g * factor))),
                max(0, min(255, int(b * factor))),
            )


def add_speckle(img, rng, density=0.018):
    w, h = img.size
    px = img.load()
    n = int(w * h * density)
    for _ in range(n):
        x = rng.randrange(w)
        y = rng.randrange(h)
        if rng.random() < 0.5:
            delta = rng.randint(-55, -15)
        else:
            delta = rng.randint(15, 55)
        r, g, b = px[x, y]
        px[x, y] = (
            max(0, min(255, r + delta)),
            max(0, min(255, g + delta)),
            max(0, min(255, b + delta)),
        )
    for _ in range(n // 4):
        x = rng.randrange(max(1, w - 1))
        y = rng.randrange(max(1, h - 1))
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            r, g, b = px[x + dx, y + dy]
            t = rng.randint(-25, 25)
            px[x + dx, y + dy] = (
                max(0, min(255, r + t)),
                max(0, min(255, g + t)),
                max(0, min(255, b + t)),
            )


def render_card(kind, text, rng):
    font = load_font()
    tmp = Image.new('RGB', (WIDTH, 200), (240, 240, 240))
    draw = ImageDraw.Draw(tmp)
    max_text_w = WIDTH - 2 * MARGIN_X
    lines = wrap_lines(draw, text, font, max_text_w)
    block_h = line_block_height(lines, font, draw)
    height = MARGIN_Y * 2 + block_h + 8

    img = Image.new('RGB', (WIDTH, height), (168, 168, 168))

    if kind == 'uniform':
        pass

    elif kind == 'gradient':
        fill_vertical_gradient(img, (144, 144, 144), (200, 200, 200))

    elif kind == 'shading':
        px = img.load()
        g = 175
        for y in range(height):
            for x in range(WIDTH):
                px[x, y] = (g, g, g)
        img = add_low_frequency_shading(img, rng)
        add_vignette(img)

    elif kind == 'speckle':
        px = img.load()
        g = 165
        for y in range(height):
            for x in range(WIDTH):
                px[x, y] = (g, g, g)
        add_speckle(img, rng, density=0.022)

    draw = ImageDraw.Draw(img)
    y = MARGIN_Y
    text_fill = (26, 26, 26)
    for line in lines:
        draw.text((MARGIN_X, y), line, font=font, fill=text_fill)
        bbox = draw.textbbox((MARGIN_X, y), line, font=font)
        y = bbox[3] + LINE_GAP

    return img


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = random.Random(SEED)

    cards = (
        ('uniform-dark.png', 'uniform', TEXT_UNIFORM),
        ('gradient-panel.png', 'gradient', TEXT_GRADIENT),
        ('uneven-shading.png', 'shading', TEXT_SHADING),
        ('speckle-print.png', 'speckle', TEXT_SPECKLE),
    )

    for filename, kind, text in cards:
        img = render_card(kind, text, rng)
        path = os.path.join(OUT_DIR, filename)
        img.save(path, 'PNG', dpi=(144, 144))
        print('wrote', path)


if __name__ == '__main__':
    main()
