import time
import mss
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from capture import capture_screen_np
from logger_config import get_logger

logger = get_logger("WorkerThread")

# Diferença média de brilho (miniatura) a partir da qual consideramos troca completa de cena/fala
SCENE_CHANGE_DIFF = 8.0
# Intervalo de verificação quando a tela não mudou / entre ciclos
IDLE_POLL = 0.05
# Amostragem enquanto espera o texto parar de ser digitado, e limite dessa espera
SETTLE_POLL = 0.06
MAX_SETTLE_WAIT = 2.5
# Diferença mínima de miniatura para considerar que a tela mudou
CHANGE_DIFF = 0.8
# Diferença mínima para adiar a tradução depois do OCR (mais alta: ignora animações sutis)
DEFER_DIFF = 2.0
CYCLE_PAUSE = 0.03

class WorkerThread(QThread):
    """
    Thread que captura frames diretamente na memória RAM
    e envia para a IA processar.
    """
    update_signal = pyqtSignal(list)
    
    def __init__(self, capture_region, ocr_engine, debounce_ms=200):
        super().__init__()
        # Espera máxima para o efeito máquina de escrever assentar (trocas bruscas de tela ignoram a espera)
        self.debounce = max(0, int(debounce_ms)) / 1000.0
        self.capture_region = capture_region
        self.offset_x = capture_region.get('offset_x', 0)
        self.offset_y = capture_region.get('offset_y', 0)
        self.ocr_engine = ocr_engine
        self.running = True
        self.paused = False
        self.force_reload = False
        self._deferred_last_cycle = False
        
    def set_paused(self, is_paused):
        self.paused = is_paused

    def request_reload(self):
        """Solicita releitura da tela e retradução."""
        self.force_reload = True

    @staticmethod
    def _thumb(frame):
        return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (128, 64))

    @staticmethod
    def _thumb_diff(a, b):
        return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))

    def _wait_until_settled(self, sct, frame, thumb):
        """
        Amostra a tela até ficar parada por `debounce` segundos (fim da digitação),
        limitado a MAX_SETTLE_WAIT. Barato: só compara miniaturas, sem OCR.
        """
        start = last_change = time.time()
        while self.running and time.time() - last_change < self.debounce and time.time() - start < MAX_SETTLE_WAIT:
            time.sleep(SETTLE_POLL)
            try:
                nxt = capture_screen_np(self.capture_region, sct=sct)
            except Exception:
                continue
            if nxt is None or nxt.size == 0:
                continue
            nxt_thumb = self._thumb(nxt)
            if self._thumb_diff(nxt_thumb, thumb) >= CHANGE_DIFF:
                last_change = time.time()
            frame, thumb = nxt, nxt_thumb
        return frame, thumb

    def _should_defer(self, sct, reference_thumb):
        """Adia a tradução no máximo uma vez seguida, para animações de fundo não travarem o ciclo."""
        if self._deferred_last_cycle:
            self._deferred_last_cycle = False
            return False
        self._deferred_last_cycle = self._frame_changed(sct, reference_thumb)
        return self._deferred_last_cycle

    def _frame_changed(self, sct, reference_thumb):
        """True se a tela atual já difere do frame que está sendo traduzido."""
        if reference_thumb is None:
            return False
        try:
            current = capture_screen_np(self.capture_region, sct=sct)
        except Exception:
            return False
        if current is None or current.size == 0:
            return False
        return self._thumb_diff(self._thumb(current), reference_thumb) >= DEFER_DIFF

    def run(self):
        logger.info("WorkerThread iniciada.")
        prev_thumb = None
        last_processed_thumb = None  # miniatura do último frame que passou pelo OCR
        
        try:
            # Instância MSS 
            with mss.MSS() as sct:
                while self.running:
                    is_reload = self.force_reload
                    if is_reload:
                        self.force_reload = False
                        prev_thumb = None
                        last_processed_thumb = None

                    if self.paused and not is_reload:
                        time.sleep(0.5)
                        continue

                    # 1. Captura
                    try:
                        frame_np = capture_screen_np(self.capture_region, sct=sct)
                    except Exception as cap_err:
                        logger.warning(f"Erro momentâneo na captura de tela: {cap_err}")
                        time.sleep(0.5)
                        continue

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
                                time.sleep(IDLE_POLL)
                                continue
                            is_scene_change = diff >= SCENE_CHANGE_DIFF
                        else:
                            is_scene_change = True
                                
                        prev_thumb = thumb
                        
                        # Debounce adaptativo: troca brusca de tela vai direto ao OCR;
                        # mudanças pequenas (digitação) aguardam o texto assentar
                        if not is_scene_change and self.debounce > 0:
                            frame_np, prev_thumb = self._wait_until_settled(sct, frame_np, thumb)
                    
                    # Frame assentado igual ao último já processado (ex: animação de fundo que voltou ao
                    # mesmo estado): não há nada novo para ler
                    if not is_reload:
                        settled_thumb = cv2.resize(cv2.cvtColor(frame_np, cv2.COLOR_BGR2GRAY), (128, 64))
                        if last_processed_thumb is not None:
                            d = np.mean(np.abs(settled_thumb.astype(np.float32) - last_processed_thumb.astype(np.float32)))
                            if d < 0.8:
                                time.sleep(IDLE_POLL)
                                continue
                        last_processed_thumb = settled_thumb
                    else:
                        last_processed_thumb = cv2.resize(cv2.cvtColor(frame_np, cv2.COLOR_BGR2GRAY), (128, 64))

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
                        force_reload=is_reload,
                        should_abort_translation=lambda: self._should_defer(sct, last_processed_thumb)
                    )
                    
                    # 5. Resultado final traduzido
                    if resultados is not None:
                        self._deferred_last_cycle = False
                        self.update_signal.emit(resultados)
                    
                    # Intervalo entre verificações
                    time.sleep(CYCLE_PAUSE)

        except Exception as e:
            logger.error(f"Erro inesperado no WorkerThread: {e}", exc_info=True)
        finally:
            logger.info("WorkerThread finalizada.")

    def stop(self):
        logger.info("Parada solicitada para WorkerThread.")
        self.running = False


