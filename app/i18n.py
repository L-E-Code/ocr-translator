"""
Interface language: English or Brazilian Portuguese.

Every user-facing string goes through tr(), with the English text as the key. A string without a
Portuguese entry simply shows in English. Logs stay in English, for the developer.
"""
from config_manager import load_config, DEFAULT_CONFIG

UI_LANGUAGES = {"en": "English", "pt": "Português (Brasil)"}
DEFAULT_UI_LANGUAGE = DEFAULT_CONFIG["ui_language"]

_current = None  # read from the saved settings on the first call


def ui_language():
    """Code of the language in use ('en' or 'pt')."""
    if _current is None:
        set_ui_language(load_config().get("ui_language", DEFAULT_UI_LANGUAGE))
    return _current


def set_ui_language(code):
    """Changes the language used by tr(). Unknown codes fall back to English."""
    global _current
    _current = code if code in UI_LANGUAGES else DEFAULT_UI_LANGUAGE


def tr(text, **values):
    """Returns the text in the current language, filling in {placeholders} with the given values."""
    translated = _PT.get(text, text) if ui_language() == "pt" else text
    return translated.format(**values) if values else translated


_PT = {
    # ---- Control Center (launcher) ----
    "Real-time screen translation": "Tradução de tela em tempo real",
    "Ready to start": "Pronto para iniciar",
    "Profile": "Perfil",
    "Save as profile…": "Salvar como perfil…",
    "Stores the current settings (area, languages, display, window) in a profile":
        "Guarda as configurações atuais (área, idiomas, exibição, janela) em um perfil",
    "Delete": "Excluir",
    "Switch profile automatically": "Trocar de perfil automaticamente",
    "Pause / resume": "Pausar / retomar",
    "Retranslate now": "Traduzir novamente agora",
    "Show / hide the panel": "Mostrar / ocultar o painel",
    "Open / close the history": "Abrir / fechar o histórico",
    "Clear the current line": "Limpar a linha atual",
    "Bottom third": "Terço inferior",
    "Default for dialogue boxes and subtitles": "Padrão para caixas de diálogo e legendas",
    "Bottom half": "Metade inferior",
    "Full screen": "Tela inteira",
    "Slower": "Mais lento",
    "Custom": "Personalizada",
    "Area: not set": "Área: não definida",
    "Capture regions (several areas at once: dialogue, menu…)":
        "Regiões de captura (várias áreas ao mesmo tempo: diálogo, menu…)",
    "Add region…": "Adicionar região…",
    "Remove": "Remover",
    "Game window": "Janela do jogo",
    "Choose…": "Escolher…",
    "Follow the window": "Acompanhar a janela",
    "The area follows the game if it is moved or resized. Applies to the custom area. The window must be visible with no other window on top of it.":
        "A área segue o jogo se ele for movido ou redimensionado. Vale para a área personalizada. "
        "A janela precisa estar visível e sem outra janela por cima.",
    "Languages": "Idiomas",
    "Processing": "Processamento",
    "Automatic (uses the GPU if there is one)": "Automático (usa a GPU, se houver)",
    "How to show the translation": "Como exibir a tradução",
    "Side panel": "Painel lateral",
    "Window with the current line and history": "Janela com a linha atual e o histórico",
    "On screen": "Na tela",
    "Translation drawn on top of the game or video": "Tradução desenhada sobre o jogo ou vídeo",
    "Cover the original text": "Cobrir o texto original",
    "Bottom subtitle": "Legenda na parte inferior",
    "Opacity": "Opacidade",
    "Wait for the text": "Aguardar o texto",
    "Use previous lines as context": "Usar linhas anteriores como contexto",
    "Minimize this window on start": "Minimizar esta janela ao iniciar",
    "Forces a re-read and a new translation of the scene now": "Força uma nova leitura e uma nova tradução da cena agora",
    "Open the log files folder": "Abrir a pasta de logs",
    "Restore default settings": "Restaurar configurações padrão",
    " Pause": " Pausar",
    " Retranslate": " Traduzir novamente",
    " History": " Histórico",
    " Logs": " Logs",
    "  Start translation": "  Iniciar tradução",
    "  Stop translation": "  Parar tradução",
    "Translating": "Traduzindo",
    "Translating · {device}": "Traduzindo · {device}",
    "Settings restored": "Configurações restauradas",
    "Restore defaults": "Restaurar padrões",
    "GPU not found": "GPU não encontrada",
    "GPU support": "Suporte a GPU",
    "Enable the GPU": "Ativar a GPU",
    "Graphics card detected: {gpu_name}": "Placa de vídeo detectada: {gpu_name}",
    "Download and install": "Baixar e instalar",
    "Not now": "Agora não",
    "Error": "Erro",
    "Could not start the installer:\n{e}": "Não foi possível iniciar o instalador:\n{e}",
    "GPU available ({name}), but CPU mode is selected.": "GPU disponível ({name}), mas o modo CPU está selecionado.",
    "Will use the GPU: {name} ({kind}).": "Vai usar a GPU: {name} ({kind}).",
    "Checking graphics card…": "Verificando a placa de vídeo…",
    "No compatible GPU found. Processing will run on the CPU.":
        "Nenhuma GPU compatível encontrada. O processamento vai usar a CPU.",
    "No monitor detected": "Nenhum monitor detectado",
    "Area not set": "Área não definida",
    "No profile (current settings)": "Nenhum perfil (configurações atuais)",
    "Save profile": "Salvar perfil",
    "Profile name (for example, the game's name):": "Nome do perfil (por exemplo, o nome do jogo):",
    "Replace profile": "Substituir perfil",
    "A profile named “{name}” already exists. Replace it?": "Já existe um perfil chamado “{name}”. Substituí-lo?",
    "Profile “{name}” saved": "Perfil “{name}” salvo",
    "Delete profile": "Excluir perfil",
    "Delete the profile “{name}”?": "Excluir o perfil “{name}”?",
    "Profile “{name}” deleted": "Perfil “{name}” excluído",
    "Profile “{name}” activated by the game window": "Perfil “{name}” ativado pela janela do jogo",
    "Rename, duplicate or delete the profile": "Renomear, duplicar ou excluir o perfil",
    "Rename…": "Renomear…",
    "Duplicate…": "Duplicar…",
    "Rename profile": "Renomear perfil",
    "Duplicate profile": "Duplicar perfil",
    "A profile named “{name}” already exists.": "Já existe um perfil chamado “{name}”.",
    "Profile “{name}” renamed": "Perfil “{name}” renomeado",
    "{name} (copy)": "{name} (cópia)",
    "Glossary": "Glossário",
    "Fixed translations for names and terms. Each profile can use its own file.":
        "Traduções fixas para nomes e termos. Cada perfil pode usar o próprio arquivo.",
    "Edit terms…": "Editar termos…",
    "New…": "Novo…",
    "Creates a glossary file for this game": "Cria um arquivo de glossário para este jogo",
    "Default ({name})": "Padrão ({name})",
    "New glossary": "Novo glossário",
    "Name (for example, the game's name):": "Nome (por exemplo, o nome do jogo):",
    "Could not save the file:\n{e}": "Não foi possível salvar o arquivo:\n{e}",
    "Could not read the file:\n{e}": "Não foi possível ler o arquivo:\n{e}",
    "{file} · {pair}": "{file} · {pair}",
    "Fixed translations for names and terms: the AI must use exactly these. Changes apply to the next line, even with the translation running.":
        "Traduções fixas para nomes e termos: a IA deve usar exatamente estas. As alterações valem a partir da próxima linha, mesmo com a tradução rodando.",
    "Original": "Original",
    "Translation": "Tradução",
    "Add term": "Adicionar termo",
    "Cancel": "Cancelar",
    "Save": "Salvar",
    "Fill in both the original and the translation, or remove the line.":
        "Preencha o original e a tradução, ou remova a linha.",
    "Main": "Principal",
    "Region {n}": "Região {n}",
    "Additional region": "Região adicional",
    "The limit is {n} regions.": "O limite é de {n} regiões.",
    "Region name": "Nome da região",
    "Name (for example: menu, names, subtitle):": "Nome (por exemplo: menu, nomes, legenda):",
    "Remove region": "Remover região",
    "No window found": "Nenhuma janela encontrada",
    "Enter the game window in order to follow it": "Informe a janela do jogo para acompanhá-la",
    "Window “{title}” not found: open the game and try again":
        "Janela “{title}” não encontrada: abra o jogo e tente de novo",
    "Show the control center": "Mostrar a central de controle",
    "Quit": "Sair",
    "No monitor available.": "Nenhum monitor disponível.",
    "Same languages": "Idiomas iguais",
    "Choose a source language different from the target language.":
        "Escolha um idioma de origem diferente do idioma de destino.",
    "Loading AI engines…": "Carregando os motores de IA…",
    "Initialization error": "Erro de inicialização",
    "Could not load the AI engines:\n{err}": "Não foi possível carregar os motores de IA:\n{err}",
    "Failed to load models": "Falha ao carregar os modelos",
    "Stopping…": "Parando…",
    "Stopped": "Parado",
    "Capture paused": "Captura pausada",
    "Reading the screen…": "Lendo a tela…",
    "Monitor": "Monitor",
    "Interface language": "Idioma da interface",
    # ---- Languages (names shown in the combo boxes) ----
    "Japanese": "Japonês",
    "English": "Inglês",
    "Portuguese (BR)": "Português (BR)",
    # ---- Reading panel (sidebar) ----
    "OCR Translator — Reading Panel": "OCR Translator — Painel de leitura",
    "Monitoring": "Monitorando",
    "Retranslate: re-reads the screen now and produces a new translation":
        "Traduzir novamente: relê a tela agora e gera uma nova tradução",
    "Open history": "Abrir histórico",
    "Pause reading": "Pausar leitura",
    "Keep always on top": "Manter sempre no topo",
    "Waiting for text on screen…": "Aguardando texto na tela…",
    "Resume reading": "Retomar leitura",
    "Paused": "Pausado",
    "From cache · instant": "Do cache · instantâneo",
    "Groq limit reached · using {engine} · {ms} ms": "Limite do Groq atingido · usando {engine} · {ms} ms",
    "Translation unavailable: no connection or services are down":
        "Tradução indisponível: sem conexão ou serviços fora do ar",
    "Backup engine: {engine} · {ms} ms": "Motor reserva: {engine} · {ms} ms",
    "Translating…": "Traduzindo…",
    "Copy translation": "Copiar tradução",
    "Click a word to see its reading and meaning": "Clique em uma palavra para ver a leitura e o significado",
    "No entry in the dictionary.": "Sem entrada no dicionário.",
    # ---- History window ----
    "OCR Translator — History": "OCR Translator — Histórico",
    "History": "Histórico",
    "No lines yet": "Nenhuma linha ainda",
    "1 line": "1 linha",
    "{n} lines": "{n} linhas",
    "Export history (.txt)": "Exportar histórico (.txt)",
    "Copy all translations": "Copiar todas as traduções",
    "Clear history": "Limpar histórico",
    "Search the history…": "Pesquisar no histórico…",
    "Translated lines will appear here.": "As linhas traduzidas aparecerão aqui.",
    "Export history": "Exportar histórico",
    "Text (*.txt)": "Texto (*.txt)",
    # ---- Screen selection and overlay ----
    "Click and drag over the text area to translate   ·   Esc cancels":
        "Clique e arraste sobre a área de texto para traduzir   ·   Esc cancela",
    # ---- Wording added with the translation of the dialogs and tooltips ----
    "  Select area with the mouse": "  Selecionar área com o mouse",
    "1 · Capture": "1 · Captura",
    "2 · Translation": "2 · Tradução",
    "3 · Global hotkeys": "3 · Atalhos globais",
    "First choose \"Custom\" and select the main area.": "Primeiro escolha \"Personalizada\" e selecione a área principal.",
    "Select an additional region. The main one is changed with \"Select area with the mouse\".":
        "Selecione uma região adicional. A principal é alterada com \"Selecionar área com o mouse\".",
    "Hotkey unavailable (in use by another program or invalid): ":
        "Atalho indisponível (em uso por outro programa ou inválido): ",
    "  ·  attached to the window": "  ·  vinculada à janela",
    "  ·  +{n} region(s)": "  ·  +{n} região(ões)",
    "{status} · backup engine": "{status} · motor reserva",
    "{shown} of {count} lines": "{shown} de {count} linhas",
    "Graphics card detected: {gpu}, but PyTorch support is missing. Choose \"GPU\" to download and enable it.":
        "Placa de vídeo detectada: {gpu}, mas falta o suporte do PyTorch. Escolha \"GPU\" para baixar e ativar.",
    "Graphics card detected: {gpu_name}.\nInstall the PyTorch build for {family} manually.":
        "Placa de vídeo detectada: {gpu_name}.\nInstale manualmente o PyTorch com suporte a {family}.",
    "To use the GPU you need to download the PyTorch build with {family} support (over 2 GB).\n\n"
    "OCR Translator will be closed, the installation runs in a terminal window and the app reopens by itself when it finishes. Download now?":
        "Para usar a GPU é preciso baixar a versão do PyTorch com suporte a {family} (mais de 2 GB).\n\n"
        "O OCR Translator será fechado, a instalação roda em uma janela do terminal e o app reabre sozinho quando terminar. Baixar agora?",
    "I did not find a compatible graphics card (NVIDIA or Intel Arc) on this computer.\nProcessing will continue on the CPU.":
        "Não encontrei uma placa de vídeo compatível (NVIDIA ou Intel Arc) neste computador.\nO processamento continuará na CPU.",
    "All preferences (monitor, areas, languages, display mode, speed settings and hotkeys) will go back to their default values. Your saved profiles are kept. Continue?":
        "Todas as preferências (monitor, áreas, idiomas, modo de exibição, velocidade e atalhos) voltarão aos valores padrão. Seus perfis salvos são mantidos. Continuar?",
    "Applies to profiles with the \"Game window\" filled in: when the game is brought to the front, its profile is loaded.":
        "Vale para perfis com a \"Janela do jogo\" preenchida: quando o jogo vai para a frente, o perfil dele é carregado.",
    "They work in any window, including with the game in the foreground, while the translation is running. Use Ctrl, Alt or Shift together with the key; clear a field to disable a hotkey.":
        "Funcionam em qualquer janela, inclusive com o jogo em primeiro plano, enquanto a tradução estiver rodando. Use Ctrl, Alt ou Shift junto com a tecla; deixe um campo vazio para desativar o atalho.",
    "With several regions, each one gets its own card, in the side panel and on screen.":
        "Com várias regiões, cada uma ganha seu próprio cartão, no painel lateral e na tela.",
    "Game window “{title}” not found or minimized. Showing the last line.":
        "Janela do jogo “{title}” não encontrada ou minimizada. Mostrando a última linha.",
    "Game window not found": "Janela do jogo não encontrada",
    "Game window “{title}” found again: translation resumed.":
        "Janela do jogo “{title}” encontrada de novo: tradução retomada.",
    "How long the screen must stay still before reading.\nLower = translates faster; higher = avoids reading text that is still being typed.":
        "Quanto tempo a tela precisa ficar parada antes da leitura.\nMenor = traduz mais rápido; maior = evita ler texto que ainda está sendo digitado.",
    "The AI receives the latest lines already translated to get gender, pronouns and omitted subjects right. Makes each translation a little slower; clear it if you prefer speed.":
        "A IA recebe as últimas linhas já traduzidas para acertar gênero, pronomes e sujeitos omitidos. Deixa cada tradução um pouco mais lenta; desmarque se preferir velocidade.",
}
