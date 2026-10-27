"""Tray icon, global hotkeys and window visibility."""
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from PyQt6.QtGui import QKeySequence

from ui import ui_theme
from ui.i18n import tr


class TrayMixin:
    """Tray icon, global hotkeys and window visibility."""

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
