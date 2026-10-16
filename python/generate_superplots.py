"""
SuperPlots generator for Larva Locomotion Analysis.
Supports dynamic comparisons, control selection, and automated statistical testing.

SuperPlot principles (Lord et al., 2020):
- Individual points = individual larvae (color-coded by biological replicate / cohort, e.g., N1, N2, N3)
- Large markers = median of each biological replicate
- Summary line / error bars = Mean +/- SEM across biological replicates
- Statistical tests performed with normality test (Shapiro-Wilk) and variance test (Levene),
  applying Student's t-test, Welch's t-test, or Mann-Whitney U with significance brackets!
"""

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Add script directory to sys.path
sys.path.append(str(Path(__file__).parent))
from larva_analysis import batch_summarize, plot_superplot


# =============================================================================
# USER CONFIGURATION: DEFINE CONTROL AND GENOTYPES HERE
# =============================================================================
# Set the control genotype name (e.g. 'nSybxw1118_29C' or 'w1118').
# Every other genotype will be compared against this control with significance bars!
CONTROL_GENOTYPE = "nSybxw1118_29C"


def get_or_create_summary(csv_root, cache_file=None):
    """Load or compute summary statistics for all larva tracking CSVs."""
    if cache_file and Path(cache_file).exists():
        cached_df = pd.read_csv(cache_file)
        if "genotype" in cached_df.columns and len(cached_df) > 0:
            print(f"Loading cached summary from: {cache_file}")
            return cached_df

    csv_files = [
        p for p in sorted(Path(csv_root).rglob("*.csv"))
        if not p.name.startswith("larva_batch_summary")
    ]
    print(f"Analyzing {len(csv_files)} CSV files...")
    df = batch_summarize(csv_files)
    if cache_file:
        df.to_csv(cache_file, index=False)
        print(f"Saved cache to: {cache_file}")
    return df


def run_all_analyses(control_genotype=CONTROL_GENOTYPE):
    """
    Main routine to analyze dataset and produce all requested SuperPlots
    with statistical comparison brackets against the designated control.
    """
    base_dir = Path(__file__).resolve().parent.parent
    csv_dir = base_dir / "data" / "csvs"
    results_dir = base_dir / "data" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    cache_file = results_dir / "larva_batch_summary.csv"
    df = get_or_create_summary(csv_dir, cache_file=cache_file)

    # Clean cohort naming
    df["cohort"] = df["cohort"].astype(str).str.upper()

    # Discover available genotypes
    available_genotypes = sorted(df["genotype"].dropna().unique().tolist())
    print("\n" + "=" * 60)
    print("Discovered Genotypes in dataset:", available_genotypes)
    print(f"Selected Control Genotype: '{control_genotype}'")
    print("=" * 60)

    # Check if control exists or match case-insensitively
    actual_control = None
    for g in available_genotypes:
        if g.lower() == control_genotype.lower():
            actual_control = g
            break
        if "w1118" in g.lower() and "w1118" in control_genotype.lower():
            actual_control = g
            break

    if actual_control is None and available_genotypes:
        actual_control = available_genotypes[0]
        print(f"[Warning] Control '{control_genotype}' not found exactly. Using '{actual_control}' as fallback.")
    else:
        print(f"Using control genotype: {actual_control}")

    # Reorder genotypes so that Control is placed FIRST on the left
    other_genotypes = [g for g in available_genotypes if g != actual_control]
    ordered_genotypes = [actual_control] + other_genotypes

    # Consistent replicate palette
    palette = {
        "N1": "#2563EB",  # Blue
        "N2": "#D97706",  # Amber / Orange
        "N3": "#059669"   # Emerald Green
    }

    # =========================================================================
    # 1. GLOBAL SUPERPLOTS (ALL GENOTYPES WITH STATISTICAL BRACKETS VS CONTROL)
    # =========================================================================
    print("\n--- Generating Global SuperPlot: Total Distance ---")
    plot_superplot(
        df,
        genotypes=ordered_genotypes,
        control_genotype=actual_control,
        metric="total_distance_mm",
        ylabel="Total Distance (mm)",
        title=f"Total Distance (Control: {actual_control})",
        palette=palette,
        show_stat_test=True,
        print_stat_report=True,
        save_path=results_dir / "superplot_all_genotypes_distance.png"
    )

    print("\n--- Generating Global SuperPlot: Average Speed ---")
    plot_superplot(
        df,
        genotypes=ordered_genotypes,
        control_genotype=actual_control,
        metric="mean_speed_mm_s",
        ylabel="Average Speed (mm/s)",
        title=f"Average Speed (Control: {actual_control})",
        palette=palette,
        show_stat_test=True,
        print_stat_report=True,
        save_path=results_dir / "superplot_all_genotypes_speed.png"
    )

    # =========================================================================
    # 2. INDIVIDUAL PAIRWISE SUPERPLOTS (CONTROL VS EACH GENOTYPE ONE-BY-ONE)
    # =========================================================================
    print("\n--- Generating Pairwise 1-on-1 SuperPlots against Control ---")
    for g in other_genotypes:
        pair = [actual_control, g]
        clean_name = f"{actual_control}_vs_{g}".replace(" ", "_")

        # Total distance
        plot_superplot(
            df,
            genotypes=pair,
            control_genotype=actual_control,
            metric="total_distance_mm",
            ylabel="Total Distance (mm)",
            title=f"Total Distance: {actual_control} vs {g}",
            palette=palette,
            show_stat_test=True,
            print_stat_report=False,
            save_path=results_dir / f"superplot_{clean_name}_distance.png"
        )

        # Average speed
        plot_superplot(
            df,
            genotypes=pair,
            control_genotype=actual_control,
            metric="mean_speed_mm_s",
            ylabel="Average Speed (mm/s)",
            title=f"Average Speed: {actual_control} vs {g}",
            palette=palette,
            show_stat_test=True,
            print_stat_report=False,
            save_path=results_dir / f"superplot_{clean_name}_speed.png"
        )

    # =========================================================================
    # 3. EXPORT STATISTICAL SUMMARY TABLE
    # =========================================================================
    stats_rows = []
    for g in ordered_genotypes:
        gdf = df[df["genotype"] == g]
        for c in sorted(gdf["cohort"].unique()):
            cdf = gdf[gdf["cohort"] == c]
            stats_rows.append({
                "Genotype": g,
                "Is_Control": (g == actual_control),
                "Replicate": c,
                "N_Larvae": len(cdf),
                "Distance_Median_mm": round(float(cdf["total_distance_mm"].median()), 3),
                "Distance_Mean_mm": round(float(cdf["total_distance_mm"].mean()), 3),
                "Distance_SEM_mm": round(float(cdf["total_distance_mm"].sem()), 3),
                "Speed_Median_mm_s": round(float(cdf["mean_speed_mm_s"].median()), 3),
                "Speed_Mean_mm_s": round(float(cdf["mean_speed_mm_s"].mean()), 3),
                "Speed_SEM_mm_s": round(float(cdf["mean_speed_mm_s"].sem()), 3),
            })
    stats_df = pd.DataFrame(stats_rows)
    stats_df.to_csv(results_dir / "superplot_replicate_summary.csv", index=False)
    try:
        stats_df.to_excel(results_dir / "superplot_replicate_summary.xlsx", index=False)
    except Exception:
        pass

    print(f"\nAll plots and summary tables saved to: {results_dir}\n")


if __name__ == "__main__":
    run_all_analyses()
