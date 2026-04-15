#!/usr/bin/env python3
"""
Export full-page rasters with line box outlines (same geometry as review-chunk-lines crops).

  python tests/chunk-lines-boxes-export.py --working-dir <dir>   # from prompt-based/

Uses ``--working-dir`` like transcribe-chunk.py / review-chunk.py. Without
``--raw-json``, pick a ``transcriptions/*_raw.json`` interactively (arrow keys). Use
``--raw-json`` when stdin is not a TTY (CI / scripts).
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

_STRATEGY_ROOT = Path(__file__).resolve().parent.parent
if str(_STRATEGY_ROOT) not in sys.path:
    sys.path.insert(0, str(_STRATEGY_ROOT))

import img2pdf
import questionary
from PIL import Image, ImageDraw, ImageFont

from chunk_lines_model import (
    clamp_box_2d_to_pixels,
    is_injected_page_marker,
    load_page_images,
    load_payload,
    resolve_chunk_pdf_dir,
    resolve_transcription_paths_for_chunk,
)

LABEL_STRIP_HEIGHT = 52
BOX_OUTLINE_WIDTH = 2
# Distinct outlines so neighboring boxes are easy to tell apart.
BOX_OUTLINE_COLORS = [
    (220, 40, 40),
    (30, 140, 30),
    (30, 80, 200),
    (180, 100, 20),
    (120, 40, 160),
    (20, 140, 140),
]


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(
        description=(
            'Draw line box outlines on chunk pages (same padded bounds as '
            'review-chunk-lines) and write PDF or PNG to transcriptions/.'
        ),
    )
    parser.add_argument(
        '--working-dir',
        type=Path,
        default=Path('.'),
        help=(
            'Same as transcribe-chunk.py: directory containing '
            'chunk-pdfs/ (or use --chunk-dir) and transcriptions/'
        ),
    )
    parser.add_argument(
        '--chunk-dir',
        type=Path,
        default=None,
        help=(
            'Directory containing chunk PDFs (default: working-dir/chunk-pdfs). '
            'Relative paths are resolved under working-dir.'
        ),
    )
    parser.add_argument(
        '--raw-json',
        type=Path,
        default=None,
        help=(
            'Path to *_raw.json; relative paths are under --working-dir. '
            'Required when stdin is not a TTY (non-interactive).'
        ),
    )
    parser.add_argument(
        '--format',
        dest='out_format',
        choices=('pdf', 'png'),
        default=None,
        help='Output format (default: pdf, or prompt interactively if omitted and TTY)',
    )
    return parser.parse_args(argv)


def list_raw_json_files(transcriptions_dir: Path) -> list[Path]:
    if not transcriptions_dir.is_dir():
        return []
    return sorted(
        p
        for p in transcriptions_dir.glob('*_raw.json')
        if p.is_file()
    )


def stem_from_raw_path(raw_path: Path) -> str | None:
    name = raw_path.name
    if not name.endswith('_raw.json'):
        return None
    return name[: -len('_raw.json')]


def pick_raw_json_interactive(working_dir: Path) -> Path | None:
    transcriptions_dir = working_dir / 'transcriptions'
    candidates = list_raw_json_files(transcriptions_dir)
    if not candidates:
        print(
            f'No *_raw.json files under {transcriptions_dir}',
            file=sys.stderr,
        )
        return None
    choices = [str(p.relative_to(working_dir)) for p in candidates]
    rel = questionary.select(
        'Select raw JSON:',
        choices=choices,
    ).ask()
    if rel is None:
        return None
    return (working_dir / rel).resolve()


def pick_format_interactive() -> str | None:
    choice = questionary.select(
        'Output format:',
        choices=['pdf', 'png'],
        default='pdf',
    ).ask()
    return choice


def _try_load_font(size: int) -> ImageFont.ImageFont:
    candidates = (
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    )
    for path in candidates:
        p = Path(path)
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_page_with_boxes(
    page_img: Image.Image,
    page_number: int,
    lines: list,
    label_font: ImageFont.ImageFont,
) -> Image.Image:
    """Full-width strip with ``Page N``, then page image with box outlines (reviewer geometry)."""
    if page_img.mode != 'RGB':
        page_img = page_img.convert('RGB')
    w, h = page_img.size
    strip = Image.new('RGB', (w, LABEL_STRIP_HEIGHT), (245, 245, 245))
    ds = ImageDraw.Draw(strip)
    label = f'Page {page_number}'
    ds.text((12, 10), label, fill=(20, 20, 20), font=label_font)

    composite = Image.new('RGB', (w, LABEL_STRIP_HEIGHT + h), (255, 255, 255))
    composite.paste(strip, (0, 0))
    composite.paste(page_img, (0, LABEL_STRIP_HEIGHT))

    draw = ImageDraw.Draw(composite)
    y_off = LABEL_STRIP_HEIGHT
    color_i = 0
    for line in lines:
        if is_injected_page_marker(line.get('text', '')):
            continue
        pn = line.get('page_number')
        box_2d = line.get('box_2d')
        if not isinstance(pn, int) or pn != page_number:
            continue
        if not isinstance(box_2d, list) or len(box_2d) != 4:
            continue
        left, upper, right, lower = clamp_box_2d_to_pixels(box_2d, w, h)
        color = BOX_OUTLINE_COLORS[color_i % len(BOX_OUTLINE_COLORS)]
        color_i += 1
        draw.rectangle(
            [left, upper + y_off, right - 1, lower - 1 + y_off],
            outline=color,
            width=BOX_OUTLINE_WIDTH,
        )
    return composite


def export_pdf(page_images: list[Image.Image], lines: list, out_path: Path) -> None:
    label_font = _try_load_font(22)
    buffers: list[io.BytesIO] = []
    try:
        for i, page_img in enumerate(page_images, start=1):
            comp = render_page_with_boxes(page_img, i, lines, label_font)
            buf = io.BytesIO()
            comp.save(buf, format='PNG')
            buf.seek(0)
            buffers.append(buf)
        pdf_bytes = img2pdf.convert(*buffers)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(pdf_bytes)
    finally:
        for b in buffers:
            b.close()


def export_pngs(page_images: list[Image.Image], lines: list, stem: str, out_dir: Path) -> None:
    label_font = _try_load_font(22)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, page_img in enumerate(page_images, start=1):
        comp = render_page_with_boxes(page_img, i, lines, label_font)
        out_file = out_dir / f'{stem}-boxes-p{i:04d}.png'
        comp.save(out_file, format='PNG')


def run() -> int:
    cli = parse_cli_args()
    working_dir = cli.working_dir.resolve()
    chunk_pdf_dir = resolve_chunk_pdf_dir(working_dir, cli.chunk_dir)
    transcriptions_dir = working_dir / 'transcriptions'

    if not chunk_pdf_dir.is_dir():
        print(
            f'Expected a chunk PDF directory at {chunk_pdf_dir}. '
            'Use --chunk-dir or ensure working-dir contains chunk-pdfs/ '
            'and transcriptions/.',
            file=sys.stderr,
        )
        return 1
    if not transcriptions_dir.is_dir():
        print(
            f'Expected a transcriptions directory at {transcriptions_dir}.',
            file=sys.stderr,
        )
        return 1

    raw_path: Path | None
    if cli.raw_json is not None:
        raw_candidate = cli.raw_json
        raw_path = (
            (working_dir / raw_candidate).resolve()
            if not raw_candidate.is_absolute()
            else raw_candidate.resolve()
        )
    else:
        if not sys.stdin.isatty():
            print(
                'Non-interactive mode: pass --raw-json (path to *_raw.json).',
                file=sys.stderr,
            )
            return 1
        raw_path = pick_raw_json_interactive(working_dir)
        if raw_path is None:
            return 1

    stem = stem_from_raw_path(raw_path)
    if stem is None:
        print(
            f'Raw file must be named <stem>_raw.json, got: {raw_path.name}',
            file=sys.stderr,
        )
        return 1

    chunk_name = f'{stem}.pdf'
    resolved = resolve_transcription_paths_for_chunk(
        working_dir,
        chunk_name,
        raw_path,
        chunk_pdf_dir,
    )
    if isinstance(resolved, str):
        print(resolved, file=sys.stderr)
        return 1

    out_fmt = cli.out_format
    if out_fmt is None:
        if not sys.stdin.isatty():
            out_fmt = 'pdf'
        else:
            picked = pick_format_interactive()
            if picked is None:
                return 1
            out_fmt = picked

    try:
        page_images = load_page_images(resolved.chunk_path)
    except Exception as exc:
        print(f'Could not rasterize PDF: {exc}', file=sys.stderr)
        return 1

    payload = load_payload(resolved.raw_path, resolved.final_path)
    lines = payload.get('lines')
    if not isinstance(lines, list):
        print('Invalid payload: missing "lines" list.', file=sys.stderr)
        return 1

    if out_fmt == 'pdf':
        out_file = transcriptions_dir / f'{stem}-boxes.pdf'
        try:
            export_pdf(page_images, lines, out_file)
        except Exception as exc:
            print(f'Could not write PDF: {exc}', file=sys.stderr)
            return 1
        print(out_file)
    else:
        try:
            export_pngs(page_images, lines, stem, transcriptions_dir)
        except Exception as exc:
            print(f'Could not write PNGs: {exc}', file=sys.stderr)
            return 1
        for i in range(1, len(page_images) + 1):
            print(transcriptions_dir / f'{stem}-boxes-p{i:04d}.png')

    return 0


if __name__ == '__main__':
    sys.exit(run())
