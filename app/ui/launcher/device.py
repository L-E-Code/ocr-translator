"""Processing device choice (GPU/CPU) and the GPU support offer."""
import os
import subprocess
import sys

from PyQt6.QtWidgets import QMessageBox, QApplication

from core.device import installed_gpu_names, gpu_vendor, KIND_LABELS
from ui.i18n import tr
from core.paths import root_path, FROZEN
from core.version import RELEASES_URL
from .workers import RuntimeProbe, GpuProbe
from core.logger_config import get_logger

logger = get_logger("Launcher")


class DeviceMixin:
    """Processing device choice (GPU/CPU) and the GPU support offer."""

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
