# Larva Behavior Tracking & Analysis Pipeline

Complete, automated pipeline for frame extraction, *Drosophila* larval behavioral tracking in Fiji/ImageJ, and quantitative kinematic analysis in Python.

---

## 🧭 Beginner's Guide (Quick Setup from Scratch)

If you haven't used Python before or are setting up your computer for the first time, follow these simple steps:

### 1. Install Python
1. Download **Python 3.10+** (recommended 3.10 or 3.11) from the official website: [python.org/downloads](https://www.python.org/downloads/).
2. **IMPORTANT on Windows**: During installation, check the box **"Add Python to PATH"** on the first screen before clicking *Install Now*.

---

### 2. Recommended Environment: PyCharm (Easiest) 🚀

We strongly recommend **[PyCharm Community Edition](https://www.jetbrains.com/pycharm/download/)** (free). It simplifies Python management, dependency installation, and running notebooks/scripts with a single click:

1. **Download and Install**:
   - Download **PyCharm Community Edition**.
2. **Open the Project**:
   - Open PyCharm and select **Open**.
   - Choose the root folder of this repository (`Behavior`).
3. **Configure Virtual Environment (Virtualenv)**:
   - PyCharm usually asks automatically if you want to create a virtual environment (`venv`). If prompted, click **Create**.
   - Otherwise: go to `File` -> `Settings` (or `Ctrl+Alt+S`) -> `Project: Behavior` -> `Python Interpreter` -> `Add Interpreter` -> `New Virtualenv Environment` and click **OK**.
4. **Install Dependencies**:
   - Open the integrated terminal at the bottom of PyCharm (**Terminal** tab) and run:
     ```bash
     pip install -r requirements.txt
     ```
   - *Alternative in PyCharm*: When opening `requirements.txt`, PyCharm displays a bar at the top suggesting *"Install requirements"*. You can click it directly!

---

### 3. Command Line / Terminal Alternative (VS Code or PowerShell)

If you prefer using the standard terminal:
```bash
# 1. Clone the repository
git clone https://github.com/TSGouveia/Behavior.git
cd Behavior

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment:
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# On Mac/Linux:
source venv/bin/activate

# 4. Install required libraries
pip install -r requirements.txt
```

---

### 🔄 Synchronizing / Downloading from GitHub (`sync.py`)

To pull and update the latest changes from the repository to your local machine:
```bash
python sync.py
```
*(Automatically executes `git fetch origin` and aligns your branch via `git reset --hard origin/main`, ensuring clean synchronization without conflicts across Windows, Mac, and Linux)*.

---

## 📁 Project Structure

Data files are organized by **genotype** to enable automatic comparative analyses:

```text
Behavior/
├── data/
│   ├── csvs/                          # Coordinate CSV files divided by genotype and cohort
│   │   ├── nSybxRalRNAi/              # Genotype folder name
│   │   │   ├── N1/                    # N1 cohort subfolder
│   │   │   │   ├── *_L1_FA.csv
│   │   │   │   └── ...
│   │   │   ├── N2/                    # N2 cohort subfolder
│   │   │   │   └── ...
│   │   │   └── N3/                    # N3 cohort subfolder
│   │   │       └── ...
│   │   └── AnotherGenotype/           # Add any new genotype with its own N1, N2... subfolders
│   │       ├── N1/
│   │       └── ...
│   └── results/                       # Consolidated output tables and plots
│       ├── larva_batch_summary.csv
│       ├── larva_batch_summary.xlsx
│       └── <Genotype>_<Cohort>_larvae_trajectory_overlay.png
├── frames/
│   └── extract_parallel.py            # Parallel script to extract .h264 videos to PNG sequences via ffmpeg
├── macro/
│   └── larva_tracking.ijm             # Fiji/ImageJ macro for tracking with median background subtraction
├── python/
│   ├── larva_analysis.py              # Core module with physics, filtering, kinematics, and QC
│   └── larva_crawling_analysis.ipynb  # Interactive Jupyter notebook for visual and batch analysis
├── requirements.txt                   # List of required Python packages
├── sync.py                            # Fast synchronization utility
└── README.md                          # Project documentation
```

> [!NOTE]
> **Folder Organization (Genotype → NX)**: CSV filenames no longer need to follow rigid naming conventions! Simply place the coordinate CSVs inside `data/csvs/<Genotype>/<NX>/` (e.g. `data/csvs/nSybxRalRNAi/N1/`, `data/csvs/nSybxRalRNAi/N2/`, `data/csvs/nSybxRalRNAi/N3/`). The pipeline automatically detects genotype and cohort from the directory hierarchy, grouping all plots and summary tables accordingly.

---

## 🚀 How to Run the Pipeline

### Step 1: Frame Extraction (`frames/extract_parallel.py`)
Converts Raspberry Pi video recordings (`.h264`, 30 fps) into `.png` image sequences organized in folders:
```bash
python frames/extract_parallel.py --dir /path/to/videos
```
*(If run directly inside the videos folder without arguments, it defaults to the current directory)*.

---

### Step 2: Tracking in Fiji / ImageJ (`macro/larva_tracking.ijm`)
1. Open **Fiji / ImageJ**.
2. Drag and drop `macro/larva_tracking.ijm` into Fiji and click **Run**.
3. Select the folder containing the PNG frame sequence for the recording.
4. Follow the interactive calibration prompts:
   - Color channel with highest larva contrast (Red, Green, or Blue).
   - Circular arena boundary (ROI).
   - Pixel-to-millimeter scale (using the plate ruler).
   - Outline one larva to calibrate expected size range.
5. Save the output CSV file inside the corresponding cohort folder in `data/csvs/<GenotypeName>/<NX>/` (e.g. `data/csvs/nSybxRalRNAi/N1/`).

---

### Step 3: Analysis and Plotting in Python

#### Option A: Interactive Notebook (Recommended)
1. In **PyCharm** (or via Jupyter Lab / Notebook), open `python/larva_crawling_analysis.ipynb`.
2. If using the terminal, launch Jupyter with:
   ```bash
   jupyter notebook python/larva_crawling_analysis.ipynb
   ```
3. Run the cells in sequential order (or click **Run All**):
   - **Recursive Discovery**: Automatically parses all CSV files across all folders in `data/csvs/`.
   - **Artifact Filtering**: Interpolates brief tracking drops without fabricating artificial motion or jumps during long pauses.
   - **Plots by Genotype and Cohort (NX)**:
     - Speed over time (with shaded IQR band for each cohort: N1, N2, etc.).
     - Cumulative distance traveled over time.
     - Smoothed trajectories centered on the arena (`*_larvae_trajectory_overlay.png`).
     - Individual trajectory for each larva with normalized time colormaps.
   - **Batch Summary Table**: Automatically generates consolidated Excel (`.xlsx`) and CSV (`.csv`) reports.

#### Option B: Direct Command Line (CLI)
You can also run the analysis module directly from the terminal:
```bash
python python/larva_analysis.py --folder data/csvs --summary-out data/results/larva_batch_summary.csv --overlay-out data/results/all_larvae_trajectory_overlay.png
```

---

## 📊 Output Files (`data/results/`)

- **`larva_batch_summary.csv` / `.xlsx`**: Table with all computed metrics per larva (total distance traveled, mean and median speed, undetected duration, etc.).
- **`<Genotype>_<Cohort>_larvae_trajectory_overlay.png`**: Arena-centered trajectory overlay for each cohort (NX) within each genotype.
