# Larva Behavior Tracking & Analysis Pipeline

Pipeline completo e automatizado para extração de frames, rastreamento comportamental de larvas de *Drosophila* no Fiji/ImageJ e análise quantitativa/cinemática em Python.

---

## 🧭 Guia para Iniciantes (Setup Rápido do Zero)

Se nunca usaste Python antes ou estás a configurar o teu computador pela primeira vez, segue estes passos simples:

### 1. Instalar o Python
1. Faz o download do **Python 3.10+** (recomendado 3.10 ou 3.11) no site oficial: [python.org/downloads](https://www.python.org/downloads/).
2. **IMPORTANTE no Windows**: Durante a instalação, marca a opção **"Add Python to PATH"** no primeiro ecrã antes de clicar em *Install Now*.

---

### 2. Ambiente Recomendado: PyCharm (Mais Fácil) 🚀

Recomendamos vivamente o **[PyCharm Community Edition](https://www.jetbrains.com/pycharm/download/)** (gratuito). Ele simplifica a gestão do Python, a instalação de bibliotecas e a execução de notebooks/scripts com apenas um clique:

1. **Descarregar e Instalar**:
   - Faz o download do **PyCharm Community Edition**.
2. **Abrir o Projeto**:
   - Abre o PyCharm e escolhe **Open**.
   - Seleciona a pasta raiz deste repositório (`Behavior`).
3. **Configurar o Ambiente Virtual (Virtualenv)**:
   - O PyCharm costuma perguntar automaticamente se queres criar um ambiente virtual (`venv`). Se sim, clica em **Create**.
   - Caso contrário: vai a `File` -> `Settings` (ou `Ctrl+Alt+S`) -> `Project: Behavior` -> `Python Interpreter` -> `Add Interpreter` -> `New Virtualenv Environment` e clica em **OK**.
4. **Instalar Dependências**:
   - Abre o terminal integrado no fundo do PyCharm (separador **Terminal**) e corre:
     ```bash
     pip install -r requirements.txt
     ```
   - *Alternativa no PyCharm*: Ao abrir o ficheiro `requirements.txt`, o PyCharm apresentará uma barra no topo a sugerir *"Install requirements"*. Podes clicar aí diretamente!

---

### 3. Alternativa via Linha de Comandos / Terminal (VS Code ou PowerShell)

Se preferires usar o terminal padrão:
```bash
# 1. Clonar o repositório
git clone https://github.com/TSGouveia/Behavior.git
cd Behavior

# 2. Criar ambiente virtual
python -m venv venv

# 3. Ativar o ambiente virtual:
# No Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# No Mac/Linux:
source venv/bin/activate

# 4. Instalar as bibliotecas necessárias
pip install -r requirements.txt
```

---

## 📁 Estrutura do Projeto

Os ficheiros de dados estão organizados por **genótipo** para permitir análises comparativas automáticas:

```text
Behavior/
├── data/
│   ├── csvs/                          # Ficheiros CSV de coordenadas divididos por genótipo
│   │   ├── nSybxRalRNAi/              # Pasta com o nome do genótipo
│   │   │   ├── N1_..._L1_FA.csv
│   │   │   ├── N2_..._L1_FA.csv
│   │   │   └── N3_..._L1_FA.csv
│   │   └── OutroGenotipo/             # Podes adicionar novos genótipos em novas pastas
│   │       └── ...
│   └── results/                       # Tabelas e gráficos consolidados de saída
│       ├── larva_batch_summary.csv
│       ├── larva_batch_summary.xlsx
│       └── all_larvae_trajectory_overlay.png
├── python/
│   ├── larva_analysis.py              # Módulo com a física, limpeza, cinemática e QC
│   └── larva_crawling_analysis.ipynb  # Notebook Jupyter interativo para análise visual e em lote
├── videos/
│   └── extract_parallel.py            # Script paralelo para extrair .h264 para sequências PNG via ffmpeg
├── larva_tracking.ijm                 # Macro de Fiji/ImageJ para tracking com subtração de fundo
├── requirements.txt                   # Lista de bibliotecas Python necessárias
└── README.md                          # Documentação do projeto
```

> [!NOTE]
> **Organização por Genótipo**: Dentro de `data/csvs/`, cria uma pasta para cada genótipo (por exemplo `data/csvs/Controlo/`, `data/csvs/Mutante/`). O código deteta automaticamente o genótipo com base no nome da pasta e gera gráficos de linhas separados por genótipo, agrupando as coortes `N1`, `N2`, `N3` de cada um!

---

## 🚀 Como Usar o Pipeline

### Passo 1: Extração de Frames (`videos/extract_parallel.py`)
Converte os vídeos gravados pela Raspberry Pi (`.h264`, 30 fps) numa sequência de imagens `.png` organizadas em pastas:
```bash
python videos/extract_parallel.py --dir /caminho/para/os/videos
```
*(Se executares o script diretamente dentro da pasta dos vídeos, não precisas de passar argumentos)*.

---

### Passo 2: Tracking no Fiji / ImageJ (`larva_tracking.ijm`)
1. Abre o **Fiji / ImageJ**.
2. Arrasta o ficheiro `larva_tracking.ijm` para o Fiji e clica em **Run**.
3. Seleciona a pasta com a sequência de frames PNG da gravação.
4. Segue os passos de calibração na interface:
   - Canal de cor com maior contraste (Red, Green ou Blue).
   - Delimitação da arena circular (ROI).
   - Escala de píxeis para milímetros (usando a régua da placa).
   - Delinear uma larva para definir o tamanho esperado.
5. Guarda o ficheiro CSV resultante dentro da subpasta do respetivo genótipo em `data/csvs/<NomeDoGenotipo>/`.

---

### Passo 3: Análise e Gráficos em Python

#### Opção A: Usar o Notebook Interativo (Recomendado)
1. No **PyCharm** (ou via Jupyter Lab / Notebook), abre o ficheiro `python/larva_crawling_analysis.ipynb`.
2. Se estiveres no terminal, podes abrir o Jupyter com:
   ```bash
   jupyter notebook python/larva_crawling_analysis.ipynb
   ```
3. Executa as células por ordem (ou clica em **Run All**):
   - **Busca Recursiva**: O notebook lê automaticamente todos os ficheiros CSV dentro de todas as pastas em `data/csvs/`.
   - **Limpeza de Artefactos**: Interpola falhas curtas de deteção sem inventar movimento ou teletransporte durante pausas longas.
   - **Gráficos por Genótipo e Coorte (NX)**:
     - Velocidade ao longo do tempo (com faixa de IQR sombreada para cada N1, N2, etc.).
     - Distância acumulada ao longo do tempo.
     - Trajetórias suavizadas e centralizadas na arena (`*_larvae_trajectory_overlay.png`).
     - Trajetória individual de cada larva com escala de cor temporal uniforme.
   - **Tabela Resumo (Batch)**: Gera automaticamente ficheiros Excel e CSV com todas as métricas consolidadas.

#### Opção B: Linha de Comandos direta (CLI)
Podes também executar o módulo de análise diretamente no terminal:
```bash
python python/larva_analysis.py --folder data/csvs --summary-out data/results/larva_batch_summary.csv --overlay-out data/results/all_larvae_trajectory_overlay.png
```

---

## 📊 Ficheiros de Saída (`data/results/`)

- **`larva_batch_summary.csv` / `.xlsx`**: Tabela com todas as métricas por larva (distância total percorrida, velocidade média e mediana, tempo sem deteção, etc.).
- **`<Genotipo>_<Cohort>_larvae_trajectory_overlay.png`**: Sobreposição das trajetórias de cada coorte de um genótipo centradas na arena.
- **`all_larvae_trajectory_overlay.png`**: Sobreposição geral com todas as larvas do lote.
