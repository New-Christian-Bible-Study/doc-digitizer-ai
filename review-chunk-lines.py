#!/usr/bin/env python3
"""Line-by-line transcription review with approximate image sync."""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGraphicsPixmapItem,
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
    list_chunk_pdf_filenames,
    normalized_center_y_for_line,
)


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
        '--raw-json',
        type=Path,
        default=None,
        help=(
            'Path to *_raw.json; relative paths are under --working-dir '
            '(default: transcriptions/<stem>_raw.json)'
        ),
    )
    return parser.parse_args(argv)


class ReviewMainWindow(QMainWindow):
    """Dual-pane review UI with approximate page sync."""

    def __init__(
        self,
        working_dir: Path,
        chunk_pdf_names: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._working_dir = working_dir.resolve()
        self._chunk_pdf_names = chunk_pdf_names
        self._line_edits: list[FocusLineEdit] = []
        self._line_badges: list[QLabel] = []
        self._line_notes: list[QLabel] = []
        self._line_rows: list[QWidget] = []
        self._row_indices: list[int] = []
        self._page_pixmap: QPixmap | None = None
        self._last_center_y: float | None = None
        self._zoom_factor: float = 1.0
        self._fit_scale: float = 1.0

        root = self._init_window_shell()
        self._add_chunk_pdf_row(root, chunk_pdf_names)
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

    def _add_chunk_pdf_row(self, root: QVBoxLayout, chunk_pdf_names: list[str]):
        """Dropdown listing ``chunk-pdfs/*.pdf`` so the user picks the active chunk."""
        chunk_row = QHBoxLayout()
        chunk_row.setSpacing(8)
        chunk_row.addWidget(QLabel('Chunk PDF'))
        self._chunk_combo = QComboBox()
        self._chunk_combo.setMinimumWidth(280)
        self._chunk_combo.addItems(chunk_pdf_names)
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
        self._page_view = QGraphicsView(self._scene)
        self._page_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._page_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        splitter.addWidget(self._page_view)

        self._line_scroll = QScrollArea()
        self._line_scroll.setWidgetResizable(True)
        self._line_host = QWidget()
        self._line_layout = QVBoxLayout(self._line_host)
        self._line_layout.setContentsMargins(6, 6, 6, 6)
        self._line_layout.setSpacing(8)
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
        self._btn_save = QPushButton('Save to final JSON')
        self._btn_reload = QPushButton('Reload from raw')
        btn_row.addWidget(self._btn_prev)
        btn_row.addWidget(self._btn_next)
        btn_row.addWidget(self._btn_next_flagged)
        btn_row.addWidget(self._btn_save)
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
    def chunk_pdf_names(self) -> list[str]:
        return self._chunk_pdf_names

    @property
    def chunk_combo(self) -> QComboBox:
        return self._chunk_combo

    def connect_controller_signals(self, ctrl: 'ReviewChunkLinesController') -> None:
        self._chunk_combo.currentIndexChanged.connect(ctrl._on_chunk_combo_index_changed)
        self._btn_prev.clicked.connect(ctrl._on_prev)
        self._btn_next.clicked.connect(ctrl._on_next)
        self._btn_next_flagged.clicked.connect(ctrl._on_next_flagged)
        self._btn_save.clicked.connect(ctrl._on_save)
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
        self._row_indices = []

    def populate_lines(self, session: ChunkLinesSession, ctrl: 'ReviewChunkLinesController') -> None:
        self.clear_line_rows()
        for ridx, payload_idx in enumerate(session.editable_indices):
            line = session.lines[payload_idx]
            conf = line_confidence_label(line) or 'high'
            notes_text = line_notes(line).strip()
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(6, 6, 6, 6)
            row_layout.setSpacing(4)
            badge = QLabel(conf.upper())

            # Keep high-confidence rows visually quiet. For medium/low rows, put a
            # clear warning line above the editor with confidence + reason.
            if conf != 'high':
                warn = QLabel(
                    f'Confidence: {conf.upper()}'
                    + (f' - {notes_text}' if notes_text else ' - No reason provided')
                )
                warn.setWordWrap(True)
                warn.setStyleSheet('QLabel { font-weight: 700; }')
                row_layout.addWidget(warn)

            edit = FocusLineEdit(ridx)
            edit.setText((line.get('text', '') if isinstance(line.get('text', ''), str) else '').rstrip())
            edit.textChanged.connect(ctrl._on_text_changed)
            edit.focused.connect(ctrl._on_row_focused)
            row_layout.addWidget(edit)
            self._apply_row_confidence_style(row, badge, conf)

            self._line_layout.insertWidget(self._line_layout.count() - 1, row)
            self._line_rows.append(row)
            self._line_edits.append(edit)
            self._line_badges.append(badge)
            self._line_notes.append(QLabel(''))
            self._row_indices.append(payload_idx)

    def _apply_row_confidence_style(self, row: QWidget, badge: QLabel, label: str | None) -> None:
        if label == 'low':
            row.setStyleSheet('QWidget { border: 1px solid #6f2e2e; border-radius: 5px; }')
            badge.setStyleSheet('QLabel { color: #cf3a3a; font-weight: 700; }')
        elif label == 'medium':
            row.setStyleSheet('QWidget { border: 1px solid #796324; border-radius: 5px; }')
            badge.setStyleSheet('QLabel { color: #9d7d1d; font-weight: 700; }')
        else:
            row.setStyleSheet('QWidget { border: 1px solid #444; border-radius: 5px; }')
            badge.setStyleSheet('QLabel { color: #cfcfcf; font-weight: 600; }')

    def set_active_row(self, ridx: int) -> None:
        for i, row in enumerate(self._line_rows):
            if i == ridx:
                palette = row.palette()
                palette.setColor(QPalette.Window, QColor(36, 53, 84))
                row.setPalette(palette)
                row.setAutoFillBackground(True)
            else:
                row.setAutoFillBackground(False)
        if 0 <= ridx < len(self._line_edits):
            self._line_edits[ridx].setFocus()
            self._line_edits[ridx].selectAll()
            self._line_scroll.ensureWidgetVisible(self._line_edits[ridx], 0, 100)

    def set_page_image(self, page_image: Image.Image | None) -> None:
        if page_image is None:
            self._page_item.setPixmap(QPixmap())
            self._page_pixmap = None
            return
        self._page_pixmap = pil_to_qpixmap(page_image)
        self._page_item.setPixmap(self._page_pixmap)
        self._scene.setSceneRect(self._page_item.boundingRect())
        self.reset_zoom_to_fit()

    def center_page_on_normalized_y(self, normalized_y: float) -> None:
        if self._page_pixmap is None or self._page_pixmap.isNull():
            return
        self._last_center_y = normalized_y
        page_h = self._page_pixmap.height()
        target_y = int((normalized_y / float(BOX_2D_NORMALIZED_MAX)) * page_h)
        self._smooth_center_on_y(target_y)

    def _smooth_center_on_y(self, y: int) -> None:
        self._page_view.centerOn(0, y)

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
    ) -> None:
        self._session = session
        self._view = view
        self._raw_json_cli = raw_json_cli
        view.connect_controller_signals(self)

    def try_initial_chunk(self) -> None:
        names = self._view.chunk_pdf_names
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
        )
        if err is not None:
            if show_error:
                QMessageBox.warning(self._view, 'Cannot load chunk', err)
            return False

        paths = self._session.paths
        assert paths is not None

        self._view.setWindowTitle(f'Line review — {paths.chunk_name}')
        self._view.set_path_labels(paths.raw_path.name, paths.final_path.name)
        self._view.populate_lines(self._session, self)
        self._view.set_review_controls_enabled(True)
        self._show_line()
        return True

    def _show_line(self) -> None:
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
        self._session.save_to_final()
        self._session.dirty = False
        self._view.statusBar().showMessage(f'Wrote {paths.final_path}', 6000)

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
        for ridx, idx in enumerate(self._session.editable_indices):
            self._session.lines[idx]['text'] = self._view.line_text(ridx).rstrip()


def main() -> int:
    cli = parse_cli_args()
    working_dir = cli.working_dir.resolve()
    chunk_pdfs_dir = working_dir / 'chunk-pdfs'
    if not chunk_pdfs_dir.is_dir():
        print(
            f'Expected a chunk-pdfs directory at {chunk_pdfs_dir}. '
            '--working-dir should be the folder that contains chunk-pdfs/ '
            'and transcriptions/.',
            file=sys.stderr,
        )
        return 1

    pdf_names = list_chunk_pdf_filenames(chunk_pdfs_dir)
    if not pdf_names:
        print(f'No .pdf files found in {chunk_pdfs_dir}', file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName('Line review')
    _ic = _review_app_icon()
    if not _ic.isNull():
        app.setWindowIcon(_ic)

    session = ChunkLinesSession()
    win = ReviewMainWindow(working_dir, pdf_names)
    ctrl = ReviewChunkLinesController(session, win, raw_json_cli=cli.raw_json)
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
