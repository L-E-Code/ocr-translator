import time
import mss
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from capture import capture_screen_np
from logger_config import get_logger

logger = get_logger("WorkerThread")

class WorkerThread(QThread):
    """
    Thread que captura frames diretamente na memória RAM
    e envia para a IA processar.
    """
    update_signal = pyqtSignal(list)
    
    def __init__(self, capture_region, ocr_engine):
        super().__init__()
        self.capture_region = capture_region
        self.offset_x = capture_region.get('offset_x', 0)
        self.offset_y = capture_region.get('offset_y', 0)
        self.ocr_engine = ocr_engine
        self.running = True
        self.paused = False
        self.force_reload = False
        
    def set_paused(self, is_paused):
        self.paused = is_paused

    def request_reload(self):
        """Solicita releitura da tela e retradução."""
        self.force_reload = True

    def run(self):
        logger.info("WorkerThread iniciada.")
        prev_thumb = None
        
        try:
            # Instância MSS 
            with mss.MSS() as sct:
                while self.running:
                    is_reload = self.force_reload
                    if is_reload:
                        self.force_reload = False
                        prev_thumb = None

                    if self.paused and not is_reload:
                        time.sleep(0.5)
                        continue

                    # 1. Captura
                    frame_np = capture_screen_np(self.capture_region, sct=sct)
                    if frame_np is None or frame_np.size == 0:
                        time.sleep(0.15)
                        continue

                    # 2. Detecção de Mudança de Tela
                    if not is_reload:
                        # Reduz o frame para miniatura em tons de cinza para medir se a fala mudou
                        gray = cv2.cvtColor(frame_np, cv2.COLOR_BGR2GRAY)
                        thumb = cv2.resize(gray, (128, 64))
                        
                        if prev_thumb is not None:
                            diff = np.mean(np.abs(thumb.astype(np.float32) - prev_thumb.astype(np.float32)))
                            # Se a tela está praticamente idêntica
                            if diff < 0.8:
                                time.sleep(0.15)
                                continue
                                
                        prev_thumb = thumb
                        
                        # Aguarda 0.20s para o efeito de digitação
                        time.sleep(0.20)
                        # Recaptura o frame após a digitação
                        settled_frame = capture_screen_np(self.capture_region, sct=sct)
                        if settled_frame is not None and settled_frame.size > 0:
                            frame_np = settled_frame
                            prev_thumb = cv2.resize(cv2.cvtColor(frame_np, cv2.COLOR_BGR2GRAY), (128, 64))
                    
                    # 3. O painel atualiza assim que o OCR captura a frase
                    def on_intermediate(prelim):
                        if self.running and prelim:
                            self.update_signal.emit(prelim)

                    # 4. OCR e Tradução
                    resultados = self.ocr_engine.process_image(
                        frame_np, 
                        offset_x=self.offset_x, 
                        offset_y=self.offset_y,
                        on_intermediate=on_intermediate,
                        force_reload=is_reload
                    )
                    
                    # 5. Resultado final traduzido
                    if resultados:
                        self.update_signal.emit(resultados)
                    
                    # Intervalo entre verificações
                    time.sleep(0.15)

        except Exception as e:
            logger.error(f"Erro inesperado no WorkerThread: {e}", exc_info=True)
        finally:
            logger.info("WorkerThread finalizada.")

    def stop(self):
        logger.info("Parada solicitada para WorkerThread.")
        self.running = False


