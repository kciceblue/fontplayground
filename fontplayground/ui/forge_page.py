"""Step 3, Forge & save: name the result, watch it being forged, look at it, then save or install it.

A centred column: the names form (Family name, Style, "Saved as … [Change…]"), a recap line, and a stack with
three states — ready/stale (the composite preview and a hint), forging (the same preview, the stage, a progress
bar, Cancel) and result (a card with the real forged font in the preview, a summary sentence, warnings, what the
sample still lacks, the raw report under Details, and Install for me / Open folder / Start another).

Everything shown comes from the ForgeModel; every action goes back through it. The page never owns the primary
button: the app's tray does, and asks this page what it should say (primary_state) and what a click does
(primary_clicked).
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from fontplayground.catalog.face import read_faces
from fontplayground.engine.scripts import LABELS
from fontplayground.engine.spec import MaterialReport
from fontplayground.ui import install
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.preview import PreviewWidget

FaceKey = tuple[str, int]

STATE_READY, STATE_FORGING, STATE_RESULT = range(3)   # indices into ForgePage.stack
COLUMN_MAX_WIDTH = 760
MAX_SUMMARY_GROUPS = 4        # scripts named per material in the summary sentence before "…"
MAX_MISSING_CHARS = 20        # missing characters listed before "…" (the tooltip has them all)
MAX_BUTTON_PATH = 44          # longer paths are shown as '~\…\name.ttf' on the primary button
FONT_FILTER = "TrueType font (*.ttf)"

HINT_ARRIVE = "The forge starts when you arrive here."
HINT_STALE = "Settings changed — press Rebuild."
HINT_CANCELLED = "Forging was cancelled — press Rebuild to try again."
HINT_FAILED = "Forging failed: {error} Press Rebuild to try again."
HINT_INVALID = "Can't forge yet — {problem}"
STAGE_STARTING = "Starting…"
STAGE_STOPPING = "Stopping…"
MISSING_PREFIX = "Not in this font: "
COVERED_TEXT = "sample fully covered"
INSTALLED_TEXT = "Installed for your account as {name}"
REMOVED_TEXT = "Removed from your fonts."
NOT_INSTALLED_TEXT = "That font was no longer installed."

LABEL_FORGING, LABEL_REBUILD, LABEL_SAVED = "Forging…", "Rebuild", "Saved ✓"
ACTION_FORGING, ACTION_REBUILD, ACTION_SAVE, ACTION_OPEN = "forging", "rebuild", "save", "open"

COLOR_ACCENT, COLOR_MUTED, COLOR_MISSING, COLOR_OK = "#1a6bd8", "#777777", "#b3261e", "#2f8f46"

STYLE = f"""
QFrame#card {{ background: #ffffff; border: 1px solid #e3e3e3; border-radius: 8px; }}
QLabel#title {{ font-size: 16px; font-weight: 600; color: #1f2933; }}
QLabel#recap {{ color: {COLOR_MUTED}; }}
QLabel#stage {{ color: #1f2933; }}
QLabel#pathLabel {{ color: #1f2933; }}
QLabel#summary {{ color: #1f2933; }}
QLabel#warning {{ background: #fff6e0; border: 1px solid #f2c94c; border-radius: 6px; padding: 6px 10px;
                  color: #7a4b00; }}
QLabel#missing {{ color: {COLOR_MISSING}; }}
QLineEdit#nameEdit {{ border: 1px solid #c8d0dc; border-radius: 6px; padding: 4px 8px; background: #ffffff; }}
QLineEdit#nameEdit:focus {{ border: 1px solid {COLOR_ACCENT}; }}
QPushButton#secondary {{ border: 1px solid #c8d0dc; border-radius: 6px; background: #ffffff; padding: 6px 14px;
                         color: #1f2933; }}
QPushButton#secondary:hover {{ background: #eef1f5; }}
QPushButton#secondary:disabled {{ color: #a0a0a0; background: #f7f7f7; }}
QPushButton#link {{ border: none; background: transparent; color: {COLOR_ACCENT}; text-decoration: underline;
                    padding: 0; }}
QToolButton#details {{ border: none; background: transparent; color: {COLOR_ACCENT}; padding: 2px 0; }}
QToolButton#details:hover {{ color: #144f9f; }}
QProgressBar {{ border: 1px solid #d3dae6; border-radius: 6px; background: #ffffff; max-height: 12px; }}
QProgressBar::chunk {{ background: {COLOR_ACCENT}; border-radius: 5px; }}
QPlainTextEdit#details {{ background: #fafafa; border: 1px solid #e3e3e3; border-radius: 6px; color: #1f2933; }}
"""


# ----- small helpers (pure) -----------------------------------------------------------------------
def short_path(path: str) -> str:
    """'C:\\Users\\me\\Documents\\X.ttf' -> '~\\Documents\\X.ttf'; paths outside the home folder stay as they are."""
    p = Path(path)
    try:
        return "~" + os.sep + str(p.relative_to(Path.home()))
    except (ValueError, RuntimeError):
        return str(p)


def compact_path(path: str, max_len: int = MAX_BUTTON_PATH) -> str:
    """short_path, but a long one keeps only its first part and the file name: '~\\…\\X.ttf'."""
    short = short_path(path)
    if len(short) <= max_len:
        return short
    parts = Path(short).parts
    if len(parts) <= 2:
        return short
    return parts[0].rstrip(os.sep) + os.sep + "…" + os.sep + parts[-1]


def supplied_text(material: MaterialReport, limit: int | None = MAX_SUMMARY_GROUPS) -> str:
    """'Segoe UI Regular supplied Latin, Greek …' for one material of the report."""
    labels = [LABELS.get(g, g) for g in material.groups]
    if not labels:
        return f"{material.name} supplied nothing"
    if limit is not None and len(labels) > limit:
        return f"{material.name} supplied {', '.join(labels[:limit])} …"
    return f"{material.name} supplied {', '.join(labels)}"


def summary_sentence(materials: list[MaterialReport], limit: int | None = MAX_SUMMARY_GROUPS) -> str:
    """The materials joined with ' · ': who supplied which scripts."""
    return " · ".join(supplied_text(m, limit) for m in materials)


def listed_chars(chars: list[str], limit: int = MAX_MISSING_CHARS) -> str:
    return " ".join(chars[:limit]) + (" …" if len(chars) > limit else "")


def plural(n: int, word: str) -> str:
    return f"{n} {word if n == 1 else word + 's'}"


def open_folder(folder: str) -> bool:
    """Show a folder in the system's file manager."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


# ----- the page ------------------------------------------------------------------------------------
class ForgePage(QWidget):
    primaryStateChanged = Signal()   # primary_state() would now return something else
    startOverClicked = Signal()      # "Start another"

    def __init__(self, model: ForgeModel, preview: PreviewWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.preview = preview
        self._syncing = False                              # names are being copied model -> edits
        self._saved_for: tuple[str | None, str] | None = None   # (result path, output path) of the last save
        self._installed_name: str | None = None            # full name of the font installed from this page
        self._shown_result: str | None = None              # result path the preview currently shows
        self._last_error: str | None = None                # first line of the last failure
        self._error_detail: str | None = None
        self._cancelled = False
        self._cancel_requested = False
        self._last_primary: tuple[str, bool] | None = None
        self.setObjectName("forgePage")
        self.setStyleSheet(STYLE)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        self.column = QWidget()
        self.column.setMaximumWidth(COLUMN_MAX_WIDTH)
        self.column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addStretch(1)
        root.addWidget(self.column, 100)   # takes everything up to COLUMN_MAX_WIDTH; the rest centres it
        root.addStretch(1)
        column = QVBoxLayout(self.column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        column.addWidget(self._build_form())
        self.recap_label = QLabel("")
        self.recap_label.setObjectName("recap")
        self.recap_label.setWordWrap(True)
        column.addWidget(self.recap_label)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_ready_page())
        self.stack.addWidget(self._build_forging_page())
        self.stack.addWidget(self._build_result_page())
        column.addWidget(self.stack, 1)

        # widgets -> model / actions
        self.family_edit.textChanged.connect(self._on_family_edited)
        self.style_edit.textChanged.connect(self._on_style_edited)
        self.change_button.clicked.connect(self._choose_output)
        self.cancel_button.clicked.connect(self._cancel)
        self.details_button.toggled.connect(self._toggle_details)
        self.install_button.clicked.connect(self._install)
        self.open_folder_button.clicked.connect(self._open_folder)
        self.start_over_button.clicked.connect(self.startOverClicked)
        self.remove_button.clicked.connect(self._uninstall)
        self.preview.sampleChanged.connect(self._on_preview_sample_changed)
        # model -> page (bound methods: Qt drops them cleanly if the page dies before the model)
        self.model.materialsChanged.connect(self._on_materials_changed)
        self.model.planChanged.connect(self._on_plan_changed)
        self.model.validityChanged.connect(self._on_validity_changed)
        self.model.sampleChanged.connect(self._on_model_sample_changed)
        self.model.busyChanged.connect(self._on_busy_changed)
        self.model.progress.connect(self._on_progress)
        self.model.resultReady.connect(self._on_result_ready)
        self.model.resultFailed.connect(self._on_result_failed)
        self.model.resultCancelled.connect(self._on_result_cancelled)
        self.model.resultStale.connect(self._on_result_stale)
        self.model.namesChanged.connect(self._on_names_changed)

        self.preview.set_sample_text(self.model.sample_text)
        self._sync_names()
        self._sync_state()
        self._last_primary = self.primary_state()

    # ----- construction -----
    def _build_form(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QFormLayout(card)
        form.setContentsMargins(16, 12, 16, 12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.family_edit = QLineEdit()
        self.family_edit.setObjectName("nameEdit")
        self.family_edit.setToolTip("The name programs list the font under")
        self.style_edit = QLineEdit()
        self.style_edit.setObjectName("nameEdit")
        self.style_edit.setToolTip("Regular, Bold, Italic…")
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(8)
        self.path_label = QLabel("")
        self.path_label.setObjectName("pathLabel")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.change_button = QPushButton("Change…")
        self.change_button.setObjectName("secondary")
        self.change_button.setToolTip("Choose where the font is saved")
        self.change_button.setCursor(Qt.CursorShape.PointingHandCursor)
        path_layout.addWidget(self.path_label, 1)
        path_layout.addWidget(self.change_button)
        form.addRow("Family name", self.family_edit)
        form.addRow("Style", self.style_edit)
        form.addRow("Saved as", path_row)
        return card

    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        return card, layout

    def _build_ready_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        self.ready_card, self._ready_layout = self._card()
        self.hint_label = QLabel(HINT_ARRIVE)   # the preview goes above it (index 0)
        self.hint_label.setObjectName("hint")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setStyleSheet(f"color: {COLOR_MUTED};")
        self._ready_layout.addWidget(self.hint_label)
        outer.addWidget(self.ready_card, 1)
        return page

    def _build_forging_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        self.forging_card, self._forging_layout = self._card()
        self.stage_label = QLabel("")           # the preview goes above it (index 0)
        self.stage_label.setObjectName("stage")
        self.stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("secondary")
        self.cancel_button.setToolTip("Stop forging; nothing is kept")
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        self._forging_layout.addWidget(self.stage_label)
        self._forging_layout.addWidget(self.progress_bar)
        self._forging_layout.addLayout(row)
        outer.addWidget(self.forging_card, 1)
        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        self.result_card, self._result_layout = self._card()
        self.title_label = QLabel("")
        self.title_label.setObjectName("title")
        self._result_layout.addWidget(self.title_label)   # the preview goes right after it (index 1)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("summary")
        self.summary_label.setWordWrap(True)
        self.warnings_box = QWidget()
        self.warnings_layout = QVBoxLayout(self.warnings_box)
        self.warnings_layout.setContentsMargins(0, 0, 0, 0)
        self.warnings_layout.setSpacing(4)
        self.missing_label = QLabel("")
        self.missing_label.setObjectName("missing")
        self.missing_label.setWordWrap(True)
        self.missing_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.missing_label.hide()
        self.details_button = QToolButton()
        self.details_button.setObjectName("details")
        self.details_button.setText("Details")
        self.details_button.setCheckable(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_button.setArrowType(Qt.ArrowType.RightArrow)
        self.details_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.details_button.setToolTip("The full report of this forge")
        self.details_text = QPlainTextEdit()
        self.details_text.setObjectName("details")
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(220)
        self.details_text.hide()
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.install_button = QPushButton("Install for me")
        self.install_button.setToolTip("Save the font and make it available to your programs (this account only)")
        self.open_folder_button = QPushButton("Open folder")
        self.open_folder_button.setToolTip("Show the saved font in its folder")
        self.open_folder_button.setEnabled(False)
        self.start_over_button = QPushButton("Start another")
        self.start_over_button.setToolTip("Begin a new font from scratch")
        for button in (self.install_button, self.open_folder_button, self.start_over_button):
            button.setObjectName("secondary")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.install_button.setVisible(install.is_supported())
        status = QHBoxLayout()
        status.setSpacing(8)
        self.saved_label = QLabel("")
        self.saved_label.setObjectName("saved")
        self.saved_label.setWordWrap(True)
        self.saved_label.setStyleSheet(f"color: {COLOR_OK};")
        self.saved_label.hide()
        self.remove_button = QPushButton("Remove from my fonts")
        self.remove_button.setObjectName("link")
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.setFlat(True)
        self.remove_button.setToolTip("Undo the install for your account")
        self.remove_button.hide()
        status.addWidget(self.saved_label)
        status.addWidget(self.remove_button)
        status.addStretch(1)
        self._result_layout.addWidget(self.summary_label)
        self._result_layout.addWidget(self.warnings_box)
        self._result_layout.addWidget(self.missing_label)
        self._result_layout.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._result_layout.addWidget(self.details_text)
        self._result_layout.addLayout(buttons)
        self._result_layout.addLayout(status)
        outer.addWidget(self.result_card, 1)
        return page

    # ----- public API -----
    def activate(self) -> None:
        """The app shows the page: refresh it and start forging when the spec is valid and no fresh result exists."""
        self._sync_state()
        m = self.model
        if m.validity() == "" and (m.result_path is None or m.is_stale) and not m.is_busy():
            m.combine()

    def state(self) -> int:
        """STATE_READY, STATE_FORGING or STATE_RESULT: which page of the stack is showing."""
        return self.stack.currentIndex()

    def primary_state(self) -> tuple[str, bool]:
        """(label, enabled) for the tray's primary button."""
        _action, text, enabled = self._primary()
        return text, enabled

    def primary_clicked(self) -> None:
        """What the tray's primary button does on this page: Rebuild forges, Save copies, Saved ✓ opens the folder."""
        action, _text, enabled = self._primary()
        if not enabled:
            return
        if action == ACTION_REBUILD:
            self.model.combine()
        elif action == ACTION_SAVE:
            self._save_result()
        elif action == ACTION_OPEN:
            self._open_folder()

    def warning_labels(self) -> list[QLabel]:
        return [self.warnings_layout.itemAt(i).widget() for i in range(self.warnings_layout.count())]

    # ----- primary button contract -----
    def _primary(self) -> tuple[str, str, bool]:
        m = self.model
        if m.is_busy():
            return ACTION_FORGING, LABEL_FORGING, False
        if m.result_path is None or m.is_stale:
            return ACTION_REBUILD, LABEL_REBUILD, m.validity() == ""
        if self._saved_for == (m.result_path, m.output):
            return ACTION_OPEN, LABEL_SAVED, True
        return ACTION_SAVE, f"Save to {compact_path(m.output)}", bool(m.output.strip())

    def _announce_primary(self) -> None:
        state = self.primary_state()
        if state != self._last_primary:
            self._last_primary = state
            self.primaryStateChanged.emit()

    # ----- state machine -----
    def _sync_state(self) -> None:
        """Show the stack page that matches the model (idempotent; safe to call from any signal)."""
        m = self.model
        if m.is_busy():
            self._enter(STATE_FORGING, self._forging_layout, 0)
        elif m.result_report is not None and m.result_path is not None and not m.is_stale:
            self._enter(STATE_RESULT, self._result_layout, 1)
            if self._shown_result != m.result_path:
                self._fill_result_card(m.result_report)
        else:
            self._enter(STATE_READY, self._ready_layout, 0)
            self._refresh_hint()
        if self.state() != STATE_RESULT and (self._shown_result is not None or not self.preview.in_plan_mode()):
            self._show_plan()

    def _enter(self, state: int, layout: QVBoxLayout, index: int) -> None:
        self._place_preview(layout, index)
        if self.stack.currentIndex() != state:
            self.stack.setCurrentIndex(state)

    def _place_preview(self, layout: QVBoxLayout, index: int) -> None:
        """Move the one PreviewWidget into the layout of the state being shown (a widget has one parent)."""
        if layout.indexOf(self.preview) != -1:
            return
        parent = self.preview.parentWidget()
        old = parent.layout() if parent is not None else None
        if old is not None and old.indexOf(self.preview) != -1:
            old.removeWidget(self.preview)
        layout.insertWidget(index, self.preview, 1)

    def _show_plan(self) -> None:
        """Composite mode: each sample character in the font that will supply it, red where none does."""
        rows = self.model.rows
        keys = [r.face.key for r in rows]
        fonts = {r.face.key: (r.face.path, r.face.style, r.face.family, r.face.axes) for r in rows}
        plan = self.model.plan
        source = plan.source if plan is not None else {}

        def source_of(cp: int) -> FaceKey | None:
            i = source.get(cp)
            return keys[i] if i is not None and 0 <= i < len(keys) else None

        self.preview.set_plan(fonts, source_of)
        self._shown_result = None
        self._refresh_recap()

    def _fill_result_card(self, report) -> None:
        m = self.model
        self.title_label.setText(f"Forged ✓ — {m.family} {m.style}".rstrip())
        preview_note = None
        try:
            self.preview.set_face(read_faces(m.result_path)[0])
        except Exception as e:  # the file exists but could not be read back: keep the composite instead
            self._show_plan()
            preview_note = f"The preview could not load the forged font: {e}"
        self._shown_result = m.result_path
        self.summary_label.setText(summary_sentence(report.materials))
        self.summary_label.setToolTip(summary_sentence(report.materials, limit=None).replace(" · ", "\n"))
        self._set_warnings(list(report.warnings) + ([preview_note] if preview_note else []))
        self.details_text.setPlainText(report.as_text())
        self.details_button.setChecked(False)
        self.install_button.setVisible(install.is_supported())
        self.open_folder_button.setEnabled(self._saved_for is not None)
        self._refresh_missing()
        self._refresh_recap()

    def _set_warnings(self, warnings: list[str]) -> None:
        for label in self.warning_labels():
            self.warnings_layout.removeWidget(label)
            label.hide()
            label.deleteLater()
        for text in warnings:
            label = QLabel(text)
            label.setObjectName("warning")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.warnings_layout.addWidget(label)
        self.warnings_box.setVisible(bool(warnings))

    # ----- refreshers -----
    def _refresh_hint(self) -> None:
        m = self.model
        problem = m.validity()
        color = COLOR_MUTED
        tooltip = ""
        if problem:
            text, color = HINT_INVALID.format(problem=problem), COLOR_MISSING
        elif self._last_error:
            text, color = HINT_FAILED.format(error=self._last_error), COLOR_MISSING
            tooltip = self._error_detail or ""
        elif self._cancelled:
            text = HINT_CANCELLED
        elif m.is_stale:
            text = HINT_STALE
        else:
            text = HINT_ARRIVE
        self.hint_label.setText(text)
        self.hint_label.setToolTip(tooltip)
        self.hint_label.setStyleSheet(f"color: {color};")

    def _refresh_recap(self) -> None:
        m = self.model
        n = len(m.rows)
        if self.state() == STATE_RESULT and m.result_report is not None:
            chars = m.result_report.total_codepoints
        else:
            chars = len(m.plan.source) if m.plan is not None else 0
        text = f"{plural(n, 'font')} · {chars:,} characters"
        if n:
            missing = self.preview.missing_characters()
            if missing:
                text += f" · {plural(len(missing), 'sample character')} missing: {listed_chars(missing)}"
                self.recap_label.setToolTip(" ".join(missing))
            else:
                text += f" · {COVERED_TEXT}"
                self.recap_label.setToolTip("")
        else:
            self.recap_label.setToolTip("")
        self.recap_label.setText(text)

    def _refresh_missing(self) -> None:
        missing = self.preview.missing_characters() if self._shown_result is not None else []
        if missing:
            self.missing_label.setText(MISSING_PREFIX + listed_chars(missing))
            self.missing_label.setToolTip(" ".join(missing))
            self.missing_label.show()
        else:
            self.missing_label.setText("")
            self.missing_label.setToolTip("")
            self.missing_label.hide()

    def _sync_names(self) -> None:
        m = self.model
        self._syncing = True
        try:
            if self.family_edit.text() != m.family:
                self.family_edit.setText(m.family)
            if self.style_edit.text() != m.style:
                self.style_edit.setText(m.style)
        finally:
            self._syncing = False
        self.path_label.setText(short_path(m.output))
        self.path_label.setToolTip(m.output)

    # ----- model -> page -----
    def _on_materials_changed(self) -> None:
        self._sync_state()
        if self.state() != STATE_RESULT:
            self._show_plan()
        else:
            self._refresh_recap()

    def _on_plan_changed(self, _plan) -> None:
        self._on_materials_changed()

    def _on_validity_changed(self, _text: str) -> None:
        if self.state() == STATE_READY:
            self._refresh_hint()
        self._announce_primary()

    def _on_model_sample_changed(self, text: str) -> None:
        self.preview.set_sample_text(text)
        self._refresh_recap()
        self._refresh_missing()

    def _on_busy_changed(self, busy: bool) -> None:
        if busy:
            self._last_error = self._error_detail = None
            self._cancelled = self._cancel_requested = False
            self.progress_bar.setValue(0)
            self.stage_label.setText(STAGE_STARTING)
            self.cancel_button.setEnabled(True)
        self._sync_state()
        self._announce_primary()

    def _on_progress(self, text: str, fraction: float) -> None:
        if self._cancel_requested:
            return
        self.stage_label.setText(text)
        self.progress_bar.setValue(int(round(fraction * 100)))

    def _on_result_ready(self, _report) -> None:
        self._sync_state()
        self._announce_primary()

    def _on_result_failed(self, message: str) -> None:
        lines = message.strip().splitlines()
        self._last_error = lines[0] if lines else "unknown error"
        self._error_detail = message
        self._sync_state()
        self._announce_primary()

    def _on_result_cancelled(self) -> None:
        self._cancelled = True
        self._sync_state()
        self._announce_primary()

    def _on_result_stale(self) -> None:
        self._sync_state()
        self._announce_primary()

    def _on_names_changed(self) -> None:
        self._sync_names()
        self._announce_primary()

    # ----- widgets -> model / actions -----
    def _on_family_edited(self, text: str) -> None:
        if not self._syncing:
            self.model.set_family(text, by_user=True)

    def _on_style_edited(self, text: str) -> None:
        if not self._syncing:
            self.model.set_style(text, by_user=True)

    def _on_preview_sample_changed(self, text: str) -> None:
        self.model.set_sample_text(text)
        self._refresh_recap()
        self._refresh_missing()

    def _choose_output(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "Save the font as", self.model.output, FONT_FILTER)
        if path:
            self.model.set_output(path, by_user=True)

    def _cancel(self) -> None:
        if self.model.cancel():
            self._cancel_requested = True
            self.cancel_button.setEnabled(False)
            self.stage_label.setText(STAGE_STOPPING)

    def _toggle_details(self, open_: bool) -> None:
        self.details_text.setVisible(open_)
        self.details_button.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)

    def _confirm_overwrite(self, path: Path) -> bool:
        answer = QMessageBox.question(self, "Replace the file?",
                                      f"{short_path(str(path))} already exists.\nReplace it with the new font?")
        return answer == QMessageBox.StandardButton.Yes

    def _save_result(self) -> Path | None:
        """Copy the result to the output path (asking before replacing a file this page did not write itself)."""
        m = self.model
        out = Path(m.output)
        if out.exists() and self._saved_for != (m.result_path, m.output) and not self._confirm_overwrite(out):
            return None
        try:
            saved = m.save_to(out)
        except (RuntimeError, OSError) as e:
            QMessageBox.critical(self, "Could not save the font", str(e))
            return None
        self._saved_for = (m.result_path, m.output)
        self.open_folder_button.setEnabled(True)
        self._announce_primary()
        return saved

    def _install(self) -> None:
        saved = self._save_result()
        if saved is None:
            return
        full_name = f"{self.model.family} {self.model.style}".strip()
        try:
            install.install_font_for_user(saved, full_name)
        except Exception as e:  # not supported here, a locked file, a registry refusal…
            QMessageBox.critical(self, "Could not install the font", str(e))
            return
        self._installed_name = full_name
        self.saved_label.setText(INSTALLED_TEXT.format(name=full_name))
        self.saved_label.setStyleSheet(f"color: {COLOR_OK};")
        self.saved_label.show()
        self.remove_button.show()

    def _uninstall(self) -> None:
        if self._installed_name is None:
            return
        try:
            removed = install.uninstall_font_for_user(self._installed_name)
        except Exception as e:
            QMessageBox.critical(self, "Could not remove the font", str(e))
            return
        self._installed_name = None
        self.saved_label.setText(REMOVED_TEXT if removed else NOT_INSTALLED_TEXT)
        self.saved_label.setStyleSheet(f"color: {COLOR_MUTED};")
        self.remove_button.hide()

    def _open_folder(self) -> None:
        target = self._saved_for[1] if self._saved_for is not None else self.model.output
        open_folder(str(Path(target).parent))
