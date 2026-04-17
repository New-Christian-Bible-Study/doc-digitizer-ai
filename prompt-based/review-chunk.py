#!/usr/bin/env python3
"""Line-by-line transcription review with approximate image sync."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from PIL import Image

from chunk_lines_model import (
    BOX_2D_NORMALIZED_MAX,
    ChunkLinesSession,
    line_confidence_label,
    line_notes,
    list_chunk_filenames,
    normalized_center_y_for_line,
    resolve_chunk_pdf_dir,
)

CHUNK_STATE_FILENAME = '.chunk-state.json'


def pil_to_qpixmap(im: Image.Image) -> QPixmap:
    if im.mode != 'RGB':
        im = im.convert('RGB')
    w, h = im.size
    bpl = 3 * w
    buf = im.tobytes('raw', 'RGB')
    qimg = QImage(buf, w, h, bpl, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _review_app_icon() -> QIcon:
    """Window icon: ``icons/review-chunk-lines.png`` beside this script (optional file)."""
    p = Path(__file__).resolve().parent / 'icons' / 'review-chunk-lines.png'
    if p.is_file():
        return QIcon(str(p))
    return QIcon()


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(
        description='Review and correct per-line transcriptions for a chunk.',
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
        '--transcriptions-dir',
        type=Path,
        default=None,
        help=(
            'Directory containing chunk transcription JSON files '
            '(default: working-dir/transcriptions). Relative paths are '
            'resolved under working-dir.'
        ),
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


def _has_review_chunk_state(root: Path) -> bool:
    return (root / CHUNK_STATE_FILENAME).is_file()


def _pick_transcription_root_with_dialog(default_root: Path) -> Path | None:
    if not _can_show_transcription_root_dialog():
        return None

    while True:
        dialog = QFileDialog(
            None,
            f'Select transcription root containing {CHUNK_STATE_FILENAME}',
            str(default_root),
        )
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        # Avoid native platform dialog integration, which can segfault on some Linux setups.
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        if dialog.exec() != QFileDialog.Accepted:
            return None
        selected_paths = dialog.selectedFiles()
        if not selected_paths:
            return None
        candidate = Path(selected_paths[0]).resolve()

        if not candidate.is_dir():
            print(f'Not a directory: {candidate}', file=sys.stderr)
            continue
        if not _has_review_chunk_state(candidate):
            print(
                f'Missing {CHUNK_STATE_FILENAME} in {candidate}',
                file=sys.stderr,
            )
            continue
        return candidate


def _can_show_transcription_root_dialog() -> bool:
    if not sys.stdin.isatty() and not sys.stdout.isatty():
        return False
    if not sys.platform.startswith('linux'):
        return True

    # Guard against common invalid values that can crash Qt initialization.
    display = (os.environ.get('DISPLAY') or '').strip()
    wayland = (os.environ.get('WAYLAND_DISPLAY') or '').strip()
    if not display and not wayland:
        return False
    invalid_display_tokens = {'$0', '0', 'false', 'none', 'null'}
    if display.lower() in invalid_display_tokens:
        return False
    if wayland.lower() in invalid_display_tokens:
        return False
    return True


class ReviewMainWindow(QMainWindow):
    """Dual-pane review UI with approximate page sync."""

    def __init__(
        self,
        working_dir: Path,
        chunk_pdf_dir: Path,
        chunk_filenames: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._working_dir = working_dir.resolve()
        self._chunk_pdf_dir = chunk_pdf_dir.resolve()
        self._chunk_filenames = chunk_filenames
        self._line_edits: list[FocusLineEdit] = []
        self._line_badges: list[QLabel] = []
        self._line_notes: list[QLabel] = []
        self._line_rows: list[QWidget] = []
        self._line_warning_labels: list[QLabel | None] = []
        self._line_original_texts: list[str] = []
        self._line_conf_labels: list[str] = []
        self._row_indices: list[int] = []
        self._page_pixmap: QPixmap | None = None
        self._last_center_y: float | None = None
        self._zoom_factor: float = 1.0
        self._fit_scale: float = 1.0

        root = self._init_window_shell()
        self._add_chunk_row(root, chunk_filenames)
        self._add_paths_row(root)
        self._add_error_label(root)
        self._add_dual_pane(root)
        self._add_navigation_button_row(root)
        self._add_zoom_shortcuts()

        self.set_review_controls_enabled(False)

    def _init_window_shell(self) -> QVBoxLayout:
        """Title, icon, default size, central widget, and root ``QVBoxLayout``."""
        self.setWindowTitle('Line review (Approximate Sync)')
        _ic = _review_app_icon()
        if not _ic.isNull():
            self.setWindowIcon(_ic)
        self.resize(880, 480)

        central = QWidget()
        self.setCentralWidget(central)
        central.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)
        return root

    def _add_chunk_row(self, root: QVBoxLayout, chunk_filenames: list[str]):
        """Dropdown listing ``chunk-pdfs/*.pdf`` so the user picks the active chunk."""
        chunk_row = QHBoxLayout()
        chunk_row.setSpacing(8)
        chunk_row.addWidget(QLabel('Chunk'))
        self._chunk_combo = QComboBox()
        self._chunk_combo.setMinimumWidth(280)
        self._chunk_combo.addItems(chunk_filenames)
        chunk_row.addWidget(self._chunk_combo)
        chunk_row.addStretch()
        root.addLayout(chunk_row)

    def _add_paths_row(self, root: QVBoxLayout):
        row = QHBoxLayout()
        row.addWidget(QLabel('Raw:'))
        self._raw_path_lbl = QLabel('—')
        row.addWidget(self._raw_path_lbl)
        row.addSpacing(14)
        row.addWidget(QLabel('Final:'))
        self._final_path_lbl = QLabel('—')
        row.addWidget(self._final_path_lbl)
        row.addStretch()
        root.addLayout(row)

    def _add_error_label(self, root: QVBoxLayout):
        """Amber text for non-fatal issues (e.g. crop generation failed)."""
        self._err_lbl = QLabel()
        self._err_lbl.setStyleSheet('color: #b06000;')
        self._err_lbl.setWordWrap(True)
        self._err_lbl.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        root.addWidget(self._err_lbl, alignment=Qt.AlignmentFlag.AlignLeft)

    def _add_dual_pane(self, root: QVBoxLayout):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        self._scene = QGraphicsScene(self)
        self._page_item = QGraphicsPixmapItem()
        self._scene.addItem(self._page_item)
        self._active_line_box_item = QGraphicsRectItem()
        self._active_line_box_item.setPen(QPen(QColor(61, 149, 255, 230), 2))
        self._active_line_box_item.setBrush(QColor(61, 149, 255, 35))
        self._active_line_box_item.setZValue(5)
        self._active_line_box_item.setVisible(False)
        self._scene.addItem(self._active_line_box_item)
        self._page_view = QGraphicsView(self._scene)
        self._page_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._page_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        splitter.addWidget(self._page_view)

        self._line_scroll = QScrollArea()
        self._line_scroll.setWidgetResizable(True)
        self._line_host = QWidget()
        self._line_layout = QVBoxLayout(self._line_host)
        self._line_layout.setContentsMargins(2, 2, 2, 2)
        self._line_layout.setSpacing(2)
        self._line_layout.addStretch()
        self._line_scroll.setWidget(self._line_host)
        splitter.addWidget(self._line_scroll)
        splitter.setSizes([550, 550])
        splitter.splitterMoved.connect(self._on_splitter_moved)

    def _add_navigation_button_row(self, root: QVBoxLayout):
        """Line navigation and persistence actions for the current chunk."""
        btn_row = QHBoxLayout()
        self._btn_prev = QPushButton('◀ Prev')
        self._btn_next = QPushButton('Next ▶')
        self._btn_next_flagged = QPushButton('Next flagged')
        self._btn_save = QPushButton('Save to final')
        self._btn_complete_review = QPushButton('Mark review complete')
        self._btn_reload = QPushButton('Reload from raw')
        btn_row.addWidget(self._btn_prev)
        btn_row.addWidget(self._btn_next)
        btn_row.addWidget(self._btn_next_flagged)
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_complete_review)
        btn_row.addWidget(self._btn_reload)
        btn_row.addStretch()
        root.addLayout(btn_row)

    def _add_zoom_shortcuts(self) -> None:
        zoom_in = QShortcut('Ctrl+=', self)
        zoom_in.activated.connect(lambda: self.adjust_zoom(1.15))
        zoom_in2 = QShortcut('Ctrl++', self)
        zoom_in2.activated.connect(lambda: self.adjust_zoom(1.15))
        zoom_out = QShortcut('Ctrl+-', self)
        zoom_out.activated.connect(lambda: self.adjust_zoom(1 / 1.15))
        zoom_reset = QShortcut('Ctrl+0', self)
        zoom_reset.activated.connect(self.reset_zoom_to_fit)

    @property
    def working_dir(self) -> Path:
        return self._working_dir

    @property
    def chunk_pdf_dir(self) -> Path:
        return self._chunk_pdf_dir

    @property
    def chunk_filenames(self) -> list[str]:
        return self._chunk_filenames

    @property
    def chunk_combo(self) -> QComboBox:
        return self._chunk_combo

    def connect_controller_signals(self, ctrl: 'ReviewChunkLinesController') -> None:
        self._chunk_combo.currentIndexChanged.connect(ctrl._on_chunk_combo_index_changed)
        self._btn_prev.clicked.connect(ctrl._on_prev)
        self._btn_next.clicked.connect(ctrl._on_next)
        self._btn_next_flagged.clicked.connect(ctrl._on_next_flagged)
        self._btn_save.clicked.connect(ctrl._on_save)
        self._btn_complete_review.clicked.connect(ctrl._on_complete_review)
        self._btn_reload.clicked.connect(ctrl._on_reload)

    def sync_combo_to_chunk_name(self, chunk_name: str | None) -> None:
        if chunk_name is None:
            return
        idx = self._chunk_combo.findText(chunk_name)
        if idx >= 0:
            self._chunk_combo.blockSignals(True)
            self._chunk_combo.setCurrentIndex(idx)
            self._chunk_combo.blockSignals(False)

    def set_path_labels(self, raw_name: str, final_name: str) -> None:
        self._raw_path_lbl.setText(raw_name)
        self._final_path_lbl.setText(final_name)

    def set_review_controls_enabled(self, enabled: bool) -> None:
        self._btn_prev.setEnabled(enabled)
        self._btn_next.setEnabled(enabled)
        self._btn_next_flagged.setEnabled(enabled)
        self._btn_save.setEnabled(enabled)
        self._btn_complete_review.setEnabled(enabled)
        self._btn_reload.setEnabled(enabled)

    def clear_line_rows(self) -> None:
        while self._line_layout.count() > 1:
            item = self._line_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._line_edits = []
        self._line_badges = []
        self._line_notes = []
        self._line_rows = []
        self._line_warning_labels = []
        self._line_original_texts = []
        self._line_conf_labels = []
        self._row_indices = []

    def populate_lines(self, session: ChunkLinesSession, ctrl: 'ReviewChunkLinesController') -> None:
        self.clear_line_rows()
        for ridx, payload_idx in enumerate(session.editable_indices):
            line = session.lines[payload_idx]
            conf = line_confidence_label(line) or 'high'
            notes_text = line_notes(line).strip()
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(2, 2, 2, 2)
            row_layout.setSpacing(2)
            badge = QLabel(conf.upper())

            # Keep high-confidence rows visually quiet. For medium/low rows, put a
            # clear warning line above the editor with confidence + reason.
            if conf != 'high':
                warn = QLabel(
                    f'Confidence: {conf.upper()}'
                    + (f' - {notes_text}' if notes_text else ' - No reason provided')
                )
                warn.setWordWrap(True)
                warn.setStyleSheet('QLabel { font-weight: 700; margin-bottom: 1px; }')
                row_layout.addWidget(warn)
            else:
                warn = None

            edit = FocusLineEdit(ridx)
            edit.setStyleSheet('QLineEdit { padding-top: 2px; padding-bottom: 2px; }')
            original_text = (
                line.get('text', '') if isinstance(line.get('text', ''), str) else ''
            ).rstrip()
            edit.setText(original_text)
            edit.textChanged.connect(ctrl._on_text_changed)
            edit.textChanged.connect(lambda _text, i=ridx: self._on_editor_text_changed(i))
            edit.focused.connect(ctrl._on_row_focused)
            row_layout.addWidget(edit)
            self._apply_row_confidence_style(row, badge, conf)

            self._line_layout.insertWidget(self._line_layout.count() - 1, row)
            self._line_rows.append(row)
            self._line_edits.append(edit)
            self._line_badges.append(badge)
            self._line_notes.append(QLabel(''))
            self._line_warning_labels.append(warn)
            self._line_original_texts.append(original_text)
            self._line_conf_labels.append(conf)
            self._row_indices.append(payload_idx)

    def _apply_row_confidence_style(self, row: QWidget, badge: QLabel, label: str | None) -> None:
        if label == 'low':
            row.setStyleSheet('QWidget { border: 1px solid #6f2e2e; border-radius: 5px; }')
            badge.setStyleSheet('QLabel { color: #cf3a3a; font-weight: 700; }')
        elif label == 'medium':
            row.setStyleSheet('QWidget { border: 1px solid #796324; border-radius: 5px; }')
            badge.setStyleSheet('QLabel { color: #9d7d1d; font-weight: 700; }')
        else:
            row.setStyleSheet('')
            badge.setStyleSheet('QLabel { color: #cfcfcf; font-weight: 600; }')

    def set_active_row(self, ridx: int) -> None:
        if 0 <= ridx < len(self._line_edits):
            self._line_edits[ridx].setFocus()
            self._line_edits[ridx].selectAll()
            self._line_scroll.ensureWidgetVisible(self._line_edits[ridx], 0, 100)

    def set_page_image(self, page_image: Image.Image | None) -> None:
        if page_image is None:
            self._page_item.setPixmap(QPixmap())
            self._page_pixmap = None
            self._active_line_box_item.setVisible(False)
            return
        self._page_pixmap = pil_to_qpixmap(page_image)
        self._page_item.setPixmap(self._page_pixmap)
        self._scene.setSceneRect(self._page_item.boundingRect())
        # Preserve current zoom when focus changes lines/pages; only Ctrl+0 resets.
        self._refit_and_restore_focus_center()

    def center_page_on_normalized_y(self, normalized_y: float) -> None:
        if self._page_pixmap is None or self._page_pixmap.isNull():
            return
        # Usually ``(ymin+ymax)/2`` from ``normalized_center_y_for_line`` (0..1000 grid).
        self._last_center_y = normalized_y
        page_h = self._page_pixmap.height()
        target_y = int((normalized_y / float(BOX_2D_NORMALIZED_MAX)) * page_h)
        self._smooth_center_on_y(target_y)

    def show_active_line_box(self, line: dict) -> None:
        # Overlay padding is for human-friendly hints only. Crop padding for PIL lives
        # in ``chunk_lines_model.clamp_box_2d_to_pixels`` (used by ``crop_for_line``).
        if self._page_pixmap is None or self._page_pixmap.isNull():
            self._active_line_box_item.setVisible(False)
            return
        box_2d = line.get('box_2d')
        if not isinstance(box_2d, list) or len(box_2d) != 4:
            self._active_line_box_item.setVisible(False)
            return

        try:
            ymin = float(box_2d[0])
            xmin = float(box_2d[1])
            ymax = float(box_2d[2])
            xmax = float(box_2d[3])
        except (TypeError, ValueError):
            self._active_line_box_item.setVisible(False)
            return

        page_w = self._page_pixmap.width()
        page_h = self._page_pixmap.height()
        g = float(BOX_2D_NORMALIZED_MAX)

        left = int(round((xmin / g) * page_w))
        right = int(round((xmax / g) * page_w))
        top = int(round((ymin / g) * page_h))
        bottom = int(round((ymax / g) * page_h))

        left = max(0, min(left, page_w))
        right = max(0, min(right, page_w))
        top = max(0, min(top, page_h))
        bottom = max(0, min(bottom, page_h))

        if right <= left:
            right = min(page_w, left + 1)
        if bottom <= top:
            bottom = min(page_h, top + 1)

        # Expand the visual hint box (especially vertically) to absorb model drift.
        box_h = bottom - top
        box_w = right - left
        pad_y = max(6, min(28, box_h // 2))
        pad_x = max(3, min(16, box_w // 8))

        left = max(0, left - pad_x)
        right = min(page_w, right + pad_x)
        top = max(0, top - pad_y)
        bottom = min(page_h, bottom + pad_y)

        self._active_line_box_item.setRect(left, top, max(1, right - left), max(1, bottom - top))
        self._active_line_box_item.setVisible(True)

    def _smooth_center_on_y(self, y: int) -> None:
        current_center = self._page_view.mapToScene(self._page_view.viewport().rect().center())
        self._page_view.centerOn(current_center.x(), y)

    def _fit_page_to_pane_width(self) -> None:
        if self._page_pixmap is None or self._page_pixmap.isNull():
            return
        viewport_w = max(1, self._page_view.viewport().width())
        pixmap_w = max(1, self._page_pixmap.width())
        self._fit_scale = viewport_w / float(pixmap_w)
        scale = self._fit_scale * self._zoom_factor
        self._page_view.resetTransform()
        self._page_view.scale(scale, scale)

    def adjust_zoom(self, factor: float) -> None:
        if self._page_pixmap is None or self._page_pixmap.isNull():
            return
        self._zoom_factor = max(0.25, min(5.0, self._zoom_factor * factor))
        self._refit_and_restore_focus_center()

    def reset_zoom_to_fit(self) -> None:
        self._zoom_factor = 1.0
        self._refit_and_restore_focus_center()

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        self._refit_and_restore_focus_center()

    def _refit_and_restore_focus_center(self) -> None:
        self._fit_page_to_pane_width()
        if self._last_center_y is not None:
            self.center_page_on_normalized_y(self._last_center_y)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._refit_and_restore_focus_center)

    def line_text(self, ridx: int) -> str:
        if 0 <= ridx < len(self._line_edits):
            return self._line_edits[ridx].text()
        return ''

    def set_prev_next_enabled(self, prev_enabled: bool, next_enabled: bool) -> None:
        self._btn_prev.setEnabled(prev_enabled)
        self._btn_next.setEnabled(next_enabled)

    def _on_editor_text_changed(self, ridx: int) -> None:
        if not (0 <= ridx < len(self._line_edits)):
            return
        conf = self._line_conf_labels[ridx] if ridx < len(self._line_conf_labels) else 'high'
        if conf == 'high':
            return
        warn = (
            self._line_warning_labels[ridx]
            if ridx < len(self._line_warning_labels)
            else None
        )
        if warn is None:
            return
        current_text = self._line_edits[ridx].text().rstrip()
        changed = current_text != self._line_original_texts[ridx]
        if changed:
            warn.setStyleSheet(
                'QLabel { font-weight: 700; text-decoration: line-through; opacity: 0.75; margin-bottom: 1px; }'
            )
        else:
            warn.setStyleSheet('QLabel { font-weight: 700; margin-bottom: 1px; }')


class FocusLineEdit(QLineEdit):
    def __init__(self, ridx: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ridx = ridx
        self.focused = FocusEmitter()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focused.emit(self._ridx)


class FocusEmitter:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, ridx: int) -> None:
        for cb in self._callbacks:
            cb(ridx)


class ReviewChunkLinesController:
    """Connects ``ChunkLinesSession`` to ``ReviewMainWindow`` actions."""

    def __init__(
        self,
        session: ChunkLinesSession,
        view: ReviewMainWindow,
        raw_json_cli: Path | None,
        transcriptions_dir: Path | None,
    ) -> None:
        self._session = session
        self._view = view
        self._raw_json_cli = raw_json_cli
        self._transcriptions_dir = transcriptions_dir
        view.connect_controller_signals(self)

    def try_initial_chunk(self) -> None:
        names = self._view.chunk_filenames
        for name in names:
            if self._load_chunk(name, show_error=False):
                self._view.sync_combo_to_chunk_name(
                    self._session.paths.chunk_name if self._session.paths else None,
                )
                return
        self._view.chunk_combo.setCurrentIndex(0)
        self._load_chunk(names[0], show_error=True)

    def _on_text_changed(self) -> None:
        self._session.dirty = True

    def _sync_combo_to_loaded_chunk(self) -> None:
        if self._session.paths is None:
            return
        self._view.sync_combo_to_chunk_name(self._session.paths.chunk_name)

    def _on_chunk_combo_index_changed(self, index: int) -> None:
        if index < 0:
            return
        name = self._view.chunk_combo.itemText(index)
        if self._session.paths is not None and name == self._session.paths.chunk_name:
            return
        self._switch_to_chunk(name)

    def _switch_to_chunk(self, chunk_name: str) -> None:
        if self._session.paths is not None and self._session.dirty:
            box = QMessageBox(self._view)
            box.setWindowTitle('Unsaved changes')
            box.setText('You have unsaved edits for this chunk.')
            box.setInformativeText('Save them before opening another chunk?')
            box.setStandardButtons(
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            box.setDefaultButton(QMessageBox.Save)
            reply = box.exec()
            if reply == QMessageBox.Cancel:
                self._sync_combo_to_loaded_chunk()
                return
            if reply == QMessageBox.Save:
                self._commit_all()
                self._session.save_to_final()
                self._session.dirty = False
        if not self._load_chunk(chunk_name, show_error=True):
            self._sync_combo_to_loaded_chunk()

    def _load_chunk(self, chunk_name: str, show_error: bool) -> bool:
        err = self._session.load_chunk(
            self._view.working_dir,
            chunk_name,
            self._raw_json_cli,
            self._view.chunk_pdf_dir,
            self._transcriptions_dir,
        )
        if err is not None:
            if show_error:
                QMessageBox.warning(self._view, 'Cannot load chunk', err)
            return False

        paths = self._session.paths
        assert paths is not None

        if self._session.is_review_complete():
            box = QMessageBox(self._view)
            box.setWindowTitle('Already marked complete')
            box.setText('This final JSON is already marked as review complete.')
            box.setInformativeText('Choose whether to keep it complete or reset and continue editing.')
            keep_btn = box.addButton('Keep complete', QMessageBox.AcceptRole)
            reset_btn = box.addButton('Reset and continue', QMessageBox.DestructiveRole)
            cancel_btn = box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(keep_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked == cancel_btn:
                return False
            if clicked == reset_btn:
                self._session.set_review_complete(False)
                self._session.dirty = True

        self._view.setWindowTitle(f'Line review — {paths.chunk_name}')
        self._view.set_path_labels(paths.raw_path.name, paths.final_path.name)
        self._view.populate_lines(self._session, self)
        self._view.set_review_controls_enabled(True)
        self._show_line()
        return True

    def _show_line(self) -> None:
        # Line/image sync uses only persisted ``page_number`` and ``box_2d``; no OCR
        # or re-snap at focus time.
        self._session.clamp_editable_ridx()
        s = self._session
        n_editable = len(s.editable_indices)
        ridx = s.editable_ridx
        line = s.line_at_editable_ridx()
        page_number = line.get('page_number')
        if isinstance(page_number, int) and 1 <= page_number <= len(s.page_images):
            self._view.set_page_image(s.page_images[page_number - 1])
        else:
            self._view.set_page_image(None)
        self._view.set_active_row(ridx)
        self._view.show_active_line_box(line)
        center = normalized_center_y_for_line(line)
        if center is not None:
            self._view.center_page_on_normalized_y(center)
        self._view.set_prev_next_enabled(ridx > 0, ridx < n_editable - 1)

    def _on_prev(self) -> None:
        if not self._session.is_loaded or self._session.editable_ridx <= 0:
            return
        self._session.editable_ridx -= 1
        self._show_line()

    def _on_next(self) -> None:
        s = self._session
        if not s.is_loaded or s.editable_ridx >= len(s.editable_indices) - 1:
            return
        s.editable_ridx += 1
        self._show_line()

    def _on_row_focused(self, ridx: int) -> None:
        if not self._session.is_loaded:
            return
        self._session.editable_ridx = ridx
        self._show_line()

    def _on_next_flagged(self) -> None:
        s = self._session
        if not s.is_loaded:
            return
        start = s.editable_ridx + 1
        for ridx in range(start, len(s.editable_indices)):
            line = s.lines[s.editable_indices[ridx]]
            if line_confidence_label(line) in {'low', 'medium'}:
                s.editable_ridx = ridx
                self._show_line()
                return

    def _on_save(self) -> None:
        if not self._session.is_loaded:
            return
        self._commit_all()
        paths = self._session.paths
        assert paths is not None
        self._session.set_review_complete(False)
        self._session.save_to_final()
        self._session.dirty = False
        self._view.statusBar().showMessage(f'Wrote {paths.final_path}', 6000)

    def _on_complete_review(self) -> None:
        if not self._session.is_loaded:
            return
        self._commit_all()
        unchanged_low, total_low = self._session.low_confidence_unchanged_stats()

        box = QMessageBox(self._view)
        box.setWindowTitle('Mark review complete')
        box.setText('Set review_complete=true, save the final JSON, and exit?')
        if total_low > 0 and unchanged_low > 0:
            box.setInformativeText(
                f'{unchanged_low} of {total_low} low confidence lines were not changed.'
            )
            box.setIcon(QMessageBox.Warning)
        else:
            box.setIcon(QMessageBox.Question)
        cancel_btn = box.addButton('Cancel completion', QMessageBox.RejectRole)
        exit_btn = box.addButton('Exit and mark complete', QMessageBox.AcceptRole)
        box.setDefaultButton(exit_btn)
        box.exec()
        if box.clickedButton() != exit_btn:
            return

        paths = self._session.paths
        assert paths is not None
        self._session.set_review_complete(True)
        self._session.save_to_final()
        self._session.dirty = False
        self._view.statusBar().showMessage(f'Wrote {paths.final_path}', 6000)
        self._view.close()

    def _on_reload(self) -> None:
        if not self._session.is_loaded:
            return
        reply = QMessageBox.question(
            self._view,
            'Reload from raw',
            'Discard edits in memory and reload from raw JSON on disk?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        err = self._session.reload_from_raw_disk()
        if err is not None:
            QMessageBox.warning(self._view, 'Reload', err)
            return
        self._view.populate_lines(self._session, self)
        self._show_line()

    def _commit_all(self) -> None:
        for ridx in range(len(self._session.editable_indices)):
            self._session.editable_ridx = ridx
            self._session.commit_editable_text(self._view.line_text(ridx))
        self._session.refresh_reviewer_changed_flags()


def main() -> int:
    cli = parse_cli_args()
    has_chunk_dir = cli.chunk_dir is not None
    has_transcriptions_dir = cli.transcriptions_dir is not None
    if has_chunk_dir != has_transcriptions_dir:
        print(
            'Pass --chunk-dir and --transcriptions-dir together, or pass neither.',
            file=sys.stderr,
        )
        return 2

    working_dir = cli.working_dir.resolve()
    if not has_chunk_dir and not has_transcriptions_dir and not _has_review_chunk_state(working_dir):
        prompted_root: Path | None = None
        if _can_show_transcription_root_dialog():
            app_for_picker = QApplication.instance()
            created_picker_app = False
            if app_for_picker is None:
                app_for_picker = QApplication(sys.argv)
                created_picker_app = True
            prompted_root = _pick_transcription_root_with_dialog(working_dir)
            if created_picker_app:
                app_for_picker.quit()
        if prompted_root is None:
            print(
                f'Could not resolve transcription root: {working_dir} is missing '
                f'{CHUNK_STATE_FILENAME}. Select a valid root in the file dialog '
                'or pass both --chunk-dir and --transcriptions-dir.',
                file=sys.stderr,
            )
            return 2
        working_dir = prompted_root

    chunk_pdf_dir = resolve_chunk_pdf_dir(working_dir, cli.chunk_dir)
    if not chunk_pdf_dir.is_dir():
        print(
            f'Expected a chunk PDF directory at {chunk_pdf_dir}. '
            'Use --chunk-dir or ensure working-dir contains chunk-pdfs/ '
            'and transcriptions/.',
            file=sys.stderr,
        )
        return 1

    pdf_names = list_chunk_filenames(chunk_pdf_dir)
    if not pdf_names:
        print(f'No .pdf files found in {chunk_pdf_dir}', file=sys.stderr)
        return 1

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName('Line review')
    _ic = _review_app_icon()
    if not _ic.isNull():
        app.setWindowIcon(_ic)

    session = ChunkLinesSession()
    win = ReviewMainWindow(working_dir, chunk_pdf_dir, pdf_names)
    ctrl = ReviewChunkLinesController(
        session,
        win,
        raw_json_cli=cli.raw_json,
        transcriptions_dir=cli.transcriptions_dir,
    )
    win.show()
    ctrl.try_initial_chunk()
    _install_terminal_interrupt_handlers(app)
    return app.exec()


def _install_terminal_interrupt_handlers(app: QApplication) -> None:
    def _quit(_signum=None, _frame=None) -> None:
        app.quit()

    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, _quit)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _quit)

    # Wake the event loop periodically so Python can run signal handlers (Ctrl+C works under Qt).
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)
    app._sigint_poll_timer = timer


if __name__ == '__main__':
    sys.exit(main())
