# 💡 Ideia do Projeto: Tradutor em Tempo Real

## 🎯 Objetivo Principal
O objetivo do projeto é desenvolver um tradutor de tela em tempo real para **tradução em geral**.

A ideia inicial surgiu da necessidade de traduzir **jogos em Japonês para Inglês**, mas hoje o escopo abrange a tradução de qualquer conteúdo na tela. Atualmente, os principais pares de idiomas são:
- Tradução geral de **Japonês para Inglês**.
- Tradução geral de **Inglês para Português Brasileiro**.

---

## 🚀 Como o Projeto Funciona Atualmente

O programa roda em um ciclo contínuo dividido nas seguintes etapas:

### 1. Configuração Inicial (via Launcher ou Terminal)
Ao iniciar o programa, o usuário escolhe:
- **Monitor:** em qual monitor o conteúdo está sendo exibido.
- **Área de Captura:** seleção interativa com o mouse, presets rápidos ou tela cheia.
- **Modo de Exibição:**
  - *Modo Painel:* janela lateral com histórico de legendas e controles.
  - *Modo Fantasma:* tarja transparente flutuante sobreposta diretamente na tela.
- **Idiomas:** seleção do par de tradução (*Japonês -> Inglês*, *Inglês -> Português do Brasil* ou *Japonês -> Português*).

### 2. Captura de Tela
- **Ferramenta:** biblioteca `mss`.
- **Funcionamento:** captura apenas a região selecionada direto na memória RAM, sem salvar imagens no disco.

### 3. Detecção de Alteração de Tela
- O sistema compara o frame atual com o anterior para saber se o texto mudou.
- Se a tela estiver parada, o processamento é pausado.
- Quando uma mudança é detectada, o programa aguarda uma fração de segundo para que eventuais efeitos de digitação terminem antes de fazer a leitura.

### 4. Extração de Texto (OCR)
O texto da tela é extraído utilizando dois motores:
- **MangaOCR:** especializado no idioma **Japonês**. Consegue ler fontes estilizadas, textos verticais e horizontais, além de descartar automaticamente legendas secundárias em inglês.
- **EasyOCR:** motor mais generalista, utilizado para idiomas de **alfabeto latino** (como Inglês e Espanhol).

**Tratamentos aplicados ao texto:**
- Filtro para ignorar botões de interface/HUD.
- Separação automática entre o **nome/título do locutor** e o **texto principal**.

- Correção de pontuações e caracteres corrompidos por fontes personalizadas.
- Trava de estabilidade: evita retraduzir caso a mesma frase apresente pequenas oscilações de leitura.

### 5. Tradução
- **Motor Principal:** utiliza a **Groq API** (modelo Qwen).
- **Motor de Fallback:** se estiver sem internet, sem chave de API ou houver falha de conexão, o sistema usa automaticamente o `deep-translator` (Google Tradutor ou MyMemory).

### 6. Exibição na Interface Gráfica (PyQt6)
- Os textos traduzidos são exibidos em tempo real na interface escolhida (Painel lateral ou Overlay sobreposto).
- Na janela lateral, o usuário pode pausar a captura ou forçar uma releitura manual da tela a qualquer momento.

---

## 🔮 Planos Futuros

- **Mais idiomas:** adicionar suporte a novos idiomas de origem e destino (a serem definidos).
- **Tradução de áudio:** capturar e traduzir o áudio em tempo real.
- **Modo educativo:** tradução parcial para ajudar no aprendizado de novos idiomas.

