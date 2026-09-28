"""ActionBar: the strip along the bottom of the window (spec §2 "Action bar").

"Name" and "Style" fields, a two-line status area (what happened last, with Show file / Uninstall / Notes links,
or the build's progress and Cancel), then [Save a copy…] and the primary button (Install, Update installed font,
Installed ✓; Save… where installing is not supported).

Everything shown comes from the ForgeModel (names, validity, busy, glyph budget) and the BuildController (state,
stage, result); every action goes back through them. The bar owns the dialogs an action can need: the path of a
saved copy, the warning when the name clashes with a font the user already has, and the question before a font
installed earlier is replaced.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from fontplayground.ui.build import BuildController, BuildState
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.theme import LIGHT, Theme
from fontplayground.ui.widgets import ElidedLabel, set_flag

BAR_HEIGHT = 84
NAME_WIDTH, STYLE_WIDTH = 240, 110
PRIMARY_MIN_WIDTH = 140
FONT_FILTER = "TrueType font (*.ttf)"

IDLE_TEXT = "Installs for your account only — no admin rights needed."
IDLE_SAVE_TEXT = "Saves a .ttf file you can install yourself."
BUILDING_TEXT = "Building your font — {stage}"
INSTALLED_TEXT = "✓ Installed as “{name}” for your account."
INSTALLED_DETAIL = "Choose it in any app's font list."
SAVED_TEXT = "✓ Saved to {path}"
CANCELLED_TEXT = "Cancelled."
NOTES_TEXT = "Notes ({n})"
DETAILS_TEXT = "Details"

INSTALL, INSTALLING, SAVING, BUILDING = "Install", "Installing…", "Saving…", "Building…"
INSTALLED, UPDATE, SAVE = "Installed ✓", "Update installed font", "Save…"

STYLE = """
QWidget#bar { background: $surface; border-top: 1px solid $border_soft; }
QLabel { color: $text; background: transparent; }
QLabel#secondary { color: $text_secondary; }
QLabel#detail { color: $muted; }
QLabel#status { color: $text; }
QLabel#status[tone="muted"] { color: $muted; }
QLabel#status[tone="ok"] { color: $ok; }
QLabel#status[tone="warn"] { color: $warn_text; }
QLabel#status[tone="danger"] { color: $danger; }
QLineEdit#name { background: $surface; color: $text; border: 1px solid $border; border-radius: 6px;
                 padding: 6px 10px; font-size: 14px; }
QLineEdit#name:focus { border-color: $accent; }
QLineEdit#name:disabled { color: $faint; border-color: $border_soft; }
QPushButton#primary { background: $accent; color: $on_accent; border: none; border-radius: 8px; padding: 10px 26px;
                      font-size: 14px; font-weight: 600; }
QPushButton#primary:hover { background: $accent_hover; }
QPushButton#primary:disabled { background: $accent_disabled; color: $accent_disabled_text; }
QPushButton#primary[done="true"], QPushButton#primary[done="true"]:disabled {
    background: $ok_soft; color: $ok; border: 1px solid $ok_soft_border; }
QPushButton#secondary { background: transparent; color: $text; border: 1px solid $border; border-radius: 8px;
                        padding: 9px 16px; }
QPushButton#secondary:hover { background: $surface_alt; }
QPushButton#secondary:disabled { color: $faint; border-color: $border_soft; }
QPushButton#link { background: transparent; border: none; color: $accent; padding: 0 2px; }
QPushButton#link:hover { color: $accent_hover; text-decoration: underline; }
QProgressBar { border: none; background: $surface_alt; border-radius: 4px; max-height: 8px; min-height: 8px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
"""


def short_path(path: str) -> str:
    """'C:\\Users\\me\\Documents\\X.ttf' -> '~\\Documents\\X.ttf'; paths outside the home folder stay as they are."""
    p = Path(path)
    try:
        return "~" + os.sep + str(p.relative_to(Path.home()))
    except (ValueError, RuntimeError):
        return str(p)


def open_folder(folder: str) -> bool:
    """Show a folder in the system's file manager (tests replace this)."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def _lower_first(text: str) -> str:
    """'Preparing Segoe UI…' -> 'preparing Segoe UI…' (to follow a dash); 'UI…' stays as it is."""
    return text[:1].lower() + text[1:] if text[1:2].islower() else text


@dataclass
class _Status:
    text: str
    tone: str                 # muted | ok | warn | danger | plain
    detail: str = ""
    show_file: bool = False
    uninstall: bool = False
    notes: str = ""           # the notes link's text; "" hides it


class ActionBar(QWidget):
    detailsRequested = Signal()   # "Notes (n)" or "Details": show the build report

    def __init__(self, model: ForgeModel, controller: BuildController, parent: QWidget | None = None,
                 theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.model = model
        self.controller = controller
        self._theme = theme
        self.setObjectName("bar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(BAR_HEIGHT)
        self._build()
        self.apply_theme(theme)

        self.family_edit.textEdited.connect(lambda text: model.set_family(text, by_user=True))
        self.style_edit.textEdited.connect(lambda text: model.set_style(text, by_user=True))
        self.primary_button.clicked.connect(self._on_primary)
        self.save_button.clicked.connect(self._ask_save)
        self.cancel_button.clicked.connect(controller.cancel)
        self.show_file_link.clicked.connect(self._show_file)
        self.uninstall_link.clicked.connect(controller.uninstall)
        self.notes_link.clicked.connect(self.detailsRequested)

        controller.changed.connect(self.refresh)
        model.namesChanged.connect(self._on_names_changed)
        for signal in (model.validityChanged, model.busyChanged, model.materialsChanged, model.planChanged,
                       model.resultStale):
            signal.connect(self.refresh)
        self._sync_names()
        self.refresh()

    # ----- construction -----
    def _build(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 12, 18, 12)
        row.setSpacing(8)

        self.family_edit = self._name_edit(NAME_WIDTH, "Name your font")
        self.style_edit = self._name_edit(STYLE_WIDTH, "Regular")
        for text, edit in (("Name", self.family_edit), ("Style", self.style_edit)):
            label = QLabel(text)
            label.setObjectName("secondary")
            label.setBuddy(edit)
            row.addWidget(label)
            row.addWidget(edit)
        row.addSpacing(18)

        status = QWidget()
        status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        column = QVBoxLayout(status)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        self.status_label = ElidedLabel()
        self.status_label.setObjectName("status")
        column.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        column.addWidget(self.progress_bar)
        self.detail_row = QWidget()
        details = QHBoxLayout(self.detail_row)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(8)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("detail")
        details.addWidget(self.detail_label)
        self.show_file_link = self._link("Show file")
        self.uninstall_link = self._link("Uninstall")
        self.notes_link = self._link(DETAILS_TEXT)
        for link in (self.show_file_link, self.uninstall_link, self.notes_link):
            details.addWidget(link)
        details.addStretch(1)
        column.addWidget(self.detail_row)
        row.addWidget(status, 1)
        row.addSpacing(12)

        self.cancel_button = self._button("Cancel", "secondary")
        self.save_button = self._button("Save a copy…", "secondary")
        self.primary_button = self._button(INSTALL, "primary")
        self.primary_button.setMinimumWidth(PRIMARY_MIN_WIDTH)
        for button in (self.cancel_button, self.save_button, self.primary_button):
            row.addWidget(button)

    def _name_edit(self, width: int, placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("name")
        edit.setFixedWidth(width)
        edit.setPlaceholderText(placeholder)
        return edit

    def _button(self, text: str, name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        return button

    def _link(self, text: str) -> QPushButton:
        link = self._button(text, "link")
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        return link

    # ----- public -----
    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(theme.render(STYLE))

    def refresh(self) -> None:
        """Show what the model and the controller say now (names are synced separately, on namesChanged)."""
        m, c = self.model, self.controller
        building = c.state is BuildState.BUILDING or m.is_busy()
        supported = c.can_install()
        problem = m.validity()

        for edit in (self.family_edit, self.style_edit):
            edit.setEnabled(not building)

        status = self._status(building, problem, supported)
        self.status_label.set_text(status.text)
        set_flag(self.status_label, "tone", status.tone)
        self.detail_label.setText(status.detail)
        self.detail_label.setVisible(bool(status.detail))
        self.show_file_link.setVisible(status.show_file and c.shown_file() is not None)
        self.uninstall_link.setVisible(status.uninstall)
        self.notes_link.setText(status.notes or DETAILS_TEXT)
        self.notes_link.setVisible(bool(status.notes))
        self.detail_row.setVisible(not building and (bool(status.detail) or status.show_file or status.uninstall
                                                     or bool(status.notes)))
        self.progress_bar.setVisible(building)
        self.progress_bar.setValue(max(0, min(100, round(c.fraction * 100))) if building else 0)

        self.cancel_button.setVisible(building)
        self.cancel_button.setEnabled(building and not c.stopping)
        self.save_button.setVisible(supported and not building)
        self.save_button.setEnabled(not problem and not building)

        text, enabled, done = self._primary(building, problem, supported)
        self.primary_button.setText(text)
        self.primary_button.setEnabled(enabled)
        set_flag(self.primary_button, "done", done)

    # ----- what to show -----
    def _status(self, building: bool, problem: str, supported: bool) -> _Status:
        c = self.controller
        if building:
            stage = _lower_first(c.stage) if c.stage else "starting…"
            return _Status(BUILDING_TEXT.format(stage=stage), "plain")
        if problem:
            return _Status(problem, "danger")
        notes = self._notes_text()
        if c.state is BuildState.INSTALLED:
            return _Status(INSTALLED_TEXT.format(name=c.installed_name), "ok", INSTALLED_DETAIL, show_file=True,
                           uninstall=True, notes=notes)
        if c.state is BuildState.SAVED:
            return _Status(SAVED_TEXT.format(path=short_path(str(c.saved_path))), "ok", show_file=True, notes=notes)
        if c.state is BuildState.FAILED:
            return _Status(c.error or "", "danger", notes=DETAILS_TEXT)
        if c.state is BuildState.CANCELLED:
            return _Status(CANCELLED_TEXT, "muted")
        if c.notice:
            return _Status(c.notice, "muted")
        warning = self.model.glyph_warning()
        if warning:
            return _Status(warning, "warn")
        return _Status(IDLE_TEXT if supported else IDLE_SAVE_TEXT, "muted")

    def _notes_text(self) -> str:
        report = self.controller.report
        n = len(report.warnings) if report is not None else 0
        return NOTES_TEXT.format(n=n) if n else ""

    def _primary(self, building: bool, problem: str, supported: bool) -> tuple[str, bool, bool]:
        """(text, enabled, done look) of the primary button."""
        c = self.controller
        if building:
            return {"install": INSTALLING, "save": SAVING}.get(c.intent, BUILDING), False, False
        if not supported:
            return SAVE, not problem, False
        if c.installed_name is not None:
            if c.is_update():
                return UPDATE, not problem, False
            return INSTALLED, False, True
        return INSTALL, not problem, False

    # ----- actions -----
    def _on_primary(self) -> None:
        c = self.controller
        if not c.can_install():
            self._ask_save()
            return
        kind, message = c.conflict()
        if kind == "block":
            QMessageBox.warning(self, "Choose another name", message)
            return
        if kind == "replace" and QMessageBox.question(self, "Replace the font?", message) \
                != QMessageBox.StandardButton.Yes:
            return
        c.install()

    def _ask_save(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "Save the font as", self.model.output, FONT_FILTER)
        if path:
            self.controller.save_copy(path)

    def _show_file(self) -> None:
        shown = self.controller.shown_file()
        if shown is not None:
            open_folder(str(Path(shown).parent))

    # ----- names -----
    def _on_names_changed(self) -> None:
        self._sync_names()
        self.refresh()

    def _sync_names(self) -> None:
        for edit, value in ((self.family_edit, self.model.family), (self.style_edit, self.model.style)):
            if edit.text() != value:
                edit.setText(value)   # setText does not emit textEdited: nothing echoes back to the model
