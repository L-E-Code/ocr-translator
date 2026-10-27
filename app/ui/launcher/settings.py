"""Reading, applying and saving the preferences; interface language and API key."""
import copy

from PyQt6.QtWidgets import QMessageBox, QLineEdit, QInputDialog, QColorDialog
from PyQt6.QtGui import QKeySequence, QColor
from PyQt6.QtCore import QTimer

from core.capture import get_roi_region
from ui.sidebar import SidebarWindow
from core import config_manager, secrets_store
from ui.i18n import tr, ui_language, set_ui_language
from core.logger_config import get_logger
from ui.ui_theme import color_swatch

logger = get_logger("Launcher")


class SettingsMixin:
    """Reading, applying and saving the preferences; interface language and API key."""

    def _connect_autosave(self):
        """Saves the preferences whenever the user changes something (with a short delay for sliders)."""
        for combo in (self.combo_monitors, self.combo_source, self.combo_target, self.combo_device):
            combo.currentIndexChanged.connect(self.schedule_save)
        for group in (self.roi_group, self.mode_group):
            group.idClicked.connect(self.schedule_save)
        for slider in (self.slider_opacity, self.slider_padding, self.slider_debounce):
            slider.valueChanged.connect(self.schedule_save)
        self.chk_minimize.toggled.connect(self.schedule_save)
        self.chk_context.toggled.connect(self.schedule_save)
        self.chk_auto_profile.toggled.connect(self.schedule_save)
        self.chk_updates.toggled.connect(self.schedule_save)
        self.edit_window.editingFinished.connect(self.on_window_settings_changed)
        self.chk_track.toggled.connect(self.on_window_settings_changed)
        for edit in self.hotkey_edits.values():
            edit.keySequenceChanged.connect(self.schedule_save)

    def show_text_color(self):
        self.btn_text_color.setIcon(color_swatch(self.text_color_hex, 14))
        self.btn_text_color.setText(f"  {self.text_color_hex.upper()}")
        self.btn_text_color_reset.setEnabled(
            self.text_color_hex != config_manager.DEFAULT_CONFIG["overlay_text_color"])

    def on_pick_text_color(self):
        color = QColorDialog.getColor(QColor(self.text_color_hex), self, tr("Text color"))
        if color.isValid():
            self.text_color_hex = color.name()
            self.show_text_color()
            self.schedule_save()

    def on_reset_text_color(self):
        self.text_color_hex = config_manager.DEFAULT_CONFIG["overlay_text_color"]
        self.show_text_color()
        self.schedule_save()

    def schedule_save(self, *_):
        if not self._loading_settings:
            self._save_timer.start()

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
        try:
            opacity = int(round(float(self.config.get("overlay_opacity", 1.0)) * 100))
        except (TypeError, ValueError):
            opacity = 100
        self.slider_opacity.setValue(min(100, max(30, opacity)))
        self.lbl_opacity.setText(f"{self.slider_opacity.value()}%")
        try:
            padding = int(self.config.get("overlay_padding", 20))
        except (TypeError, ValueError):
            padding = 20
        self.slider_padding.setValue(min(40, max(0, padding)))
        self.lbl_padding.setText(f"{self.slider_padding.value()} px")
        saved_color = config_manager.validate_config({"overlay_text_color": self.config.get("overlay_text_color")})[0]
        self.text_color_hex = saved_color["overlay_text_color"]
        self.show_text_color()
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
            "overlay_opacity": round(self.slider_opacity.value() / 100, 2),
            "overlay_padding": self.slider_padding.value(),
            "overlay_text_color": self.text_color_hex,
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
            self.slider_opacity,
            self.slider_padding, self.btn_text_color, self.btn_text_color_reset, self.slider_debounce, self.btn_select_roi, self.btn_restore, self.chk_context,
            self.combo_profile, self.btn_profile_new, self.btn_profile_more, self.chk_auto_profile,
            self.combo_glossary, self.btn_glossary_new,
            self.edit_window, self.btn_pick_window, self.chk_track, self.btn_add_region, self.btn_remove_region,
            *self.hotkey_edits.values(),
        ):
            w.setEnabled(enabled)
        if enabled:
            self.update_roi_info_label()  # reapplies what only applies to the custom area

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

    def update_overlay_options_visibility(self, *_):
        self.overlay_options.setVisible(self.radio_overlay.isChecked())
