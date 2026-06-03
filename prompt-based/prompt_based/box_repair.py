"""Post-processing repair for pathological line boxes.

A *pathological* line box is one where ≥75 % of its height is nested inside
an adjacent (or near-adjacent) line's box on the same page.  Two root causes:

A) Snap-to-ink failure: PaddleOCR couldn't match the line, snap-to-ink
   locked onto the wrong ink band → tiny box nested inside a neighbour.

B) Shared Paddle detection: two consecutive transcript lines both claimed the
   same Paddle detection because Paddle merged them → heavily overlapping
   large boxes.

``repair_pathological_boxes`` is the public entry point.  It is called by
``transcribe_chunk.py`` automatically after ``assign_paddle_line_boxes`` so
that every new ``*_raw.json`` already has the best achievable box geometry.

The standalone CLI script ``tests/fix_pathological_boxes.py`` uses the same
functions to repair existing JSON files on disk.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PIL import Image

from chunk_lines_model import (
    BOX_2D_NORMALIZED_MAX,
    SNAP_DARK_PIXEL_THRESHOLD,
    SNAP_MIN_BAND_HEIGHT_PX,
    SNAP_MIN_DARK_PIXELS,
    SNAP_MIN_DARK_PIXELS_WINDOW_DIVISOR,
    SNAP_SEARCH_MARGIN_BOX_H_DIVISOR,
    SNAP_SEARCH_MARGIN_MIN_PX,
    SNAP_SMOOTH_RADIUS,
    SNAP_VALLEY_RATIO,
    _moving_average,
    _normalize_box_axis_pair,
    line_box_dict_from_normalized_aabb,
    load_page_images,
)

# ── constants ─────────────────────────────────────────────────────────────────

NESTING_PATHOLOGICAL = 0.75   # fraction of box height that must overlap to flag

# Detection window: how many JSON positions away to check for nesting.
# window=2 catches the canonical failure (line N nested inside line N-2)
# without falsely flagging distant lines that merely have overlapping ranges
# due to shared Paddle detections.
_WINDOW = 2


# ── helpers ───────────────────────────────────────────────────────────────────

def _lb(line: dict) -> dict | None:
    lb = line.get('line_box')
    return lb if isinstance(lb, dict) else None


def _nesting(a: dict, b: dict) -> float:
    """Fraction of *a*'s height that is covered by *b* (0..1)."""
    la, lb = _lb(a), _lb(b)
    if la is None or lb is None:
        return 0.0
    overlap = min(la['ymax'], lb['ymax']) - max(la['ymin'], lb['ymin'])
    if overlap <= 0:
        return 0.0
    return overlap / max(1, la['ymax'] - la['ymin'])


def _norm_box(lb: dict) -> list[int]:
    return [int(lb['ymin']), int(lb['xmin']), int(lb['ymax']), int(lb['xmax'])]


def _snap_below(page_image: Image.Image, anchor_norm: list[int], min_top_px: int) -> dict | None:
    """Snap anchor_norm to the nearest ink band, with the search window floored at min_top_px."""
    g = float(BOX_2D_NORMALIZED_MAX)
    ymin, xmin, ymax, xmax = anchor_norm
    width, height = page_image.size
    left, right = _normalize_box_axis_pair(xmin / g * width, xmax / g * width, width)
    top, bottom = _normalize_box_axis_pair(ymin / g * height, ymax / g * height, height)
    if right <= left or bottom <= top:
        return None

    box_h = max(1, bottom - top)
    anchor_y = (top + bottom) // 2
    margin = max(SNAP_SEARCH_MARGIN_MIN_PX, box_h // SNAP_SEARCH_MARGIN_BOX_H_DIVISOR)
    ideal_top = anchor_y - margin
    search_top = max(min_top_px, ideal_top)
    top_clipped = max(0, search_top - ideal_top)
    search_bottom = min(height, anchor_y + margin + top_clipped)
    if search_bottom <= search_top:
        return None

    region = page_image.crop((left, search_top, right, search_bottom)).convert('L')
    rw, rh = region.size
    if rw <= 0 or rh <= 0:
        return None

    pixels = list(region.getdata())
    row_counts = [0] * rh
    for row in range(rh):
        base = row * rw
        row_counts[row] = sum(1 for col in range(rw) if pixels[base + col] < SNAP_DARK_PIXEL_THRESHOLD)

    smoothed = _moving_average(row_counts, SNAP_SMOOTH_RADIUS)
    min_dark = max(SNAP_MIN_DARK_PIXELS, rw // SNAP_MIN_DARK_PIXELS_WINDOW_DIVISOR)

    peak_idx, peak_score = -1, -1.0
    for idx, score in enumerate(smoothed):
        if score < float(min_dark):
            continue
        dist = abs((search_top + idx) - anchor_y)
        weighted = score - 0.02 * dist
        if weighted > peak_score:
            peak_score = weighted
            peak_idx = idx
    if peak_idx < 0:
        return None

    peak_val = smoothed[peak_idx]
    valley_th = max(1.0, peak_val * SNAP_VALLEY_RATIO)
    band_top = peak_idx
    while band_top > 0 and smoothed[band_top - 1] >= valley_th:
        band_top -= 1
    band_bottom = peak_idx
    while band_bottom + 1 < rh and smoothed[band_bottom + 1] >= valley_th:
        band_bottom += 1

    snapped_top = search_top + band_top
    snapped_bottom = search_top + band_bottom + 1
    if snapped_bottom - snapped_top < SNAP_MIN_BAND_HEIGHT_PX:
        pad = SNAP_MIN_BAND_HEIGHT_PX - (snapped_bottom - snapped_top)
        snapped_top = max(min_top_px, snapped_top - pad // 2)
        snapped_bottom = min(height, snapped_bottom + pad - pad // 2)
    if snapped_bottom <= snapped_top:
        return None

    nymin, nymax = _normalize_box_axis_pair(
        snapped_top / float(height) * g, snapped_bottom / float(height) * g, int(g)
    )
    nxmin, nxmax = _normalize_box_axis_pair(xmin, xmax, int(g))
    return line_box_dict_from_normalized_aabb([nymin, nxmin, nymax, nxmax])


# ── detection ─────────────────────────────────────────────────────────────────

def find_pathological(lines: list[dict], window: int = _WINDOW) -> list[int]:
    """Return sorted indices of lines that are ≥NESTING_PATHOLOGICAL nested in
    any line within *window* positions on the same page."""
    bad: set[int] = set()
    n = len(lines)
    for i in range(n):
        a = lines[i]
        if not isinstance(a, dict):
            continue
        for delta in range(1, window + 1):
            for j in (i - delta, i + delta):
                if not (0 <= j < n):
                    continue
                b = lines[j]
                if not isinstance(b, dict):
                    continue
                if a.get('page_number') != b.get('page_number'):
                    continue
                if _nesting(a, b) >= NESTING_PATHOLOGICAL:
                    bad.add(i)
    return sorted(bad)


# ── overlap guard ─────────────────────────────────────────────────────────────

def _creates_new_overlap(
    snap_lb: dict,
    page_number,
    pos: int,
    page_lines: list[dict],
    window: int = 5,
    repairs: dict | None = None,
) -> bool:
    """Return True if accepting *snap_lb* would create unacceptable overlaps.

    Rules (checked within *window* positions of *pos*):

    1. Reject if snap_lb is ≥75 % nested inside any *preceding* neighbour
       (lower JSON index) — snap went backward into already-assigned territory.
    2. Reject if any *preceding* neighbour is ≥75 % nested inside snap_lb —
       snap result is oversized and covers previously-assigned lines.
    3. Reject if *two or more* following neighbours (higher JSON index) are
       ≥75 % nested inside snap_lb — snap swallows too many future lines.
    4. Reject if snap_lb is ≥75 % nested inside any *following* neighbour that
       was NOT itself repaired — snap overshot into an already-occupied band.

    Exactly one following neighbour sharing the band is allowed (shared-band
    case: text genuinely sits on the same visual line as the next JSON entry).

    *repairs* – optional dict mapping id(line) -> box for lines already
    repaired (e.g. during a sweep); their effective geometry is used instead
    of the original line_box so overlap checks reflect current state.
    """
    def _effective_lb(line):
        if repairs and id(line) in repairs:
            return repairs[id(line)]
        return _lb(line)

    snap_dummy = {'line_box': snap_lb, 'page_number': page_number}
    next_swallowed = 0
    for nbr_pos, nbr in enumerate(page_lines):
        if abs(nbr_pos - pos) > window:
            continue
        if nbr.get('page_number') != page_number:
            continue
        eff_lb = _effective_lb(nbr)
        if eff_lb is None:
            continue
        nbr_eff = {'line_box': eff_lb, 'page_number': page_number}
        if nbr_pos < pos:
            if _nesting(snap_dummy, nbr_eff) >= NESTING_PATHOLOGICAL:
                return True  # rule 1: snap nested in preceding neighbour
            if _nesting(nbr_eff, snap_dummy) >= NESTING_PATHOLOGICAL:
                return True  # rule 2: preceding neighbour absorbed by snap
        else:
            if _nesting(nbr_eff, snap_dummy) >= NESTING_PATHOLOGICAL:
                next_swallowed += 1
                if next_swallowed > 1:
                    return True  # rule 3: snap swallows too many future lines
    return False


# ── per-page repair ───────────────────────────────────────────────────────────

def repair_page(
    page_image: Image.Image,
    page_lines: list[dict],
    pathological_set: set[int],
    g: float = float(BOX_2D_NORMALIZED_MAX),
) -> dict[int, dict]:
    """Repair pathological lines on one page using constrained snap-to-ink.

    Small-box failures (h < 12):
        Re-snap with the search window floored at the bottom of the most recent
        non-pathological preceding line.  Guards: discard if snap is shorter
        than the original, identical to original, or still nested.

    Large shared-detection pairs:
        Re-snap the higher-indexed line below the overlapping preceding line's
        bottom edge.

    Returns ``{id(line): new_line_box_dict}`` for changed lines only.
    """
    SMALL_BOX_H = 12
    page_w, page_h = page_image.size
    repairs: dict[int, dict] = {}

    for pos, line in enumerate(page_lines):
        if id(line) not in pathological_set:
            continue
        lb = _lb(line)
        if lb is None:
            continue

        anchor_norm = _norm_box(lb)
        orig_h = lb['ymax'] - lb['ymin']
        new_lb: dict | None = None

        if orig_h < SMALL_BOX_H:
            # ── Case A: tiny box from bad snap-to-ink ──────────────────────
            prev_bottom: int | None = None
            for prev_line in reversed(page_lines[:pos]):
                if id(prev_line) in pathological_set:
                    continue
                plb = _lb(prev_line)
                if plb is not None:
                    prev_bottom = int(round(plb['ymax'] / g * page_h))
                    break
            if prev_bottom is None:
                continue

            snap_lb = _snap_below(page_image, anchor_norm, prev_bottom)
            if snap_lb is None:
                continue
            new_h = snap_lb['ymax'] - snap_lb['ymin']
            if new_h < orig_h:
                continue
            if snap_lb == lb:
                continue
            if _creates_new_overlap(snap_lb, line.get('page_number'), pos, page_lines):
                continue
            new_lb = snap_lb

        else:
            # ── Case B: large shared-detection box ─────────────────────────
            for prev_line in reversed(page_lines[:pos]):
                plb = repairs.get(id(prev_line)) or _lb(prev_line)
                if plb is None:
                    continue
                if prev_line.get('page_number') != line.get('page_number'):
                    break
                if _nesting({'line_box': lb}, {'line_box': plb}) >= NESTING_PATHOLOGICAL:
                    prev_bottom = int(round(plb['ymax'] / g * page_h))
                    snap_lb = _snap_below(page_image, anchor_norm, prev_bottom)
                    if snap_lb and snap_lb != lb:
                        if not _creates_new_overlap(
                            snap_lb, line.get('page_number'), pos, page_lines
                        ):
                            new_lb = snap_lb
                    break

        if new_lb is not None and new_lb != lb:
            repairs[id(line)] = new_lb

    return repairs


# ── drift sweep ───────────────────────────────────────────────────────────────

def sweep_repair_page(
    page_image: Image.Image,
    page_lines: list[dict],
    start_pos: int,
    prev_bottom_px: int,
    existing_repairs: dict[int, dict],
    g: float = float(BOX_2D_NORMALIZED_MAX),
) -> dict[int, dict]:
    """Top-to-bottom re-snap sweep for drifted lines starting at *start_pos*.

    When Paddle merges consecutive lines, ``assign_paddle_line_boxes`` falls
    behind by N positions and every line from the merge point onward has a box
    pointing to text N lines earlier.  This sweep re-snaps each line to the
    first ink band below the previous line's bottom, correcting the drift.

    *start_pos*      – index in *page_lines* of the first drifted line.
    *prev_bottom_px* – pixel bottom of the last correctly-placed line (floor for
                       the first snap).
    *existing_repairs* – repairs dict already built by ``repair_page``; updated
                         in-place and returned.
    """
    _, page_h = page_image.size
    repairs = existing_repairs
    MIN_SNAP_H = 5   # normalized units; reject degenerate snap results
    pn = page_lines[start_pos].get('page_number') if start_pos < len(page_lines) else None

    # IDs already repaired by Pass 1 (repair_page) – the sweep must NOT re-snap
    # these; they are already in their correct positions.  We do advance the
    # floor from their repaired geometry so subsequent lines are anchored correctly.
    pass1_ids: set[int] = set(existing_repairs.keys())

    # sliding_anchor chains snaps sequentially: each snap's result anchors the
    # next one, so the search window tracks the true ink band progression even
    # when individual lines have drifted original boxes.
    sliding_anchor: list[int] | None = None

    for pos in range(start_pos, len(page_lines)):
        line = page_lines[pos]
        curr_lb = repairs.get(id(line)) or _lb(line)
        if curr_lb is None:
            continue

        # Lines already fixed by Pass 1: just advance the floor/anchor.
        if id(line) in pass1_ids:
            prev_bottom_px = max(prev_bottom_px, int(round(curr_lb['ymax'] / g * page_h)))
            sliding_anchor = _norm_box(curr_lb)
            continue

        # Use sliding anchor when available; fall back to the line's own box so
        # the X column range stays correct even when the Y has drifted.
        if sliding_anchor is not None:
            anchor_norm = [
                sliding_anchor[0],  # ymin from previous snap
                curr_lb['xmin'],    # xmin from this line's column range
                sliding_anchor[2],  # ymax from previous snap
                curr_lb['xmax'],    # xmax from this line's column range
            ]
        else:
            anchor_norm = _norm_box(curr_lb)

        snap_lb = _snap_below(page_image, anchor_norm, prev_bottom_px)

        # If the snap hit a tiny artifact (h < MIN_SNAP_H), skip past it and
        # retry once so we don't miss the real ink band just below.
        if snap_lb is not None and (snap_lb['ymax'] - snap_lb['ymin']) < MIN_SNAP_H:
            retry_floor = int(round(snap_lb['ymax'] / g * page_h)) + 1
            snap_lb = _snap_below(page_image, anchor_norm, retry_floor)

        accepted = False
        if snap_lb is not None and (snap_lb['ymax'] - snap_lb['ymin']) >= MIN_SNAP_H:
            if snap_lb != (repairs.get(id(line)) or _lb(line)):
                repairs[id(line)] = snap_lb
            prev_bottom_px = int(round(snap_lb['ymax'] / g * page_h))
            sliding_anchor = _norm_box(snap_lb)
            accepted = True

        if not accepted:
            # Snap failed; advance the floor but do not update sliding anchor so
            # the next line's anchor stays relative to the last good snap.
            prev_bottom_px = max(prev_bottom_px, int(round(curr_lb['ymax'] / g * page_h)))

    return repairs


# ── public entry point ────────────────────────────────────────────────────────

def repair_pathological_boxes(chunk_path: Path, lines: list[dict]) -> int:
    """Detect and repair pathological line boxes in *lines* in-place.

    Pass 1 – repair_page: fix pathological lines (≥75 % nested) using
    constrained snap-to-ink.

    Pass 2 – sweep_repair_page: when Pass 1 fixes a tiny-box (Case A) trigger,
    lines downstream on the same page often have drifted boxes (pointing to text
    1-3 rows earlier) because Paddle merged consecutive lines.  The sweep re-
    snaps every line from the repaired trigger onward, using the repaired line's
    bottom as the new floor.

    Loads page images from *chunk_path* (PDF).  Mutates ``line['line_box']``
    for repaired lines.  Returns the total number of lines repaired.
    """
    pathological_idxs = find_pathological(lines)
    if not pathological_idxs:
        return 0

    page_images = load_page_images(chunk_path)

    pathological_set_by_page: dict[int, set] = {}
    for idx in pathological_idxs:
        pn = lines[idx].get('page_number')
        if isinstance(pn, int):
            pathological_set_by_page.setdefault(pn, set()).add(id(lines[idx]))

    by_page: dict[int, list[dict]] = defaultdict(list)
    for line in lines:
        pn = line.get('page_number')
        if isinstance(pn, int):
            by_page[pn].append(line)

    total_repairs = 0
    for pn, plines in sorted(by_page.items()):
        if pn not in pathological_set_by_page:
            continue
        if pn < 1 or pn > len(page_images):
            continue

        page_image = page_images[pn - 1]
        _, page_h = page_image.size
        g = float(BOX_2D_NORMALIZED_MAX)

        repairs = repair_page(
            page_image,
            plines,
            pathological_set_by_page[pn],
        )

        # Pass 2: drift sweep.  Paddle merging causes cumulative drift where
        # every line from the merge point onward has a box pointing to text
        # N rows earlier.  The pattern manifests as many tiny-box pathological
        # lines on the same page.  Only sweep when the evidence is strong
        # (≥ 4 tiny-box pathological lines on this page) AND the trigger line
        # is nested inside its NEXT sibling (not a previous one — that would be
        # an isolated backward failure rather than a forward drift).
        SMALL_BOX_H = 12
        DRIFT_TINY_BOX_THRESHOLD = 4
        tiny_box_count = sum(
            1 for ln in plines
            if id(ln) in pathological_set_by_page[pn]
            and ((_lb(ln) or {}).get('ymax', 0) - (_lb(ln) or {}).get('ymin', 0)) < SMALL_BOX_H
        )
        if tiny_box_count >= DRIFT_TINY_BOX_THRESHOLD:
            for pos, line in enumerate(plines):
                if id(line) not in pathological_set_by_page[pn]:
                    continue
                orig_lb = _lb(line)
                if orig_lb is None:
                    continue
                orig_h = orig_lb['ymax'] - orig_lb['ymin']
                if orig_h >= SMALL_BOX_H:
                    continue
                # Confirm forward drift: tiny line nested inside its NEXT sibling.
                if pos + 1 >= len(plines):
                    continue
                next_lb = _lb(plines[pos + 1])
                if next_lb is None:
                    continue
                if _nesting({'line_box': orig_lb}, {'line_box': next_lb}) < NESTING_PATHOLOGICAL:
                    continue
                floor_lb = repairs.get(id(line)) or orig_lb
                prev_bottom_px = int(round(floor_lb['ymax'] / g * page_h))
                sweep_repair_page(page_image, plines, pos + 1, prev_bottom_px, repairs)
                break

        for line in plines:
            if id(line) in repairs:
                line['line_box'] = repairs[id(line)]
                total_repairs += 1

    return total_repairs
