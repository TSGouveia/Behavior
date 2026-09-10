# Larva Behavior Tracking & Analysis Pipeline

End-to-end pipeline for frame extraction, automated behavioral tracking, and kinematic analysis of *Drosophila* larvae.

---

## 📁 Directory Structure

```text
behavior/
├── data/
│   ├── csvs/                          # Individual coordinate CSV files (output from Fiji)
│   │   ├── N2_nSybxRalRNAi_L1_FA.csv
│   │   ├── ...
│   └── results/                       # Consolidated batch tables and trajectory plots
│       ├── larva_batch_summary.csv
│       ├── larva_batch_summary.xlsx
│       └── all_larvae_trajectory_overlay.png
├── python/
│   ├── larva_analysis.py              # Python module (cleaning, kinematics, outlier rejection & batch tools)
│   └── larva_crawling_analysis.ipynb  # Interactive Jupyter notebook for single-video & batch analysis
├── videos/
│   └── extract_parallel.py            # Multi-threaded ffmpeg video extractor (.h264 to PNG sequence)
├── larva_tracking.ijm                 # Fiji/ImageJ macro for memory-safe median background subtraction tracking
└── README.md                          # Pipeline documentation and usage instructions
```

---

## 🚀 Workflow

### 1. Frame Extraction (`videos/extract_parallel.py`)
Converts raw `.h264` recordings (30 fps) into per-frame `.png` image folders using parallel `ffmpeg` workers:
```bash
python behavior/videos/extract_parallel.py --dir /path/to/videos
```
*(Or simply run inside the folder containing your `.h264` files without arguments)*.

### 2. Tracking with Fiji / ImageJ (`larva_tracking.ijm`)
1. Open **Fiji / ImageJ**.
2. Open `behavior/larva_tracking.ijm` and click **Run**.
3. Select the PNG frame sequence folder for a recording (e.g., `*_frames`).
4. Follow the interactive calibration prompts:
   - Select color channel with highest larva contrast (Red, Green, or Blue).
   - Define circular arena boundary (ROI).
   - Set pixel-to-millimeter scale using the dish ruler.
   - Outline a larva to initialize expected size range.
5. Save the generated coordinate CSV (columns: `Frame`, `Time_s`, `X_px`, `Y_px`, `X_mm`, `Y_mm`, etc.) into `behavior/data/csvs/`.

### 3. Quantitative Analysis (`python/`)

#### Option A: Jupyter Notebook (Interactive)
Open `behavior/python/larva_crawling_analysis.ipynb`:
- Automatically scans `behavior/data/csvs/` for coordinate files.
- Cleans tracking artifacts: interpolates short tracking gaps without false teleportation over long breaks.
- Computes distances, velocities, epoch speeds, and quality control (QC) outlier detection metrics.
- Automatically exports consolidated summaries and figures to `behavior/data/results/`.

#### Option B: Command-Line Interface (CLI)
Run `larva_analysis.py` directly:
```bash
python behavior/python/larva_analysis.py --folder behavior/data/csvs --summary-out behavior/data/results/larva_batch_summary.csv --overlay-out behavior/data/results/all_larvae_trajectory_overlay.png
```

---

## 📊 Outputs & Results (`data/results/`)
- **`larva_batch_summary.csv` / `.xlsx`**: Aggregated table containing all per-larva kinematics (total distance, mean/median speed, percent untracked time, flagged QC outliers).
- **`all_larvae_trajectory_overlay.png`**: Arena-centered multi-larva trajectory overlay plot with color-coded paths.
