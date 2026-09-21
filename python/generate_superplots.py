"""
SuperPlots generator for Larva Locomotion Analysis.
Supports comparing 2 genotypes, or N genotypes (3, 4, etc.) dynamically.

SuperPlot principles (Lord et al., 2020):
- Individual points = individual larvae (color-coded by biological replicate / cohort, e.g., N1, N2, N3)
- Large markers = median of each biological replicate
- Summary line / error bars = Mean +/- SEM (or SD) across biological replicates
- Statistical tests performed at the biological replicate level (or across larvae)
"""

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy import stats

# Add script directory to sys.path
sys.path.append(str(Path(__file__).parent))
from larva_analysis import batch_summarize, plot_superplot


def get_or_create_summary(csv_root, cache_file=None):
    """Load or compute summary statistics for all larva tracking CSVs."""
    if cache_file and Path(cache_file).exists():
        cached_df = pd.read_csv(cache_file)
        # Check if cache is up-to-date
        if "w1118" in cached_df.get("genotype", []).values:
            print(f"Loading cached summary from: {cache_file}")
            return cached_df

    csv_files = [
        p for p in sorted(Path(csv_root).rglob("*.csv"))
        if not p.name.startswith("larva_batch_summary")
    ]
    print(f"Analyzing {len(csv_files)} CSV files...")
    df = batch_summarize(csv_files)
    if cache_file:
        df.to_csv(cache_file)
        print(f"Saved cache to: {cache_file}")
    return df


def run_all_analyses():
    """Main routine to analyze dataset and produce all requested SuperPlots."""
    base_dir = Path(__file__).resolve().parent.parent
    csv_dir = base_dir / "data" / "csvs"
    results_dir = base_dir / "data" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    cache_file = results_dir / "larva_batch_summary.csv"
    df = get_or_create_summary(csv_dir, cache_file=cache_file)

    # Make sure cohort is formatted cleanly (e.g. N1, N2, N3)
    df["cohort"] = df["cohort"].astype(str).str.upper()

    print("\nDataset overview:")
    print(df.groupby(["genotype", "cohort"])[["total_distance_mm", "mean_speed_mm_s"]].agg(["count", "median"]))

    # Pairwise comparison definitions
    # Comparison 1: w1118 vs RalG0501
    comp1 = ["w1118", "RalG0501"]
    comp1_labels = ["w1118", "RalG0501"]

    # Comparison 2: nSybxw1118 vs nSybxRalRNAi
    comp2 = ["nSybxw1118", "nSybxRalRNAi"]
    comp2_labels = ["nSyb > w1118", "nSyb > RalRNAi"]

    # All 4 genotypes (demonstrating multi-genotype scalability)
    all_genotypes = ["w1118", "RalG0501", "nSybxw1118", "nSybxRalRNAi"]
    all_labels = ["w1118", "RalG0501", "nSyb > w1118", "nSyb > RalRNAi"]

    # Consistent palette for replicates across all graphs
    palette = {
        "N1": "#2563EB",  # Vibrant Blue
        "N2": "#D97706",  # Warm Amber / Orange
        "N3": "#059669"   # Emerald Green
    }

    # =========================================================================
    # 1. INDIVIDUAL SUPERPLOTS (2 BY 2 COMPARISONS)
    # =========================================================================

    # --- Comparison 1: Total Distance ---
    plot_superplot(
        df,
        genotypes=comp1,
        genotype_labels=comp1_labels,
        metric="total_distance_mm",
        ylabel="Total Distance (mm)",
        title="Total Distance: w1118 vs RalG0501",
        palette=palette,
        save_path=results_dir / "superplot_w1118_vs_ralg0501_distance.png"
    )

    # --- Comparison 1: Average Speed ---
    plot_superplot(
        df,
        genotypes=comp1,
        genotype_labels=comp1_labels,
        metric="mean_speed_mm_s",
        ylabel="Average Speed (mm/s)",
        title="Average Speed: w1118 vs RalG0501",
        palette=palette,
        save_path=results_dir / "superplot_w1118_vs_ralg0501_speed.png"
    )

    # --- Comparison 2: Total Distance ---
    plot_superplot(
        df,
        genotypes=comp2,
        genotype_labels=comp2_labels,
        metric="total_distance_mm",
        ylabel="Total Distance (mm)",
        title="Total Distance: nSyb > w1118 vs nSyb > RalRNAi",
        palette=palette,
        save_path=results_dir / "superplot_nsybxw1118_vs_nsybxralrnai_distance.png"
    )

    # --- Comparison 2: Average Speed ---
    plot_superplot(
        df,
        genotypes=comp2,
        genotype_labels=comp2_labels,
        metric="mean_speed_mm_s",
        ylabel="Average Speed (mm/s)",
        title="Average Speed: nSyb > w1118 vs nSyb > RalRNAi",
        palette=palette,
        save_path=results_dir / "superplot_nsybxw1118_vs_nsybxralrnai_speed.png"
    )

    # =========================================================================
    # 2. COMBINED 2-PANEL FIGURES (Side-by-side comparisons for paper/presentation)
    # =========================================================================

    # Total Distance combined
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 5.8), dpi=300, sharey=False)
    plot_superplot(
        df, genotypes=comp1, genotype_labels=comp1_labels,
        metric="total_distance_mm", ylabel="Total Distance (mm)",
        title="w1118 vs RalG0501", ax=ax1, palette=palette,
        show_legend=False, print_stat_report=False
    )
    plot_superplot(
        df, genotypes=comp2, genotype_labels=comp2_labels,
        metric="total_distance_mm", ylabel="Total Distance (mm)",
        title="nSyb > w1118 vs nSyb > RalRNAi", ax=ax2, palette=palette,
        show_legend=True, print_stat_report=False
    )
    fig.suptitle("SuperPlots: Total Distance (mm)", fontsize=15, fontweight="bold", y=1.02)
    plt.tight_layout()
    dist_comb_path = results_dir / "superplot_distance_comparisons.png"
    fig.savefig(dist_comb_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved combined distance plot: {dist_comb_path}")

    # Average Speed combined
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 5.8), dpi=300, sharey=False)
    plot_superplot(
        df, genotypes=comp1, genotype_labels=comp1_labels,
        metric="mean_speed_mm_s", ylabel="Average Speed (mm/s)",
        title="w1118 vs RalG0501", ax=ax1, palette=palette,
        show_legend=False, print_stat_report=False
    )
    plot_superplot(
        df, genotypes=comp2, genotype_labels=comp2_labels,
        metric="mean_speed_mm_s", ylabel="Average Speed (mm/s)",
        title="nSyb > w1118 vs nSyb > RalRNAi", ax=ax2, palette=palette,
        show_legend=True, print_stat_report=False
    )
    fig.suptitle("SuperPlots: Average Speed (mm/s)", fontsize=15, fontweight="bold", y=1.02)
    plt.tight_layout()
    speed_comb_path = results_dir / "superplot_speed_comparisons.png"
    fig.savefig(speed_comb_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved combined speed plot: {speed_comb_path}")

    # =========================================================================
    # 3. MULTI-GENOTYPE SUPERPLOTS (All 4 genotypes on single axis)
    # Scalable to any N genotypes!
    # =========================================================================
    plot_superplot(
        df,
        genotypes=all_genotypes,
        genotype_labels=all_labels,
        metric="total_distance_mm",
        ylabel="Total Distance (mm)",
        title="Total Distance across Genotypes",
        palette=palette,
        show_stat_test=False,
        save_path=results_dir / "superplot_all_genotypes_distance.png"
    )

    plot_superplot(
        df,
        genotypes=all_genotypes,
        genotype_labels=all_labels,
        metric="mean_speed_mm_s",
        ylabel="Average Speed (mm/s)",
        title="Average Speed across Genotypes",
        palette=palette,
        show_stat_test=False,
        save_path=results_dir / "superplot_all_genotypes_speed.png"
    )

    # =========================================================================
    # 4. EXPORT STATISTICAL REPORT TO EXCEL AND CSV
    # =========================================================================
    stats_rows = []
    for g in all_genotypes:
        gdf = df[df["genotype"] == g]
        for c in sorted(gdf["cohort"].unique()):
            cdf = gdf[gdf["cohort"] == c]
            stats_rows.append({
                "Genotype": g,
                "Replicate": c,
                "N_Larvae": len(cdf),
                "Distance_Median_mm": cdf["total_distance_mm"].median(),
                "Distance_Mean_mm": cdf["total_distance_mm"].mean(),
                "Distance_SEM_mm": cdf["total_distance_mm"].sem(),
                "Speed_Median_mm_s": cdf["mean_speed_mm_s"].median(),
                "Speed_Mean_mm_s": cdf["mean_speed_mm_s"].mean(),
                "Speed_SEM_mm_s": cdf["mean_speed_mm_s"].sem(),
            })
    stats_df = pd.DataFrame(stats_rows)
    stats_df.to_csv(results_dir / "superplot_replicate_summary.csv", index=False)
    try:
        stats_df.to_excel(results_dir / "superplot_replicate_summary.xlsx", index=False)
    except Exception:
        pass

    print("\nAll SuperPlots and summary tables successfully generated in:", results_dir)


if __name__ == "__main__":
    run_all_analyses()
