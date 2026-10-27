"""Main window of the Control Center."""
import sys
from dotenv import load_dotenv

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QFrame, QMessageBox, QApplication,
    QScrollArea, QBoxLayout
)
from PyQt6.QtGui import QKeySequence
from PyQt6.QtCore import Qt, QTimer

from core.capture import get_available_monitors
from ui.hotkeys import GlobalHotkeys
from core.dictionary import get_dictionary
from ui.worker import WorkerThread
from ui.sidebar import SidebarWindow
from ui.overlay import OverlayWindow
from ui.history_window import HistoryWindow
from core import config_manager
from ui import ui_theme
from ui.ui_theme import icon, set_variant, TEXT
from core.logger_config import get_logger
from ui.i18n import tr
from core.paths import root_path
from .workers import ModelInitWorker, UpdateCheck
from .panels import PanelsMixin
from .profiles import ProfilesMixin
from .regions import RegionsMixin
from .settings import SettingsMixin
from .device import DeviceMixin
from .tray import TrayMixin

logger = get_logger("Launcher")
load_dotenv(root_path(".env"))


class LauncherWindow(PanelsMixin, ProfilesMixin, RegionsMixin, SettingsMixin, DeviceMixin, TrayMixin, QMainWindow):
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

    def running_text(self):
        return tr("Translating · {device}", device=self.device_label) if self.device_label else tr("Translating")

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

    def set_status(self, text, kind="idle"):
        self.status.set_state(text, kind)

    @staticmethod
    def setup_word_dictionary(source_lang):
        """Hooks up the word dictionary (Japanese only); without the libraries, the panel works without it."""
        if source_lang == "ja":
            dictionary = get_dictionary()
            dictionary.load_async()
            ui_theme.set_word_dictionary(dictionary)
        else:
            ui_theme.set_word_dictionary(None)

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
    from core.logger_config import setup_logger
    setup_logger()
    logger.info("Starting Control Center (GUI)...")
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    ui_theme.apply_theme(app)
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())
