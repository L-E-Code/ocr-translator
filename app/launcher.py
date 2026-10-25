import copy
import os
import sys
import subprocess
from dotenv import load_dotenv

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QFrame, QMessageBox,
    QProgressBar, QApplication, QScrollArea, QSlider, QListWidget, QLineEdit, QInputDialog,
    QMenu, QSystemTrayIcon, QKeySequenceEdit, QBoxLayout
)
from PyQt6.QtGui import QKeySequence, QDesktopServices
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QUrl

from capture import (
    get_available_monitors, get_roi_region, save_custom_roi, list_windows, foreground_window_title,
    region_to_window_relative, resolve_region
)
from hotkeys import GlobalHotkeys
from selector import select_region_interactive
from languages import LANGUAGES
from dictionary import get_dictionary
from worker import WorkerThread
from sidebar import SidebarWindow
from overlay import OverlayWindow
from history_window import HistoryWindow
import config_manager
import ui_theme
from device import available_gpus, installed_gpu_names, gpu_vendor, KIND_LABELS
from ui_theme import (
    Card, StatusPill, SegmentedControl, RegionPreview,
    icon, set_variant, TEXT
)
from logger_config import get_logger, open_log_folder
from i18n import tr, ui_language, set_ui_language, UI_LANGUAGES
from glossary import glossary_path, list_glossary_files
from paths import root_path, FROZEN
import secrets_store
import updater
from version import __version__, RELEASES_URL
from glossary_editor import GlossaryEditor

logger = get_logger("Launcher")
load_dotenv(root_path(".env"))


class ModelInitWorker(QThread):
    """
    Background thread that initializes the OCR/Translation models
    without freezing the user interface.
    """
    finished_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, source_lang, target_lang, device_preference="auto"):
        super().__init__()
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.device_preference = device_preference

    def run(self):
        logger.info(f"ModelInitWorker: Loading OCR/Translation engines ({self.source_lang} -> {self.target_lang})...")
        try:
            from ocr import OCRTranslator  # heavy import: only here, outside the interface thread
            config = config_manager.load_config()
            regions = [config.get("last_custom_roi")] + list(config.get("extra_regions") or [])
            engine = OCRTranslator(
                source_lang=self.source_lang,
                target_lang=self.target_lang,
                device_preference=self.device_preference,
                groq_models=config.get("groq_models"),
                context_lines=config.get("translation_context", 3),
                warm_shapes=[(r["width"], r["height"]) for r in regions if r and r.get("width") and r.get("height")],
            )
            logger.info("ModelInitWorker: Engines initialized successfully.")
            self.finished_signal.emit(engine)
        except Exception as e:
            logger.error(f"ModelInitWorker: Failed to load engines: {e}", exc_info=True)
            self.error_signal.emit(str(e))


class RuntimeProbe(QThread):
    """
    Imports PyTorch and the OCR engine in the background right after the window opens, and reports the usable
    GPUs. By the time the user clicks start, the heavy libraries are usually already loaded.
    """
    gpus_ready = pyqtSignal(list)

    def run(self):
        try:
            self.gpus_ready.emit(available_gpus())
        except Exception as e:
            logger.warning(f"Failed to query the GPUs: {e}")
            self.gpus_ready.emit([])
        try:
            import ocr  # noqa: F401  (warms up the OCR imports for the start of the translation)
        except Exception as e:
            logger.warning(f"OCR preload failed: {e}")


class UpdateCheck(QThread):
    """Asks GitHub for the latest release in the background (only reads the version)."""
    found = pyqtSignal(dict)

    def run(self):
        release = updater.check_for_update()
        if release:
            self.found.emit(release)


class GpuProbe(QThread):
    """Queries the system's graphics cards without freezing the interface."""
    finished_signal = pyqtSignal(list)

    def run(self):
        self.finished_signal.emit(installed_gpu_names())


class LauncherWindow(QMainWindow):
    """
    Control Center and Main Launcher of OCR Translator.
    """
    def __init__(self):
        super().__init__()
        self.config = config_manager.load_config()
        self.monitors = get_available_monitors()
        self.selected_roi = None
        self.custom_roi = None  # last custom main area (independent of the mode chosen right now)
        self.extra_regions = []  # additional regions of the custom area
        self.profiles = {}
        self.active_profile = None
        self._last_foreground = ""
        self._fallback_active = False
        self.ocr_engine = None
        self.current_engine_langs = (None, None, None)

        self.worker = None
        self.ui_window = None
        self.history_window = None
        self.init_worker = None
        self.gpu_probe = None
        self.runtime_probe = None
        self.gpus = None  # None = still querying; [] = no usable GPU
        self.system_gpus = None
        self.device_label = ""

        self.is_running = False
        self.is_paused = False
        self.update_check = None
        self.update_release = None  # newer release found on GitHub, if any

        # While the saved preferences are applied to the controls, nothing must be written back
        self._loading_settings = True
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_current_settings)

        self.hotkeys = GlobalHotkeys(self)
        self.hotkeys.triggered.connect(self.on_hotkey)
        self.tray = None

        self.initUI()
        self.apply_saved_config()
        self._connect_autosave()
        self._setup_tray()

        # Automatic profile: follows the foreground window while nothing is running
        self._profile_timer = QTimer(self)
        self._profile_timer.setInterval(1000)
        self._profile_timer.timeout.connect(self.auto_profile_tick)
        self._profile_timer.start()

        if self.config.get("check_updates", True):
            QTimer.singleShot(4000, self.start_update_check)  # after the window is up and the first work is done

    # ------------------------------------------------------------------
    # Interface construction
    # ------------------------------------------------------------------
    def initUI(self):
        self.setWindowTitle("OCR Translator")
        self.resize(1040, 700)  # widened below to fit the two columns, when the screen allows
        self.setMinimumSize(500, 460)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("root")

        # Central column with a maximum width: with a maximized window the content does not stretch
        column = QWidget()
        column.setMaximumWidth(1200)
        main_layout = QVBoxLayout(column)
        main_layout.setContentsMargins(22, 20, 22, 22)
        main_layout.setSpacing(14)

        outer = QHBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        outer.addWidget(column, 100)
        outer.addStretch(1)

        scroll_area.setWidget(content)
        self.setCentralWidget(scroll_area)

        main_layout.addLayout(self._build_header())

        # Two columns (capture on the left, translation on the right); a narrow window stacks them
        left = QVBoxLayout()
        left.setSpacing(14)
        left.addWidget(self._build_profile_card())
        left.addWidget(self._build_capture_card())
        left.addStretch()
        right = QVBoxLayout()
        right.setSpacing(14)
        right.addWidget(self._build_translation_card())
        right.addWidget(self._build_hotkeys_card())
        right.addStretch()
        self._column_layouts = (left, right)
        self._columns = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._columns.setSpacing(14)
        self._columns.addLayout(left, 11)
        self._columns.addLayout(right, 9)
        main_layout.addLayout(self._columns)

        main_layout.addWidget(self._build_action_card())
        main_layout.addStretch()

        # Selectors shrink with the column instead of forcing the width of their longest item
        for combo in content.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)

        self._content = content
        self._fitted = False
        screen = QApplication.primaryScreen()
        if screen is not None:
            width = min(max(1120, self._two_column_width()), screen.availableGeometry().width() - 40)
            self.resize(width, self.height())
        self._update_columns()

    def _two_column_width(self):
        """Window width from which the two columns fit side by side (margins, spacing and scrollbar included)."""
        left, right = self._column_layouts
        return left.minimumSize().width() + right.minimumSize().width() + self._columns.spacing() + 22 * 2 + 24

    def _update_columns(self):
        wide = self.width() >= self._two_column_width()
        direction = QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom
        if self._columns.direction() != direction:
            self._columns.setDirection(direction)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_columns"):
            self._update_columns()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            # Only after the window is shown does the layout know the real height of the content
            QTimer.singleShot(0, self._fit_height_to_content)

    def _fit_height_to_content(self):
        """Opens at the exact height of the content (no scrollbar), limited to the usable screen area."""
        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()
        frame_extra = self.frameGeometry().height() - self.geometry().height()
        needed = self._content.sizeHint().height() + 2
        height = max(self.minimumHeight(), min(needed, area.height() - frame_extra - 20))
        self.resize(self.width(), height)
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())

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

        self.seg_style = SegmentedControl()
        self.radio_style_inplace = self.seg_style.add(tr("Cover the original text"), 1)
        self.radio_style_subtitle = self.seg_style.add(tr("Bottom subtitle"), 2)
        ov.addWidget(self.seg_style)

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

    def running_text(self):
        return tr("Translating · {device}", device=self.device_label) if self.device_label else tr("Translating")

    def _connect_autosave(self):
        """Saves the preferences whenever the user changes something (with a short delay for sliders)."""
        for combo in (self.combo_monitors, self.combo_source, self.combo_target, self.combo_device):
            combo.currentIndexChanged.connect(self.schedule_save)
        for group in (self.roi_group, self.mode_group, self.seg_style.group):
            group.idClicked.connect(self.schedule_save)
        for slider in (self.slider_opacity, self.slider_debounce):
            slider.valueChanged.connect(self.schedule_save)
        self.chk_minimize.toggled.connect(self.schedule_save)
        self.chk_context.toggled.connect(self.schedule_save)
        self.chk_auto_profile.toggled.connect(self.schedule_save)
        self.chk_updates.toggled.connect(self.schedule_save)
        self.edit_window.editingFinished.connect(self.on_window_settings_changed)
        self.chk_track.toggled.connect(self.on_window_settings_changed)
        for edit in self.hotkey_edits.values():
            edit.keySequenceChanged.connect(self.schedule_save)

    def schedule_save(self, *_):
        if not self._loading_settings:
            self._save_timer.start()

    def on_ui_language_changed(self, _index):
        """Saves the interface language and rebuilds the window in it (deferred: the combo being used is replaced)."""
        code = self.combo_ui_language.currentData()
        if code == ui_language():
            return
        QTimer.singleShot(0, lambda: self.apply_ui_language(code))

    def apply_ui_language(self, code):
        """Switches the interface language without restarting. The reading panel and the history, if open, change
        the next time they are created."""
        if code == ui_language():
            return
        self._save_timer.stop()
        self.save_current_settings()
        set_ui_language(code)
        self.config["ui_language"] = code
        config_manager.save_config({"ui_language": code})

        size = self.size()
        self.initUI()  # replaces the central widget; every control is created again in the new language
        self.resize(size)
        self._fitted = True  # keeps the position and size the user already has
        self.apply_saved_config()
        self._connect_autosave()

        if self.is_running:
            self.set_inputs_enabled(False)
            self._set_start_button(True)
            self._set_pause_button(self.is_paused)
            self.btn_pause.setEnabled(True)
            self.btn_reload.setEnabled(True)
            self.set_status(tr("Capture paused") if self.is_paused else self.running_text(),
                            "paused" if self.is_paused else "running")
        elif self.init_worker is not None and self.init_worker.isRunning():
            self.set_inputs_enabled(False)
            self.btn_toggle_start.setEnabled(False)
            self.progress_bar.setVisible(True)
            self.set_status(tr("Loading AI engines…"), "loading")

        if self.tray:
            self.tray.hide()
            self.tray.deleteLater()
            self._setup_tray()
        # Windows that are already open follow the new language too
        if isinstance(self.ui_window, SidebarWindow):
            self.ui_window.retranslate()
            if self._problems:
                self.ui_window.set_problem(self._problem_message())
        if self.history_window:
            self.history_window.retranslate()
        logger.info(f"Interface language changed to '{code}'.")

    # ------------------------------------------------------------------
    # Groq key and updates
    # ------------------------------------------------------------------
    def refresh_key_status(self):
        source = secrets_store.groq_key_source()
        if source == secrets_store.SOURCE_STORE:
            text = tr("Saved in the Windows Credential Manager")
        elif source == secrets_store.SOURCE_ENV:
            text = tr("From the .env file (plain text). Use “Set key…” to store it safely.")
        else:
            text = tr("No key: using the free translators (lower quality)")
        self.lbl_key_status.setText(text)
        self.btn_key_remove.setEnabled(source == secrets_store.SOURCE_STORE)

    def _apply_key_to_engine(self):
        """A key changed: the translation engine already loaded picks it up without restarting."""
        engine = self.ocr_engine
        if engine is not None:
            engine.translator.refresh_groq_client()

    def on_set_key(self):
        text, ok = QInputDialog.getText(
            self, tr("Groq key"), tr("Paste your Groq API key (it is not shown or logged):"),
            QLineEdit.EchoMode.Password)
        text = text.strip()
        if not ok or not text:
            return
        if not text.startswith("gsk_"):
            answer = QMessageBox.question(
                self, tr("Groq key"), tr("This does not look like a Groq key (they start with “gsk_”). Save it anyway?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        saved, error = secrets_store.set_groq_key(text)
        if not saved:
            QMessageBox.critical(self, tr("Error"), tr("Could not save the key:\n{e}", e=error))
            return
        self.refresh_key_status()
        self._apply_key_to_engine()
        self.set_status(tr("Key saved"), "idle")

    def on_remove_key(self):
        answer = QMessageBox.question(
            self, tr("Groq key"), tr("Remove the key saved in the Windows Credential Manager?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        secrets_store.delete_groq_key()
        self.refresh_key_status()
        self._apply_key_to_engine()
        self.set_status(tr("Key removed"), "idle")

    def start_update_check(self):
        if self.update_check is not None or not self.chk_updates.isChecked():
            return
        self.update_check = UpdateCheck()
        self.update_check.found.connect(self.on_update_found)
        self.update_check.start()

    def on_update_found(self, release):
        self.update_release = release
        self._show_update_label()
        if self.tray and not self.isVisible():
            self.notify(tr("Version {version} is available.", version=release["version"]))

    def _show_update_label(self):
        release = getattr(self, "update_release", None)
        label = getattr(self, "lbl_update", None)
        if label is None:
            return
        if release:
            label.setText(f'<a href="{release["url"]}" style="color:{ui_theme.WARN};">'
                          + tr("Update available: {version}", version=release["version"]) + "</a>")
        label.setVisible(bool(release))

    def restore_defaults(self):
        """Resets every preference to its default, after confirming."""
        answer = QMessageBox.question(
            self, tr("Restore defaults"),
            tr("All preferences (monitor, areas, languages, display mode, speed settings "
            "and hotkeys) will go back to their default values. Your saved profiles are kept. Continue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._save_timer.stop()
        self.config = config_manager.reset_config()
        self.apply_saved_config()
        self.set_status(tr("Settings restored"), "idle")
        logger.info("Preferences restored to their default values.")

    def set_status(self, text, kind="idle"):
        self.status.set_state(text, kind)

    # ------------------------------------------------------------------
    # Processing (CPU / GPU)
    # ------------------------------------------------------------------
    def setup_device_options(self):
        """Detects usable GPUs in the background (PyTorch takes a while to import)."""
        self._last_device_index = self.combo_device.currentIndex()
        if self.runtime_probe is None:
            self.runtime_probe = RuntimeProbe()
            self.runtime_probe.gpus_ready.connect(self.on_gpus_detected)
            self.runtime_probe.start()
        elif self.gpus is not None:
            self.on_gpus_detected(self.gpus)
        self.update_device_hint()

    def on_gpus_detected(self, gpus):
        """With no usable GPU, finds out which card is installed to guide the user."""
        self.gpus = gpus
        if not gpus and self.combo_device.currentData() == "gpu":
            self.combo_device.setCurrentIndex(0)
        self._last_device_index = self.combo_device.currentIndex()
        if not gpus and self.system_gpus is None and self.gpu_probe is None:
            self.gpu_probe = GpuProbe()
            self.gpu_probe.finished_signal.connect(self.on_gpu_probe_done)
            self.gpu_probe.start()
        self.update_device_hint()

    def on_device_chosen(self, index):
        """Choosing a GPU without installed support offers to download what is missing."""
        if self.combo_device.itemData(index) == "gpu" and self.gpus is not None and not self.gpus:
            if not self.offer_gpu_support():
                self.combo_device.setCurrentIndex(self._last_device_index)
                return
        self._last_device_index = self.combo_device.currentIndex()

    def offer_gpu_support(self):
        """Asks whether to download PyTorch with GPU support. Returns True if the app will close to install."""
        if FROZEN:
            # The portable build carries its own PyTorch: it cannot install another one over itself
            QMessageBox.information(
                self, tr("GPU support"),
                tr("This portable version uses the CPU. For the GPU, download the GPU version from the releases page:\n{url}",
                   url=RELEASES_URL))
            return False
        names = self.system_gpus if self.system_gpus is not None else installed_gpu_names()
        self.system_gpus = names
        vendor_pkg = {"intel": ("Intel Arc", "intel"), "nvidia": ("NVIDIA", "nvidia")}
        found = next(((n, vendor_pkg[gpu_vendor(n)]) for n in names if gpu_vendor(n) in vendor_pkg), None)

        if found is None:
            QMessageBox.information(
                self, tr("GPU not found"),
                tr("I did not find a compatible graphics card (NVIDIA or Intel Arc) on this computer.\n"
                "Processing will continue on the CPU.")
            )
            return False

        gpu_name, (family, package) = found
        if sys.platform != "win32":
            QMessageBox.information(
                self, tr("GPU support"),
                tr("Graphics card detected: {gpu_name}.\nInstall the PyTorch build for {family} manually.", gpu_name=gpu_name, family=family)
            )
            return False

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("Enable the GPU"))
        box.setText(tr("Graphics card detected: {gpu_name}", gpu_name=gpu_name))
        box.setInformativeText(
            tr("To use the GPU you need to download the PyTorch build with {family} support "
            "(over 2 GB).\n\n"
            "OCR Translator will be closed, the installation runs in a terminal window "
            "and the app reopens by itself when it finishes. Download now?", family=family)
        )
        yes = box.addButton(tr("Download and install"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Not now"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return False

        root = root_path()
        script = os.path.join(root, "install_gpu.bat")
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "GPU Support - OCR Translator", script, package, str(os.getpid()), "relaunch"],
                cwd=root,
            )
        except Exception as e:
            logger.error(f"Failed to start the GPU installer: {e}")
            QMessageBox.critical(self, tr("Error"), tr("Could not start the installer:\n{e}", e=e))
            return False

        logger.info("GPU support installer started; closing the application.")
        self.close()
        QApplication.quit()
        return True

    def on_gpu_probe_done(self, names):
        self.system_gpus = names
        self.update_device_hint()

    def update_device_hint(self, *_):
        pref = self.combo_device.currentData()
        if self.gpus:
            kind, name = self.gpus[0]
            if pref == "cpu":
                text = tr("GPU available ({name}), but CPU mode is selected.", name=name)
            else:
                text = tr("Will use the GPU: {name} ({kind}).", name=name, kind=KIND_LABELS.get(kind, kind))
        elif self.system_gpus is None:
            text = tr("Checking graphics card…")
        else:
            usable = [n for n in self.system_gpus if gpu_vendor(n) in ("nvidia", "intel")]
            if usable:
                text = tr("Graphics card detected: {gpu}, but PyTorch support is missing. "
                        "Choose \"GPU\" to download and enable it.", gpu=usable[0])
            else:
                text = tr("No compatible GPU found. Processing will run on the CPU.")
        self.lbl_device_hint.setText(text)

    def update_overlay_options_visibility(self, *_):
        self.overlay_options.setVisible(self.radio_overlay.isChecked())

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def apply_saved_config(self):
        """Loads and applies the preferences saved in config.json."""
        self._loading_settings = True
        try:
            self._apply_saved_config()
        finally:
            self._loading_settings = False

    def _apply_saved_config(self):
        # Profiles, game window, regions and hotkeys
        self.profiles = self.config.setdefault("profiles", {})
        self.glossary_file = self.config.get("glossary_file")
        self.refresh_glossary_combo()
        active = self.config.get("active_profile")
        self.active_profile = active if active in self.profiles else None
        self.chk_auto_profile.setChecked(self.config.get("auto_profile", True))
        self.refresh_profile_combo()
        hotkeys = self.config.get("hotkeys", {})
        for action, edit in self.hotkey_edits.items():
            edit.setKeySequence(QKeySequence(hotkeys.get(action, "")))
        self.edit_window.setText(self.config.get("window_title", ""))
        self.chk_track.setChecked(self.config.get("track_window", False))
        self.extra_regions = copy.deepcopy(self.config.get("extra_regions", []))

        # Monitor
        mon_idx = self.config.get("monitor_index", 0)
        if 0 <= mon_idx < self.combo_monitors.count():
            self.combo_monitors.setCurrentIndex(mon_idx)

        # Languages
        src = self.config.get("source_lang", "ja")
        tgt = self.config.get("target_lang", "en")
        self.combo_source.setCurrentIndex(max(0, self.combo_source.findData(src)))
        self.combo_target.setCurrentIndex(max(0, self.combo_target.findData(tgt)))

        # Display mode
        mode = self.config.get("display_mode", "sidebar")
        (self.radio_overlay if mode == "overlay" else self.radio_sidebar).setChecked(True)
        (self.radio_style_subtitle if self.config.get("overlay_mode") == "subtitle"
         else self.radio_style_inplace).setChecked(True)
        try:
            opacity = int(round(float(self.config.get("overlay_opacity", 1.0)) * 100))
        except (TypeError, ValueError):
            opacity = 100
        self.slider_opacity.setValue(min(100, max(30, opacity)))
        self.lbl_opacity.setText(f"{self.slider_opacity.value()}%")
        self.update_overlay_options_visibility()

        # Processing
        idx = self.combo_device.findData(self.config.get("compute_device", "auto"))
        self.combo_device.setCurrentIndex(idx if idx >= 0 else 0)
        self.setup_device_options()

        # Text wait and window
        try:
            debounce = int(self.config.get("debounce_ms", 200))
        except (TypeError, ValueError):
            debounce = 200
        self.slider_debounce.setValue(min(400, max(50, debounce)))
        self.lbl_debounce.setText(f"{self.slider_debounce.value()} ms")
        self.chk_minimize.setChecked(self.config.get("minimize_on_start", True))
        self.chk_updates.setChecked(self.config.get("check_updates", True))
        self.chk_context.setChecked(self.config.get("translation_context", 3) > 0)

        # ROI Mode
        roi_mode = self.config.get("roi_mode", "bottom_third")
        custom_roi = self.config.get("last_custom_roi")
        current_mon = self.get_current_monitor()

        self.custom_roi = copy.deepcopy(custom_roi)
        is_custom_valid = False
        if custom_roi and custom_roi.get("rel"):
            is_custom_valid = True  # attached to the game window: the position is recomputed on every capture
        elif custom_roi and current_mon:
            mon_left = current_mon['left']
            mon_top = current_mon['top']
            mon_right = mon_left + current_mon['width']
            mon_bottom = mon_top + current_mon['height']
            roi_left = custom_roi.get('left', 0)
            roi_top = custom_roi.get('top', 0)
            if mon_left <= roi_left < mon_right and mon_top <= roi_top < mon_bottom:
                is_custom_valid = True

        if roi_mode == "custom" and is_custom_valid:
            self.radio_custom.setChecked(True)
            self.selected_roi = self.custom_roi
        elif roi_mode == "bottom_half":
            self.radio_half.setChecked(True)
            self.selected_roi = get_roi_region(current_mon, "bottom_half") if current_mon else None
        elif roi_mode == "full":
            self.radio_full.setChecked(True)
            self.selected_roi = get_roi_region(current_mon, "full") if current_mon else None
        else:
            self.radio_third.setChecked(True)
            self.selected_roi = get_roi_region(current_mon, "bottom_third") if current_mon else None

        self.update_roi_info_label()

    def get_current_monitor(self):
        idx = self.combo_monitors.currentIndex()
        if 0 <= idx < len(self.monitors):
            return self.monitors[idx]
        return self.monitors[0] if self.monitors else None

    def on_monitor_changed(self):
        mon = self.get_current_monitor()
        if not mon:
            return
        if self.radio_custom.isChecked():
            if self.selected_roi:
                mon_left = mon['left']
                mon_top = mon['top']
                mon_right = mon_left + mon['width']
                mon_bottom = mon_top + mon['height']
                r_left = self.selected_roi.get('left', 0)
                r_top = self.selected_roi.get('top', 0)
                if not (mon_left <= r_left < mon_right and mon_top <= r_top < mon_bottom):
                    self.radio_third.setChecked(True)
                    self.selected_roi = get_roi_region(mon, "bottom_third")
        else:
            self.on_roi_mode_changed()
        self.update_roi_info_label()

    def on_roi_mode_changed(self):
        mon = self.get_current_monitor()
        if not mon:
            return

        if self.radio_third.isChecked():
            self.selected_roi = get_roi_region(mon, "bottom_third")
        elif self.radio_half.isChecked():
            self.selected_roi = get_roi_region(mon, "bottom_half")
        elif self.radio_full.isChecked():
            self.selected_roi = get_roi_region(mon, "full")
        elif self.radio_custom.isChecked():
            if self.custom_roi:
                self.selected_roi = self.custom_roi
            else:
                self.on_select_roi_clicked()

        self.update_roi_info_label()

    def on_select_roi_clicked(self):
        mon = self.get_current_monitor()
        if not mon:
            return

        # Temporarily hides the launcher window to allow a clean selection
        self.hide()
        QApplication.processEvents()

        try:
            roi = select_region_interactive(mon, app=QApplication.instance())
        finally:
            self.show()
            self.raise_()

        if roi:
            self.custom_roi = roi
            self.selected_roi = roi
            save_custom_roi(roi)
            self.radio_custom.setChecked(True)
            if self.chk_track.isChecked():
                self.apply_window_binding()
            self.schedule_save()
        else:
            if not self.selected_roi:
                self.radio_third.setChecked(True)
                self.selected_roi = get_roi_region(mon, "bottom_third")

        self.update_roi_info_label()

    def update_roi_info_label(self):
        mon = self.get_current_monitor()
        if not mon:
            self.lbl_roi_info.setText(tr("No monitor detected"))
            return

        self.preview.set_monitor(mon['width'], mon['height'])

        if self.radio_custom.isChecked() and self.selected_roi:
            w = self.selected_roi.get("width", 0)
            h = self.selected_roi.get("height", 0)
            x = self.selected_roi.get("offset_x", 0)
            y = self.selected_roi.get("offset_y", 0)
            extra = tr("  ·  +{n} region(s)", n=len(self.extra_regions)) if self.extra_regions else ""
            text = tr("{w}×{h} px  ·  X {x}, Y {y}{extra}", w=w, h=h, x=x, y=y, extra=extra)
        elif self.radio_third.isChecked():
            roi = get_roi_region(mon, "bottom_third")
            self.selected_roi = roi
            text = f"{roi['width']}×{roi['height']} px"
        elif self.radio_half.isChecked():
            roi = get_roi_region(mon, "bottom_half")
            self.selected_roi = roi
            text = f"{roi['width']}×{roi['height']} px"
        elif self.radio_full.isChecked():
            roi = get_roi_region(mon, "full")
            self.selected_roi = roi
            text = f"{roi['width']}×{roi['height']} px"
        else:
            text = tr("Area not set")
        self.lbl_roi_info.setText(text)

        # Extra regions and window following only make sense in the custom area
        is_custom = self.radio_custom.isChecked()
        self.regions_box.setVisible(is_custom)
        self.chk_track.setEnabled(is_custom)
        self.refresh_regions_list()

        # Monitor thumbnail with the regions highlighted
        if is_custom and self.custom_roi:
            shown = [(r, r.get('label') or tr("capture area")) for r in [self.custom_roi] + self.extra_regions]
        else:
            shown = [(self.selected_roi, tr("capture area"))] if self.selected_roi else []
        previews = []
        for region, label in shown:
            region = resolve_region(region) or region  # regions attached to the window show up where it is now
            previews.append((
                ((region['left'] - mon['left']) / mon['width'], (region['top'] - mon['top']) / mon['height'],
                 region['width'] / mon['width'], region['height'] / mon['height']),
                label if len(shown) > 1 else tr("capture area"),
            ))
        self.preview.set_regions(previews)

    @staticmethod
    def setup_word_dictionary(source_lang):
        """Hooks up the word dictionary (Japanese only); without the libraries, the panel works without it."""
        if source_lang == "ja":
            dictionary = get_dictionary()
            dictionary.load_async()
            ui_theme.set_word_dictionary(dictionary)
        else:
            ui_theme.set_word_dictionary(None)

    def selected_langs(self):
        """(source language, target language) chosen in the selectors."""
        return self.combo_source.currentData(), self.combo_target.currentData()

    def collect_settings(self):
        """All the current choices in the interface, in the config.json format."""
        source_lang, target_lang = self.selected_langs()
        display_mode = "overlay" if self.radio_overlay.isChecked() else "sidebar"

        roi_mode = "bottom_third"
        if self.radio_custom.isChecked():
            roi_mode = "custom"
        elif self.radio_half.isChecked():
            roi_mode = "bottom_half"
        elif self.radio_full.isChecked():
            roi_mode = "full"

        settings = {
            "monitor_index": self.combo_monitors.currentIndex(),
            "source_lang": source_lang,
            "target_lang": target_lang,
            "display_mode": display_mode,
            "roi_mode": roi_mode,
            "minimize_on_start": self.chk_minimize.isChecked(),
            "overlay_mode": "subtitle" if self.radio_style_subtitle.isChecked() else "inplace",
            "overlay_opacity": round(self.slider_opacity.value() / 100, 2),
            "debounce_ms": self.slider_debounce.value(),
            "compute_device": self.combo_device.currentData(),
            "last_custom_roi": self.custom_roi,
            "extra_regions": self.extra_regions,
            "window_title": self.edit_window.text().strip(),
            "track_window": self.chk_track.isChecked(),
            "glossary_file": self.glossary_file,
            "auto_profile": self.chk_auto_profile.isChecked(),
            "check_updates": self.chk_updates.isChecked(),
            "translation_context": 3 if self.chk_context.isChecked() else 0,
            "hotkeys": {a: e.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                        for a, e in self.hotkey_edits.items()},
        }
        return settings

    def save_current_settings(self):
        """Persists the current choices in config.json (and in the active profile, if any)."""
        settings = self.collect_settings()
        if self.active_profile in self.profiles:
            self.profiles[self.active_profile] = self.profile_snapshot(settings)
        settings["profiles"] = self.profiles
        settings["active_profile"] = self.active_profile
        self.config.update(copy.deepcopy(settings))
        config_manager.save_config(settings)

    def set_inputs_enabled(self, enabled):
        """Locks the settings fields while running."""
        for w in (
            self.combo_monitors, self.combo_source, self.combo_target, self.combo_device,
            self.radio_third, self.radio_half, self.radio_full, self.radio_custom,
            self.radio_sidebar, self.radio_overlay,
            self.radio_style_inplace, self.radio_style_subtitle, self.slider_opacity,
            self.slider_debounce, self.btn_select_roi, self.btn_restore, self.chk_context,
            self.combo_profile, self.btn_profile_new, self.btn_profile_more, self.chk_auto_profile,
            self.combo_glossary, self.btn_glossary_new,
            self.edit_window, self.btn_pick_window, self.chk_track, self.btn_add_region, self.btn_remove_region,
            *self.hotkey_edits.values(),
        ):
            w.setEnabled(enabled)
        if enabled:
            self.update_roi_info_label()  # reapplies what only applies to the custom area

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------
    @staticmethod
    def profile_snapshot(settings):
        return {k: copy.deepcopy(settings[k]) for k in config_manager.PROFILE_KEYS if k in settings}

    def refresh_profile_combo(self):
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        self.combo_profile.addItem(tr("No profile (current settings)"), None)
        for name in sorted(self.profiles, key=str.lower):
            self.combo_profile.addItem(name, name)
        idx = self.combo_profile.findData(self.active_profile)
        self.combo_profile.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_profile.blockSignals(False)
        self.btn_profile_more.setEnabled(self.active_profile is not None and not self.is_running)

    def on_profile_chosen(self, index):
        self.apply_profile(self.combo_profile.itemData(index))

    def apply_profile(self, name):
        """Loads a profile into the controls (or just detaches it, with name=None)."""
        if name is not None and name not in self.profiles:
            return
        if name is not None:
            cfg = dict(self.config)
            for key in config_manager.PROFILE_KEYS:
                cfg[key] = copy.deepcopy(self.profiles[name].get(key, config_manager.DEFAULT_CONFIG.get(key)))
            self.config = cfg
        self.config["active_profile"] = name
        self.apply_saved_config()
        self.save_current_settings()
        logger.info(f"Active profile: {name or 'none'}")

    def on_new_profile(self):
        suggestion = self.active_profile or self.edit_window.text().strip()[:40]
        name, ok = QInputDialog.getText(self, tr("Save profile"), tr("Profile name (for example, the game's name):"),
                                        text=suggestion)
        name = name.strip()[:40]
        if not ok or not name:
            return
        if name in self.profiles and name != self.active_profile:
            answer = QMessageBox.question(self, tr("Replace profile"), tr("A profile named “{name}” already exists. Replace it?", name=name),
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.profiles[name] = self.profile_snapshot(self.collect_settings())
        self.active_profile = name
        self.refresh_profile_combo()
        self.save_current_settings()
        self.set_status(tr("Profile “{name}” saved", name=name), "idle")

    def on_delete_profile(self):
        name = self.active_profile
        if name is None:
            return
        answer = QMessageBox.question(self, tr("Delete profile"), tr("Delete the profile “{name}”?", name=name),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.profiles.pop(name, None)
        self.active_profile = None
        self.refresh_profile_combo()
        self.save_current_settings()
        self.set_status(tr("Profile “{name}” deleted", name=name), "idle")

    def _ask_profile_name(self, title, suggestion):
        """Asks for a profile name that is not used by another profile; '' if cancelled."""
        while True:
            name, ok = QInputDialog.getText(self, title, tr("Profile name (for example, the game's name):"), text=suggestion)
            name = name.strip()[:40]
            if not ok or not name:
                return ""
            if name in self.profiles and name != self.active_profile:
                QMessageBox.information(self, title, tr("A profile named “{name}” already exists.", name=name))
                suggestion = name
                continue
            return name

    def on_rename_profile(self):
        old = self.active_profile
        if old is None:
            return
        name = self._ask_profile_name(tr("Rename profile"), old)
        if not name or name == old:
            return
        # Keeps the position of the profile in the dictionary
        self.profiles = {(name if k == old else k): v for k, v in self.profiles.items()}
        self.active_profile = name
        self.refresh_profile_combo()
        self.save_current_settings()
        self.set_status(tr("Profile “{name}” renamed", name=name), "idle")

    def on_duplicate_profile(self):
        source = self.active_profile
        if source is None:
            return
        self.save_current_settings()  # the copy starts from what is on screen now
        name = self._ask_profile_name(tr("Duplicate profile"), tr("{name} (copy)", name=source)[:40])
        if not name:
            return
        self.profiles[name] = copy.deepcopy(self.profiles[source])
        self.active_profile = name
        self.refresh_profile_combo()
        self.save_current_settings()
        self.set_status(tr("Profile “{name}” saved", name=name), "idle")

    # ------------------------------------------------------------------
    # Glossary
    # ------------------------------------------------------------------
    def refresh_glossary_combo(self):
        default_name = os.path.basename(glossary_path())
        files = [f for f in list_glossary_files() if f != default_name]
        if self.glossary_file and self.glossary_file not in files and self.glossary_file != default_name:
            files.append(self.glossary_file)  # chosen file that no longer exists: keeps showing it
        self.combo_glossary.blockSignals(True)
        self.combo_glossary.clear()
        self.combo_glossary.addItem(tr("Default ({name})", name=default_name), None)
        for f in files:
            self.combo_glossary.addItem(f, f)
        self.combo_glossary.setCurrentIndex(max(0, self.combo_glossary.findData(self.glossary_file)))
        self.combo_glossary.blockSignals(False)

    def on_glossary_chosen(self, index):
        self.glossary_file = self.combo_glossary.itemData(index)
        self.schedule_save()

    def on_edit_glossary(self):
        source, target = self.selected_langs()
        GlossaryEditor(self.glossary_file, source, target, self).exec()

    def on_new_glossary(self):
        text, ok = QInputDialog.getText(self, tr("New glossary"), tr("Name (for example, the game's name):"),
                                        text=self.active_profile or self.edit_window.text().strip()[:30])
        slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in text.strip()).strip("_")[:40]
        if not ok or not slug:
            return
        filename = f"glossary_{slug}.json"
        path = glossary_path(filename)
        if not os.path.exists(path):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("{}\n")
            except OSError as e:
                QMessageBox.critical(self, tr("Error"), tr("Could not save the file:\n{e}", e=e))
                return
        self.glossary_file = filename
        self.refresh_glossary_combo()
        self.schedule_save()
        self.on_edit_glossary()

    def auto_profile_tick(self):
        """Loads the profile whose 'Game window' matches the foreground window."""
        if self.is_running or not self.profiles or not self.chk_auto_profile.isChecked():
            return
        title = foreground_window_title(exclude_pid=os.getpid())
        if not title or title == self._last_foreground:
            return
        self._last_foreground = title
        low = title.lower()
        matches = [(len(p["window_title"]), name) for name, p in self.profiles.items()
                   if p.get("window_title") and p["window_title"].lower() in low]
        if not matches:
            return
        name = max(matches)[1]
        if name != self.active_profile:
            self.apply_profile(name)
            self.set_status(tr("Profile “{name}” activated by the game window", name=name), "idle")

    # ------------------------------------------------------------------
    # Capture regions and game window
    # ------------------------------------------------------------------
    def custom_region_list(self):
        return ([self.custom_roi] if self.custom_roi else []) + self.extra_regions

    def refresh_regions_list(self):
        self.list_regions.clear()
        for i, region in enumerate(self.custom_region_list()):
            name = region.get("label") or (tr("Main") if i == 0 else tr("Region {n}", n=i + 1))
            bound = tr("  ·  attached to the window") if region.get("rel") else ""
            self.list_regions.addItem(tr("{name}  ·  {w}×{h} px{bound}", name=name, w=region['width'], h=region['height'], bound=bound))
        self.btn_remove_region.setEnabled(len(self.extra_regions) > 0)

    def on_add_region(self):
        mon = self.get_current_monitor()
        if not mon:
            return
        if not self.radio_custom.isChecked() or not self.custom_roi:
            QMessageBox.information(self, tr("Additional region"),
                                    tr("First choose \"Custom\" and select the main area."))
            return
        if len(self.custom_region_list()) >= config_manager.MAX_REGIONS:
            QMessageBox.information(self, tr("Additional region"),
                                    tr("The limit is {n} regions.", n=config_manager.MAX_REGIONS))
            return
        self.hide()
        QApplication.processEvents()
        try:
            roi = select_region_interactive(mon, app=QApplication.instance())
        finally:
            self.show()
            self.raise_()
        if not roi:
            return
        taken = {(r.get("label") or "Main") for r in self.custom_region_list()}
        label, ok = QInputDialog.getText(self, tr("Region name"), tr("Name (for example: menu, names, subtitle):"),
                                         text=tr("Region {n}", n=len(taken) + 1))
        label = label.strip()[:30]
        if not ok or not label:
            return
        while label in taken:
            label = (label + " 2")[:30]
        roi["label"] = label
        self.extra_regions.append(roi)
        if self.chk_track.isChecked():
            self.apply_window_binding()
        self.update_roi_info_label()
        self.schedule_save()

    def on_remove_region(self):
        row = self.list_regions.currentRow()
        if row < 1:
            QMessageBox.information(self, tr("Remove region"),
                                    tr("Select an additional region. The main one is changed with "
                                    "\"Select area with the mouse\"."))
            return
        del self.extra_regions[row - 1]
        self.update_roi_info_label()
        self.schedule_save()

    def on_pick_window(self):
        menu = QMenu(self)
        windows = list_windows(exclude_pid=os.getpid())
        if not windows:
            menu.addAction(tr("No window found")).setEnabled(False)
        for _, title in windows[:25]:
            shown = title if len(title) <= 70 else title[:67] + "…"
            menu.addAction(shown).setData(title)
        chosen = menu.exec(self.btn_pick_window.mapToGlobal(self.btn_pick_window.rect().bottomLeft()))
        if chosen is not None and chosen.data():
            self.edit_window.setText(chosen.data())
            self.on_window_settings_changed()

    def on_window_settings_changed(self, *_):
        if self._loading_settings:
            return
        self.apply_window_binding()
        self.schedule_save()

    def apply_window_binding(self):
        """Attaches the custom areas to the game window (relative positions) or detaches them (fixed positions)."""
        regions = self.custom_region_list()
        if not regions:
            return
        title = self.edit_window.text().strip()
        want_track = self.chk_track.isChecked()
        if want_track and not title:
            self.set_status(tr("Enter the game window in order to follow it"), "paused")
            self._set_track_checked(False)
            want_track = False

        updated = []
        for region in regions:
            absolute = (resolve_region(region) or region) if region.get("rel") else region
            if want_track:
                bound = region_to_window_relative(absolute, title)
                if bound is None:
                    self.set_status(tr("Window “{title}” not found: open the game and try again", title=title), "paused")
                    self._set_track_checked(False)
                    return
                updated.append(bound)
            else:
                loose = dict(absolute)
                loose.pop("rel", None)
                loose.pop("window_title", None)
                updated.append(loose)

        if self.custom_roi:
            self.custom_roi = updated[0]
            save_custom_roi(self.custom_roi)
            updated = updated[1:]
            if self.radio_custom.isChecked():
                self.selected_roi = self.custom_roi
        self.extra_regions = updated
        self.update_roi_info_label()

    def _set_track_checked(self, value):
        self.chk_track.blockSignals(True)
        self.chk_track.setChecked(value)
        self.chk_track.blockSignals(False)

    def build_capture_regions(self):
        """Regions the worker will read: the chosen area or, in custom mode, the main one and the extras."""
        if not (self.radio_custom.isChecked() and self.custom_roi):
            return [dict(self.selected_roi)]
        regions = [dict(r) for r in self.custom_region_list()]
        if len(regions) == 1:
            regions[0].pop("label", None)
        else:
            regions[0].setdefault("label", "Main")
        return regions

    # ------------------------------------------------------------------
    # System tray and global hotkeys
    # ------------------------------------------------------------------
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(ui_theme.app_icon(), self)
        self.tray.setToolTip("OCR Translator")
        menu = QMenu(self)
        menu.addAction(tr("Show the control center"), self.show_launcher)
        menu.addSeparator()
        self.act_pause = menu.addAction(tr("Pause / resume"), self.toggle_pause)
        self.act_reload = menu.addAction(tr("Retranslate now"), self.force_reload)
        self.act_ui = menu.addAction(tr("Show / hide the panel"), self.toggle_ui_visibility)
        self.act_history = menu.addAction(tr("Open / close the history"), self.toggle_history_window)
        menu.addSeparator()
        menu.addAction(tr("Quit"), self.quit_app)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        # With the launcher hidden in the tray, closing the panel must not end the program
        QApplication.instance().setQuitOnLastWindowClosed(False)
        self._update_tray_actions()

    def _update_tray_actions(self):
        if self.tray:
            for act in (self.act_pause, self.act_reload, self.act_ui, self.act_history):
                act.setEnabled(self.is_running)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_launcher()

    def show_launcher(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self.close()
        QApplication.quit()

    def notify(self, message):
        if self.tray:
            self.tray.showMessage("OCR Translator", message, QSystemTrayIcon.MessageIcon.Information, 6000)
        else:
            self.set_status(message, "paused")

    def start_hotkeys(self):
        bindings = {a: e.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                    for a, e in self.hotkey_edits.items()}
        failed = self.hotkeys.start(bindings)
        if failed:
            names = {"pause": tr("pause"), "reload": tr("retranslate"), "toggle_ui": tr("show/hide"),
                     "history": tr("history"), "clear": tr("clear")}
            self.notify(tr("Hotkey unavailable (in use by another program or invalid): ")
                        + ", ".join(names.get(a, a) for a in failed))

    def on_hotkey(self, action):
        if not self.is_running:
            return
        if action == "pause":
            self.toggle_pause()
        elif action == "reload":
            self.force_reload()
        elif action == "toggle_ui":
            self.toggle_ui_visibility()
        elif action == "history":
            self.toggle_history_window()
        elif action == "clear":
            self.clear_current_text()

    def toggle_history_window(self):
        """Opens the history or, if it is already visible, closes it."""
        history = getattr(self.ui_window, "history_window", None) or self.history_window
        if history is not None and history.isVisible():
            history.hide()
        else:
            self.open_history()

    def clear_current_text(self):
        """Clears the line shown (side panel or overlay)."""
        for name in ("clear_current_view", "_clear_texts"):
            clear = getattr(self.ui_window, name, None)
            if clear:
                clear()
                return

    def toggle_ui_visibility(self):
        if self.ui_window:
            self.ui_window.setVisible(not self.ui_window.isVisible())

    def on_translation_info(self, info):
        """Engine that translated the last cycle: forwards it to the panel and warns in the launcher when it falls back to the backup."""
        if isinstance(self.ui_window, SidebarWindow):
            self.ui_window.update_info(info)
        degraded = bool(info.get("fallback") or info.get("limited") or info.get("engine") == "failed")
        if degraded != self._fallback_active and self.is_running and not self.is_paused:
            self._fallback_active = degraded
            if degraded:
                self.set_status(tr("{status} · backup engine", status=self.running_text()), "paused")
            else:
                self.set_status(self.running_text(), "running")

    def on_capture_status(self, available, title):
        """The followed game window went away (minimized or closed) or came back."""
        if isinstance(self.ui_window, SidebarWindow):
            self.ui_window.set_capture_available(available, title)
        elif not available:
            self.clear_current_text()  # the overlay would keep showing the last line over nothing
        if available:
            if not self.is_paused:
                self.set_status(self.running_text(), "running")
            else:
                self.set_status(tr("Capture paused"), "paused")
            if self.tray and not self.isVisible():
                self.notify(tr("Game window “{title}” found again: translation resumed.", title=title))
        else:
            self.set_status(tr("Game window not found"), "paused")
            logger.info(f"Capture waiting for the game window '{title}'.")

    def on_worker_health(self, kind, working, error):
        """Screen capture or text recognition keeps failing (or is working again)."""
        if working:
            self._problems.pop(kind, None)
        else:
            self._problems[kind] = error
        message = self._problem_message()
        if isinstance(self.ui_window, SidebarWindow):
            self.ui_window.set_problem(message)
        if message:
            self.set_status(tr("Attention"), "error")
            if not working:
                self.notify(self._problem_text(kind, error))
        elif not self.is_paused:
            self.set_status(self.running_text(), "running")

    @staticmethod
    def _problem_text(kind, error):
        if kind == "capture":
            return tr("Screen capture is failing ({error}). Check the selected monitor and area.", error=error)
        return tr("Reading the text failed ({error}). Trying again.", error=error)

    def _problem_message(self):
        return "  ".join(self._problem_text(kind, error) for kind, error in self._problems.items())

    # ------------------------------------------------------------------
    # Translation lifecycle
    # ------------------------------------------------------------------
    def toggle_translation(self):
        if self.is_running:
            self.stop_translation()
        else:
            self.start_translation()

    def _set_start_button(self, running):
        if running:
            self.btn_toggle_start.setText(tr("  Stop translation"))
            self.btn_toggle_start.setIcon(icon("stop", ui_theme.BAD, 18))
            set_variant(self.btn_toggle_start, "danger")
        else:
            self.btn_toggle_start.setText(tr("  Start translation"))
            self.btn_toggle_start.setIcon(icon("play", "#04101f", 18))
            set_variant(self.btn_toggle_start, "primary")

    def _set_pause_button(self, paused):
        if paused:
            self.btn_pause.setText(tr(" Resume"))
            self.btn_pause.setIcon(icon("play", TEXT, 16))
        else:
            self.btn_pause.setText(tr(" Pause"))
            self.btn_pause.setIcon(icon("pause", TEXT, 16))

    def start_translation(self):
        mon = self.get_current_monitor()
        if not mon:
            logger.error("Attempt to start translation with no monitor selected.")
            QMessageBox.critical(self, tr("Error"), tr("No monitor available."))
            return

        if not self.selected_roi:
            self.on_roi_mode_changed()

        source_lang, target_lang = self.selected_langs()
        if source_lang == target_lang:
            QMessageBox.warning(self, tr("Same languages"), tr("Choose a source language different from the target language."))
            return

        self.save_current_settings()
        self.set_inputs_enabled(False)
        self.btn_toggle_start.setEnabled(False)

        device_pref = self.combo_device.currentData()
        logger.info(f"Starting translation with languages: {source_lang} -> {target_lang} (processing: {device_pref})")

        # Checks whether the engine is already loaded for these same languages and device
        if self.ocr_engine and self.current_engine_langs == (source_lang, target_lang, device_pref):
            logger.info("Reusing the OCR engine that is already instantiated.")
            self.on_engine_ready(self.ocr_engine)
        else:
            logger.info("Loading the AI engines in the background...")
            self.set_status(tr("Loading AI engines…"), "loading")
            self.progress_bar.setVisible(True)

            self.init_worker = ModelInitWorker(source_lang, target_lang, device_pref)
            self.init_worker.finished_signal.connect(self.on_engine_ready)
            self.init_worker.error_signal.connect(self.on_engine_error)
            self.init_worker.start()

    def on_engine_ready(self, engine):
        self.ocr_engine = engine
        source_lang, target_lang = self.selected_langs()
        self.current_engine_langs = (source_lang, target_lang, self.combo_device.currentData())
        self.device_label = "GPU" if engine.device != "cpu" else "CPU"
        self.setup_word_dictionary(source_lang)
        self.progress_bar.setVisible(False)

        # Creates the display window
        mon = self.get_current_monitor()
        is_sidebar = self.radio_sidebar.isChecked()

        logger.info(f"Creating display interface: {'Sidebar' if is_sidebar else 'Overlay'}")
        if is_sidebar:
            self.ui_window = SidebarWindow()
            self.ui_window.pause_toggled.connect(self.on_sidebar_pause_toggled)
            self.ui_window.reload_requested.connect(self.force_reload)
            self.ui_window.set_shortcut_hints({
                a: e.keySequence().toString(QKeySequence.SequenceFormat.NativeText)
                for a, e in self.hotkey_edits.items()
            })
        else:
            if not self.history_window:
                self.history_window = HistoryWindow()
            self.ui_window = OverlayWindow(mon, history_window=self.history_window)

        self.ui_window.show()

        # Starts the capture and translation thread
        logger.info("Starting the continuous capture WorkerThread...")
        self.ocr_engine.set_glossary_file(self.config.get("glossary_file"))
        # The engine may have been reused: applies the current context preference
        self.ocr_engine.context_lines = 3 if self.chk_context.isChecked() else 0
        self.worker = WorkerThread(
            self.build_capture_regions(),
            self.ocr_engine,
            debounce_ms=config_manager.load_config().get("debounce_ms", 200)
        )
        self.worker.update_signal.connect(self.ui_window.update_texts)
        self.worker.info_signal.connect(self.on_translation_info)
        self.worker.capture_status.connect(self.on_capture_status)
        self.worker.health_signal.connect(self.on_worker_health)
        self._problems = {}
        if hasattr(self.ui_window, "clear_region"):
            self.worker.region_cleared.connect(self.ui_window.clear_region)
        self.worker.start()

        self.is_running = True
        self.is_paused = False

        self.btn_toggle_start.setEnabled(True)
        self._set_start_button(True)
        self._set_pause_button(False)
        self.btn_pause.setEnabled(True)
        self.btn_reload.setEnabled(True)
        self.set_status(self.running_text(), "running")
        self._fallback_active = False
        self._update_tray_actions()
        self.start_hotkeys()

        if self.chk_minimize.isChecked():
            # With the tray available the launcher disappears from the taskbar; otherwise it just minimizes
            self.hide() if self.tray else self.showMinimized()

    def on_engine_error(self, err_msg):
        logger.error(f"Error reported while loading the AI engine: {err_msg}")
        self.progress_bar.setVisible(False)
        self.set_inputs_enabled(True)
        self.btn_toggle_start.setEnabled(True)
        self.set_status(tr("Failed to load models"), "error")
        QMessageBox.critical(self, tr("Initialization error"), tr("Could not load the AI engines:\n{err}", err=err_msg))

    def stop_translation(self):
        logger.info("Stopping capture and translation...")
        self.set_status(tr("Stopping…"), "loading")
        QApplication.processEvents()

        if self.worker:
            self.worker.stop()
            self.worker.wait(1500)
            self.worker = None

        if self.ui_window:
            self.ui_window.close()
            self.ui_window = None

        self.hotkeys.stop()
        self.is_running = False
        self.is_paused = False
        self._fallback_active = False
        self._update_tray_actions()

        self.set_inputs_enabled(True)
        self._set_start_button(False)
        self._set_pause_button(False)
        self.btn_pause.setEnabled(False)
        self.btn_reload.setEnabled(False)

        self.set_status(tr("Stopped"), "idle")
        logger.info("Translation stopped successfully.")

        # Restores it if minimized or hidden in the tray
        if self.isMinimized() or not self.isVisible():
            self.showNormal()

    def toggle_pause(self):
        if not self.is_running or not self.worker:
            return

        self.is_paused = not self.is_paused
        self.worker.set_paused(self.is_paused)
        self._set_pause_button(self.is_paused)
        if isinstance(self.ui_window, SidebarWindow):
            self.ui_window.set_paused(self.is_paused)  # the panel shows the same state, even when paused from outside

        if self.is_paused:
            logger.info("Translation paused by the user.")
            self.set_status(tr("Capture paused"), "paused")
        else:
            logger.info("Translation resumed by the user.")
            self.set_status(self.running_text(), "running")

    def on_sidebar_pause_toggled(self, is_paused):
        self.is_paused = is_paused
        if self.worker:
            self.worker.set_paused(is_paused)
        self._set_pause_button(is_paused)
        if is_paused:
            logger.info("Translation paused via the side panel.")
            self.set_status(tr("Capture paused"), "paused")
        else:
            logger.info("Translation resumed via the side panel.")
            self.set_status(self.running_text(), "running")

    def force_reload(self):
        if self.worker and self.is_running:
            logger.info("Screen re-read and retranslation requested manually.")
            self.worker.request_reload()
            self.set_status(tr("Reading the screen…"), "busy")
            QTimer.singleShot(
                1200,
                lambda: self.set_status(self.running_text(), "running") if self.is_running and not self.is_paused else None
            )

    def open_history(self):
        logger.info("Opening the history window...")
        if self.ui_window and isinstance(self.ui_window, SidebarWindow):
            self.ui_window.open_history()
        else:
            if not self.history_window:
                self.history_window = HistoryWindow()
            self.history_window.show()
            self.history_window.raise_()
            self.history_window.activateWindow()

    def closeEvent(self, event):
        """When the main window closes, stops the worker thread and child windows."""
        logger.info("Closing LauncherWindow...")
        self._save_timer.stop()
        self.save_current_settings()
        if self.is_running:
            self.stop_translation()
        if self.history_window:
            self.history_window.close()
        self.hotkeys.stop()
        if self.tray:
            self.tray.hide()
        logger.info("Session ended.")
        event.accept()
        QApplication.quit()


def run_gui():
    from logger_config import setup_logger
    setup_logger()
    logger.info("Starting Control Center (GUI)...")
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    ui_theme.apply_theme(app)
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
