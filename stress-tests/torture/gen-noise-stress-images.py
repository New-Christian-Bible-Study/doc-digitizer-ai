#!/usr/bin/env python3
'''Raster stress strips for OCR PDF (gradient, vignette shading, speckle).

One ``--lang-dir`` per torture language (e.g. ``english/``, ``italian/``). PNGs
must match the prose baked into that folder's ``test-ocr.adoc`` (PDF branch of
section 4); see ``noise-image-text.json`` for the same strings in a machine-
readable form. Shared tooling lives next to this file; only ``noise-assets/`` is
language-specific.
'''

import argparse
import json
import math
import os
import random
import re
import sys
from pathlib import Path

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

ACCENT_LINE_PATTERN = re.compile(r'^:accent-stress-line:\s*(.+)$', re.MULTILINE)


def parse_accent_stress_line(adoc_path: Path) -> str:
    raw = adoc_path.read_text(encoding='utf-8')
    match = ACCENT_LINE_PATTERN.search(raw)
    if not match:
        raise ValueError(f'no :accent-stress-line: in {adoc_path}')
    return match.group(1).strip()


def load_noise_config(lang_dir: Path) -> dict:
    # Accent line is duplicated on purpose: the .adoc attribute drives the page,
    # JSON holds the same string so we fail fast if an editor updates one file
    # and forgets the other (the raster text must match OCR expectations).
    adoc_path = lang_dir / 'test-ocr.adoc'
    json_path = lang_dir / 'noise-image-text.json'
    if not json_path.is_file():
        raise FileNotFoundError(f'missing {json_path}')
    accent_adoc = parse_accent_stress_line(adoc_path)
    with json_path.open(encoding='utf-8') as f:
        data = json.load(f)
    accent_json = data.get('accent_stress_line')
    if not isinstance(accent_json, str):
        raise ValueError(f'{json_path} must have string accent_stress_line')
    if accent_json != accent_adoc:
        raise ValueError(
            f'accent_stress_line mismatch:\n  adoc ({adoc_path}): {accent_adoc!r}\n'
            f'  json ({json_path}): {accent_json!r}',
        )
    required = ('uniform', 'gradient', 'shading', 'speckle')
    for key in required:
        val = data.get(key)
        if not isinstance(val, str):
            raise ValueError(f'{json_path} must have string key {key!r}')
    return data


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Write noise strip PNGs under <lang-dir>/noise-assets/.',
    )
    parser.add_argument(
        '--lang-dir',
        type=Path,
        required=True,
        help='Path to torture/<language> (contains test-ocr.adoc, noise-image-text.json).',
    )
    args = parser.parse_args()
    lang_dir = args.lang_dir.resolve()
    if not lang_dir.is_dir():
        print(f'Error: not a directory: {lang_dir}', file=sys.stderr)
        return 1
    try:
        data = load_noise_config(lang_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1

    accent = data['accent_stress_line']
    cards = (
        ('uniform-dark.png', 'uniform', data['uniform'] + accent),
        ('gradient-panel.png', 'gradient', data['gradient'] + accent),
        ('uneven-shading.png', 'shading', data['shading'] + accent),
        ('speckle-print.png', 'speckle', data['speckle'] + accent),
    )

    out_dir = lang_dir / 'noise-assets'
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(SEED)

    for filename, kind, text in cards:
        img = render_card(kind, text, rng)
        path = out_dir / filename
        img.save(str(path), 'PNG', dpi=(144, 144))
        print('wrote', path)

    return 0


if __name__ == '__main__':
    sys.exit(main())
