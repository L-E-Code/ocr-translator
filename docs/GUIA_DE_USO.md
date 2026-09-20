# Guia de Uso e Operação — OCR Translator

Este guia orienta passo a passo a instalação, configuração de credenciais, calibração de tela e operação dos modos de tradução do **OCR Translator**.

---

## 1. Pré-Requisitos e Configuração Inicial

### Requisitos do Sistema:
- **Sistema Operacional:** Windows 10 ou 11 (64-bit).
- **Python:** Versão 3.10 ou superior instalada (com a opção *"Add Python to PATH"* marcada).
- **Conexão com a Internet:** Necessária para o download automático dos modelos na primeira execução e para as requisições de tradução da IA.

---

### Configuração da Chave de Inteligência Artificial (Groq):

O projeto utiliza primariamente o modelo **Qwen-2.5 27B** através da API de ultra-baixa latência da **Groq** para realizar localização inteligente de jogos (corrigindo eventuais ruídos de OCR e mantendo o tom dos personagens).

1. Acesse o portal da [Groq Console](https://console.groq.com/) e crie uma conta gratuita.
2. No menu lateral, acesse **API Keys** e clique em **Create API Key**.
3. Copie a chave gerada (ela começa com `gsk_...`).
4. Na pasta raiz do projeto, copie ou renomeie o arquivo `.env.example` para `.env`.
5. Abra o arquivo `.env` com qualquer editor de texto e insira sua chave:
   ```env
   GROQ_API_KEY=gsk_sua_chave_aqui_sem_aspas
   ```
> [!NOTE]
> Se você não configurar a chave da Groq, o sistema funcionará normalmente usando o mecanismo de **fallback automático** (Google Translate e MyMemory), porém sem a autocorreção de contexto fornecida pelo modelo neural.

---

## 2. Inicialização do Programa

Existem duas formas de iniciar o aplicativo:

### Opção A: Execução Rápida (Recomendada)
- Dê um duplo clique no arquivo **`iniciar.bat`**.
- Caso seja a sua primeira execução, o script chamará automaticamente o `instalar.bat` para criar o ambiente virtual (`.venv`) e instalar todas as dependências necessárias.

### Opção B: Via Terminal (PowerShell / CMD)
```powershell
# Ative o ambiente virtual
.\.venv\Scripts\Activate.ps1

# Inicie o orquestrador
python app/main.py
```

---

## 3. Central de Controle (Interface Gráfica - GUI)

Ao iniciar o programa (pelo `iniciar.bat` ou via `python app/main.py`), a **Central de Controle (GUI)** é aberta imediatamente. Nela você pode configurar tudo visualmente antes de iniciar a captura:

```
┌────────────────────────────────────────────────────────┐
│ OCR TRANSLATOR                                         │
│ Tradutor de Tela em Tempo Real                         │
├────────────────────────────────────────────────────────┤
│ 1. MONITOR & ÁREA DE CAPTURA                           │
│ Monitor: [ Monitor 1 (1920x1080 px)                  ▼]│
│ (•) Caixa de Diálogos Padrão (Terço Inferior)          │
│ ( ) Metade Inferior da Tela                            │
│ ( ) Tela Inteira (Mais lento)                          │
│ ( ) Área Personalizada                                 │
│ [🎯 Demarcar Área com o Mouse]   Área: 1066x279 px...  │
├────────────────────────────────────────────────────────┤
│ 2. IDIOMAS & MODO DE VISUALIZAÇÃO                      │
│ Tradução: [ Japonês ➔ Inglês (MangaOCR)              ▼]│
│ (•) Modo Painel (Janela Lateral com Legendas)          │
│ ( ) Modo Fantasma (Tarjas Sobrepostas no Jogo)         │
│ [x] Minimizar esta central ao iniciar a tradução       │
├────────────────────────────────────────────────────────┤
│ [             ▶ INICIAR TRADUÇÃO                     ] │
│ [ ❚❚ Pausar ]    [ 🔄 Retraduzir ]    [ 📜 Histórico ] │
│ ● Pronto para iniciar                                  │
└────────────────────────────────────────────────────────┘
```

### Principais Recursos da Central:
1. **Seleção de Monitor:** Detecta e lista todos os monitores conectados com suas resoluções.
2. **Área de Captura (ROI):**
   - **`🎯 Demarcar Área com o Mouse`**: Ao clicar, a tela é coberta com uma máscara e você desenha o retângulo sobre o diálogo do jogo. As coordenadas são salvas no `config.json`.
   - **Presets Rápidos**: Terço Inferior, Metade Inferior ou Tela Cheia.
3. **Pares de Idiomas Suportados:**
   - *Japonês ➔ Inglês* (MangaOCR)
   - *Inglês ➔ Português do Brasil* (EasyOCR)
   - *Japonês ➔ Português do Brasil* (MangaOCR)
4. **Modo de Exibição:** Escolha entre o *Modo Painel* (sidebar lateral) ou *Modo Fantasma* (overlay sobre o jogo).
5. **Carregamento Não-Bloqueante:** Os modelos de IA são carregados em segundo plano, sem congelar ou travar o Windows.
6. **Modo Terminal Legado (Opcional):**
   - Se preferir o assistente interativo via terminal de texto, basta executar:
     ```powershell
     python app/main.py --cli
     ```

---

## 4. Operando no Modo Painel (`SidebarWindow`)

O Modo Painel é a interface principal de leitura, ideal para ser posicionada na lateral da tela ou em um segundo monitor.

```
┌──────────────────────────────────────────────┐
│ ● Monitorando    [🔄 Retraduzir] [📜 Histórico] [❚❚ Pausar] [🗑 Limpar] │
├──────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────┐ │
│ │ 👤 [Nome do Personagem]                  │ │
│ │                                          │ │
│ │ Original: お待たせしました！             │ │
│ │ Tradução: Obrigado por esperar!          │ │
│ └──────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

### Recursos da Barra Superior:
1. **Indicador de Status Dinâmico:**
   - `● Monitorando` (Verde): O sistema está capturando e aguardando novas falas.
   - `● Traduzindo...` (Azul): Texto detectado; a IA está formulando a tradução.
   - `🔄 Lendo tela...` (Azul claro): Releitura forçada em andamento.
   - `❚❚ Pausado` (Amarelo): Captura suspensa temporariamente.
2. **Botão `🔄 Retraduzir`**:
   - Força uma releitura imediata da tela naquele mesmo instante, ignorando o teste de semelhança de cena e esvaziando o cache.
   - Ideal para casos em que o jogo estava terminando uma animação quando o OCR leu, ou se você desejar uma nova alternativa de tradução da IA.
3. **Botão `📜 Histórico`**:
   - Abre ou traz para frente a **Janela de Histórico Dedicada**.
4. **Botão `❚❚ Pausar / ▶ Retomar`**:
   - Congela temporariamente a leitura da tela (ideal para cutscenes longas sem texto ou momentos em que você precisa pausar o jogo sem que o OCR continue consumindo recursos).
5. **Botão `🗑 Limpar`**:
   - Limpa a visualização da tela atual da sidebar.

---

## 5. Operando a Janela de Histórico (`HistoryWindow`)

Ao clicar em **`📜 Histórico`**, uma janela independente é exibida:

- **Ordem Cronológica:** Registra todas as falas finalizadas da sessão de jogo.
- **Identificação Completa:** Cada entrada traz o nome do locutor destacado (`👤 [Nome]`), o horário exato da captura (`HH:MM:SS`), o texto original e a tradução definitiva.
- **Deduplicação Inteligente:** Se o jogo apresentar efeito máquina de escrever (letras surgindo uma a uma), o histórico atualiza a frase no mesmo card em vez de gerar dezenas de mensagens duplicadas.
- **Auto-Scroll Inteligente:** A janela acompanha as falas mais recentes descendo automaticamente até o final, **a menos que você role a barra para cima** para ler falas antigas (evitando puxar a tela contra a sua vontade durante a leitura).
- **Botão `🗑 Limpar`:** Zera a lista de falas da sessão.

---

## 6. Operando no Modo Fantasma (`OverlayWindow`)

O Modo Fantasma projeta as legendas diretamente em cima da imagem do jogo:

1. **Passagem de Cliques (`Click-Through`):**
   - A janela do overlay possui o atributo `WA_TransparentForInput`. Isso significa que **nenhum clique do mouse é bloqueado**. Você pode clicar nos menus, botões do jogo e movimentar o mouse normalmente, pois a janela é intangível.
2. **Caixas Translúcidas:**
   - Um retângulo preto com 85% de opacidade é desenhado exatamente sobre a caixa de texto original do jogo, cobrindo o texto original com a tradução em letras brancas legíveis.
3. **Configuração Recomendada do Jogo:**
   - Para que o overlay funcione com perfeição, configure o seu jogo no modo de vídeo **Janela Sem Bordas (Borderless Window / Windowed Fullscreen)**. Jogos em modo *Fullscreen Exclusivo* podem sobrepor janelas do sistema operacional.

---

## 7. Encerrando o Aplicativo

Para encerrar a execução a qualquer momento:
- Feche a janela da interface (Sidebar ou Overlay).
- Ou pressione `Ctrl + C` no terminal onde o programa foi iniciado.
