# Referência Técnica da API — OCR Translator

Este documento fornece a especificação técnica exaustiva de classes, métodos, funções utilitárias, assinaturas de tipos e contratos de dados de cada módulo do **OCR Translator**.

---

## Índice de Módulos

1. [`app/capture.py`](#1-appcapturepy) — Captura de Tela e I/O de Monitores
2. [`app/selector.py`](#2-appselectorpy) — Seletor Interativo de Área (ROI)
3. [`app/ocr.py`](#3-appocrpy) — Motores de OCR, Heurísticas e Tradução
4. [`app/main.py`](#4-appmainpy) — Orquestrador e Thread Concorrente
5. [`app/sidebar.py`](#5-appsidebarpy) — Modo Painel (Sidebar)
6. [`app/history_window.py`](#6-apphistory_windowpy) — Janela de Histórico Dedicada
7. [`app/overlay.py`](#7-appoverlaypy) — Modo Fantasma (Overlay HUD)
8. [Dicionário de Estruturas de Dados](#8-dicionário-de-estruturas-de-dados)

---

## 1. `app/capture.py`

Módulo responsável pela interface com o subsistema de vídeo via biblioteca `mss`, enumeração de displays físicos, recorte em memória RAM e persistência de ROI no arquivo `config.json`.

### Funções:

#### `get_available_monitors() -> list[dict]`
- **Descrição:** Retorna a lista de monitores físicos disponíveis conectados ao sistema operacional.
- **Retorno:** Lista de dicionários contendo `{'left': int, 'top': int, 'width': int, 'height': int}`.
- **Nota Técnica:** O monitor global de índice `0` gerado pelo `mss` (que soma todas as telas virtuais) é descartado para retornar exclusivamente displays físicos individuais.

#### `capture_screen_np(region: dict, sct: mss.MSS | None = None) -> np.ndarray | None`
- **Parâmetros:**
  - `region`: Dicionário com `top`, `left`, `width` e `height`.
  - `sct`: Instância opcional de `mss.MSS`. Se omitido, uma nova instância é instanciada temporariamente.
- **Retorno:** Matriz NumPy 3D contendo a imagem em formato `RGB` (`shape: (H, W, 3)`), ou `None` caso a captura falhe.
- **Eficiência:** Transmissão estritamente em memória RAM, sem salvar arquivos em disco.

#### `load_saved_roi() -> dict | None`
- **Descrição:** Lê o arquivo `config.json` na raiz do projeto e carrega as coordenadas da última seleção realizada.
- **Retorno:** Dicionário com as coordenadas da ROI ou `None` se o arquivo não existir ou estiver corrompido.

#### `save_custom_roi(roi_data: dict) -> None`
- **Descrição:** Serializa o dicionário de coordenadas da ROI no arquivo `config.json` para reutilização em sessões futuras.

#### `get_roi_region(monitor: dict, roi_type: str) -> dict`
- **Parâmetros:**
  - `monitor`: Coordenadas do monitor de referência.
  - `roi_type`: Uma das opções: `"bottom_third"`, `"bottom_half"` ou `"full"`.
- **Retorno:** Dicionário com as coordenadas absolutas calculadas e os offsets relativos `offset_x` e `offset_y`.

#### `cli_select_monitor() -> dict`
- **Descrição:** Exibe no terminal a lista de telas físicas e aguarda a seleção do usuário. Retorna o dicionário do monitor escolhido.

#### `cli_select_focus_area(monitor: dict) -> dict`
- **Descrição:** Exibe o menu de seleção da área de foco (presets ou seletor gráfico com o mouse) e retorna a ROI final calibrada.

---

## 2. `app/selector.py`

Fornece a ferramenta visual de recorte de tela retangular transparente estilo snipping tool.

### Classes:

#### `ScreenSelector(QWidget)`
- **Herança:** `PyQt6.QtWidgets.QWidget`
- **Flags de Janela:** `Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint`.
- **Métodos:**
  - `__init__(self, monitor_region: dict)`: Dimensiona a janela exatamente sobre o monitor especificado.
  - `paintEvent(self, event)`: Desenha o véu preto translúcido e aplica composição `CompositionMode_Clear` para deixar o retângulo selecionado com visão nítida do jogo.
  - `mousePressEvent(self, event)`: Registra a coordenada inicial `start_pos`.
  - `mouseMoveEvent(self, event)`: Atualiza `current_pos` e força repintura dinâmica da tela exibindo as dimensões em pixels.
  - `mouseReleaseEvent(self, event)`: Valida dimensões mínimas úteis ($L > 30\text{px}$, $A > 20\text{px}$), calcula os offsets e encerra o seletor.
  - `keyPressEvent(self, event)`: Interrompe a seleção e fecha o seletor sem salvar caso a tecla `ESC` seja pressionada.

### Funções:

#### `select_region_interactive(monitor_region: dict, app: QApplication | None = None) -> dict | None`
- **Descrição:** Instancia o `ScreenSelector` e gerencia o loop de eventos local até que o usuário conclua o arraste com o mouse.
- **Retorno:** Dicionário com a ROI selecionada contendo `{'left', 'top', 'width', 'height', 'offset_x', 'offset_y'}`, ou `None` se cancelado.

---

## 3. `app/ocr.py`

O núcleo algorítmico do projeto. Contém as heurísticas de sanitização, os motores de visão computacional e a integração com a IA de tradução.

### Funções Heurísticas e Utilitárias:

#### `clean_character_name(text: str) -> str`
- Higieniza nomes lidos por OCR, normalizando símbolos corruptos e espaços espúrios.

#### `clean_ocr_punctuation(text: str) -> str`
- Remove aspas corrompidas, símbolos de notas musicais distorcidas e pontuações imperfeitas causadas por fontes estilizadas de jogos.

#### `compute_text_similarity(text1: str, text2: str) -> float`
- Calcula o índice de semelhança entre duas strings (entre `0.0` e `1.0`) usando `difflib.SequenceMatcher`.

#### `stitch_ocr_chunks(texts: list[str]) -> str`
- Concatena blocos de texto sobrepostos provenientes do fatiamento por janela deslizante (*sliding window*), identificando o maior sufixo comum com o prefixo subsequente.

#### `is_english_subtitle(easy_txt: str, manga_txt: str) -> bool`
- Detecta e descarta caixas de legendas duplas concorrentes (ex: jogos com legenda em inglês embaixo e áudio/japonês em cima), garantindo que kanjis e kanas nunca sejam descartados.

#### `preprocess_for_ocr(image: np.ndarray) -> tuple[np.ndarray, float]`
- Realiza upscale inteligente da imagem via interpolação `Lanczos4` e conversão para escala de cinza para maximizar a acurácia de leitura de caracteres de baixa resolução.

#### `calculate_dominant_font_height(items: list[dict]) -> float`
- Calcula a mediana ponderada da altura das caixas de texto para definir a escala tipográfica dominante da cena.

#### `cluster_dialogue_lines(candidates: list[dict], h_ref: float) -> list[dict]`
- Agrupa espacialmente linhas de texto com continuidade vertical e proximidade horizontal, descartando textos aleatórios de HUD ou cenário.

---

### Classes:

#### `BaseOCREngine(ABC)`
- Classe abstrata base para os motores de reconhecimento de imagem.
- **Método Obrigatório:**
  ```python
  @abstractmethod
  def extract_text_boxes(self, image_np: np.ndarray, offset_x: int = 0, offset_y: int = 0) -> list[tuple]:
      pass
  ```

#### `MangaOCREngine(BaseOCREngine)`
- Pipeline híbrido de OCR de alta precisão para caracteres japoneses.
- **Componentes:**
  - Detector de caixas: Rede neural CRAFT do `EasyOCR` em modo somente detecção (`detect_only=True`).
  - Reconhecedor: Modelo Vision Transformer `manga_ocr.MangaOcr`.
- **Fatiamento Dinâmico:** Linhas de largura $> 360\text{px}$ são fatiadas em janelas deslizantes de 340px com 80px de sobreposição e remontadas via `stitch_ocr_chunks`.
- **Retorno:** Lista de tuplas: `(box, texto, confianca, is_name)`.

#### `EasyOCREngine(BaseOCREngine)`
- Motor de OCR otimizado para alfabetos comuns/latinos (inglês, espanhol, etc.).
- Utiliza inferência direta com filtros de proporção e altura dominante de fonte.

#### `TranslationEngine`
- Gerenciador de tradução contextual com tolerância a falhas.
- **Provedores:**
  - Primário: Groq Cloud API executando modelos como `qwen/qwen3.8-27b` com prompts especializados de localização de jogos.
  - Fallback Secundário: `deep_translator.MyMemoryTranslator`.
  - Fallback Terciário: `deep_translator.GoogleTranslator`.
- **Métodos:**
  - `translate(self, text: str, is_name: bool = False) -> str`: Traduz o texto respeitando regras de nomes próprios se `is_name=True`.

#### `OCRTranslator`
- **Fachada (Facade)** que unifica visão e tradução.
- **Atributos:**
  - `translation_cache`: Dicionário em memória para cache de pares `{ chave: traducao }`.
  - `last_detected_raw`: String consolidada do último frame lido para teste anti-jitter.
  - `last_results`: Lista de dicionários da última inferência confirmada.
- **Métodos:**
  - `process_image(self, image_data, offset_x=0, offset_y=0, on_intermediate=None, force_reload=False) -> list[dict]`:
    - Processa o frame completo.
    - Se `force_reload=True`, invalida o cache, zera o anti-jitter e refaz a tradução do zero.
    - Emite chamadas intermediárias via `on_intermediate` com `[Traduzindo com IA...]`.
    - Retorna lista de dicionários no formato de saída de tradução.

---

## 4. `app/main.py`

Orquestrador e ponto de entrada da aplicação.

### Classes:

#### `WorkerThread(QThread)`
- Thread contínua de captura em background.
- **Sinais:**
  - `update_signal = pyqtSignal(list)`: Emite listas de dicionários com as traduções preliminares ou finais.
- **Métodos:**
  - `__init__(self, capture_region: dict, ocr_engine: OCRTranslator)`
  - `set_paused(self, is_paused: bool) -> None`: Pausa ou retoma o loop de processamento.
  - `request_reload(self) -> None`: Ativa a flag `force_reload`, forçando um novo ciclo de captura e OCR mesmo com a tela estática ou pausada.
  - `run(self) -> None`: Loop principal contendo o **Fast Frame Diffing** (downscale 128x64 com desvio de 0.8%), debounce de 200ms e chamada ao `process_image`.
  - `stop(self) -> None`: Sinaliza o encerramento seguro da thread.

---

## 5. `app/sidebar.py`

Interface gráfica do **Modo Painel**.

### Classes:

#### `SidebarWindow(QWidget)`
- Janela lateral compacta com visualização focada exclusivamente na fala da cena atual.
- **Flags de Janela:** `Qt.WindowType.WindowStaysOnTopHint`.
- **Sinais:**
  - `pause_toggled = pyqtSignal(bool)`: Emite `True` quando pausado e `False` quando ativo.
  - `reload_requested = pyqtSignal()`: Notifica o worker para forçar releitura da tela.
- **Métodos:**
  - `initUI(self)`: Monta toolbar superior, botões e área de rolagem `QScrollArea`.
  - `trigger_reload(self)`: Atualiza status para `🔄 Lendo tela...` e dispara `reload_requested`.
  - `toggle_history(self)`: Abre ou traz para frente a instância de `HistoryWindow`.
  - `toggle_pause(self)`: Alterna entre estado pausado e monitorando.
  - `clear_current_view(self)`: Limpa os cartões de fala exibidos no momento.
  - `update_texts(self, new_texts: list[dict])`:
    - Separa locutor de diálogo via `'is_name'`.
    - Renderiza a fala atual com badge destacado `👤 [Nome]`.
    - Quando a tradução final chega, compara com a fala anterior; se for nova, adiciona no `HistoryWindow`; se for continuação, atualiza a entrada correspondente.
  - `closeEvent(self, event)`: Garante que a janela de histórico seja fechada junto com a sidebar.

---

## 6. `app/history_window.py`

Janela dedicada à visualização do histórico de falas acumuladas na sessão.

### Classes:

#### `HistoryCardWidget(QFrame)`
- Card visual individual de cada diálogo registrado no histórico.
- **Métodos:**
  - `__init__(self, speaker: str, original: str, traducao: str, timestamp: str)`: Formata badge de locutor, horário da fala, texto original e texto traduzido.
  - `update_content(self, speaker: str, original: str, traducao: str)`: Atualiza o texto em tempo real (utilizado para efeito máquina de escrever).

#### `HistoryWindow(QWidget)`
- Janela rolável com lista completa de diálogos.
- **Flags de Janela:** `Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window`.
- **Métodos:**
  - `add_entry(self, speaker, original, traducao, timestamp=None)`: Adiciona um novo `HistoryCardWidget` e executa auto-scroll para o final (se o usuário não estiver lendo mensagens antigas).
  - `update_last_entry(self, speaker, original, traducao)`: Altera os dados da última fala registrada.
  - `clear_history(self)`: Remove todos os cards da interface e zera o contador.
  - `update_count_label(self)`: Atualiza o contador de falas na barra superior (`📜 Histórico (X falas)`).

---

## 7. `app/overlay.py`

Interface do **Modo Fantasma** para renderização de HUD transparente sobreposto ao jogo.

### Classes:

#### `OverlayWindow(QWidget)`
- **Flags de Janela:**
  - `FramelessWindowHint`: Remove bordas da janela.
  - `WindowStaysOnTopHint`: Fixa sobreposição sobre o jogo em modo janela sem bordas.
  - `WindowTransparentForInput`: **Garante passagem total de cliques do mouse para o jogo**.
  - `WA_TranslucentBackground`: Torna o fundo 100% transparente.
- **Métodos:**
  - `update_texts(self, new_texts: list[dict])`: Recebe as caixas e chama `self.update()`.
  - `paintEvent(self, event)`: Utiliza `QPainter` para desenhar retângulos semi-transparentes escuros sob cada caixa detectada e estampar a tradução com tamanho de fonte proporcional e quebra automática de linha.

---

## 8. Dicionário de Estruturas de Dados

### Dicionário de Monitor (`monitor`)
```python
{
    "left": 0,       # Posição X inicial no desktop virtual (int)
    "top": 0,        # Posição Y inicial (int)
    "width": 1920,   # Largura do monitor em pixels (int)
    "height": 1080   # Altura do monitor em pixels (int)
}
```

### Dicionário de Região de Interesse (`ROI`)
```python
{
    "left": 400,      # Coordenada X absoluta da captura (int)
    "top": 750,       # Coordenada Y absoluta da captura (int)
    "width": 1120,    # Largura da área capturada (int)
    "height": 280,    # Altura da área capturada (int)
    "offset_x": 400,  # Deslocamento horizontal em relação à tela (int)
    "offset_y": 750   # Deslocamento vertical em relação à tela (int)
}
```

### Matriz de Caixa Delimitadora (`box`)
Representada por uma lista de 4 vértices bidimensionais no sentido horário `[[x1, y1], [x2, y2], [x3, y3], [x4, y4]]`:
```python
[
    [450, 780],  # Superior Esquerdo
    [980, 780],  # Superior Direito
    [980, 840],  # Inferior Direito
    [450, 840]   # Inferior Esquerdo
]
```

### Dicionário de Saída de Tradução (`item`)
Emitido pelo `WorkerThread` para as janelas gráficas através do `update_signal`:
```python
{
    "original": "お待たせしました！",          # Texto puro capturado pelo OCR (str)
    "traducao": "Obrigado por esperar!",       # Texto traduzido final ou preliminar (str)
    "box": [[450, 780], ...],                 # Coordenadas absolutas na tela (list[list[int]])
    "confidence": 0.98,                       # Grau de confiança do OCR entre 0.0 e 1.0 (float)
    "is_name": False                          # True se for identificado como nome de personagem (bool)
}
```

