#!/usr/bin/env python3
"""
Line-by-line review UI: show PDF page crops next to editable transcription text.

Requires Poppler (system) for pdf2image — see README.md.

``--working-dir`` is the same as for ``transcribe-chunk-pdf.py``: the directory
that *contains* ``chunk-pdfs/`` and ``transcriptions/`` (not either of those
folders themselves).

Streamlit may prompt for an email in the terminal before this file runs; that
comes from the ``streamlit`` CLI, not this app. Use ``STREAMLIT_SERVER_HEADLESS=true``
on the command line, repo ``.streamlit/config.toml`` (when cwd is this repo), or
a one-time ``~/.streamlit/credentials.toml`` with ``email = ""`` — see README.

Run:
  streamlit run review-chunk-lines.py -- --working-dir . --chunk-pdf mychunk.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from pdf2image import convert_from_path
from PIL import Image

# Prompt-injected markers (not printed on the page); skip in the review UI.
_PAGE_MARKER_PATTERN = re.compile(r'^\s*//\s*Page\s+\d+\s*$', re.IGNORECASE)


def is_injected_page_marker(text: object) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip()
    if t.startswith('{empty}'):
        t = t[len('{empty}') :].strip()
    return bool(_PAGE_MARKER_PATTERN.match(t))


def reviewable_line_indices(lines: list) -> list[int]:
    return [i for i, ln in enumerate(lines) if not is_injected_page_marker(ln.get('text', ''))]


def parse_cli_args() -> argparse.Namespace | None:
    argv = sys.argv[1:]
    if '--' in argv:
        argv = argv[argv.index('--') + 1 :]
    # When started via `streamlit run`, the CLI usually forwards only the
    # script arguments (no `--` in sys.argv), so we parse argv[1:] as above.

    if not argv:
        return None

    parser = argparse.ArgumentParser(
        description='Review and correct per-line transcriptions for a chunk PDF.',
    )
    parser.add_argument(
        '--working-dir',
        type=Path,
        default=Path('.'),
        help=(
            'Same as transcribe-chunk-pdf.py: directory containing '
            'chunk-pdfs/ and transcriptions/'
        ),
    )
    parser.add_argument(
        '--chunk-pdf',
        required=True,
        help='Chunk PDF filename only (must exist under chunk-pdfs/).',
    )
    parser.add_argument(
        '--raw-json',
        type=Path,
        default=None,
        help=(
            'Path to *_raw.json; relative paths are under --working-dir '
            '(default: transcriptions/<stem>_raw.json)'
        ),
    )
    return parser.parse_args(argv)


def clamp_box_2d_to_pixels(
    box_2d: list,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    ymin, xmin, ymax, xmax = (int(box_2d[0]), int(box_2d[1]), int(box_2d[2]), int(box_2d[3]))
    left = int(round(xmin / 1000.0 * width))
    upper = int(round(ymin / 1000.0 * height))
    right = int(round(xmax / 1000.0 * width))
    lower = int(round(ymax / 1000.0 * height))
    left = max(0, min(left, width))
    right = max(0, min(right, width))
    upper = max(0, min(upper, height))
    lower = max(0, min(lower, height))
    if right <= left:
        right = min(width, left + 1)
    if lower <= upper:
        lower = min(height, upper + 1)
    box_h = lower - upper
    box_w = right - left
    # Scale padding to the model box, not the full page — page-based pad_bot could be ~80px on
    # tall rasters and pulled the next line into the crop. Keep top tight; modest bottom for descenders.
    pad_top = min(8, max(0, box_h // 14))
    pad_bot = min(28, max(3, box_h // 5 + 2))
    pad_x = min(24, max(1, box_w // 50 + 1))
    left = max(0, left - pad_x)
    upper = max(0, upper - pad_top)
    right = min(width, right + pad_x)
    lower = min(height, lower + pad_bot)
    if right <= left:
        right = min(width, left + 1)
    if lower <= upper:
        lower = min(height, upper + 1)
    return left, upper, right, lower


def estimate_transcription_font_px(text: str, crop_width: int | None) -> int:
    """Rough px font size before the JS fit runs (initial render only)."""
    t = text.rstrip() if isinstance(text, str) else text
    n = max(len(t), 1)
    w = min(1100, max(crop_width or 640, 320))
    return max(13, min(160, int(w / (n * 0.48))))


def rstrip_line_text(value: object) -> object:
    if isinstance(value, str):
        return value.rstrip()
    return value


def inject_transcription_font_fit() -> None:
    """Binary-search font size vs image width; small trailing gap is acceptable."""
    components.html(
        """
        <script>
        (function () {
          var doc = window.parent.document;
          function innerTextWidth(el) {
            var cs = window.parent.getComputedStyle(el);
            var pl = parseFloat(cs.paddingLeft) || 0;
            var pr = parseFloat(cs.paddingRight) || 0;
            return Math.max(0, el.clientWidth - pl - pr);
          }
          function fit() {
            var imgs = doc.querySelectorAll('[data-testid="stImage"] img');
            var tas = doc.querySelectorAll('[data-testid="stTextArea"] textarea');
            var inps = doc.querySelectorAll('[data-testid="stTextInput"] input');
            var ta = tas.length ? tas[tas.length - 1] : null;
            var inp = inps.length ? inps[inps.length - 1] : null;
            var el = ta || inp;
            if (!imgs.length || !el) { return; }
            var img = imgs[imgs.length - 1];
            el.style.width = '100%';
            el.style.boxSizing = 'border-box';
            if (ta) { ta.style.whiteSpace = 'nowrap'; }
            void el.offsetWidth;
            var iw = img.clientWidth;
            var inner = innerTextWidth(el);
            if (inner < 40) { return; }
            var maxW = Math.min(iw, inner) - 1;
            if (maxW < 36) { return; }
            var lo = 8;
            var hi = 320;
            var i;
            for (i = 0; i < 32; i++) {
              var mid = (lo + hi) / 2;
              el.style.fontSize = mid + 'px';
              el.style.lineHeight = '1.2';
              void el.offsetWidth;
              if (el.scrollWidth <= maxW) { lo = mid; } else { hi = mid; }
            }
            el.style.fontSize = lo + 'px';
            void el.offsetWidth;
            var fs = lo;
            var j;
            for (j = 0; j < 36; j++) {
              var next = fs + 0.5;
              if (next > 340) { break; }
              el.style.fontSize = next + 'px';
              void el.offsetWidth;
              if (el.scrollWidth > maxW) {
                el.style.fontSize = fs + 'px';
                break;
              }
              fs = next;
            }
            if (!el.dataset.reviewFitBound) {
              el.dataset.reviewFitBound = '1';
              el.addEventListener('input', function () { setTimeout(fit, 0); });
            }
          }
          setTimeout(fit, 0);
          setTimeout(function () { window.parent.requestAnimationFrame(fit); }, 0);
          setTimeout(fit, 120);
          setTimeout(fit, 350);
          window.parent.addEventListener('resize', fit);
        })();
        </script>
        """,
        height=0,
    )


def load_page_images(pdf_path: Path) -> list[Image.Image]:
    return convert_from_path(str(pdf_path))


def load_payload(raw_path: Path, final_path: Path) -> dict:
    if final_path.exists():
        return json.loads(final_path.read_text(encoding='utf-8'))
    return json.loads(raw_path.read_text(encoding='utf-8'))


def save_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main() -> None:
    st.set_page_config(page_title='Line review', layout='wide')
    cli = parse_cli_args()
    if cli is None:
        st.error(
            'Missing arguments. Example:\n\n'
            'streamlit run review-chunk-lines.py -- '
            '--working-dir <dir> --chunk-pdf <filename.pdf>\n\n'
            'Use the same <dir> as transcribe-chunk-pdf.py (the folder that '
            'contains chunk-pdfs/ and transcriptions/).',
        )
        st.stop()

    working_dir = cli.working_dir.resolve()
    chunk_pdfs_dir = working_dir / 'chunk-pdfs'
    transcriptions_dir = working_dir / 'transcriptions'
    if not chunk_pdfs_dir.is_dir():
        st.error(
            f'Expected a chunk-pdfs directory at {chunk_pdfs_dir}. '
            '--working-dir should be the project/work folder that contains '
            'chunk-pdfs/ (and usually transcriptions/), same as '
            'transcribe-chunk-pdf.py.',
        )
        st.stop()

    chunk_name = cli.chunk_pdf.strip()
    if Path(chunk_name).name != chunk_name:
        st.error('Use chunk PDF filename only, not a path.')
        st.stop()
    if not chunk_name.lower().endswith('.pdf'):
        st.error("Chunk PDF filename must end with '.pdf'.")
        st.stop()

    chunk_pdf_path = chunk_pdfs_dir / chunk_name
    if not chunk_pdf_path.is_file():
        st.error(f'Chunk PDF not found: {chunk_pdf_path}')
        st.stop()

    stem = Path(chunk_name).stem
    if cli.raw_json is not None:
        raw_candidate = cli.raw_json
        raw_path = (
            (working_dir / raw_candidate).resolve()
            if not raw_candidate.is_absolute()
            else raw_candidate.resolve()
        )
    else:
        raw_path = transcriptions_dir / f'{stem}_raw.json'
    final_path = transcriptions_dir / f'{stem}_final.json'

    if not raw_path.is_file():
        st.error(f'Raw JSON not found: {raw_path}')
        st.stop()

    if 'page_images' not in st.session_state:
        try:
            st.session_state.page_images = load_page_images(chunk_pdf_path)
        except Exception as exc:
            st.error(
                f'Could not rasterize PDF (is Poppler installed?). {exc}',
            )
            st.stop()

    if 'payload' not in st.session_state:
        st.session_state.payload = load_payload(raw_path, final_path)
        st.session_state.source_raw_path = str(raw_path)
        st.session_state.final_path = str(final_path)

    if 'line_idx' not in st.session_state:
        st.session_state.line_idx = 0

    payload = st.session_state.payload
    lines = payload.get('lines')
    if not isinstance(lines, list) or not lines:
        st.error('Invalid payload: missing or empty "lines" array.')
        st.stop()

    page_images: list[Image.Image] = st.session_state.page_images
    n_pages = len(page_images)
    n_lines = len(lines)

    review_indices = reviewable_line_indices(lines)
    n_review = len(review_indices)
    if n_review == 0:
        st.error(
            'No lines to review: every entry looks like a synthetic '
            '`// Page N` marker. Check the raw JSON or prompt.',
        )
        st.stop()

    skipped = n_lines - n_review
    st.title('Line-by-line transcription review')
    st.caption(
        f'Chunk: `{chunk_name}` · Raw: `{raw_path.name}` · '
        f'Final: `{final_path.name}`',
    )
    if skipped:
        st.caption(
            f'Skipping **{skipped}** synthetic page marker line(s) (`// Page …`) '
            'that are not on the scanned page. They stay in the saved JSON.',
        )

    ridx = int(st.session_state.line_idx)
    ridx = max(0, min(ridx, n_review - 1))
    st.session_state.line_idx = ridx

    idx = review_indices[ridx]
    line = lines[idx]
    page_number = line.get('page_number')
    box_2d = line.get('box_2d')
    editor_key = f'editor_{idx}'
    if st.session_state.get('last_editor_idx') != idx:
        _t = line.get('text', '')
        st.session_state[editor_key] = _t.rstrip() if isinstance(_t, str) else _t
        st.session_state['last_editor_idx'] = idx

    err_msg: str | None = None
    crop_img: Image.Image | None = None
    if not isinstance(page_number, int) or page_number < 1:
        err_msg = f'Invalid page_number: {page_number!r}'
    elif page_number > n_pages:
        err_msg = (
            f'page_number {page_number} is out of range (chunk has {n_pages} page(s)).'
        )
    elif not isinstance(box_2d, list) or len(box_2d) != 4:
        err_msg = f'Invalid box_2d: {box_2d!r}'
    else:
        page_img = page_images[page_number - 1]
        w, h = page_img.size
        left, upper, right, lower = clamp_box_2d_to_pixels(box_2d, w, h)
        crop_img = page_img.crop((left, upper, right, lower))

    _raw_fit = st.session_state.get(editor_key, line.get('text', ''))
    _txt_for_fit = _raw_fit.rstrip() if isinstance(_raw_fit, str) else _raw_fit
    _multiline = isinstance(_raw_fit, str) and '\n' in _raw_fit
    _fallback_fs = estimate_transcription_font_px(
        _txt_for_fit if isinstance(_txt_for_fit, str) else '',
        crop_img.width if crop_img else None,
    )
    pn_disp = (
        str(page_number)
        if isinstance(page_number, int) and page_number >= 1
        else '—'
    )
    st.markdown(
        '<style>'
        'p.review-page-line { margin: 0 0 0.12rem 0 !important; font-size: 0.92rem !important; color: #5f6368 !important; }'
        'p.review-line-line { margin: 0 0 0.35rem 0 !important; font-size: 1.35rem !important; font-weight: 600 !important; }'
        '/* Streamlit vertical blocks use flex gap between element wrappers; negative margins pull crop + editor together */'
        'div[data-testid="stElementContainer"]:has([data-testid="stImage"]) { margin-bottom: -2.25rem !important; overflow: visible !important; }'
        'div[data-testid="stElementContainer"]:has([data-testid="stTextInput"]),'
        'div[data-testid="stElementContainer"]:has([data-testid="stTextArea"]) { margin-top: -0.75rem !important; }'
        'div[data-testid="stImage"] { margin-top: 0 !important; margin-bottom: 0 !important; overflow: visible !important; }'
        'div[data-testid="stImage"] > div { margin-bottom: 0 !important; overflow: visible !important; }'
        'div[data-testid="stImage"] img { object-fit: contain !important; max-height: none !important; }'
        'div[data-testid="stTextArea"] { margin-top: 0 !important; margin-bottom: 0.35rem !important; '
        'min-width: 0 !important; max-width: 100% !important; }'
        'div[data-testid="stTextArea"] label { display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important; }'
        'div[data-testid="stTextArea"] textarea { '
        f'font-size: {_fallback_fs}px !important; line-height: 1.2 !important; '
        'font-family: ui-sans-serif, system-ui, sans-serif !important; '
        'padding: 2px 4px !important; box-sizing: border-box !important; '
        'margin: 0 !important; white-space: nowrap !important; '
        'overflow-x: auto !important; overflow-y: hidden !important; '
        'resize: none !important; '
        '}'
        'div[data-testid="stTextInput"] { margin-top: 0 !important; margin-bottom: 0.35rem !important; '
        'min-width: 0 !important; max-width: 100% !important; }'
        'div[data-testid="stTextInput"] > div { margin-bottom: 0 !important; }'
        'div[data-testid="stTextInput"] label { display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important; }'
        'div[data-testid="stTextInput"] input { '
        f'font-size: {_fallback_fs}px !important; line-height: 1.2 !important; '
        'font-family: ui-sans-serif, system-ui, sans-serif !important; '
        'padding: 2px 4px !important; box-sizing: border-box !important; '
        'margin: 0 !important; width: 100% !important; '
        '}'
        '</style>'
        f'<p class="review-page-line">Page {pn_disp}</p>'
        f'<p class="review-line-line">Line {ridx + 1} / {n_review}</p>',
        unsafe_allow_html=True,
    )
    if err_msg:
        st.warning(err_msg)
    elif crop_img is not None:
        st.image(crop_img, use_container_width=True)

    if _multiline:
        st.text_area(
            ' ',
            height=52,
            key=editor_key,
            label_visibility='collapsed',
        )
    else:
        st.text_input(
            ' ',
            key=editor_key,
            label_visibility='collapsed',
        )
    inject_transcription_font_fit()

    c1, c2, c3, c4 = st.columns(4)
    if c1.button('◀ Prev', disabled=ridx <= 0):
        st.session_state.payload['lines'][idx]['text'] = rstrip_line_text(
            st.session_state.get(editor_key, line.get('text', '')),
        )
        st.session_state.line_idx = ridx - 1
        st.rerun()
    if c2.button('Next ▶', disabled=ridx >= n_review - 1):
        st.session_state.payload['lines'][idx]['text'] = rstrip_line_text(
            st.session_state.get(editor_key, line.get('text', '')),
        )
        st.session_state.line_idx = ridx + 1
        st.rerun()
    if c3.button('Save to final JSON'):
        st.session_state.payload['lines'][idx]['text'] = rstrip_line_text(
            st.session_state.get(editor_key, line.get('text', '')),
        )
        save_payload(Path(st.session_state.final_path), st.session_state.payload)
        st.success(f'Wrote {st.session_state.final_path}')
    if c4.button('Reload from raw (discard unsaved final file on disk)'):
        st.session_state.payload = json.loads(
            Path(st.session_state.source_raw_path).read_text(encoding='utf-8'),
        )
        st.session_state.line_idx = 0
        for k in list(st.session_state.keys()):
            if k.startswith('editor_'):
                del st.session_state[k]
        st.session_state.pop('last_editor_idx', None)
        st.rerun()


if __name__ == '__main__':
    main()
