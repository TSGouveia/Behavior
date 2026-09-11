"""
Quantify larva tracking CSVs produced by the Fiji macro.

Handles the real issue in this data: long undetected stretches (loss of contrast,
or larva mid-headsweep/rearing) should NOT be bridged with a straight line, since
that pretends the larva teleported instead of continuing to move,
undetected. Short gaps (a frame or two of noise) are safe to interpolate.

Usage in a Jupyter notebook:

    from larva_analysis import (
        load_and_clean,
        compute_kinematics,
        summarize,
        plot_trajectory,
        plot_multi_larva_overlay,
        parse_filename_metadata,
        batch_summarize,
    )

    df = load_and_clean("larva_coordinates.csv", fps=30, max_gap_frames=5)
    df = compute_kinematics(df)
    stats = summarize(df)
    print(stats)
    plot_trajectory(df)
"""

import re
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection


def parse_filename_metadata(file_path):
    """
    Parse metadata from a video or CSV filename.
    Matches conventions like:
        {Genotype}_{Stage}_{Condition}-{Replicate}
    e.g. RalG0501_L2_FA-0001.csv ->
        Genotype: RalG0501, Stage: L2, Condition: FA, Replicate: 0001
    Also handles {Genotype}_{Replicate} (e.g. Hid_1) or other underscore/dash separated formats.
    """
    path_obj = Path(file_path)
    stem = path_obj.stem
    meta = {
        "stem": stem,
        "cohort": "",
        "genotype": stem,
        "stage": "",
        "condition": "",
        "replicate": "",
    }

    # Inspect parent directories up the tree to detect genotype and cohort subfolders:
    # e.g. data/csvs/<genotype>/<cohort>/<file>.csv or data/csvs/<genotype>/<file>.csv
    folder_cohort = None
    folder_genotype = None

    for p_name in [p.name for p in path_obj.parents if p.name and p.name.lower() not in ["csvs", "data", ".", ""]]:
        if re.match(r"^N\d+$", p_name, re.IGNORECASE) and not folder_cohort:
            folder_cohort = p_name.upper()
        elif not folder_genotype:
            folder_genotype = p_name

    # Check filename cohort prefix if present (e.g. N1_, N2_, N3_)
    m_cohort = re.match(r"^(N\d+)_(.*)$", stem, re.IGNORECASE)
    if m_cohort:
        file_cohort = m_cohort.group(1).upper()
        base_stem = m_cohort.group(2)
    else:
        file_cohort = ""
        base_stem = stem

    meta["cohort"] = folder_cohort or file_cohort or "All"

    # Pattern: Genotype_Stage_Condition-Replicate or Genotype_Stage_Condition_Replicate
    m = re.match(r"^([^_]+)_([^_]+)_([^-_\s]+)[-_](\d+.*)$", base_stem)
    if m:
        meta["genotype"] = folder_genotype or m.group(1)
        meta["stage"] = m.group(2)
        meta["condition"] = m.group(3)
        meta["replicate"] = m.group(4)
        return meta

    # Pattern: Genotype_Replicate (e.g., Hid_1, Empty_2)
    m2 = re.match(r"^([^_]+)_(\d+.*)$", base_stem)
    if m2:
        meta["genotype"] = folder_genotype or m2.group(1)
        meta["replicate"] = m2.group(2)
        return meta

    # Fallback: split on underscores and dashes
    parts = re.split(r"[_\-]+", base_stem)
    if len(parts) >= 1:
        meta["genotype"] = parts[0]
    if len(parts) >= 2:
        meta["stage"] = parts[1]
    if len(parts) >= 3:
        meta["condition"] = parts[2]
    if len(parts) >= 4:
        meta["replicate"] = parts[3]

    if folder_genotype:
        meta["genotype"] = folder_genotype

    return meta


def _classify_and_interpolate(x, y, invalid_mask, max_gap_frames, max_bridge_dist_mm=1.0):
    """Shared logic: split `invalid_mask` runs into short (interpolate)
    vs long (leave as a real break), applied to the given x/y series.
    If max_bridge_dist_mm is provided, long gaps whose spatial endpoint distance is
    very small (<= max_bridge_dist_mm) are bridged (joined) via interpolation."""
    gap_id = (invalid_mask != invalid_mask.shift()).cumsum()
    gap_sizes = invalid_mask.groupby(gap_id).transform("sum")
    short_gap = invalid_mask & (gap_sizes <= max_gap_frames)
    long_gap = invalid_mask & (gap_sizes > max_gap_frames)

    x_out = x.copy()
    y_out = y.copy()
    x_out[invalid_mask] = np.nan
    y_out[invalid_mask] = np.nan
    x_out = x_out.interpolate(limit_area="inside")
    y_out = y_out.interpolate(limit_area="inside")
    x_out[long_gap] = np.nan
    y_out[long_gap] = np.nan

    # Bridge discontinuities that are very small in spatial distance
    if max_bridge_dist_mm is not None and max_bridge_dist_mm > 0 and long_gap.any():
        for gid, is_lg in long_gap.groupby(gap_id).first().items():
            if is_lg:
                sub_idx = long_gap[gap_id == gid].index
                s_i = sub_idx[0] - 1
                e_i = sub_idx[-1] + 1
                if s_i >= 0 and e_i < len(x):
                    # Check spatial distance between valid endpoints
                    p_s = (x.loc[s_i], y.loc[s_i])
                    p_e = (x.loc[e_i], y.loc[e_i])
                    if pd.notna(p_s[0]) and pd.notna(p_e[0]):
                        dist = np.sqrt((p_e[0] - p_s[0])**2 + (p_e[1] - p_s[1])**2)
                        if dist <= max_bridge_dist_mm:
                            x_span = np.linspace(p_s[0], p_e[0], len(sub_idx) + 2)[1:-1]
                            y_span = np.linspace(p_s[1], p_e[1], len(sub_idx) + 2)[1:-1]
                            x_out.loc[sub_idx] = x_span
                            y_out.loc[sub_idx] = y_span
                            short_gap.loc[sub_idx] = True
                            long_gap.loc[sub_idx] = False

    return x_out, y_out, short_gap, long_gap


def _local_deviation(x, y, local_window):
    """How far each point sits from the median position of its own
    surrounding window - the exact quantity used for outlier rejection."""
    med_x = x.rolling(local_window, center=True, min_periods=3).median()
    med_y = y.rolling(local_window, center=True, min_periods=3).median()
    return np.sqrt((x - med_x)**2 + (y - med_y)**2)


def _detect_teleport_excursions(x_series, y_series, frames, fps=30.0,
                                max_speed_mm_s=8.0, max_jump_dist_mm=10.0,
                                max_return_frames=600):
    """
    Trajectory continuity filter:
    Identifies points where tracking made an impossible jump (> max_jump_dist_mm or
    > max_speed_mm_s) away from the true larva track to a false target (e.g. debris,
    condensation, or reflection near the dish wall) and subsequently returned back to
    near the original position. All points during such false excursions are flagged.
    """
    valid_idx = x_series.dropna().index.tolist()
    is_teleport = pd.Series(False, index=x_series.index)
    if not valid_idx:
        return is_teleport

    i = 0
    while i < len(valid_idx) - 1:
        curr = valid_idx[i]
        nxt = valid_idx[i + 1]

        dt = (frames.loc[nxt] - frames.loc[curr]) / fps
        dist = np.sqrt((x_series.loc[nxt] - x_series.loc[curr])**2 + (y_series.loc[nxt] - y_series.loc[curr])**2)
        speed = dist / dt if dt > 0 else 0

        if dist > max_jump_dist_mm or speed > max_speed_mm_s:
            # A jump occurred between curr and nxt. Search ahead for a return to curr:
            return_idx = None
            for j in range(i + 1, min(i + max_return_frames, len(valid_idx))):
                test_idx = valid_idx[j]
                dist_back = np.sqrt((x_series.loc[test_idx] - x_series.loc[curr])**2 + (y_series.loc[test_idx] - y_series.loc[curr])**2)
                if dist_back <= max_jump_dist_mm:
                    return_idx = j
                    break

            if return_idx is not None and return_idx > i + 1:
                excursion_indices = [valid_idx[k] for k in range(i + 1, return_idx)]
                is_teleport.loc[excursion_indices] = True
                i = return_idx
                continue
        i += 1

    return is_teleport


def estimate_noise_scale(x, y, max_gap_frames=5, local_window=11):
    """
    Estimate this video's own typical local positional deviation,
    robust to the rare large excursions we actually want to catch.
    Measures the SAME quantity that outlier rejection thresholds
    (deviation from a local window's median position), not a proxy for
    it - using a different quantity to calibrate the threshold was the
    bug in an earlier version of this function (it used raw step-to-
    step distance, which sits on a different scale and made the
    threshold far too strict, flagging genuine slow movement as noise).
    """
    not_detected = x.isna()
    x_i, y_i, _, _ = _classify_and_interpolate(x, y, not_detected, max_gap_frames)
    dev = _local_deviation(x_i, y_i, local_window).dropna()
    if len(dev) == 0:
        return 0.3  # fallback for a degenerate/empty series
    median_dev = dev.median()
    mad = (dev - median_dev).abs().median()
    return median_dev + 1.4826 * mad


def load_and_clean(csv_path, fps=30, max_gap_frames=5, max_local_deviation_mm=None,
                    deviation_multiplier=8.0, min_deviation_floor_mm=0.3, local_window=11,
                    arena_center_mm=None, arena_radius_mm=None, arena_margin_fraction=None,
                    max_teleport_speed_mm_s=8.0, max_teleport_jump_mm=10.0,
                    max_bridge_dist_mm=1.0):
    """
    Load a tracking CSV and prepare it for analysis.
    (docstring mantida, arena_margin_fraction revertido para None por defeito)
    max_bridge_dist_mm: if > 0, long gaps with very small spatial distance (<= max_bridge_dist_mm)
    are bridged (joined) via interpolation rather than left as broken trajectories.
    """
    df = pd.read_csv(csv_path)
    df = df.sort_values("Frame").reset_index(drop=True)

    x_raw = df["X_mm"].copy()
    y_raw = df["Y_mm"].copy()
    not_detected = x_raw.isna()

    # --- Teleportation / Excursion Outlier Rejection ---
    # Catches false detections (debris, reflections, dish wall) where tracking
    # jumps far away from the larva and returns.
    is_teleport = _detect_teleport_excursions(
        x_raw, y_raw, df["Frame"], fps=fps,
        max_speed_mm_s=max_teleport_speed_mm_s,
        max_jump_dist_mm=max_teleport_jump_mm
    )

    noise_scale_mm = estimate_noise_scale(x_raw.where(~is_teleport), y_raw.where(~is_teleport), max_gap_frames, local_window)
    if max_local_deviation_mm is None:
        max_local_deviation_mm = max(min_deviation_floor_mm, deviation_multiplier * noise_scale_mm)

    x_pass1, y_pass1, _, _ = _classify_and_interpolate(x_raw, y_raw, not_detected | is_teleport, max_gap_frames, max_bridge_dist_mm=None)

    local_dev = _local_deviation(x_pass1, y_pass1, local_window)
    is_outlier = (local_dev > max_local_deviation_mm).fillna(False)

    invalid = not_detected | is_outlier | is_teleport
    x_clean, y_clean, short_gap, long_gap = _classify_and_interpolate(x_raw, y_raw, invalid, max_gap_frames, max_bridge_dist_mm=max_bridge_dist_mm)

    df["X_mm_clean"] = x_clean
    df["Y_mm_clean"] = y_clean
    df["is_long_gap"] = long_gap
    df["is_short_gap_filled"] = short_gap
    df["is_outlier_rejected"] = (is_outlier | is_teleport) & ~not_detected
    df["is_teleport_excursion"] = is_teleport
    df["fps"] = fps
    df["noise_scale_mm"] = noise_scale_mm
    df["deviation_threshold_used_mm"] = max_local_deviation_mm

    if arena_center_mm is None:
        if "Arena_center_X_mm" in df.columns and "Arena_center_Y_mm" in df.columns:
            ac_x = df["Arena_center_X_mm"].dropna()
            ac_y = df["Arena_center_Y_mm"].dropna()
            if len(ac_x) > 0 and len(ac_y) > 0:
                arena_center_mm = (float(ac_x.iloc[0]), float(ac_y.iloc[0]))
    if arena_radius_mm is None:
        if "Arena_radius_mm" in df.columns:
            ar = df["Arena_radius_mm"].dropna()
            if len(ar) > 0:
                arena_radius_mm = float(ar.iloc[0])

    # Revertido: Apenas aplica a margem se for explicitamente pedida
    is_outside_arena = pd.Series(False, index=df.index)
    if arena_center_mm is not None and arena_radius_mm is not None and arena_margin_fraction is not None:
        cx, cy = arena_center_mm
        max_r = arena_radius_mm * arena_margin_fraction
        r = np.sqrt((df["X_mm_clean"] - cx) ** 2 + (df["Y_mm_clean"] - cy) ** 2)
        is_outside_arena = r > max_r
        df.loc[is_outside_arena, "X_mm_clean"] = np.nan
        df.loc[is_outside_arena, "Y_mm_clean"] = np.nan
    df["is_outside_arena"] = is_outside_arena

    df.attrs["arena_center_mm"] = arena_center_mm
    df.attrs["arena_radius_mm"] = arena_radius_mm
    df.attrs["file_path"] = str(csv_path)
    df.attrs["metadata"] = parse_filename_metadata(csv_path)

    if arena_center_mm is not None:
        cx, cy = arena_center_mm
        df["X_centered_mm"] = df["X_mm_clean"] - cx
        df["Y_centered_mm"] = cy - df["Y_mm_clean"]
    else:
        df["X_centered_mm"] = np.nan
        df["Y_centered_mm"] = np.nan

    return df


def compute_kinematics(df, max_speed_mm_s=10.0):
    """
    Add per-frame displacement and instantaneous speed.
    Calculates velocity relative to the *last valid position* to easily catch jumps after gaps.
    """
    fps = df["fps"].iloc[0]

    # 1. Distância e tempo escalar face ao ÚLTIMO ponto válido
    last_valid_x = df["X_mm_clean"].ffill().shift(1)
    last_valid_y = df["Y_mm_clean"].ffill().shift(1)
    last_valid_frame = df["Frame"].where(df["X_mm_clean"].notna()).ffill().shift(1)

    dx_gap = df["X_mm_clean"] - last_valid_x
    dy_gap = df["Y_mm_clean"] - last_valid_y
    dt_gap = (df["Frame"] - last_valid_frame) / fps

    # Velocidade desde a última deteção real
    speed_from_last = np.sqrt(dx_gap ** 2 + dy_gap ** 2) / dt_gap

    # --- velocity-based outlier rejection ---
    if max_speed_mm_s is not None:
        too_fast = speed_from_last > max_speed_mm_s
        too_fast_next = too_fast.shift(-1, fill_value=False)
        is_speed_outlier = too_fast | too_fast_next
    else:
        is_speed_outlier = pd.Series(False, index=df.index)

    df["is_speed_outlier"] = is_speed_outlier

    # Apagar as coordenadas dos pontos com velocidade irreal
    if is_speed_outlier.any():
        df.loc[is_speed_outlier, "X_mm_clean"] = np.nan
        df.loc[is_speed_outlier, "Y_mm_clean"] = np.nan
        for col in ("X_centered_mm", "Y_centered_mm"):
            if col in df.columns:
                df.loc[is_speed_outlier, col] = np.nan

    # 2. Computar os valores finais estritos de frame-a-frame (após a limpeza dos saltos)
    dt_step = 1.0 / fps
    dx = df["X_mm_clean"].diff()
    dy = df["Y_mm_clean"].diff()
    dist = np.sqrt(dx ** 2 + dy ** 2)
    speed = dist / dt_step

    df["step_dist_mm"] = dist
    df["speed_mm_s"] = speed
    df["cumulative_distance_mm"] = dist.fillna(0).cumsum()

    return df

def summarize(df):
    """Return a dict of headline numbers for one video."""
    fps = df["fps"].iloc[0]
    total_frames = len(df)
    n_long_gap = df["is_long_gap"].sum()
    n_short_gap_filled = df["is_short_gap_filled"].sum()
    n_outliers = df["is_outlier_rejected"].sum()
    n_speed_outliers = df["is_speed_outlier"].sum() if "is_speed_outlier" in df.columns else 0

    total_distance_mm = df["step_dist_mm"].sum(skipna=True)
    valid_speeds = df["speed_mm_s"].dropna()

    # Longest single untracked stretch, in seconds - useful to flag
    # whether results are trustworthy for this particular video
    is_missing = df["X_mm"].isna()
    gap_id = (is_missing != is_missing.shift()).cumsum()
    gap_lengths = is_missing.groupby(gap_id).sum()
    longest_gap_frames = gap_lengths.max() if len(gap_lengths) else 0

    return {
        "total_frames": total_frames,
        "pct_time_untracked": 100 * n_long_gap / total_frames,
        "longest_untracked_stretch_s": longest_gap_frames / fps,
        "n_short_gaps_interpolated": n_short_gap_filled,
        "n_outliers_rejected": n_outliers,
        "n_speed_outliers": n_speed_outliers,
        "total_distance_mm": total_distance_mm,
        "mean_speed_mm_s": valid_speeds.mean(),
        "median_speed_mm_s": valid_speeds.median(),
        "max_speed_mm_s": valid_speeds.max(),
    }


def summarize_by_epoch(df, epoch_s=10):
    """
    Max speed per N-second epoch, rather than one global max.
    (This mirrors a common approach in the larva/fly-tracking literature:
    a single global max is very sensitive to one noisy frame, whereas
    per-epoch maxima give a steadier picture of locomotor activity over
    time and let you see whether/when the larva was moving vs resting.)
    """
    fps = df["fps"].iloc[0]
    frames_per_epoch = int(epoch_s * fps)
    df = df.copy()
    df["epoch"] = df["Frame"] // frames_per_epoch
    return df.groupby("epoch")["speed_mm_s"].agg(["max", "mean", "median"]).reset_index()


def plot_trajectory(df, title=None, dish_center_mm=None, dish_radius_mm=None, clim=None,
                    show_larva_max_indicator=True, save_path=None):
    """
    Plot the trajectory, colored by time. Long-gap stretches are simply
    not drawn (rather than connected), so you can visually see where and
    for how long tracking was lost.
    clim: optional tuple (vmin, vmax) for the time colorbar scale, ensuring consistent
    colors across different videos (e.g. clim=(0, 180)).
    show_larva_max_indicator: if True, draws a red line on the colorbar indicating the
    maximum tracked time reached by this specific larva.
    """
    fig, ax = plt.subplots(figsize=(6, 6))

    x = df["X_mm_clean"].values
    y = df["Y_mm_clean"].values
    t = df["Frame"].values / df["fps"].iloc[0]

    # Build line segments only between consecutive valid points
    points = np.array([x, y]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    valid_seg = ~(np.isnan(x[:-1]) | np.isnan(x[1:]))

    lc = LineCollection(segments[valid_seg], cmap="viridis")
    lc.set_array(t[:-1][valid_seg])
    if clim is not None:
        vmin, vmax = float(round(clim[0])), float(round(clim[1]))
        lc.set_clim(vmin, vmax)
    ax.add_collection(lc)
    cbar = fig.colorbar(lc, ax=ax)
    cbar.set_label("Time (s)")

    # Ensure ticks clearly display the full range, rounded to the nearest integer units
    if clim is not None:
        vmin_int, vmax_int = int(round(clim[0])), int(round(clim[1]))
        tick_step = 30 if vmax_int >= 120 else (20 if vmax_int >= 60 else 10)
        ticks = list(range(vmin_int, vmax_int, tick_step))
        if vmax_int not in ticks:
            ticks.append(vmax_int)
        cbar.set_ticks(ticks)
        cbar.set_ticklabels([str(val) for val in ticks])

    # Red indicator line on colorbar for this specific larva's maximum tracked time
    if show_larva_max_indicator and valid_seg.any():
        larva_t_max = float(np.nanmax(t[np.concatenate([[valid_seg[0]], valid_seg])]))
        cbar.ax.axhline(larva_t_max, color="red", linewidth=2.5, linestyle="-", zorder=5)
        cbar.ax.plot(1.0, larva_t_max, marker="<", color="red", markersize=7, clip_on=False, zorder=6)

    if dish_center_mm is None:
        dish_center_mm = df.attrs.get("arena_center_mm")
    if dish_radius_mm is None:
        dish_radius_mm = df.attrs.get("arena_radius_mm")

    if dish_center_mm is not None and dish_radius_mm is not None:
        dish = plt.Circle(dish_center_mm, dish_radius_mm, fill=False,
                           linestyle="--", color="gray", label="dish edge")
        ax.add_patch(dish)
        ax.set_xlim(dish_center_mm[0] - dish_radius_mm - 2, dish_center_mm[0] + dish_radius_mm + 2)
        ax.set_ylim(dish_center_mm[1] - dish_radius_mm - 2, dish_center_mm[1] + dish_radius_mm + 2)
    else:
        ax.set_xlim(np.nanmin(x) - 2, np.nanmax(x) + 2)
        ax.set_ylim(np.nanmin(y) - 2, np.nanmax(y) + 2)

    ax.set_aspect("equal")
    ax.set_xlabel("X (mm)", fontsize=12)
    ax.set_ylabel("Y (mm)", fontsize=12)
    ax.set_title(title or df.attrs.get("metadata", {}).get("stem", "Larva trajectory"), fontsize=14, weight="bold")
    ax.invert_yaxis()  # image coordinates: Y increases downward

    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")
    return fig, ax


def plot_multi_larva_overlay(df_list, labels=None, title="Larva Trajectories Clean",
                             palette_name="viridis", arena_radius_mm=None,
                             trajectory_alpha=0.8, start_alpha=0.9, end_alpha=0.6,
                             start_marker_size=10, end_marker_size=8,
                             arena_color="black", arena_linewidth=2.5,
                             flagged=None,
                             save_path=None):
    """
    Reproduce the arena-centered multi-larva overlay plot from Empty_Trajectories / Hid_all_larvae_inferno.png.

    Each larva's trajectory is re-centered around its arena center (0, 0), with Y flipped so
    up is positive (+Y), and drawn within the common circular petri dish boundary.

    df_list: list of cleaned kinematics DataFrames (output of load_and_clean).
    labels: list of larva names (e.g. ['Hid_1', 'Hid_2', ...] or extracted from metadata).
    palette_name: 'viridis', 'inferno', or any Matplotlib colormap name.
    """
    n_larvae = len(df_list)
    if n_larvae == 0:
        print("No DataFrames provided to plot_multi_larva_overlay.")
        return None, None

    # Colors from colormap
    cmap = plt.get_cmap(palette_name)
    colors = [cmap(val) for val in np.linspace(0.15, 0.9, n_larvae)] if n_larvae > 1 else [cmap(0.5)]

    fig, ax = plt.subplots(figsize=(8, 8))
    any_plotted = False
    effective_radius = arena_radius_mm

    for i, df in enumerate(df_list):
        label = labels[i] if labels and i < len(labels) else df.attrs.get("metadata", {}).get("stem", f"Larva_{i+1}")
        color = colors[i]
        is_flagged = bool(flagged[i]) if flagged is not None and i < len(flagged) else False

        # Extract centered coordinates
        xc = df.get("X_centered_mm")
        yc = df.get("Y_centered_mm")

        # If not centered yet, try using arena metadata
        if xc is None or xc.isna().all():
            ac = df.attrs.get("arena_center_mm")
            if ac is not None:
                xc = df["X_mm_clean"] - ac[0]
                yc = ac[1] - df["Y_mm_clean"]
            else:
                # Fallback to centering on initial valid position
                valid_idx = df["X_mm_clean"].first_valid_index()
                if valid_idx is not None:
                    xc = df["X_mm_clean"] - df["X_mm_clean"].loc[valid_idx]
                    yc = -(df["Y_mm_clean"] - df["Y_mm_clean"].loc[valid_idx])
                else:
                    continue

        if effective_radius is None:
            effective_radius = df.attrs.get("arena_radius_mm")

        # Build segments skipping NaN gaps
        x_vals = xc.values
        y_vals = yc.values
        points = np.array([x_vals, y_vals]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        valid_seg = ~(np.isnan(x_vals[:-1]) | np.isnan(x_vals[1:]))

        # Flagged larvae use dashed lines and reduced opacity so they are
        # still visible but clearly distinguished from clean trajectories.
        lc_linestyle = "--" if is_flagged else "-"
        lc_linewidth = 1.2 if is_flagged else 2
        lc_alpha = trajectory_alpha * 0.55 if is_flagged else trajectory_alpha
        lc_label = f"{label} ⚑" if is_flagged else label

        lc = LineCollection(
            segments[valid_seg],
            colors=[color],
            linewidths=lc_linewidth,
            linestyle=lc_linestyle,
            alpha=lc_alpha,
            label=lc_label,
        )
        ax.add_collection(lc)

        # Plot Start (first valid point) and End (last valid point)
        valid_mask = ~np.isnan(x_vals)
        if valid_mask.any():
            first_idx = np.where(valid_mask)[0][0]
            last_idx = np.where(valid_mask)[0][-1]
            ax.plot(x_vals[first_idx], y_vals[first_idx], 'o', color=color, alpha=start_alpha,
                    markersize=start_marker_size)
            ax.plot(x_vals[last_idx], y_vals[last_idx], 'o', color=color, alpha=end_alpha,
                    markersize=end_marker_size)
            any_plotted = True

    # Draw circular arena boundary at (0, 0)
    if effective_radius is not None:
        circle = plt.Circle(
            (0, 0),
            effective_radius,
            color=arena_color,
            fill=False,
            alpha=0.7,
            linestyle="-",
            linewidth=arena_linewidth,
            label="Arena"
        )
        ax.add_patch(circle)
        ax.set_xlim(-effective_radius - 5, effective_radius + 5)
        ax.set_ylim(-effective_radius - 5, effective_radius + 5)
    else:
        ax.autoscale()

    ax.set_title(title, fontsize=16, weight="bold")
    ax.set_xlabel("X position (mm)", fontsize=12)
    ax.set_ylabel("Y position (mm)", fontsize=12)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    
    # If there are multiple larvae, place the legend neatly on the side so it doesn't cover trajectories
    if n_larvae > 10:
        ax.legend(bbox_to_anchor=(1.04, 1), loc="upper left", frameon=True, fontsize=9, ncol=2)
    elif n_larvae > 4:
        ax.legend(bbox_to_anchor=(1.04, 1), loc="upper left", frameon=True, fontsize=10)
    else:
        ax.legend(loc="upper right", frameon=True, fontsize=10)
        
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")
    return fig, ax


def list_flagged_events(df):
    """
    Group consecutive outlier-rejected frames into distinct events, with
    their size and duration, for a quick human sanity check.
    """
    flagged = df["is_outlier_rejected"]
    if not flagged.any():
        return pd.DataFrame(columns=["start_frame", "end_frame", "n_frames"])
    event_id = (flagged != flagged.shift()).cumsum()
    events = df[flagged].groupby(event_id[flagged]).agg(
        start_frame=("Frame", "min"),
        end_frame=("Frame", "max"),
    )
    events["n_frames"] = events["end_frame"] - events["start_frame"] + 1
    return events.reset_index(drop=True)


def batch_summarize(csv_paths, fps=30, max_gap_frames=5, deviation_multiplier=8.0,
                     min_deviation_floor_mm=0.3, max_speed_mm_s=10.0,
                     arena_margin_fraction=None, max_bridge_dist_mm=1.0):
    """
    Run the full pipeline over many videos and return one summary table,
    with parsed filename metadata and automatic QC flags.
    """
    rows = []
    for path in csv_paths:
        meta = parse_filename_metadata(path)
        df = load_and_clean(path, fps=fps, max_gap_frames=max_gap_frames,
                             deviation_multiplier=deviation_multiplier,
                             min_deviation_floor_mm=min_deviation_floor_mm,
                             arena_margin_fraction=arena_margin_fraction,
                             max_bridge_dist_mm=max_bridge_dist_mm)
        df = compute_kinematics(df, max_speed_mm_s=max_speed_mm_s)
        stats = summarize(df)
        stats["cohort"] = meta["cohort"]
        stats["genotype"] = meta["genotype"]
        stats["stage"] = meta["stage"]
        stats["condition"] = meta["condition"]
        stats["replicate"] = meta["replicate"]
        stats["noise_scale_mm"] = df["noise_scale_mm"].iloc[0]
        stats["n_flagged_events"] = len(list_flagged_events(df))
        stats["file"] = str(path)
        rows.append(stats)
    table = pd.DataFrame(rows).set_index("file")
    return flag_outlier_videos(table)


def flag_outlier_videos(summary_table, mad_multiplier=3.0):
    """
    Automatically flag videos whose QC numbers stand out from the REST
    OF THE BATCH (not from a fixed universal number, since "normal"
    varies by genotype/condition/setup). Uses a robust median + MAD
    threshold per column, so a handful of genuinely unusual videos
    don't get lost among many normal ones.

    Flags:
      - pct_time_untracked far above the batch's typical value
        (noisier background / worse contrast for that recording)
      - n_outliers_rejected far above typical (noisier detection -
        more debris/false-positive picks than other videos)
      - median_speed_mm_s far above typical (could mean a genuinely
        faster-moving larva, OR could mean residual jitter got through -
        worth a quick visual check either way)

    Adds a `flagged` boolean column and a `flag_reason` column
    listing which metric(s) triggered it, so you can just filter to
    the flagged rows rather than checking every video.
    """
    table = summary_table.copy()
    reasons = pd.Series([""] * len(table), index=table.index)
    flagged = pd.Series([False] * len(table), index=table.index)

    # (col, human label, absolute floor below which we never flag regardless of z-score)
    # Floors chosen to be biologically / practically meaningful:
    #   pct_time_untracked  : < 5 % untracked is perfectly acceptable
    #   n_outliers_rejected : a handful of noisy frames is normal
    #   n_speed_outliers    : same
    #   median_speed_mm_s   : < 0.5 mm/s difference from median is noise, not biology
    checks = {
        "pct_time_untracked":  ("high untracked %",                         5.0),
        "n_outliers_rejected": ("many outliers rejected",                   10),
        "n_speed_outliers":    ("many speed outliers (tracking jumps)",     10),
        "median_speed_mm_s":   ("unusually fast median speed",              0.5),
    }
    for col, (label, abs_floor) in checks.items():
        if col not in table.columns or len(table) < 2:
            continue
        med = table[col].median()
        mad = (table[col] - med).abs().median()
        if mad == 0:
            continue
        z = (table[col] - med).abs() / (1.4826 * mad)
        # Must be a relative outlier AND exceed the absolute floor
        trigger = (z > mad_multiplier) & (table[col] > med + abs_floor)
        flagged |= trigger
        reasons[trigger] = reasons[trigger] + label + "; "

    table["flagged"] = flagged
    table["flag_reason"] = reasons.str.rstrip("; ")
    return table


def batch_plot_overlay(csv_folder=".", csv_pattern="*.csv", fps=30, max_gap_frames=5,
                       labels=None, title="Larva Trajectories Overlay",
                       palette_name="viridis", save_path="all_larvae_trajectory_overlay.png",
                       ignore_summaries=True):
    """
    Find all tracking CSVs matching `csv_pattern` in `csv_folder`, clean them,
    compute kinematics, and generate an overlaid trajectory plot with each CSV's name as its label.
    """
    p = Path(csv_folder)
    found = sorted(p.glob(csv_pattern))
    if ignore_summaries:
        found = [f for f in found if not f.name.startswith("larva_batch_summary")]

    if not found:
        print(f"No coordinate CSVs found in '{csv_folder}' with pattern '{csv_pattern}'.")
        return None, None

    print(f"Processing {len(found)} CSV files for overlay plot:")
    dfs = []
    plot_labels = []
    for i, path in enumerate(found):
        print(f"  [{i+1}/{len(found)}] {path.name}")
        df = load_and_clean(path, fps=fps, max_gap_frames=max_gap_frames)
        df = compute_kinematics(df)
        dfs.append(df)
        if labels and i < len(labels):
            plot_labels.append(labels[i])
        else:
            plot_labels.append(path.stem)

    fig, ax = plot_multi_larva_overlay(
        dfs,
        labels=plot_labels,
        title=title,
        palette_name=palette_name,
        save_path=save_path,
    )
    print(f"Overlay plot generated and saved to '{save_path}'.")
    return fig, ax


if __name__ == "__main__":
    import argparse

    default_folder = "."
    for cand in [Path("../data/csvs"), Path("data/csvs"), Path("behavior/data/csvs")]:
        if cand.exists() and any(cand.glob("*.csv")):
            default_folder = str(cand)
            break

    parser = argparse.ArgumentParser(description="Process all larva tracking CSVs and generate summary + overlay plots.")
    parser.add_argument("--folder", default=default_folder, help=f"Folder containing coordinate CSVs (default: {default_folder})")
    parser.add_argument("--pattern", default="*.csv", help="Glob pattern for CSV files (default: *.csv)")
    parser.add_argument("--fps", type=float, default=30.0, help="Recording frames per second (default: 30)")
    parser.add_argument("--palette", default="viridis", help="Colormap palette for overlay (default: viridis)")
    parser.add_argument("--overlay-out", default="all_larvae_trajectory_overlay.png", help="Path to save overlay plot")
    parser.add_argument("--summary-out", default="larva_batch_summary.csv", help="Path to save batch summary CSV")
    args = parser.parse_args()

    files = [p for p in sorted(Path(args.folder).glob(args.pattern)) if not p.name.startswith("larva_batch_summary")]
    print(f"Found {len(files)} CSV files to analyze.")
    if files:
        summary = batch_summarize(files, fps=args.fps)
        summary.to_csv(args.summary_out)
        print(f"Saved batch summary to '{args.summary_out}'.")

        batch_plot_overlay(
            csv_folder=args.folder,
            csv_pattern=args.pattern,
            fps=args.fps,
            palette_name=args.palette,
            save_path=args.overlay_out,
        )

