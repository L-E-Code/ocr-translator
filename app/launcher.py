import os
import sys
import subprocess
from dotenv import load_dotenv

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QFrame, QMessageBox,
    QProgressBar, QApplication, QScrollArea, QSlider
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize

from capture import (
    get_available_monitors, get_roi_region, load_saved_roi,
    save_custom_roi
)
from selector import select_region_interactive
from ocr import OCRTranslator
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

logger = get_logger("Launcher")
load_dotenv()


class ModelInitWorker(QThread):
    """
    Thread em segundo plano para inicialização dos modelos de OCR/Tradução
    sem congelar a interface do usuário.
    """
    finished_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, source_lang, target_lang, device_preference="auto"):
        super().__init__()
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.device_preference = device_preference

    def run(self):
        logger.info(f"ModelInitWorker: Carregando motores de OCR/Tradução ({self.source_lang} -> {self.target_lang})...")
        try:
            engine = OCRTranslator(
                source_lang=self.source_lang,
                target_lang=self.target_lang,
                device_preference=self.device_preference,
                groq_models=config_manager.load_config().get("groq_models")
            )
            logger.info("ModelInitWorker: Motores inicializados com sucesso.")
            self.finished_signal.emit(engine)
        except Exception as e:
            logger.error(f"ModelInitWorker: Falha ao carregar motores: {e}", exc_info=True)
            self.error_signal.emit(str(e))


class GpuProbe(QThread):
    """Consulta as placas de vídeo do sistema sem travar a interface."""
    finished_signal = pyqtSignal(list)

    def run(self):
        self.finished_signal.emit(installed_gpu_names())


class LauncherWindow(QMainWindow):
    """
    Central de Controle e Launcher Principal do OCR Translator.
    """
    def __init__(self):
        super().__init__()
        self.config = config_manager.load_config()
        self.monitors = get_available_monitors()
        self.selected_roi = None
        self.ocr_engine = None
        self.current_engine_langs = (None, None, None)

        self.worker = None
        self.ui_window = None
        self.history_window = None
        self.init_worker = None
        self.gpu_probe = None
        self.device_label = ""

        self.is_running = False
        self.is_paused = False

        # Enquanto as preferências salvas são aplicadas aos controles, nada deve ser regravado
        self._loading_settings = True
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_current_settings)

        self.initUI()
        self.apply_saved_config()
        self._connect_autosave()

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------
    def initUI(self):
        self.setWindowTitle("OCR Translator")
        self.resize(560, 800)
        self.setMinimumSize(500, 460)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("root")

        # Coluna central com largura máxima: com a janela maximizada o conteúdo não estica
        column = QWidget()
        column.setMaximumWidth(700)
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
        main_layout.addWidget(self._build_capture_card())
        main_layout.addWidget(self._build_translation_card())
        main_layout.addWidget(self._build_action_card())
        main_layout.addStretch()

        self._content = content
        self._fitted = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            # Só depois de exibida a janela o layout conhece a altura real do conteúdo
            QTimer.singleShot(0, self._fit_height_to_content)

    def _fit_height_to_content(self):
        """Abre com a altura exata do conteúdo (sem scrollbar), limitada à área útil da tela."""
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
        lbl_subtitle = QLabel("Tradução de tela em tempo real")
        lbl_subtitle.setObjectName("muted")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.status = StatusPill("Pronto para iniciar", "idle")
        header.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    def _build_capture_card(self):
        card = Card("1 · Captura")

        mon_row = QHBoxLayout()
        mon_row.setSpacing(10)
        lbl = QLabel("Monitor")
        lbl.setObjectName("muted")
        mon_row.addWidget(lbl)
        self.combo_monitors = QComboBox()
        for i, mon in enumerate(self.monitors):
            self.combo_monitors.addItem(f"Monitor {i + 1}  ·  {mon['width']}×{mon['height']}", i)
        self.combo_monitors.currentIndexChanged.connect(self.on_monitor_changed)
        mon_row.addWidget(self.combo_monitors, 1)
        card.body.addLayout(mon_row)

        self.preview = RegionPreview()
        card.body.addWidget(self.preview)

        # Área de captura (seletor segmentado; os botões mantêm a API de QRadioButton)
        self.seg_roi = SegmentedControl()
        self.radio_third = self.seg_roi.add("Terço inferior", 1, "Padrão para caixas de diálogo e legendas")
        self.radio_half = self.seg_roi.add("Metade inferior", 2)
        self.radio_full = self.seg_roi.add("Tela inteira", 3, "Mais lento")
        self.radio_custom = self.seg_roi.add("Personalizada", 4)
        self.roi_group = self.seg_roi.group
        self.roi_group.idClicked.connect(self.on_roi_mode_changed)
        card.body.addWidget(self.seg_roi)

        mouse_row = QHBoxLayout()
        mouse_row.setSpacing(12)
        self.btn_select_roi = QPushButton("  Demarcar área com o mouse")
        self.btn_select_roi.setIcon(icon("target", TEXT, 17))
        self.btn_select_roi.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select_roi.clicked.connect(self.on_select_roi_clicked)
        mouse_row.addWidget(self.btn_select_roi)

        self.lbl_roi_info = QLabel("Área: não definida")
        self.lbl_roi_info.setObjectName("accentValue")
        self.lbl_roi_info.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mouse_row.addWidget(self.lbl_roi_info, 1)
        card.body.addLayout(mouse_row)
        return card

    def _build_translation_card(self):
        card = Card("2 · Tradução")

        lang_row = QHBoxLayout()
        lang_row.setSpacing(10)
        lbl = QLabel("Idiomas")
        lbl.setObjectName("muted")
        lbl.setFixedWidth(100)
        lang_row.addWidget(lbl)
        self.combo_langs = QComboBox()
        self.combo_langs.addItem("Japonês  ➔  Inglês", ("ja", "en"))
        self.combo_langs.addItem("Inglês  ➔  Português (BR)", ("en", "pt"))
        self.combo_langs.addItem("Japonês  ➔  Português (BR)", ("ja", "pt"))
        lang_row.addWidget(self.combo_langs, 1)
        card.body.addLayout(lang_row)

        dev_row = QHBoxLayout()
        dev_row.setSpacing(10)
        lbl_dev = QLabel("Processamento")
        lbl_dev.setObjectName("muted")
        lbl_dev.setFixedWidth(100)
        dev_row.addWidget(lbl_dev)
        self.combo_device = QComboBox()
        self.combo_device.addItem("Automático (usa a GPU se houver)", "auto")
        self.combo_device.addItem("GPU", "gpu")
        self.combo_device.addItem("CPU", "cpu")
        self.combo_device.currentIndexChanged.connect(self.update_device_hint)
        self.combo_device.activated.connect(self.on_device_chosen)  # só escolhas do usuário
        self._last_device_index = 0
        dev_row.addWidget(self.combo_device, 1)
        card.body.addLayout(dev_row)

        self.lbl_device_hint = QLabel("")
        self.lbl_device_hint.setObjectName("hint")
        self.lbl_device_hint.setWordWrap(True)
        card.body.addWidget(self.lbl_device_hint)

        lbl_mode = QLabel("Como exibir a tradução")
        lbl_mode.setObjectName("muted")
        card.body.addWidget(lbl_mode)

        self.seg_mode = SegmentedControl()
        self.radio_sidebar = self.seg_mode.add("Painel lateral", 1, "Janela com a fala atual e histórico")
        self.radio_overlay = self.seg_mode.add("Sobre a tela", 2, "Tradução desenhada por cima do jogo ou vídeo")
        self.mode_group = self.seg_mode.group
        self.mode_group.idClicked.connect(self.update_overlay_options_visibility)
        card.body.addWidget(self.seg_mode)

        # Opções do modo "Sobre a tela"
        self.overlay_options = QWidget()
        ov = QVBoxLayout(self.overlay_options)
        ov.setContentsMargins(0, 2, 0, 0)
        ov.setSpacing(10)

        self.seg_style = SegmentedControl()
        self.radio_style_inplace = self.seg_style.add("Cobrir o texto original", 1)
        self.radio_style_subtitle = self.seg_style.add("Legenda na base", 2)
        ov.addWidget(self.seg_style)

        op_row = QHBoxLayout()
        op_row.setSpacing(10)
        lbl_op = QLabel("Opacidade")
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

        # Tempo de espera pelo texto (debounce)
        speed_row = QHBoxLayout()
        speed_row.setSpacing(10)
        lbl_speed = QLabel("Espera pelo texto")
        lbl_speed.setObjectName("muted")
        speed_row.addWidget(lbl_speed)
        self.slider_debounce = QSlider(Qt.Orientation.Horizontal)
        self.slider_debounce.setRange(50, 400)
        self.slider_debounce.setSingleStep(10)
        self.slider_debounce.setPageStep(50)
        self.slider_debounce.valueChanged.connect(lambda v: self.lbl_debounce.setText(f"{v} ms"))
        self.slider_debounce.setToolTip(
            "Quanto a tela precisa ficar parada antes de ler.\n"
            "Menor = traduz mais rápido; maior = evita ler texto ainda sendo digitado."
        )
        speed_row.addWidget(self.slider_debounce, 1)
        self.lbl_debounce = QLabel("200 ms")
        self.lbl_debounce.setObjectName("accentValue")
        self.lbl_debounce.setFixedWidth(52)
        self.lbl_debounce.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        speed_row.addWidget(self.lbl_debounce)
        card.body.addLayout(speed_row)

        self.chk_minimize = QCheckBox("Minimizar esta janela ao iniciar")
        self.chk_minimize.setChecked(True)
        card.body.addWidget(self.chk_minimize)
        return card

    def _build_action_card(self):
        card = Card()

        self.btn_toggle_start = QPushButton("  Iniciar tradução")
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

        self.btn_pause = QPushButton(" Pausar")
        self.btn_pause.setIcon(icon("pause", TEXT, 16))
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.toggle_pause)
        controls.addWidget(self.btn_pause)

        self.btn_reload = QPushButton(" Retraduzir")
        self.btn_reload.setIcon(icon("refresh", TEXT, 16))
        self.btn_reload.setEnabled(False)
        self.btn_reload.setToolTip("Força uma releitura e retradução da cena agora")
        self.btn_reload.clicked.connect(self.force_reload)
        controls.addWidget(self.btn_reload)

        self.btn_history = QPushButton(" Histórico")
        self.btn_history.setIcon(icon("history", TEXT, 16))
        self.btn_history.clicked.connect(self.open_history)
        controls.addWidget(self.btn_history)

        self.btn_logs = QPushButton(" Logs")
        self.btn_logs.setIcon(icon("folder", TEXT, 16))
        self.btn_logs.setToolTip("Abrir a pasta dos arquivos de log")
        self.btn_logs.clicked.connect(open_log_folder)
        controls.addWidget(self.btn_logs)

        for b in (self.btn_pause, self.btn_reload, self.btn_history, self.btn_logs):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        card.body.addLayout(controls)

        self.btn_restore = QPushButton("Restaurar configurações padrão")
        self.btn_restore.setProperty("variant", "ghost")
        self.btn_restore.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_restore.clicked.connect(self.restore_defaults)
        card.body.addWidget(self.btn_restore, 0, Qt.AlignmentFlag.AlignHCenter)
        return card

    def running_text(self):
        return f"Traduzindo · {self.device_label}" if self.device_label else "Traduzindo"

    def _connect_autosave(self):
        """Salva as preferências sempre que o usuário muda algo (com pequena espera para sliders)."""
        for combo in (self.combo_monitors, self.combo_langs, self.combo_device):
            combo.currentIndexChanged.connect(self.schedule_save)
        for group in (self.roi_group, self.mode_group, self.seg_style.group):
            group.idClicked.connect(self.schedule_save)
        for slider in (self.slider_opacity, self.slider_debounce):
            slider.valueChanged.connect(self.schedule_save)
        self.chk_minimize.toggled.connect(self.schedule_save)

    def schedule_save(self, *_):
        if not self._loading_settings:
            self._save_timer.start()

    def restore_defaults(self):
        """Volta todas as preferências ao padrão, depois de confirmar."""
        answer = QMessageBox.question(
            self, "Restaurar padrões",
            "Todas as preferências (monitor, área, idiomas, modo de exibição, ajustes de velocidade "
            "e a área personalizada salva) voltarão aos valores padrão. Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._save_timer.stop()
        self.config = config_manager.reset_config()
        self.apply_saved_config()
        self.set_status("Configurações restauradas", "idle")
        logger.info("Preferências restauradas para os valores padrão.")

    def set_status(self, text, kind="idle"):
        self.status.set_state(text, kind)

    # ------------------------------------------------------------------
    # Processamento (CPU / GPU)
    # ------------------------------------------------------------------
    def setup_device_options(self):
        """Detecta GPUs utilizáveis; sem elas, descobre a placa instalada para orientar o usuário."""
        self.gpus = available_gpus()
        if not self.gpus and self.combo_device.currentData() == "gpu":
            self.combo_device.setCurrentIndex(0)
        self._last_device_index = self.combo_device.currentIndex()
        self.system_gpus = None
        if not self.gpus:
            self.gpu_probe = GpuProbe()
            self.gpu_probe.finished_signal.connect(self.on_gpu_probe_done)
            self.gpu_probe.start()
        self.update_device_hint()

    def on_device_chosen(self, index):
        """Escolher GPU sem suporte instalado oferece baixar o que falta."""
        if self.combo_device.itemData(index) == "gpu" and not self.gpus:
            if not self.offer_gpu_support():
                self.combo_device.setCurrentIndex(self._last_device_index)
                return
        self._last_device_index = self.combo_device.currentIndex()

    def offer_gpu_support(self):
        """Pergunta se deve baixar o PyTorch com suporte à GPU. Retorna True se o app vai fechar para instalar."""
        names = self.system_gpus if self.system_gpus is not None else installed_gpu_names()
        self.system_gpus = names
        vendor_pkg = {"intel": ("Intel Arc", "intel"), "nvidia": ("NVIDIA", "nvidia")}
        found = next(((n, vendor_pkg[gpu_vendor(n)]) for n in names if gpu_vendor(n) in vendor_pkg), None)

        if found is None:
            QMessageBox.information(
                self, "GPU não encontrada",
                "Não encontrei uma placa de vídeo compatível (NVIDIA ou Intel Arc) neste computador.\n"
                "O processamento continuará na CPU."
            )
            return False

        gpu_name, (family, package) = found
        if sys.platform != "win32":
            QMessageBox.information(
                self, "Suporte a GPU",
                f"Placa detectada: {gpu_name}.\nInstale manualmente a versão do PyTorch para {family}."
            )
            return False

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Habilitar a GPU")
        box.setText(f"Placa detectada: {gpu_name}")
        box.setInformativeText(
            f"Para usar a GPU é preciso baixar a versão do PyTorch com suporte a {family} "
            "(mais de 2 GB).\n\n"
            "O OCR Translator será fechado, a instalação roda numa janela de terminal "
            "e o app reabre sozinho ao terminar. Baixar agora?"
        )
        yes = box.addButton("Baixar e instalar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Agora não", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return False

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(root, "instalar_gpu.bat")
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "Suporte a GPU - OCR Translator", script, package, str(os.getpid()), "relaunch"],
                cwd=root,
            )
        except Exception as e:
            logger.error(f"Falha ao iniciar o instalador de GPU: {e}")
            QMessageBox.critical(self, "Erro", f"Não foi possível iniciar o instalador:\n{e}")
            return False

        logger.info("Instalador de suporte a GPU iniciado; fechando o aplicativo.")
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
                text = f"GPU disponível ({name}), mas o modo CPU está selecionado."
            else:
                text = f"Usará a GPU: {name} ({KIND_LABELS.get(kind, kind)})."
        elif self.system_gpus is None:
            text = "Verificando placa de vídeo…"
        else:
            usable = [n for n in self.system_gpus if gpu_vendor(n) in ("nvidia", "intel")]
            if usable:
                text = (f"Placa detectada: {usable[0]}, mas falta o suporte no PyTorch. "
                        "Escolha \"GPU\" para baixar e habilitar.")
            else:
                text = "Nenhuma GPU compatível encontrada. O processamento será feito pela CPU."
        self.lbl_device_hint.setText(text)

    def update_overlay_options_visibility(self, *_):
        self.overlay_options.setVisible(self.radio_overlay.isChecked())

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------
    def apply_saved_config(self):
        """Carrega e aplica as preferências salvas no config.json."""
        self._loading_settings = True
        try:
            self._apply_saved_config()
        finally:
            self._loading_settings = False

    def _apply_saved_config(self):
        # Monitor
        mon_idx = self.config.get("monitor_index", 0)
        if 0 <= mon_idx < self.combo_monitors.count():
            self.combo_monitors.setCurrentIndex(mon_idx)

        # Idiomas
        src = self.config.get("source_lang", "ja")
        tgt = self.config.get("target_lang", "en")
        for i in range(self.combo_langs.count()):
            langs = self.combo_langs.itemData(i)
            if langs == (src, tgt):
                self.combo_langs.setCurrentIndex(i)
                break

        # Modo de exibição
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

        # Processamento
        idx = self.combo_device.findData(self.config.get("compute_device", "auto"))
        self.combo_device.setCurrentIndex(idx if idx >= 0 else 0)
        self.setup_device_options()

        # Espera pelo texto e janela
        try:
            debounce = int(self.config.get("debounce_ms", 200))
        except (TypeError, ValueError):
            debounce = 200
        self.slider_debounce.setValue(min(400, max(50, debounce)))
        self.lbl_debounce.setText(f"{self.slider_debounce.value()} ms")
        self.chk_minimize.setChecked(self.config.get("minimize_on_start", True))

        # ROI Mode
        roi_mode = self.config.get("roi_mode", "bottom_third")
        custom_roi = self.config.get("last_custom_roi")
        current_mon = self.get_current_monitor()

        is_custom_valid = False
        if custom_roi and current_mon:
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
            self.selected_roi = custom_roi
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
            saved = load_saved_roi()
            if saved:
                self.selected_roi = saved
            else:
                self.on_select_roi_clicked()

        self.update_roi_info_label()

    def on_select_roi_clicked(self):
        mon = self.get_current_monitor()
        if not mon:
            return

        # Oculta temporariamente a janela do launcher para permitir a seleção limpa
        self.hide()
        QApplication.processEvents()

        try:
            roi = select_region_interactive(mon, app=QApplication.instance())
        finally:
            self.show()
            self.raise_()

        if roi:
            self.selected_roi = roi
            save_custom_roi(roi)
            self.radio_custom.setChecked(True)
        else:
            if not self.selected_roi:
                self.radio_third.setChecked(True)
                self.selected_roi = get_roi_region(mon, "bottom_third")

        self.update_roi_info_label()

    def update_roi_info_label(self):
        mon = self.get_current_monitor()
        if not mon:
            self.lbl_roi_info.setText("Nenhum monitor detectado")
            return

        self.preview.set_monitor(mon['width'], mon['height'])

        if self.radio_custom.isChecked() and self.selected_roi:
            w = self.selected_roi.get("width", 0)
            h = self.selected_roi.get("height", 0)
            x = self.selected_roi.get("offset_x", 0)
            y = self.selected_roi.get("offset_y", 0)
            text = f"{w}×{h} px  ·  X {x}, Y {y}"
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
            text = "Área não definida"
        self.lbl_roi_info.setText(text)

        # Miniatura do monitor com a região destacada
        roi = self.selected_roi
        if roi:
            rel = (
                (roi['left'] - mon['left']) / mon['width'],
                (roi['top'] - mon['top']) / mon['height'],
                roi['width'] / mon['width'],
                roi['height'] / mon['height'],
            )
            self.preview.set_region(rel, "área de captura")
        else:
            self.preview.set_region(None)

    def save_current_settings(self):
        """Persiste as escolhas atuais no config.json."""
        source_lang, target_lang = self.combo_langs.currentData()
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
        }
        config_manager.save_config(settings)

    def set_inputs_enabled(self, enabled):
        """Trava os campos de configuração durante a execução."""
        for w in (
            self.combo_monitors, self.combo_langs, self.combo_device,
            self.radio_third, self.radio_half, self.radio_full, self.radio_custom,
            self.radio_sidebar, self.radio_overlay,
            self.radio_style_inplace, self.radio_style_subtitle, self.slider_opacity,
            self.slider_debounce, self.btn_select_roi, self.btn_restore,
        ):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Ciclo de vida da tradução
    # ------------------------------------------------------------------
    def toggle_translation(self):
        if self.is_running:
            self.stop_translation()
        else:
            self.start_translation()

    def _set_start_button(self, running):
        if running:
            self.btn_toggle_start.setText("  Parar tradução")
            self.btn_toggle_start.setIcon(icon("stop", ui_theme.BAD, 18))
            set_variant(self.btn_toggle_start, "danger")
        else:
            self.btn_toggle_start.setText("  Iniciar tradução")
            self.btn_toggle_start.setIcon(icon("play", "#04101f", 18))
            set_variant(self.btn_toggle_start, "primary")

    def _set_pause_button(self, paused):
        if paused:
            self.btn_pause.setText(" Retomar")
            self.btn_pause.setIcon(icon("play", TEXT, 16))
        else:
            self.btn_pause.setText(" Pausar")
            self.btn_pause.setIcon(icon("pause", TEXT, 16))

    def start_translation(self):
        mon = self.get_current_monitor()
        if not mon:
            logger.error("Tentativa de iniciar tradução sem monitor selecionado.")
            QMessageBox.critical(self, "Erro", "Nenhum monitor disponível.")
            return

        if not self.selected_roi:
            self.on_roi_mode_changed()

        self.save_current_settings()
        self.set_inputs_enabled(False)
        self.btn_toggle_start.setEnabled(False)

        source_lang, target_lang = self.combo_langs.currentData()
        device_pref = self.combo_device.currentData()
        logger.info(f"Iniciando tradução com idiomas: {source_lang} -> {target_lang} (processamento: {device_pref})")

        # Verifica se já temos o engine carregado para esses mesmos idiomas e dispositivo
        if self.ocr_engine and self.current_engine_langs == (source_lang, target_lang, device_pref):
            logger.info("Reaproveitando motor OCR já instanciado.")
            self.on_engine_ready(self.ocr_engine)
        else:
            logger.info("Carregando motores de IA em segundo plano...")
            self.set_status("Carregando motores de IA…", "loading")
            self.progress_bar.setVisible(True)

            self.init_worker = ModelInitWorker(source_lang, target_lang, device_pref)
            self.init_worker.finished_signal.connect(self.on_engine_ready)
            self.init_worker.error_signal.connect(self.on_engine_error)
            self.init_worker.start()

    def on_engine_ready(self, engine):
        self.ocr_engine = engine
        source_lang, target_lang = self.combo_langs.currentData()
        self.current_engine_langs = (source_lang, target_lang, self.combo_device.currentData())
        self.device_label = "GPU" if engine.device != "cpu" else "CPU"
        self.progress_bar.setVisible(False)

        # Cria a janela de exibição
        mon = self.get_current_monitor()
        is_sidebar = self.radio_sidebar.isChecked()

        logger.info(f"Criando interface de exibição: {'Sidebar' if is_sidebar else 'Overlay'}")
        if is_sidebar:
            self.ui_window = SidebarWindow()
            self.ui_window.pause_toggled.connect(self.on_sidebar_pause_toggled)
            self.ui_window.reload_requested.connect(self.force_reload)
        else:
            if not self.history_window:
                self.history_window = HistoryWindow()
            self.ui_window = OverlayWindow(mon, history_window=self.history_window)

        self.ui_window.show()

        # Inicia a thread de captura e tradução
        logger.info("Iniciando WorkerThread de captura contínua...")
        self.worker = WorkerThread(
            self.selected_roi,
            self.ocr_engine,
            debounce_ms=config_manager.load_config().get("debounce_ms", 200)
        )
        self.worker.update_signal.connect(self.ui_window.update_texts)
        self.worker.start()

        self.is_running = True
        self.is_paused = False

        self.btn_toggle_start.setEnabled(True)
        self._set_start_button(True)
        self._set_pause_button(False)
        self.btn_pause.setEnabled(True)
        self.btn_reload.setEnabled(True)
        self.set_status(self.running_text(), "running")

        if self.chk_minimize.isChecked():
            self.showMinimized()

    def on_engine_error(self, err_msg):
        logger.error(f"Erro reportado ao carregar motor de IA: {err_msg}")
        self.progress_bar.setVisible(False)
        self.set_inputs_enabled(True)
        self.btn_toggle_start.setEnabled(True)
        self.set_status("Falha ao carregar modelos", "error")
        QMessageBox.critical(self, "Erro de inicialização", f"Não foi possível carregar os motores de IA:\n{err_msg}")

    def stop_translation(self):
        logger.info("Encerrando captura e tradução...")
        self.set_status("Encerrando…", "loading")
        QApplication.processEvents()

        if self.worker:
            self.worker.stop()
            self.worker.wait(1500)
            self.worker = None

        if self.ui_window:
            self.ui_window.close()
            self.ui_window = None

        self.is_running = False
        self.is_paused = False

        self.set_inputs_enabled(True)
        self._set_start_button(False)
        self._set_pause_button(False)
        self.btn_pause.setEnabled(False)
        self.btn_reload.setEnabled(False)

        self.set_status("Parado", "idle")
        logger.info("Tradução parada com sucesso.")

        # Restaura se estiver minimizado
        if self.isMinimized():
            self.showNormal()

    def toggle_pause(self):
        if not self.is_running or not self.worker:
            return

        self.is_paused = not self.is_paused
        self.worker.set_paused(self.is_paused)
        self._set_pause_button(self.is_paused)

        if self.is_paused:
            logger.info("Tradução pausada pelo usuário.")
            self.set_status("Captura pausada", "paused")
        else:
            logger.info("Tradução retomada pelo usuário.")
            self.set_status(self.running_text(), "running")

    def on_sidebar_pause_toggled(self, is_paused):
        self.is_paused = is_paused
        if self.worker:
            self.worker.set_paused(is_paused)
        self._set_pause_button(is_paused)
        if is_paused:
            logger.info("Tradução pausada via painel lateral.")
            self.set_status("Captura pausada", "paused")
        else:
            logger.info("Tradução retomada via painel lateral.")
            self.set_status(self.running_text(), "running")

    def force_reload(self):
        if self.worker and self.is_running:
            logger.info("Releitura e retradução da tela solicitada manualmente.")
            self.worker.request_reload()
            self.set_status("Lendo a tela…", "busy")
            QTimer.singleShot(
                1200,
                lambda: self.set_status(self.running_text(), "running") if self.is_running and not self.is_paused else None
            )

    def open_history(self):
        logger.info("Abrindo janela de histórico...")
        if self.ui_window and isinstance(self.ui_window, SidebarWindow):
            self.ui_window.open_history()
        else:
            if not self.history_window:
                self.history_window = HistoryWindow()
            self.history_window.show()
            self.history_window.raise_()
            self.history_window.activateWindow()

    def closeEvent(self, event):
        """Ao fechar a janela principal, encerra a thread de trabalho e janelas filhas."""
        logger.info("Fechando LauncherWindow...")
        self._save_timer.stop()
        self.save_current_settings()
        if self.is_running:
            self.stop_translation()
        if self.history_window:
            self.history_window.close()
        logger.info("Sessão finalizada.")
        event.accept()


def run_gui():
    from logger_config import setup_logger
    setup_logger()
    logger.info("Iniciando Central de Controle (GUI)...")
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    ui_theme.apply_theme(app)
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
