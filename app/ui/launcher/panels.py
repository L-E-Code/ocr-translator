"""Builds the cards of the launcher window (header, profile, hotkeys, capture, translation, actions)."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox, QProgressBar,
    QSlider, QListWidget, QLineEdit, QMenu, QKeySequenceEdit
)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import Qt, QSize, QUrl

from core.languages import LANGUAGES
from ui.ui_theme import Card, StatusPill, SegmentedControl, RegionPreview, icon, TEXT
from core.logger_config import open_log_folder
from ui.i18n import tr, ui_language, UI_LANGUAGES
from core.version import __version__


class PanelsMixin:
    """Builds the cards of the launcher window (header, profile, hotkeys, capture, translation, actions)."""

    def _build_header(self):
        header = QHBoxLayout()
        header.setSpacing(14)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        lbl_title = QLabel("OCR Translator")
        lbl_title.setStyleSheet("font-size: 21px; font-weight: 700;")
        lbl_subtitle = QLabel(tr("Real-time screen translation"))
        lbl_subtitle.setObjectName("muted")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.lbl_update = QLabel("")
        self.lbl_update.setOpenExternalLinks(False)
        self.lbl_update.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.lbl_update.setVisible(False)
        header.addWidget(self.lbl_update, 0, Qt.AlignmentFlag.AlignVCenter)
        self._show_update_label()

        self.status = StatusPill(tr("Ready to start"), "idle")
        header.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    def _build_profile_card(self):
        card = Card(tr("Profile"))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.combo_profile = QComboBox()
        self.combo_profile.activated.connect(self.on_profile_chosen)
        row.addWidget(self.combo_profile, 1)
        self.btn_profile_new = QPushButton(tr("Save as profile…"))
        self.btn_profile_new.setToolTip(tr("Stores the current settings (area, languages, display, window) in a profile"))
        self.btn_profile_new.clicked.connect(self.on_new_profile)
        row.addWidget(self.btn_profile_new)
        self.btn_profile_more = QPushButton("⋯")
        self.btn_profile_more.setToolTip(tr("Rename, duplicate or delete the profile"))
        self.btn_profile_more.setFixedWidth(44)
        self.btn_profile_more.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0; }")
        menu = QMenu(self.btn_profile_more)
        menu.addAction(tr("Rename…"), self.on_rename_profile)
        menu.addAction(tr("Duplicate…"), self.on_duplicate_profile)
        menu.addSeparator()
        menu.addAction(tr("Delete"), self.on_delete_profile)
        self.btn_profile_more.setMenu(menu)
        row.addWidget(self.btn_profile_more)
        card.body.addLayout(row)

        gloss_row = QHBoxLayout()
        gloss_row.setSpacing(8)
        lbl_gloss = QLabel(tr("Glossary"))
        lbl_gloss.setObjectName("muted")
        gloss_row.addWidget(lbl_gloss)
        self.combo_glossary = QComboBox()
        self.combo_glossary.setToolTip(tr("Fixed translations for names and terms. Each profile can use its own file."))
        self.combo_glossary.activated.connect(self.on_glossary_chosen)
        gloss_row.addWidget(self.combo_glossary, 1)
        self.btn_glossary_edit = QPushButton(tr("Edit terms…"))
        self.btn_glossary_edit.clicked.connect(self.on_edit_glossary)
        gloss_row.addWidget(self.btn_glossary_edit)
        self.btn_glossary_new = QPushButton(tr("New…"))
        self.btn_glossary_new.setToolTip(tr("Creates a glossary file for this game"))
        self.btn_glossary_new.clicked.connect(self.on_new_glossary)
        gloss_row.addWidget(self.btn_glossary_new)
        card.body.addLayout(gloss_row)

        self.chk_auto_profile = QCheckBox(tr("Switch profile automatically"))
        self.chk_auto_profile.setToolTip(
            tr("Applies to profiles with the \"Game window\" filled in: when the game is brought to the front, "
            "its profile is loaded.")
        )
        card.body.addWidget(self.chk_auto_profile)
        return card

    def _build_hotkeys_card(self):
        card = Card(tr("3 · Global hotkeys"))
        self.hotkey_edits = {}
        for action, label in (("pause", tr("Pause / resume")), ("reload", tr("Retranslate now")),
                              ("toggle_ui", tr("Show / hide the panel")), ("history", tr("Open / close the history")),
                              ("clear", tr("Clear the current line"))):
            row = QHBoxLayout()
            row.setSpacing(10)
            lbl = QLabel(label)
            lbl.setObjectName("muted")
            lbl.setFixedWidth(170)
            row.addWidget(lbl)
            edit = QKeySequenceEdit()
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            self.hotkey_edits[action] = edit
            row.addWidget(edit, 1)
            card.body.addLayout(row)
        hint = QLabel(tr("They work in any window, including with the game in the foreground, while the translation is running. "
                      "Use Ctrl, Alt or Shift together with the key; clear a field to disable a hotkey."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        return card

    def _build_capture_card(self):
        card = Card(tr("1 · Capture"))

        mon_row = QHBoxLayout()
        mon_row.setSpacing(10)
        lbl = QLabel(tr("Monitor"))
        lbl.setObjectName("muted")
        mon_row.addWidget(lbl)
        self.combo_monitors = QComboBox()
        for i, mon in enumerate(self.monitors):
            self.combo_monitors.addItem(tr("Monitor {n}  ·  {w}×{h}", n=i + 1, w=mon['width'], h=mon['height']), i)
        self.combo_monitors.currentIndexChanged.connect(self.on_monitor_changed)
        mon_row.addWidget(self.combo_monitors, 1)
        card.body.addLayout(mon_row)

        self.preview = RegionPreview()
        card.body.addWidget(self.preview)

        # Capture area (segmented selector; the buttons keep the QRadioButton API)
        self.seg_roi = SegmentedControl()
        self.radio_third = self.seg_roi.add(tr("Bottom third"), 1, tr("Default for dialogue boxes and subtitles"))
        self.radio_half = self.seg_roi.add(tr("Bottom half"), 2)
        self.radio_full = self.seg_roi.add(tr("Full screen"), 3, tr("Slower"))
        self.radio_custom = self.seg_roi.add(tr("Custom"), 4)
        self.roi_group = self.seg_roi.group
        self.roi_group.idClicked.connect(self.on_roi_mode_changed)
        card.body.addWidget(self.seg_roi)

        mouse_row = QHBoxLayout()
        mouse_row.setSpacing(12)
        self.btn_select_roi = QPushButton(tr("  Select area with the mouse"))
        self.btn_select_roi.setIcon(icon("target", TEXT, 17))
        self.btn_select_roi.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select_roi.clicked.connect(self.on_select_roi_clicked)
        mouse_row.addWidget(self.btn_select_roi)

        self.lbl_roi_info = QLabel(tr("Area: not set"))
        self.lbl_roi_info.setObjectName("accentValue")
        self.lbl_roi_info.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_roi_info.setWordWrap(True)
        mouse_row.addWidget(self.lbl_roi_info, 1)
        card.body.addLayout(mouse_row)

        # Additional regions (custom area only)
        self.regions_box = QWidget()
        rv = QVBoxLayout(self.regions_box)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        lbl_regions = QLabel(tr("Capture regions (several areas at once: dialogue, menu…)"))
        lbl_regions.setObjectName("muted")
        lbl_regions.setWordWrap(True)
        rv.addWidget(lbl_regions)
        self.list_regions = QListWidget()
        self.list_regions.setMaximumHeight(86)
        rv.addWidget(self.list_regions)
        reg_buttons = QHBoxLayout()
        reg_buttons.setSpacing(8)
        self.btn_add_region = QPushButton(tr("Add region…"))
        self.btn_add_region.clicked.connect(self.on_add_region)
        self.btn_remove_region = QPushButton(tr("Remove"))
        self.btn_remove_region.clicked.connect(self.on_remove_region)
        reg_buttons.addWidget(self.btn_add_region)
        reg_buttons.addWidget(self.btn_remove_region)
        reg_buttons.addStretch()
        rv.addLayout(reg_buttons)
        lbl_multi = QLabel(tr("With several regions, each one gets its own card, in the side panel and on screen."))
        lbl_multi.setObjectName("hint")
        lbl_multi.setWordWrap(True)
        rv.addWidget(lbl_multi)
        card.body.addWidget(self.regions_box)

        # Game window (follow movement and automatic profile)
        win_row = QHBoxLayout()
        win_row.setSpacing(8)
        lbl_win = QLabel(tr("Game window"))
        lbl_win.setObjectName("muted")
        win_row.addWidget(lbl_win)
        self.edit_window = QLineEdit()
        self.edit_window.setPlaceholderText(tr("part of the window title (optional)"))
        win_row.addWidget(self.edit_window, 1)
        self.btn_pick_window = QPushButton(tr("Choose…"))
        self.btn_pick_window.clicked.connect(self.on_pick_window)
        win_row.addWidget(self.btn_pick_window)
        card.body.addLayout(win_row)

        self.chk_track = QCheckBox(tr("Follow the window"))
        self.chk_track.setToolTip(tr("The area follows the game if it is moved or resized. Applies to the custom area. "
                                     "The window must be visible with no other window on top of it."))
        card.body.addWidget(self.chk_track)
        return card

    def _build_translation_card(self):
        card = Card(tr("2 · Translation"))

        lang_row = QHBoxLayout()
        lang_row.setSpacing(10)
        lbl = QLabel(tr("Languages"))
        lbl.setObjectName("muted")
        lbl.setFixedWidth(100)
        lang_row.addWidget(lbl)
        self.combo_source = QComboBox()
        self.combo_target = QComboBox()
        for code, lang in LANGUAGES.items():
            self.combo_source.addItem(tr(lang.label), code)
            self.combo_target.addItem(tr(lang.label), code)
        arrow = QLabel("➔")
        arrow.setObjectName("muted")
        lang_row.addWidget(self.combo_source, 1)
        lang_row.addWidget(arrow)
        lang_row.addWidget(self.combo_target, 1)
        card.body.addLayout(lang_row)

        dev_row = QHBoxLayout()
        dev_row.setSpacing(10)
        lbl_dev = QLabel(tr("Processing"))
        lbl_dev.setObjectName("muted")
        lbl_dev.setFixedWidth(100)
        dev_row.addWidget(lbl_dev)
        self.combo_device = QComboBox()
        self.combo_device.addItem(tr("Automatic (uses the GPU if there is one)"), "auto")
        self.combo_device.addItem("GPU", "gpu")
        self.combo_device.addItem("CPU", "cpu")
        self.combo_device.currentIndexChanged.connect(self.update_device_hint)
        self.combo_device.activated.connect(self.on_device_chosen)  # user choices only
        self._last_device_index = 0
        dev_row.addWidget(self.combo_device, 1)
        card.body.addLayout(dev_row)

        self.lbl_device_hint = QLabel("")
        self.lbl_device_hint.setObjectName("hint")
        self.lbl_device_hint.setWordWrap(True)
        card.body.addWidget(self.lbl_device_hint)

        lbl_mode = QLabel(tr("How to show the translation"))
        lbl_mode.setObjectName("muted")
        card.body.addWidget(lbl_mode)

        self.seg_mode = SegmentedControl()
        self.radio_sidebar = self.seg_mode.add(tr("Side panel"), 1, tr("Window with the current line and history"))
        self.radio_overlay = self.seg_mode.add(tr("On screen"), 2, tr("Translation drawn on top of the game or video"))
        self.mode_group = self.seg_mode.group
        self.mode_group.idClicked.connect(self.update_overlay_options_visibility)
        card.body.addWidget(self.seg_mode)

        # Options of the "On screen" mode
        self.overlay_options = QWidget()
        ov = QVBoxLayout(self.overlay_options)
        ov.setContentsMargins(0, 2, 0, 0)
        ov.setSpacing(10)

        op_row = QHBoxLayout()
        op_row.setSpacing(10)
        lbl_op = QLabel(tr("Opacity"))
        lbl_op.setObjectName("muted")
        op_row.addWidget(lbl_op)
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(30, 100)
        self.slider_opacity.valueChanged.connect(lambda v: self.lbl_opacity.setText(f"{v}%"))
        op_row.addWidget(self.slider_opacity, 1)
        self.lbl_opacity = QLabel("100%")
        self.lbl_opacity.setObjectName("accentValue")
        self.lbl_opacity.setFixedWidth(44)
        self.lbl_opacity.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        op_row.addWidget(self.lbl_opacity)
        ov.addLayout(op_row)

        pad_row = QHBoxLayout()
        pad_row.setSpacing(10)
        lbl_pad = QLabel(tr("Text padding"))
        lbl_pad.setObjectName("muted")
        lbl_pad.setFixedWidth(100)
        lbl_op.setFixedWidth(100)
        pad_row.addWidget(lbl_pad)
        self.slider_padding = QSlider(Qt.Orientation.Horizontal)
        self.slider_padding.setRange(0, 40)
        self.slider_padding.setToolTip(tr("Space between the text and the edge of the translation box."))
        self.slider_padding.valueChanged.connect(lambda v: self.lbl_padding.setText(f"{v} px"))
        pad_row.addWidget(self.slider_padding, 1)
        self.lbl_padding = QLabel("20 px")
        self.lbl_padding.setObjectName("accentValue")
        self.lbl_padding.setFixedWidth(44)
        self.lbl_padding.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        pad_row.addWidget(self.lbl_padding)
        ov.addLayout(pad_row)
        card.body.addWidget(self.overlay_options)

        # Text wait time (debounce)
        speed_row = QHBoxLayout()
        speed_row.setSpacing(10)
        lbl_speed = QLabel(tr("Wait for the text"))
        lbl_speed.setObjectName("muted")
        speed_row.addWidget(lbl_speed)
        self.slider_debounce = QSlider(Qt.Orientation.Horizontal)
        self.slider_debounce.setRange(50, 400)
        self.slider_debounce.setSingleStep(10)
        self.slider_debounce.setPageStep(50)
        self.slider_debounce.valueChanged.connect(lambda v: self.lbl_debounce.setText(f"{v} ms"))
        self.slider_debounce.setToolTip(tr(
            "How long the screen must stay still before reading.\n"
            "Lower = translates faster; higher = avoids reading text that is still being typed."
        ))
        speed_row.addWidget(self.slider_debounce, 1)
        self.lbl_debounce = QLabel("200 ms")
        self.lbl_debounce.setObjectName("accentValue")
        self.lbl_debounce.setFixedWidth(52)
        self.lbl_debounce.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        speed_row.addWidget(self.lbl_debounce)
        card.body.addLayout(speed_row)

        self.chk_context = QCheckBox(tr("Use previous lines as context"))
        self.chk_context.setToolTip(tr(
            "The AI receives the latest lines already translated to get gender, pronouns and omitted subjects right. "
            "Makes each translation a little slower; clear it if you prefer speed."
        ))
        card.body.addWidget(self.chk_context)

        self.chk_minimize = QCheckBox(tr("Minimize this window on start"))
        self.chk_minimize.setChecked(True)
        card.body.addWidget(self.chk_minimize)

        # Groq API key (kept in the Windows Credential Manager, never shown)
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        lbl_key = QLabel(tr("AI key (Groq)"))
        lbl_key.setObjectName("muted")
        key_row.addWidget(lbl_key)
        self.lbl_key_status = QLabel("")
        self.lbl_key_status.setObjectName("hint")
        self.lbl_key_status.setWordWrap(True)
        key_row.addWidget(self.lbl_key_status, 1)
        self.btn_key_set = QPushButton(tr("Set key…"))
        self.btn_key_set.setToolTip(tr("Free key at console.groq.com/keys. It is stored in the Windows Credential Manager, not in a text file."))
        self.btn_key_set.clicked.connect(self.on_set_key)
        key_row.addWidget(self.btn_key_set)
        self.btn_key_remove = QPushButton(tr("Remove"))
        self.btn_key_remove.clicked.connect(self.on_remove_key)
        key_row.addWidget(self.btn_key_remove)
        card.body.addLayout(key_row)
        self.refresh_key_status()
        return card

    def _build_action_card(self):
        card = Card()

        self.btn_toggle_start = QPushButton(tr("  Start translation"))
        self.btn_toggle_start.setProperty("variant", "primary")
        self.btn_toggle_start.setIcon(icon("play", "#04101f", 18))
        self.btn_toggle_start.setIconSize(QSize(18, 18))
        self.btn_toggle_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_start.clicked.connect(self.toggle_translation)
        card.body.addWidget(self.btn_toggle_start)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        card.body.addWidget(self.progress_bar)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.btn_pause = QPushButton(tr(" Pause"))
        self.btn_pause.setIcon(icon("pause", TEXT, 16))
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.toggle_pause)
        controls.addWidget(self.btn_pause)

        self.btn_reload = QPushButton(tr(" Retranslate"))
        self.btn_reload.setIcon(icon("refresh", TEXT, 16))
        self.btn_reload.setEnabled(False)
        self.btn_reload.setToolTip(tr("Forces a re-read and a new translation of the scene now"))
        self.btn_reload.clicked.connect(self.force_reload)
        controls.addWidget(self.btn_reload)

        self.btn_history = QPushButton(tr(" History"))
        self.btn_history.setIcon(icon("history", TEXT, 16))
        self.btn_history.clicked.connect(self.open_history)
        controls.addWidget(self.btn_history)

        self.btn_logs = QPushButton(tr(" Logs"))
        self.btn_logs.setIcon(icon("folder", TEXT, 16))
        self.btn_logs.setToolTip(tr("Open the log files folder"))
        self.btn_logs.clicked.connect(open_log_folder)
        controls.addWidget(self.btn_logs)

        for b in (self.btn_pause, self.btn_reload, self.btn_history, self.btn_logs):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        card.body.addLayout(controls)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(tr("Interface language")))
        self.combo_ui_language = QComboBox()
        for code, name in UI_LANGUAGES.items():
            self.combo_ui_language.addItem(name, code)
        self.combo_ui_language.setCurrentIndex(self.combo_ui_language.findData(ui_language()))
        self.combo_ui_language.currentIndexChanged.connect(self.on_ui_language_changed)
        lang_row.addWidget(self.combo_ui_language, 1)
        card.body.addLayout(lang_row)

        self.chk_updates = QCheckBox(tr("Check for updates when the app opens"))
        self.chk_updates.setToolTip(tr("Only reads the latest version number from GitHub. Nothing is downloaded or installed."))
        card.body.addWidget(self.chk_updates)

        version = QLabel(f"OCR Translator {__version__}")
        version.setObjectName("hint")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        card.body.addWidget(version)

        self.btn_restore = QPushButton(tr("Restore default settings"))
        self.btn_restore.setProperty("variant", "ghost")
        self.btn_restore.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_restore.clicked.connect(self.restore_defaults)
        card.body.addWidget(self.btn_restore, 0, Qt.AlignmentFlag.AlignHCenter)
        return card
