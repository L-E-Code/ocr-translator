"""Profiles, glossary choice and automatic profile switching."""
import copy
import os

from PyQt6.QtWidgets import QMessageBox, QInputDialog

from core.capture import foreground_window_title
from core import config_manager
from ui.i18n import tr
from core.glossary import glossary_path, list_glossary_files
from ui.glossary_editor import GlossaryEditor
from core.logger_config import get_logger

logger = get_logger("Launcher")


class ProfilesMixin:
    """Profiles, glossary choice and automatic profile switching."""

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
