"""
Chunk line transcriptions: paths, JSON payload, page rasters, and box geometry.

No Qt — safe to import from CLI tools or other UIs besides the line reviewer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pdf2image import convert_from_path
from PIL import Image

# Line review rasterizes chunk files with Poppler at this DPI so crop geometry is stable
# across machines. Pass 1 sends the PDF bytes to the model; Gemini's internal render may
# differ slightly — ``box_2d`` crops in the UI are best-effort vs page aspect ratio.
REVIEW_PDF_RASTER_DPI = 200

# Normalized coordinate grid for ``box_2d`` (Pass 1 / model convention).
BOX_2D_NORMALIZED_MAX = 1000

# Padding around the clamped model box for line crops (preview comfort). Too much
# bottom padding pulls in the next line when line spacing is tight.
CROP_PAD_TOP_MAX_PX = 8
CROP_PAD_TOP_BOX_H_DIVISOR = 14

CROP_PAD_BOT_MAX_PX = 12
CROP_PAD_BOT_MIN_PX = 2
CROP_PAD_BOT_BOX_H_DIVISOR = 8
CROP_PAD_BOT_BOX_H_OFFSET = 1

CROP_PAD_X_MAX_PX = 24
CROP_PAD_X_MIN_PX = 1
CROP_PAD_X_BOX_W_DIVISOR = 50
CROP_PAD_X_BOX_W_OFFSET = 1

# Why this "snap-to-ink" layer exists (and why we do not rely on model `box_2d` alone):
#
# In practice, VLMs (Vision Language Models) do not mathematically calculate bounding boxes
# based on image pixels. Instead, they estimate coordinates based on the "patches" of the
# image they process as tokens.
#
# This leads to several common spatial desync issues, especially on dense historical pages:
# 1. The transcription includes more (or fewer) lines of text than there are distinct
#    visible bounding boxes.
# 2. Adjacent lines are merged into a single box, or some line boxes are skipped entirely.
# 3. "Coordinate Drift": As the model moves down the page, small estimation errors compound,
#    causing the returned `box_2d` coordinates to drift significantly below the actual text.
#
# That drift can become severe enough that a mid-page line highlights near unrelated
# content. Therefore, the `box_2d` is an approximate layout signal; it is useful
# as a coarse anchor, but not accurate enough for a deterministic human-in-the-loop UI.
#
# The projection-profile "snap" step addresses this by:
# 1. Using the model's `box_2d` *only* to identify a local vertical search neighborhood.
# 2. Detecting where dark pixels (actual printed ink) are concentrated in that area.
# 3. "Snapping" the vertical bounds to the nearest real text band.
#
# We intentionally keep this Pillow-based and local-windowed:
# - Pillow keeps dependencies light for this toolchain.
# - Local search avoids accidentally snapping to nearby paragraphs or adjacent columns.
# - If the projection profile confidence is weak, callers can fall back to the original box.
#
# During the transcription phase (`transcribe-chunk.py`), this successful snap output
# is written back into the JSON payload's `box_2d` so the reviewer UI code remains simple,
# fast, and perfectly aligned at runtime.
# Snap-to-ink tuning for line-level projection profiling.
SNAP_DARK_PIXEL_THRESHOLD = 175
SNAP_SMOOTH_RADIUS = 2
SNAP_SEARCH_MARGIN_MIN_PX = 28
SNAP_SEARCH_MARGIN_BOX_H_DIVISOR = 1
SNAP_MIN_DARK_PIXELS = 8
SNAP_MIN_DARK_PIXELS_WINDOW_DIVISOR = 80
SNAP_VALLEY_RATIO = 0.35
SNAP_MIN_BAND_HEIGHT_PX = 2

# Prompt-injected markers (not printed on the page).
# Must stay aligned with Pass 1 prompt / any transcribe normalization of line text.
_PAGE_MARKER_PATTERN = re.compile(r'^\s*//\s*Page\s+\d+\s*$', re.IGNORECASE)
# Top-level final JSON flag: true only after explicit "mark review complete" flow.
REVIEW_COMPLETE_KEY = 'review_complete'
# Per-editable-line final JSON flag: whether reviewer text differs from raw baseline.
REVIEWER_CHANGED_KEY = 'reviewer_changed'


def is_injected_page_marker(text: object) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip()
    if t.startswith('{empty}'):
        t = t[len('{empty}') :].strip()
    return bool(_PAGE_MARKER_PATTERN.match(t))


def editable_line_indices(lines: list) -> list[int]:
    """Indices into ``payload['lines']`` for rows that are not synthetic ``// Page N`` markers."""
    out: list[int] = []
    for i, line in enumerate(lines):
        record = LineRecord.from_object(line)
        if record.is_editable():
            out.append(i)
    return out


def list_chunk_filenames(chunk_dir: Path) -> list[str]:
    if not chunk_dir.exists() or not chunk_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in chunk_dir.iterdir()
        if p.is_file() and p.suffix.lower() == '.pdf'
    )


def resolve_chunk_pdf_dir(working_dir: Path, chunk_dir: Path | None) -> Path:
    """Resolve the directory that holds chunk PDFs.

    If ``chunk_dir`` is ``None``, returns ``working_dir / 'chunk-pdfs'``.
    Absolute ``chunk_dir`` is resolved as-is; relative paths join ``working_dir``
    first (same rule as ``--raw-json`` under ``--working-dir``).
    """
    working_dir = working_dir.resolve()
    if chunk_dir is None:
        return working_dir / 'chunk-pdfs'
    p = Path(chunk_dir)
    if p.is_absolute():
        return p.resolve()
    return (working_dir / p).resolve()


@dataclass(frozen=True)
class TranscriptionPaths:
    """Resolved absolute paths for the chunk file and JSON; ``stem`` is chunk filename without .pdf."""

    working_dir: Path
    chunk_path: Path
    raw_path: Path
    final_path: Path
    chunk_name: str
    stem: str


@dataclass
class LineRecord:
    """Typed wrapper around one payload line dictionary."""

    data: dict

    @classmethod
    def from_object(cls, obj: object) -> 'LineRecord':
        if isinstance(obj, dict):
            return cls(obj)
        return cls({})

    def text(self) -> str:
        value = self.data.get('text', '')
        if not isinstance(value, str):
            return ''
        return value.rstrip()

    def set_text(self, value: str) -> None:
        self.data['text'] = value.rstrip()

    def confidence_label(self) -> str | None:
        value = self.data.get('confidence_label')
        if not isinstance(value, str):
            return None
        label = value.strip().lower()
        if label not in {'low', 'medium', 'high'}:
            return None
        return label

    def notes(self) -> str:
        value = self.data.get('notes', '')
        return value if isinstance(value, str) else ''

    def is_editable(self) -> bool:
        return not is_injected_page_marker(self.text())

    def set_reviewer_changed(self, changed: bool) -> None:
        self.data[REVIEWER_CHANGED_KEY] = bool(changed)

    def reviewer_changed(self) -> bool:
        return bool(self.data.get(REVIEWER_CHANGED_KEY, False))


def resolve_transcription_paths_for_chunk(
    working_dir: Path,
    chunk_name: str,
    raw_json: Path | None,
    chunk_pdf_dir: Path | None = None,
    transcriptions_dir: Path | None = None,
) -> TranscriptionPaths | str:
    working_dir = working_dir.resolve()
    chunk_dir = resolve_chunk_pdf_dir(working_dir, chunk_pdf_dir)
    if transcriptions_dir is None:
        resolved_transcriptions_dir = working_dir / 'transcriptions'
    else:
        resolved_transcriptions_dir = (
            transcriptions_dir.resolve()
            if transcriptions_dir.is_absolute()
            else (working_dir / transcriptions_dir).resolve()
        )
    if not chunk_dir.is_dir():
        return (
            f'Expected a chunk PDF directory at {chunk_dir}. '
            'Use --chunk-dir or ensure working-dir contains chunk-pdfs/, '
            'same as transcribe-chunk.py.'
        )

    chunk_name = chunk_name.strip()
    if Path(chunk_name).name != chunk_name:
        return 'Use chunk filename only, not a path.'
    if not chunk_name.lower().endswith('.pdf'):
        return "Chunk filename must end with '.pdf'."

    chunk_path = chunk_dir / chunk_name
    if not chunk_path.is_file():
        return f'Chunk not found: {chunk_path}'

    stem = Path(chunk_name).stem
    if raw_json is not None:
        raw_candidate = raw_json
        raw_path = (
            (working_dir / raw_candidate).resolve()
            if not raw_candidate.is_absolute()
            else raw_candidate.resolve()
        )
    else:
        raw_path = resolved_transcriptions_dir / f'{stem}_raw.json'
    final_path = resolved_transcriptions_dir / f'{stem}_final.json'

    if not raw_path.is_file():
        return f'Raw JSON not found: {raw_path}'

    return TranscriptionPaths(
        working_dir=working_dir,
        chunk_path=chunk_path,
        raw_path=raw_path,
        final_path=final_path,
        chunk_name=chunk_name,
        stem=stem,
    )


def clamp_box_2d_to_pixels(
    box_2d: list,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """Turn a model line box into a PIL crop rectangle in pixel coordinates.

    Pass 1 stores ``box_2d`` as four integers ``[ymin, xmin, ymax, xmax]`` on a
    0–``BOX_2D_NORMALIZED_MAX`` grid aligned to the rasterized page (same aspect as
    ``width`` × ``height``). Review loads pages at ``REVIEW_PDF_RASTER_DPI`` via
    Poppler; the model saw the PDF in Pass 1, so coordinates are best-effort aligned
    by page aspect ratio.

    This function maps that box to ``(left, upper, right, lower)`` for ``Image.crop``,
    where ``right`` and ``lower`` are **exclusive** Pillow indices (see Pillow docs).

    Steps: scale to pixels → clamp to the page (model noise / rounding can sit on or
    outside edges) → ensure a non-empty box → add padding so ascenders, descenders,
    and side bearings are not clipped → clamp again after padding.

    Padding is derived from the **box size**, not the full page. Large bottom padding
    is a trade-off: it helps descenders but can show part of the following line in
    tight historical layouts.
    """
    ymin, xmin, ymax, xmax = (int(box_2d[0]), int(box_2d[1]), int(box_2d[2]), int(box_2d[3]))
    g = float(BOX_2D_NORMALIZED_MAX)

    left = int(round(xmin / g * width))
    upper = int(round(ymin / g * height))
    right = int(round(xmax / g * width))
    lower = int(round(ymax / g * height))

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

    pad_top = min(
        CROP_PAD_TOP_MAX_PX,
        max(0, box_h // CROP_PAD_TOP_BOX_H_DIVISOR),
    )
    pad_bot = min(
        CROP_PAD_BOT_MAX_PX,
        max(
            CROP_PAD_BOT_MIN_PX,
            box_h // CROP_PAD_BOT_BOX_H_DIVISOR + CROP_PAD_BOT_BOX_H_OFFSET,
        ),
    )
    pad_x = min(
        CROP_PAD_X_MAX_PX,
        max(
            CROP_PAD_X_MIN_PX,
            box_w // CROP_PAD_X_BOX_W_DIVISOR + CROP_PAD_X_BOX_W_OFFSET,
        ),
    )

    left = max(0, left - pad_x)
    upper = max(0, upper - pad_top)
    right = min(width, right + pad_x)
    lower = min(height, lower + pad_bot)

    if right <= left:
        right = min(width, left + 1)
    if lower <= upper:
        lower = min(height, upper + 1)
    return left, upper, right, lower


def _parse_box_2d(box_2d: object) -> tuple[float, float, float, float] | None:
    # Keep this permissive (float parse) because upstream model output can drift
    # between ints/floats/strings depending on provider behavior.
    if not isinstance(box_2d, list) or len(box_2d) != 4:
        return None
    try:
        ymin = float(box_2d[0])
        xmin = float(box_2d[1])
        ymax = float(box_2d[2])
        xmax = float(box_2d[3])
    except (TypeError, ValueError):
        return None
    return ymin, xmin, ymax, xmax


def _normalize_box_axis_pair(a: float, b: float, axis_max: int) -> tuple[int, int]:
    lo = int(round(min(a, b)))
    hi = int(round(max(a, b)))
    lo = max(0, min(lo, axis_max))
    hi = max(0, min(hi, axis_max))
    if hi <= lo:
        hi = min(axis_max, lo + 1)
    return lo, hi


def _moving_average(values: list[int], radius: int) -> list[float]:
    if radius <= 0 or not values:
        return [float(v) for v in values]
    out: list[float] = []
    n = len(values)
    for idx in range(n):
        lo = max(0, idx - radius)
        hi = min(n, idx + radius + 1)
        window = values[lo:hi]
        out.append(float(sum(window)) / float(len(window)))
    return out


def snap_box_2d_to_ink(page_image: Image.Image, box_2d: object) -> list[int] | None:
    """Snap model ``box_2d`` to nearest visible text band using a local projection profile."""
    parsed = _parse_box_2d(box_2d)
    if parsed is None:
        return None
    ymin, xmin, ymax, xmax = parsed
    width, height = page_image.size
    if width <= 0 or height <= 0:
        return None

    left, right = _normalize_box_axis_pair(
        xmin / float(BOX_2D_NORMALIZED_MAX) * width,
        xmax / float(BOX_2D_NORMALIZED_MAX) * width,
        width,
    )
    top, bottom = _normalize_box_axis_pair(
        ymin / float(BOX_2D_NORMALIZED_MAX) * height,
        ymax / float(BOX_2D_NORMALIZED_MAX) * height,
        height,
    )
    if right <= left or bottom <= top:
        return None

    box_h = max(1, bottom - top)
    anchor_y = (top + bottom) // 2
    # Search locally around the model anchor. Keeping this local avoids snapping to
    # neighboring paragraphs when the page has dense text.
    search_margin = max(SNAP_SEARCH_MARGIN_MIN_PX, box_h // SNAP_SEARCH_MARGIN_BOX_H_DIVISOR)
    search_top = max(0, anchor_y - search_margin)
    search_bottom = min(height, anchor_y + search_margin)
    if search_bottom <= search_top:
        return None

    # Evaluate darkness only in the model x-span to avoid neighboring columns.
    region = page_image.crop((left, search_top, right, search_bottom)).convert('L')
    region_w, region_h = region.size
    if region_w <= 0 or region_h <= 0:
        return None

    pixels = list(region.getdata())
    row_counts: list[int] = [0] * region_h
    for row in range(region_h):
        base = row * region_w
        cnt = 0
        for col in range(region_w):
            if pixels[base + col] < SNAP_DARK_PIXEL_THRESHOLD:
                cnt += 1
        row_counts[row] = cnt

    # Smooth out per-row noise (serifs/scan speckles) before finding peaks.
    smoothed = _moving_average(row_counts, SNAP_SMOOTH_RADIUS)
    min_dark_pixels = max(SNAP_MIN_DARK_PIXELS, region_w // SNAP_MIN_DARK_PIXELS_WINDOW_DIVISOR)

    peak_idx = -1
    peak_score = -1.0
    for idx, score in enumerate(smoothed):
        if score < float(min_dark_pixels):
            continue
        # Prefer bands near the original anchor when multiple rows are similarly dark.
        dist = abs((search_top + idx) - anchor_y)
        weighted = score - (0.02 * float(dist))
        if weighted > peak_score:
            peak_score = weighted
            peak_idx = idx
    if peak_idx < 0:
        return None

    peak_value = smoothed[peak_idx]
    # Use a relative valley threshold so band growth adapts across faint/dark scans.
    valley_threshold = max(1.0, peak_value * SNAP_VALLEY_RATIO)

    band_top = peak_idx
    while band_top > 0 and smoothed[band_top - 1] >= valley_threshold:
        band_top -= 1
    band_bottom = peak_idx
    while band_bottom + 1 < region_h and smoothed[band_bottom + 1] >= valley_threshold:
        band_bottom += 1

    snapped_top_px = search_top + band_top
    snapped_bottom_px = search_top + band_bottom + 1
    if snapped_bottom_px - snapped_top_px < SNAP_MIN_BAND_HEIGHT_PX:
        pad = SNAP_MIN_BAND_HEIGHT_PX - (snapped_bottom_px - snapped_top_px)
        snapped_top_px = max(0, snapped_top_px - (pad // 2))
        snapped_bottom_px = min(height, snapped_bottom_px + (pad - (pad // 2)))
    if snapped_bottom_px <= snapped_top_px:
        return None

    nymin, nymax = _normalize_box_axis_pair(
        (snapped_top_px / float(height)) * BOX_2D_NORMALIZED_MAX,
        (snapped_bottom_px / float(height)) * BOX_2D_NORMALIZED_MAX,
        BOX_2D_NORMALIZED_MAX,
    )
    nxmin, nxmax = _normalize_box_axis_pair(xmin, xmax, BOX_2D_NORMALIZED_MAX)
    return [nymin, nxmin, nymax, nxmax]


def rstrip_line_text(value: object) -> object:
    if isinstance(value, str):
        return value.rstrip()
    return value


def line_text(line: dict) -> str:
    return LineRecord.from_object(line).text()


def load_page_images(pdf_path: Path) -> list[Image.Image]:
    """Rasterize each PDF page to a PIL image at :data:`REVIEW_PDF_RASTER_DPI`."""
    return convert_from_path(str(pdf_path), dpi=REVIEW_PDF_RASTER_DPI)


def load_payload(raw_path: Path, final_path: Path) -> dict:
    # Prefer final when it exists so reopening the chunk loads saved review work, not stale raw.
    if final_path.exists():
        return json.loads(final_path.read_text(encoding='utf-8'))
    return json.loads(raw_path.read_text(encoding='utf-8'))


def load_raw_payload(raw_path: Path) -> dict:
    return json.loads(raw_path.read_text(encoding='utf-8'))


def save_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def crop_for_line(
    page_images: list[Image.Image],
    line: dict,
) -> tuple[Image.Image | None, str | None]:
    """Build a PIL crop for one payload line, or return (None, error_message)."""
    page_number = line.get('page_number')
    box_2d = line.get('box_2d')
    n_pages = len(page_images)

    if not isinstance(page_number, int) or page_number < 1:
        return None, f'Invalid page_number: {page_number!r}'
    if page_number > n_pages:
        return None, (
            f'page_number {page_number} is out of range '
            f'(chunk has {n_pages} page(s)).'
        )
    if not isinstance(box_2d, list) or len(box_2d) != 4:
        return None, f'Invalid box_2d: {box_2d!r}'

    page_img = page_images[page_number - 1]
    w, h = page_img.size
    left, upper, right, lower = clamp_box_2d_to_pixels(box_2d, w, h)
    return page_img.crop((left, upper, right, lower)), None


def normalized_center_y_for_line(line: dict) -> float | None:
    """Return line vertical center on the 0-1000 grid, or ``None`` if invalid."""
    box_2d = line.get('box_2d')
    if not isinstance(box_2d, list) or len(box_2d) != 4:
        return None
    try:
        ymin = float(box_2d[0])
        ymax = float(box_2d[2])
    except (TypeError, ValueError):
        return None
    return max(0.0, min(float(BOX_2D_NORMALIZED_MAX), (ymin + ymax) / 2.0))


def line_confidence_label(line: dict) -> str | None:
    return LineRecord.from_object(line).confidence_label()


def line_notes(line: dict) -> str:
    return LineRecord.from_object(line).notes()


class ChunkLinesSession:
    """Mutable state for one loaded chunk: transcription JSON, page rasters, editable-line cursor."""

    def __init__(self) -> None:
        self.paths: TranscriptionPaths | None = None
        self.page_images: list[Image.Image] = []
        self.payload: dict = {}
        self.lines: list = []
        self.line_records: list[LineRecord] = []
        self.editable_indices: list[int] = []
        self.editable_ridx: int = 0
        self.dirty: bool = False
        self.source_raw_path: str = ''
        self.original_editable_texts: dict[int, str] = {}

    @property
    def is_loaded(self) -> bool:
        return self.paths is not None

    def load_chunk(
        self,
        working_dir: Path,
        chunk_name: str,
        raw_json_cli: Path | None,
        chunk_pdf_dir: Path | None = None,
        transcriptions_dir: Path | None = None,
    ) -> str | None:
        """Load chunk file + JSON into this session. Returns an error message, or ``None`` on success."""
        resolved = resolve_transcription_paths_for_chunk(
            working_dir,
            chunk_name,
            raw_json_cli,
            chunk_pdf_dir,
            transcriptions_dir,
        )
        if isinstance(resolved, str):
            return resolved
        # On failure below (or invalid payload), return without mutating ``self`` so a
        # previously loaded chunk remains active (do not clear the session at the start).
        try:
            page_images = load_page_images(resolved.chunk_path)
            payload = load_payload(resolved.raw_path, resolved.final_path)
            raw_payload = load_raw_payload(resolved.raw_path)
        except Exception as exc:
            return f'Could not read chunk or JSON. {exc}'

        lines = payload.get('lines')
        if not isinstance(lines, list) or not lines:
            return 'Invalid payload: missing or empty "lines"'

        indices = editable_line_indices(lines)
        if not indices:
            return (
                'No editable lines: every entry looks like a synthetic '
                '`// Page N` marker.'
            )

        self.paths = resolved
        self.page_images = page_images
        self.payload = payload
        self.lines = lines
        self.line_records = [LineRecord.from_object(line) for line in lines]
        self.editable_indices = indices
        self.editable_ridx = 0
        self.dirty = False
        self.source_raw_path = str(resolved.raw_path)
        self._init_review_metadata(raw_payload)
        return None

    def _init_review_metadata(self, raw_payload: dict) -> None:
        if not isinstance(self.payload, dict):
            self.payload = {}
        self.payload.setdefault(REVIEW_COMPLETE_KEY, False)

        raw_lines = raw_payload.get('lines')
        if not isinstance(raw_lines, list):
            raw_lines = []

        self.original_editable_texts = {}
        for idx in self.editable_indices:
            if idx < len(raw_lines) and isinstance(raw_lines[idx], dict):
                baseline = LineRecord.from_object(raw_lines[idx]).text()
            else:
                baseline = self.line_records[idx].text()
            self.original_editable_texts[idx] = baseline
        self.refresh_reviewer_changed_flags()

    def clamp_editable_ridx(self) -> None:
        n = len(self.editable_indices)
        if n == 0:
            self.editable_ridx = 0
        else:
            self.editable_ridx = max(0, min(self.editable_ridx, n - 1))

    def line_at_editable_ridx(self) -> dict:
        self.clamp_editable_ridx()
        idx = self.editable_indices[self.editable_ridx]
        return self.lines[idx]

    def crop_for_current_editable(self) -> tuple[Image.Image | None, str | None]:
        self.clamp_editable_ridx()
        line = self.line_at_editable_ridx()
        return crop_for_line(self.page_images, line)

    def commit_editable_text(self, text: str) -> None:
        """Write ``text`` into ``payload['lines']`` for the current editable index."""
        self.clamp_editable_ridx()
        idx = self.editable_indices[self.editable_ridx]
        self.line_records[idx].set_text(text)

    def save_to_final(self) -> None:
        if self.paths is None:
            return
        save_payload(self.paths.final_path, self.payload)

    def is_review_complete(self) -> bool:
        return bool(self.payload.get(REVIEW_COMPLETE_KEY, False))

    def set_review_complete(self, value: bool) -> None:
        self.payload[REVIEW_COMPLETE_KEY] = bool(value)

    def refresh_reviewer_changed_flags(self) -> None:
        for idx in self.editable_indices:
            baseline = self.original_editable_texts.get(idx, '')
            current = self.line_records[idx].text()
            self.line_records[idx].set_reviewer_changed(current != baseline)

    def low_confidence_unchanged_stats(self) -> tuple[int, int]:
        total_low = 0
        unchanged_low = 0
        for idx in self.editable_indices:
            line = self.line_records[idx]
            if line.confidence_label() != 'low':
                continue
            total_low += 1
            if not line.reviewer_changed():
                unchanged_low += 1
        return unchanged_low, total_low

    def reload_from_raw_disk(self) -> str | None:
        """Reload ``payload`` from the raw JSON path on disk. Returns error or ``None``."""
        raw = Path(self.source_raw_path)
        previous_lines = self.lines if isinstance(self.lines, list) else []
        previous_records = [LineRecord.from_object(line) for line in previous_lines]
        self.payload = json.loads(raw.read_text(encoding='utf-8'))
        self.lines = self.payload['lines']
        self.line_records = [LineRecord.from_object(line) for line in self.lines]
        self._restore_confidence_metadata_from_previous(previous_records)
        self.editable_indices = editable_line_indices(self.lines)
        if not self.editable_indices:
            return 'No editable lines after reload.'
        self.editable_ridx = 0
        self.dirty = False
        self.payload[REVIEW_COMPLETE_KEY] = False
        self._init_review_metadata(self.payload)
        return None

    def _restore_confidence_metadata_from_previous(self, previous_lines: list[LineRecord]) -> None:
        """Keep confidence warnings stable across raw reloads."""
        # First pass: restore by absolute line index when layouts match.
        for idx, line in enumerate(self.line_records):
            if idx >= len(previous_lines):
                continue
            prev_line = previous_lines[idx]
            prev_label = prev_line.confidence_label()
            if prev_label is not None:
                line.data['confidence_label'] = prev_label
            line.data['notes'] = prev_line.notes()

        # Second pass: restore by editable-line order to absorb marker/index drift.
        prev_editable = [i for i, record in enumerate(previous_lines) if record.is_editable()]
        curr_editable = [i for i, record in enumerate(self.line_records) if record.is_editable()]
        for ridx, curr_idx in enumerate(curr_editable):
            if ridx >= len(prev_editable):
                break
            curr_line = self.line_records[curr_idx]
            prev_line = previous_lines[prev_editable[ridx]]
            prev_label = prev_line.confidence_label()
            if prev_label is not None:
                curr_line.data['confidence_label'] = prev_label
            curr_line.data['notes'] = prev_line.notes()
