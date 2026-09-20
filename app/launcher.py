import sys
import os
import time
from dotenv import load_dotenv

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QRadioButton, QButtonGroup,
    QCheckBox, QFrame, QMessageBox, QProgressBar, QApplication,
    QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QColor

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

    def __init__(self, source_lang, target_lang):
        super().__init__()
        self.source_lang = source_lang
        self.target_lang = target_lang

    def run(self):
        logger.info(f"ModelInitWorker: Carregando motores de OCR/Tradução ({self.source_lang} -> {self.target_lang})...")
        try:
            engine = OCRTranslator(source_lang=self.source_lang, target_lang=self.target_lang)
            logger.info("ModelInitWorker: Motores inicializados com sucesso.")
            self.finished_signal.emit(engine)
        except Exception as e:
            logger.error(f"ModelInitWorker: Falha ao carregar motores: {e}", exc_info=True)
            self.error_signal.emit(str(e))


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
        self.current_engine_langs = (None, None)
        
        self.worker = None
        self.ui_window = None
        self.history_window = None
        self.init_worker = None
        
        self.is_running = False
        self.is_paused = False

        self.initUI()
        self.apply_saved_config()

    def initUI(self):
        self.setWindowTitle("OCR Translator — Central de Controle")
        self.resize(580, 810)
        self.setMinimumSize(480, 420)
        
        # Tema Moderno Escuro
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0f172a;
            }
            QWidget {
                color: #f8fafc;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #0f172a;
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                min-height: 25px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #475569;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QFrame.card {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 10px;
            }
            QLabel.card-title {
                font-size: 13px;
                font-weight: bold;
                color: #38bdf8;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 4px;
            }
            QComboBox {
                background-color: #0f172a;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 12px;
                color: #f8fafc;
                font-size: 13px;
            }
            QComboBox:hover {
                border-color: #38bdf8;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e293b;
                border: 1px solid #475569;
                selection-background-color: #0284c7;
                color: #f8fafc;
                padding: 4px;
            }
            QRadioButton {
                font-size: 13px;
                color: #e2e8f0;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #64748b;
                background-color: #0f172a;
            }
            QRadioButton::indicator:checked {
                border-color: #38bdf8;
                background-color: #0284c7;
            }
            QCheckBox {
                font-size: 12px;
                color: #94a3b8;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #64748b;
                background-color: #0f172a;
            }
            QCheckBox::indicator:checked {
                background-color: #0284c7;
                border-color: #38bdf8;
            }
            QPushButton.btn-primary {
                background-color: #16a34a;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                border-radius: 8px;
                padding: 12px;
                border: none;
            }
            QPushButton.btn-primary:hover {
                background-color: #22c55e;
            }
            QPushButton.btn-danger {
                background-color: #dc2626;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                border-radius: 8px;
                padding: 12px;
                border: none;
            }
            QPushButton.btn-danger:hover {
                background-color: #ef4444;
            }
            QPushButton.btn-secondary {
                background-color: #334155;
                color: #f8fafc;
                font-size: 12px;
                font-weight: 600;
                border-radius: 6px;
                padding: 8px 12px;
                border: 1px solid #475569;
            }
            QPushButton.btn-secondary:hover {
                background-color: #475569;
                border-color: #64748b;
            }
            QPushButton.btn-secondary:disabled {
                background-color: #1e293b;
                color: #64748b;
                border-color: #334155;
            }
            QProgressBar {
                border: 1px solid #334155;
                border-radius: 4px;
                text-align: center;
                background-color: #0f172a;
                color: #f8fafc;
                font-size: 11px;
                height: 16px;
            }
            QProgressBar::chunk {
                background-color: #0284c7;
                border-radius: 3px;
            }
        """)

        # Scrollbar
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content_widget = QWidget()
        content_widget.setObjectName("content_widget")
        content_widget.setStyleSheet("#content_widget { background-color: transparent; }")

        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(10)

        scroll_area.setWidget(content_widget)
        self.setCentralWidget(scroll_area)

        # 1. Header
        header_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        lbl_title = QLabel("OCR Translator")
        lbl_title.setFont(QFont("Arial", 17, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #f8fafc; margin: 0;")
        
        lbl_subtitle = QLabel("Tradutor de Tela em Tempo Real")
        lbl_subtitle.setFont(QFont("Arial", 10))
        lbl_subtitle.setStyleSheet("color: #94a3b8; margin: 0;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_subtitle)
        header_layout.addLayout(title_box)
        
        header_layout.addStretch()
        main_layout.addLayout(header_layout)


        # 3. Monitor e Área de Captura
        mon_card = QFrame()
        mon_card.setProperty("class", "card")
        mon_layout = QVBoxLayout(mon_card)
        mon_layout.setSpacing(8)

        lbl_mon_title = QLabel("1. Monitor & Área de Captura")
        lbl_mon_title.setProperty("class", "card-title")
        mon_layout.addWidget(lbl_mon_title)

        # Dropdown de Monitores
        mon_row = QHBoxLayout()
        mon_row.addWidget(QLabel("Monitor:"))
        self.combo_monitors = QComboBox()
        for i, mon in enumerate(self.monitors):
            self.combo_monitors.addItem(f"Monitor {i + 1} ({mon['width']}x{mon['height']} px)", i)
        self.combo_monitors.currentIndexChanged.connect(self.on_monitor_changed)
        mon_row.addWidget(self.combo_monitors, 1)
        mon_layout.addLayout(mon_row)

        # Presets de ROI (Radio Group)
        self.roi_group = QButtonGroup(self)
        self.radio_third = QRadioButton("Terço Inferior da Tela (Padrão para legendas e caixas de texto)")
        self.radio_half = QRadioButton("Metade Inferior da Tela")
        self.radio_full = QRadioButton("Tela Inteira (Mais lento)")
        self.radio_custom = QRadioButton("Área Personalizada")

        self.roi_group.addButton(self.radio_third, 1)
        self.roi_group.addButton(self.radio_half, 2)
        self.roi_group.addButton(self.radio_full, 3)
        self.roi_group.addButton(self.radio_custom, 4)
        self.roi_group.idClicked.connect(self.on_roi_mode_changed)

        roi_radios_layout = QVBoxLayout()
        roi_radios_layout.setSpacing(4)
        roi_radios_layout.addWidget(self.radio_third)
        roi_radios_layout.addWidget(self.radio_half)
        roi_radios_layout.addWidget(self.radio_full)
        roi_radios_layout.addWidget(self.radio_custom)
        mon_layout.addLayout(roi_radios_layout)

        # Botão para demarcar com mouse
        mouse_row = QHBoxLayout()
        self.btn_select_roi = QPushButton("🎯 Demarcar Área com o Mouse")
        self.btn_select_roi.setProperty("class", "btn-secondary")
        self.btn_select_roi.clicked.connect(self.on_select_roi_clicked)
        mouse_row.addWidget(self.btn_select_roi)

        self.lbl_roi_info = QLabel("Área: Não definida")
        self.lbl_roi_info.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: bold;")
        mouse_row.addWidget(self.lbl_roi_info, 1)
        mon_layout.addLayout(mouse_row)

        main_layout.addWidget(mon_card)

        # 4. Idiomas & Modo de Exibição
        trans_card = QFrame()
        trans_card.setProperty("class", "card")
        trans_layout = QVBoxLayout(trans_card)
        trans_layout.setSpacing(8)

        lbl_trans_title = QLabel("2. Idiomas & Modo de Visualização")
        lbl_trans_title.setProperty("class", "card-title")
        trans_layout.addWidget(lbl_trans_title)

        # Idiomas
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Tradução:"))
        self.combo_langs = QComboBox()
        self.combo_langs.addItem("Japonês ➔ Inglês", ("ja", "en"))
        self.combo_langs.addItem("Inglês ➔ Português do Brasil", ("en", "pt"))
        self.combo_langs.addItem("Japonês ➔ Português do Brasil", ("ja", "pt"))
        lang_row.addWidget(self.combo_langs, 1)
        trans_layout.addLayout(lang_row)

        # Modos de exibição
        lbl_mode = QLabel("Exibição da Tradução:")
        lbl_mode.setStyleSheet("color: #cbd5e1; font-size: 12px; margin-top: 4px;")
        trans_layout.addWidget(lbl_mode)

        self.mode_group = QButtonGroup(self)
        self.radio_sidebar = QRadioButton("Modo Painel (Janela Lateral com Legendas e Histórico)")
        self.radio_overlay = QRadioButton("Modo Fantasma (Tarjas Transparentes Sobrepostas à Tela)")
        self.mode_group.addButton(self.radio_sidebar, 1)
        self.mode_group.addButton(self.radio_overlay, 2)


        trans_layout.addWidget(self.radio_sidebar)
        trans_layout.addWidget(self.radio_overlay)

        # Checkbox Minimizar ao iniciar
        self.chk_minimize = QCheckBox("Minimizar esta central ao iniciar a tradução")
        self.chk_minimize.setChecked(True)
        trans_layout.addWidget(self.chk_minimize)

        main_layout.addWidget(trans_card)

        # 5. Barra de Ação & Controles
        action_card = QFrame()
        action_card.setProperty("class", "card")
        action_layout = QVBoxLayout(action_card)
        action_layout.setSpacing(8)

        # Botão Principal Iniciar/Parar
        self.btn_toggle_start = QPushButton("▶ Iniciar Tradução")
        self.btn_toggle_start.setProperty("class", "btn-primary")
        self.btn_toggle_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_start.clicked.connect(self.toggle_translation)
        action_layout.addWidget(self.btn_toggle_start)

        # Controles Secundários durante execução
        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)

        self.btn_pause = QPushButton("❚❚ Pausar")
        self.btn_pause.setProperty("class", "btn-secondary")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.toggle_pause)
        controls_row.addWidget(self.btn_pause)

        self.btn_reload = QPushButton("🔄 Retraduzir")
        self.btn_reload.setProperty("class", "btn-secondary")
        self.btn_reload.setEnabled(False)
        self.btn_reload.setToolTip("Força uma releitura e retradução da cena agora")
        self.btn_reload.clicked.connect(self.force_reload)
        controls_row.addWidget(self.btn_reload)

        self.btn_history = QPushButton("📜 Histórico")
        self.btn_history.setProperty("class", "btn-secondary")
        self.btn_history.clicked.connect(self.open_history)
        controls_row.addWidget(self.btn_history)

        self.btn_logs = QPushButton("📁 Logs")
        self.btn_logs.setProperty("class", "btn-secondary")
        self.btn_logs.setToolTip("Abrir pasta dos arquivos de log")
        self.btn_logs.clicked.connect(open_log_folder)
        controls_row.addWidget(self.btn_logs)

        action_layout.addLayout(controls_row)


        # Barra de Progresso
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) 
        self.progress_bar.setVisible(False)
        action_layout.addWidget(self.progress_bar)

        # Indicador de Status
        self.lbl_status = QLabel("● Pronto para iniciar")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: bold;")
        action_layout.addWidget(self.lbl_status)

        main_layout.addWidget(action_card)

    def apply_saved_config(self):
        """Carrega e aplica as preferências salvas no config.json."""
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
        if mode == "overlay":
            self.radio_overlay.setChecked(True)
        else:
            self.radio_sidebar.setChecked(True)

        # Minimizar
        self.chk_minimize.setChecked(self.config.get("minimize_on_start", True))

        # ROI Mode
        roi_mode = self.config.get("roi_mode", "bottom_third")
        custom_roi = self.config.get("last_custom_roi")
        if roi_mode == "custom" and custom_roi:
            self.radio_custom.setChecked(True)
            self.selected_roi = custom_roi
        elif roi_mode == "bottom_half":
            self.radio_half.setChecked(True)
        elif roi_mode == "full":
            self.radio_full.setChecked(True)
        else:
            self.radio_third.setChecked(True)

        self.update_roi_info_label()

    def get_current_monitor(self):
        idx = self.combo_monitors.currentIndex()
        if 0 <= idx < len(self.monitors):
            return self.monitors[idx]
        return self.monitors[0] if self.monitors else None

    def on_monitor_changed(self):
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
            self.lbl_roi_info.setText("Área: Nenhum monitor detectado")
            return

        if self.radio_custom.isChecked() and self.selected_roi:
            w = self.selected_roi.get("width", 0)
            h = self.selected_roi.get("height", 0)
            x = self.selected_roi.get("offset_x", 0)
            y = self.selected_roi.get("offset_y", 0)
            self.lbl_roi_info.setText(f"Personalizada: {w}x{h} px (X:{x}, Y:{y})")
        elif self.radio_third.isChecked():
            roi = get_roi_region(mon, "bottom_third")
            self.selected_roi = roi
            self.lbl_roi_info.setText(f"Terço Inferior: {roi['width']}x{roi['height']} px")
        elif self.radio_half.isChecked():
            roi = get_roi_region(mon, "bottom_half")
            self.selected_roi = roi
            self.lbl_roi_info.setText(f"Metade Inferior: {roi['width']}x{roi['height']} px")
        elif self.radio_full.isChecked():
            roi = get_roi_region(mon, "full")
            self.selected_roi = roi
            self.lbl_roi_info.setText(f"Tela Cheia: {roi['width']}x{roi['height']} px")

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
            "minimize_on_start": self.chk_minimize.isChecked()
        }
        config_manager.save_config(settings)

    def set_inputs_enabled(self, enabled):
        """Trava os campos de configuração durante a execução."""
        self.combo_monitors.setEnabled(enabled)
        self.combo_langs.setEnabled(enabled)
        self.radio_third.setEnabled(enabled)
        self.radio_half.setEnabled(enabled)
        self.radio_full.setEnabled(enabled)
        self.radio_custom.setEnabled(enabled)
        self.radio_sidebar.setEnabled(enabled)
        self.radio_overlay.setEnabled(enabled)
        self.btn_select_roi.setEnabled(enabled)

    def toggle_translation(self):
        if self.is_running:
            self.stop_translation()
        else:
            self.start_translation()

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
        logger.info(f"Iniciando tradução com idiomas: {source_lang} -> {target_lang}")

        # Verifica se já temos o engine carregado para esses mesmos idiomas
        if self.ocr_engine and self.current_engine_langs == (source_lang, target_lang):
            logger.info("Reaproveitando motor OCR já instanciado.")
            self.on_engine_ready(self.ocr_engine)
        else:
            # Carrega em segundo plano
            logger.info("Carregando motores de IA em segundo plano...")
            self.lbl_status.setText("● Carregando motores de IA...")
            self.lbl_status.setStyleSheet("color: #facc15; font-size: 12px; font-weight: bold;")
            self.progress_bar.setVisible(True)

            self.init_worker = ModelInitWorker(source_lang, target_lang)
            self.init_worker.finished_signal.connect(self.on_engine_ready)
            self.init_worker.error_signal.connect(self.on_engine_error)
            self.init_worker.start()

    def on_engine_ready(self, engine):
        self.ocr_engine = engine
        source_lang, target_lang = self.combo_langs.currentData()
        self.current_engine_langs = (source_lang, target_lang)
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
            self.ui_window = OverlayWindow(mon)

        self.ui_window.show()

        # Inicia a thread de captura e tradução
        logger.info("Iniciando WorkerThread de captura contínua...")
        self.worker = WorkerThread(self.selected_roi, self.ocr_engine)
        self.worker.update_signal.connect(self.ui_window.update_texts)
        self.worker.start()

        self.is_running = True
        self.is_paused = False

        # Atualiza UI do Launcher
        self.btn_toggle_start.setEnabled(True)
        self.btn_toggle_start.setText("⏹ Parar Tradução")
        self.btn_toggle_start.setProperty("class", "btn-danger")
        self.btn_toggle_start.setStyle(self.btn_toggle_start.style())

        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("❚❚ Pausar")
        self.btn_reload.setEnabled(True)

        self.lbl_status.setText("● Traduzindo ativamente")
        self.lbl_status.setStyleSheet("color: #4ade80; font-size: 12px; font-weight: bold;")

        # Minimizar se a opção estiver marcada
        if self.chk_minimize.isChecked():
            self.showMinimized()

    def on_engine_error(self, err_msg):
        logger.error(f"Erro reportado ao carregar motor de IA: {err_msg}")
        self.progress_bar.setVisible(False)
        self.set_inputs_enabled(True)
        self.btn_toggle_start.setEnabled(True)
        self.lbl_status.setText("● Falha ao carregar modelos")
        self.lbl_status.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: bold;")
        QMessageBox.critical(self, "Erro de Inicialização", f"Não foi possível carregar os motores de IA:\n{err_msg}")


    def stop_translation(self):
        logger.info("Encerrando captura e tradução...")
        self.lbl_status.setText("● Encerrando captura...")
        self.lbl_status.setStyleSheet("color: #facc15; font-size: 12px; font-weight: bold;")
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
        self.btn_toggle_start.setText("▶ Iniciar Tradução")
        self.btn_toggle_start.setProperty("class", "btn-primary")
        self.btn_toggle_start.setStyle(self.btn_toggle_start.style())

        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("❚❚ Pausar")
        self.btn_reload.setEnabled(False)

        self.lbl_status.setText("● Parado / Pronto")
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: bold;")
        logger.info("Tradução parada com sucesso.")

        # Restaura se estiver minimizado
        if self.isMinimized():
            self.showNormal()

    def toggle_pause(self):
        if not self.is_running or not self.worker:
            return

        self.is_paused = not self.is_paused
        self.worker.set_paused(self.is_paused)

        if self.is_paused:
            logger.info("Tradução pausada pelo usuário.")
            self.btn_pause.setText("▶ Retomar")
            self.lbl_status.setText("❚❚ Captura Pausada")
            self.lbl_status.setStyleSheet("color: #facc15; font-size: 12px; font-weight: bold;")
        else:
            logger.info("Tradução retomada pelo usuário.")
            self.btn_pause.setText("❚❚ Pausar")
            self.lbl_status.setText("● Traduzindo ativamente")
            self.lbl_status.setStyleSheet("color: #4ade80; font-size: 12px; font-weight: bold;")

    def on_sidebar_pause_toggled(self, is_paused):
        self.is_paused = is_paused
        if self.worker:
            self.worker.set_paused(is_paused)
        self.btn_pause.setText("▶ Retomar" if is_paused else "❚❚ Pausar")
        if is_paused:
            logger.info("Tradução pausada via painel lateral.")
            self.lbl_status.setText("❚❚ Captura Pausada")
            self.lbl_status.setStyleSheet("color: #facc15; font-size: 12px; font-weight: bold;")
        else:
            logger.info("Tradução retomada via painel lateral.")
            self.lbl_status.setText("● Traduzindo ativamente")
            self.lbl_status.setStyleSheet("color: #4ade80; font-size: 12px; font-weight: bold;")

    def force_reload(self):
        if self.worker and self.is_running:
            logger.info("Releitura e retradução da tela solicitada manualmente.")
            self.worker.request_reload()
            self.lbl_status.setText("🔄 Lendo tela agora...")
            QTimer.singleShot(1000, lambda: self.lbl_status.setText("● Traduzindo ativamente") if self.is_running and not self.is_paused else None)

    def open_history(self):
        logger.info("Abrindo janela de histórico...")
        if self.ui_window and isinstance(self.ui_window, SidebarWindow):
            self.ui_window.open_history()
        else:
            if not self.history_window:
                self.history_window = HistoryWindow()
            self.history_window.show()
            self.history_window.raise_()

    def closeEvent(self, event):
        """Ao fechar a janela principal, encerra a thread de trabalho e janelas filhas."""
        logger.info("Fechando LauncherWindow...")
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
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_gui()


