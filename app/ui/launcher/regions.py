"""Monitor, capture regions and game window binding."""
import os

from PyQt6.QtWidgets import QMessageBox, QApplication, QInputDialog, QMenu

from core.capture import (
    get_roi_region, save_custom_roi, list_windows, region_to_window_relative, resolve_region
)
from ui.selector import select_region_interactive
from core import config_manager
from ui.i18n import tr


class RegionsMixin:
    """Monitor, capture regions and game window binding."""

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
