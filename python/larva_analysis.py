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
        plot_superplot,
        discover_comparisons,
        plot_average_speed_over_time,
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
    # Hierarchy: data/csvs/<genotype>/<cohort>/<file>.csv or data/csvs/<genotype>/<file>.csv
    # When folder structure exists under csvs/data, genotype is ALWAYS the genotype folder,
    # and cohort is the cohort subfolder (e.g. N1, N2, N3).
    folder_cohort = None
    folder_genotype = None

    # We inspect the parent directories in bottom-up order (immediate parent first)
    non_root_parents = [
        p.name for p in path_obj.parents
        if p.name and p.name.lower() not in ["csvs", "data", ".", ""]
    ]
    for p_name in non_root_parents:
        if re.match(r"^N\d+$", p_name, re.IGNORECASE) and not folder_cohort:
            folder_cohort = p_name.upper()
        elif not folder_genotype:
            folder_genotype = p_name

    # Check filename cohort prefix as fallback only if no folder cohort was found
    m_cohort = re.match(r"^(N\d+)_(.*)$", stem, re.IGNORECASE)
    if m_cohort:
        file_cohort = m_cohort.group(1).upper()
        base_stem = m_cohort.group(2)
    else:
        file_cohort = ""
        base_stem = stem

    meta["cohort"] = folder_cohort or file_cohort or "All"

    # Pattern: L1, L2, ... as filename stem
    m_stage = re.match(r"^L(\d+)$", stem, re.IGNORECASE)
    if m_stage:
        meta["stage"] = f"L{m_stage.group(1)}"
        if folder_genotype:
            meta["genotype"] = folder_genotype
        return meta

    # Pattern: Genotype_Stage_Condition-Replicate or Genotype_Stage_Condition_Replicate
    m = re.match(r"^([^_]+)_([^_]+)_([^-_\s]+)[-_](\d+.*)$", base_stem)
    if m:
        meta["genotype"] = folder_genotype or m.group(1)
        meta["stage"] = m.group(2)
        meta["condition"] = m.group(3)
        meta["replicate"] = m.group(4)
        if folder_genotype:
            meta["genotype"] = folder_genotype
        return meta

    # Pattern: Genotype_Replicate (e.g., Hid_1, Empty_2)
    m2 = re.match(r"^([^_]+)_(\d+.*)$", base_stem)
    if m2:
        meta["genotype"] = folder_genotype or m2.group(1)
        meta["replicate"] = m2.group(2)
        if folder_genotype:
            meta["genotype"] = folder_genotype
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


def _classify_and_interpolate(x, y, invalid_mask, max_gap_frames, max_bridge_dist_mm=1.0,
                            arena_center_mm=None, arena_radius_mm=None,
                            arena_wall_fraction=0.85):
    """Shared logic: split `invalid_mask` runs into short (interpolate)
    vs long (leave as a real break), applied to the given x/y series.
    If max_bridge_dist_mm is provided, long gaps whose spatial endpoint distance is
    very small (<= max_bridge_dist_mm) are bridged (joined) via interpolation.
    If both endpoints of an interpolated gap lie near the arena edge (>= arena_wall_fraction * R),
    the interpolated trajectory curves along the arena circumference (polar arc) rather
    than cutting through the dish as a straight chord."""
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

    # Curve interpolation along arena boundary for gaps near the arena rim
    if arena_center_mm is not None and arena_radius_mm is not None and arena_radius_mm > 0:
        cx, cy = arena_center_mm
        r_thresh = arena_radius_mm * arena_wall_fraction
        # Inspect all filled (interpolated) gaps: short_gap and bridged gaps
        filled_gaps = (short_gap | (invalid_mask & ~long_gap & x_out.notna()))
        if filled_gaps.any():
            f_gap_id = (filled_gaps != filled_gaps.shift()).cumsum()
            for fg_id, is_fg in filled_gaps.groupby(f_gap_id).first().items():
                if is_fg:
                    sub_idx = filled_gaps[f_gap_id == fg_id].index
                    s_i = sub_idx[0] - 1
                    e_i = sub_idx[-1] + 1
                    if s_i >= 0 and e_i < len(x):
                        p_s = (x_out.loc[s_i], y_out.loc[s_i])
                        p_e = (x_out.loc[e_i], y_out.loc[e_i])
                        if pd.notna(p_s[0]) and pd.notna(p_e[0]):
                            r_s = np.sqrt((p_s[0] - cx)**2 + (p_s[1] - cy)**2)
                            r_e = np.sqrt((p_e[0] - cx)**2 + (p_e[1] - cy)**2)
                            # Both endpoints must be near the arena wall
                            if r_s >= r_thresh and r_e >= r_thresh:
                                th_s = np.arctan2(p_s[1] - cy, p_s[0] - cx)
                                th_e = np.arctan2(p_e[1] - cy, p_e[0] - cx)
                                d_th = (th_e - th_s + np.pi) % (2 * np.pi) - np.pi
                                # Only curve along rim if angle sweep is reasonable (< 180 degrees)
                                if abs(d_th) < np.pi:
                                    n_pts = len(sub_idx)
                                    frac = np.linspace(0, 1, n_pts + 2)[1:-1]
                                    th_interp = th_s + frac * d_th
                                    r_interp = r_s + frac * (r_e - r_s)
                                    x_out.loc[sub_idx] = cx + r_interp * np.cos(th_interp)
                                    y_out.loc[sub_idx] = cy + r_interp * np.sin(th_interp)

    return x_out, y_out, short_gap, long_gap


def _local_deviation(x, y, local_window):
    """How far each point sits from the median position of its own
    surrounding window - the exact quantity used for outlier rejection."""
    med_x = x.rolling(local_window, center=True, min_periods=3).median()
    med_y = y.rolling(local_window, center=True, min_periods=3).median()
    return np.sqrt((x - med_x)**2 + (y - med_y)**2)


def _detect_teleport_excursions(x_series, y_series, frames, fps=30.0,
                                max_speed_mm_s=5.0, max_jump_dist_mm=5.0,
                                max_return_frames=900):
    """
    Trajectory continuity and artifact filter:
    1. Catches impossible teleports / excursions where tracking leaps far away (> max_jump_dist_mm
       or > max_speed_mm_s) from the true larva track to a stationary reflection/debris and returns.
    2. Catches start-of-video artifacts where tracking is initially locked onto a stationary edge/debris
       before jumping to the larva.
    3. Catches end-of-video artifacts where tracking loses the larva and jumps to a stationary point.
    4. Purges all detections associated with the identified stationary artifact locations.
    All points during such false excursions are marked True (invalid/NaN).
    """
    valid = pd.DataFrame({"x": x_series, "y": y_series, "frame": frames}).dropna()
    is_teleport = pd.Series(False, index=x_series.index)
    if len(valid) < 5:
        return is_teleport

    xs = valid["x"].values
    ys = valid["y"].values
    fs = valid["frame"].values
    idxs = valid.index.values
    n = len(valid)

    flagged = set()

    # 1. Start-of-video artifact
    for i in range(min(120, n - 2)):
        d_jump = np.sqrt((xs[i + 1] - xs[i]) ** 2 + (ys[i + 1] - ys[i]) ** 2)
        dt_jump = max((fs[i + 1] - fs[i]) / fps, 1e-4)
        if d_jump >= 10.0 and (d_jump / dt_jump) >= max_speed_mm_s:
            sub_x, sub_y = xs[: i + 1], ys[: i + 1]
            if np.std(sub_x) < 1.5 and np.std(sub_y) < 1.5:
                for k in range(i + 1):
                    flagged.add(idxs[k])
            break

    # 2. End-of-video artifact
    for i in range(max(0, n - 120), n - 1):
        d_jump = np.sqrt((xs[i + 1] - xs[i]) ** 2 + (ys[i + 1] - ys[i]) ** 2)
        dt_jump = max((fs[i + 1] - fs[i]) / fps, 1e-4)
        if d_jump >= 10.0 and (d_jump / dt_jump) >= max_speed_mm_s:
            sub_x, sub_y = xs[i + 1 :], ys[i + 1 :]
            if len(sub_x) > 0 and np.std(sub_x) < 1.5 and np.std(sub_y) < 1.5:
                for k in range(i + 1, n):
                    flagged.add(idxs[k])
            break

    # 3. Excursion / Teleport jumps during tracking
    for max_return in [15, 60, 300, max_return_frames]:
        for i in range(n - 1):
            if idxs[i] in flagged:
                continue
            nxt = i + 1
            while nxt < n and idxs[nxt] in flagged:
                nxt += 1
            if nxt >= n:
                break

            d_jump = np.sqrt((xs[nxt] - xs[i]) ** 2 + (ys[nxt] - ys[i]) ** 2)
            dt_jump = max((fs[nxt] - fs[i]) / fps, 1e-4)
            v_jump = d_jump / dt_jump

            if d_jump >= max_jump_dist_mm and v_jump >= max_speed_mm_s:
                return_idx = None
                for j in range(nxt + 1, min(nxt + max_return, n)):
                    d_ret = np.sqrt((xs[j] - xs[i]) ** 2 + (ys[j] - ys[i]) ** 2)
                    dt_total = (fs[j] - fs[i]) / fps
                    max_allowed_drift = max_jump_dist_mm + dt_total * 1.5
                    if d_ret <= max_allowed_drift:
                        return_idx = j
                        break
                if return_idx is not None and return_idx > nxt:
                    exc_dists = np.sqrt((xs[nxt:return_idx] - xs[i]) ** 2 + (ys[nxt:return_idx] - ys[i]) ** 2)
                    if np.min(exc_dists) >= max_jump_dist_mm * 0.8:
                        for k in range(nxt, return_idx):
                            flagged.add(idxs[k])

    # 4. Stationary debris / reflection purge
    if len(flagged) > 0:
        fl_df = valid.loc[list(flagged), ["x", "y"]].dropna()
        grid = np.round(np.column_stack([fl_df["x"].values, fl_df["y"].values]))
        u_cells, counts = np.unique(grid, axis=0, return_counts=True)
        for cell, count in zip(u_cells, counts):
            if count >= 2:
                d_to_art = np.sqrt((xs - cell[0]) ** 2 + (ys - cell[1]) ** 2)
                art_matches = np.where(d_to_art <= 3.0)[0]
                for pos in art_matches:
                    flagged.add(idxs[pos])

    # 5. Isolated transient bouts (<= 3 frames separated by speed jumps >= max_speed_mm_s)
    unflagged_pos = [k for k in range(n) if idxs[k] not in flagged]
    if len(unflagged_pos) > 1:
        uf_df = valid.iloc[unflagged_pos].copy()
        dt = uf_df["frame"].diff() / fps
        d_step = np.sqrt(uf_df["x"].diff() ** 2 + uf_df["y"].diff() ** 2)
        v_step = d_step / dt.clip(lower=1e-4)
        bout_break = (v_step >= max_speed_mm_s) | (d_step >= max_jump_dist_mm)
        bout_id = bout_break.cumsum()
        sizes = uf_df.groupby(bout_id)["frame"].transform("count")
        is_micro = sizes <= 3
        for idx_val in uf_df[is_micro].index:
            flagged.add(idx_val)

    is_teleport.loc[list(flagged)] = True
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
                    max_teleport_speed_mm_s=5.0, max_teleport_jump_mm=5.0,
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

    # Extract arena geometry early so boundary-aware interpolation can curve along rim
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

    noise_scale_mm = estimate_noise_scale(x_raw.where(~is_teleport), y_raw.where(~is_teleport), max_gap_frames, local_window)
    if max_local_deviation_mm is None:
        max_local_deviation_mm = max(min_deviation_floor_mm, deviation_multiplier * noise_scale_mm)

    x_pass1, y_pass1, _, _ = _classify_and_interpolate(
        x_raw, y_raw, not_detected | is_teleport, max_gap_frames, max_bridge_dist_mm=None,
        arena_center_mm=arena_center_mm, arena_radius_mm=arena_radius_mm
    )

    local_dev = _local_deviation(x_pass1, y_pass1, local_window)
    is_outlier = (local_dev > max_local_deviation_mm).fillna(False)

    invalid = not_detected | is_outlier | is_teleport
    x_clean, y_clean, short_gap, long_gap = _classify_and_interpolate(
        x_raw, y_raw, invalid, max_gap_frames, max_bridge_dist_mm=max_bridge_dist_mm,
        arena_center_mm=arena_center_mm, arena_radius_mm=arena_radius_mm
    )

    df["X_mm_clean"] = x_clean
    df["Y_mm_clean"] = y_clean
    df["is_long_gap"] = long_gap
    df["is_short_gap_filled"] = short_gap
    df["is_outlier_rejected"] = (is_outlier | is_teleport) & ~not_detected
    df["is_teleport_excursion"] = is_teleport
    df["fps"] = fps
    df["noise_scale_mm"] = noise_scale_mm
    df["deviation_threshold_used_mm"] = max_local_deviation_mm

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
    meta = parse_filename_metadata(csv_path)
    df.attrs["metadata"] = meta
    df.attrs["genotype"] = meta.get("genotype", "Unknown")
    df.attrs["cohort"] = meta.get("cohort", "All")

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
def discover_comparisons(csv_folder):
    """
    Scan csv_folder for comparison groups and their respective genotypes dynamically.

    Ignores parent group folder names (e.g. 'graph 1', 'graph 2', etc.), but extracts
    all genotype subfolders residing within each group. Sorts controls (e.g. w1118) first.

    Returns
    -------
    list of list of str
        e.g. [['w1118', 'RalG0501'], ['nSybxw1118', 'nSybxRalRNAi']]
    """
    csv_root = Path(csv_folder)
    comparisons = []

    def _sort_control_first(genotypes):
        def sort_key(g):
            gl = g.lower()
            if gl in ["w1118", "wt", "control", "ctrl"]:
                return (0, g)
            if "w1118" in gl or "ctrl" in gl or "control" in gl:
                return (1, g)
            return (2, g)
        return sorted(genotypes, key=sort_key)

    if csv_root.exists():
        for group_dir in sorted(csv_root.iterdir()):
            if group_dir.is_dir() and not group_dir.name.startswith("."):
                geno_dirs = [d for d in sorted(group_dir.iterdir()) if d.is_dir() and any(d.rglob("*.csv"))]
                if geno_dirs:
                    genos = [d.name for d in geno_dirs]
                    comparisons.append(_sort_control_first(genos))

        # Fallback if genotypes are placed directly in csv_folder/<genotype>/
        if not comparisons:
            direct = [d for d in sorted(csv_root.iterdir()) if d.is_dir() and not d.name.startswith(".") and any(d.rglob("*.csv"))]
            if direct:
                comparisons.append(_sort_control_first([d.name for d in direct]))

    return comparisons


def plot_superplot(
    df,
    genotypes=None,
    metric="total_distance_mm",
    ylabel="Total distance (mm)",
    title=None,
    ax=None,
    palette=None,
    replicate_col="cohort",
    genotype_col="genotype",
    genotype_labels=None,
    show_stat_test=True,
    show_legend=True,
    jitter_amount=0.18,
    individual_size=40,
    replicate_median_size=180,
    alpha_individual=0.55,
    print_stat_report=True,
    figsize=None,
    save_path=None,
    **kwargs,
):
    """
    Generate a publication-grade SuperPlot for any number of genotypes (2, 3, 4, ... N).

    SuperPlot layout (Lord et al., 2020):
      - Individual larvae: small dots with jitter, color-coded by biological replicate (cohort).
      - Replicate median: prominent large circle for each biological replicate.
      - Grand mean +/- SEM: horizontal black line and error bar across biological replicates.
      - Statistical test: automated normality test (Shapiro-Wilk) and variance test (Levene),
        followed by appropriate hypothesis testing (Student's / Welch's t-test or Mann-Whitney U).
      - Legend placed outside the plotting area to ensure zero visual obstruction.

    Parameters
    ----------
    df : pd.DataFrame
        Table with per-larva summary statistics.
    genotypes : list of str, optional
        List of genotypes to include on the X axis, in order.
        If None, automatically plots ALL genotypes present in df.
    metric : str
        Column name for Y axis ('total_distance_mm', 'mean_speed_mm_s', etc.).
    ylabel : str
        Y-axis label.
    title : str, optional
        Plot title.
    ax : matplotlib.axes.Axes, optional
        Existing Axes to plot on (for subplots / multi-panel figures).
    palette : dict, optional
        Colors for each biological replicate / cohort (e.g. {'N1': '#2563EB', ...}).
    replicate_col : str
        Column identifying biological replicates (default 'cohort').
    genotype_col : str
        Column identifying genotype (default 'genotype').
    genotype_labels : dict or list, optional
        Custom display names for genotypes on the X axis.
    show_stat_test : bool
        If True and len(genotypes)==2, performs normality evaluation and displays test result.
    jitter_amount : float
        Spread width of individual points.
    individual_size : float
        Scatter marker size for individual larvae.
    replicate_median_size : float
        Scatter marker size for biological replicate medians.
    alpha_individual : float
        Opacity of individual larva points.
    print_stat_report : bool
        If True, prints detailed statistical and normality evaluation to stdout.
    figsize : tuple, optional
        (width, height) in inches. Auto-calculated based on number of genotypes if None.
    save_path : str or Path, optional
        Path to save figure.
    """
    try:
        from scipy import stats as sp_stats
    except ImportError:
        sp_stats = None

    if genotypes is None:
        genotypes = sorted(df[genotype_col].dropna().unique().tolist())

    sub_df = df[df[genotype_col].isin(genotypes)].copy()
    if sub_df.empty:
        raise ValueError(f"No data found for genotypes: {genotypes}")

    if isinstance(genotype_labels, dict):
        label_map = genotype_labels
    elif isinstance(genotype_labels, (list, tuple)) and len(genotype_labels) == len(genotypes):
        label_map = dict(zip(genotypes, genotype_labels))
    else:
        label_map = {g: g for g in genotypes}

    all_reps = sorted(sub_df[replicate_col].dropna().astype(str).unique())

    # Distinct palette: Purple, Orange, Green (Purple & Orange if 2 items)
    # Accessible, publication-grade hex codes
    default_colors = ["#8B5CF6", "#F97316", "#10B981", "#6366F1", "#EC4899", "#14B8A6"]
    if palette is None:
        palette = {rep: default_colors[i % len(default_colors)] for i, rep in enumerate(all_reps)}

    created_fig = False
    if ax is None:
        created_fig = True
        n_geno = len(genotypes)
        fig_w = max(5.8, 2.6 * n_geno)
        fig_h = 5.8
        if figsize is not None:
            fig_w, fig_h = figsize
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=300)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(1.2)
    ax.spines["bottom"].set_linewidth(1.2)
    ax.grid(axis="y", linestyle="--", alpha=0.35, color="gray")

    rep_medians_by_geno = {}

    for x_idx, geno in enumerate(genotypes):
        g_data = sub_df[sub_df[genotype_col] == geno]
        rep_medians_by_geno[geno] = []

        rng = np.random.RandomState(42 + x_idx * 17)
        geno_reps = sorted(g_data[replicate_col].dropna().astype(str).unique())
        n_reps = len(geno_reps)

        for r_i, rep in enumerate(geno_reps):
            r_data = g_data[g_data[replicate_col].astype(str) == rep]
            vals = r_data[metric].dropna().values
            if len(vals) == 0:
                continue

            color = palette.get(rep, "#6B7280")

            if n_reps > 1:
                rep_center_offset = (r_i - (n_reps - 1) / 2.0) * (jitter_amount * 0.8)
            else:
                rep_center_offset = 0.0

            jitter = rng.uniform(-jitter_amount * 0.45, jitter_amount * 0.45, size=len(vals))
            x_vals = x_idx + rep_center_offset + jitter

            ax.scatter(
                x_vals,
                vals,
                color=color,
                alpha=alpha_individual,
                s=individual_size,
                edgecolors="none",
                zorder=2,
            )

            rep_median = np.median(vals)
            rep_medians_by_geno[geno].append(rep_median)

            ax.scatter(
                x_idx + rep_center_offset,
                rep_median,
                color=color,
                edgecolor="black",
                linewidth=1.8,
                s=replicate_median_size,
                zorder=4,
            )

        medians_array = np.array(rep_medians_by_geno[geno])
        if len(medians_array) > 0:
            grand_mean = np.mean(medians_array)
            sem = (
                np.std(medians_array, ddof=1) / np.sqrt(len(medians_array))
                if len(medians_array) > 1
                else 0.0
            )

            bar_half_width = 0.28
            ax.hlines(
                y=grand_mean,
                xmin=x_idx - bar_half_width,
                xmax=x_idx + bar_half_width,
                color="black",
                linewidth=2.8,
                zorder=5,
            )
            if len(medians_array) > 1 and sem > 0:
                ax.errorbar(
                    x=x_idx,
                    y=grand_mean,
                    yerr=sem,
                    fmt="none",
                    ecolor="black",
                    elinewidth=2.2,
                    capsize=6,
                    capthick=2.0,
                    zorder=5,
                )

    ax.set_xticks(range(len(genotypes)))
    ax.set_xticklabels(
        [label_map.get(g, g) for g in genotypes],
        fontsize=11.5,
        fontweight="bold",
    )
    ax.set_xlim(-0.55, len(genotypes) - 0.45)
    ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")

    if title:
        ax.set_title(title, fontsize=13, fontweight="bold", pad=12)

    # Statistical testing with automated normality & variance evaluation
    stat_report = None
    if show_stat_test and len(genotypes) == 2 and sp_stats is not None:
        g1, g2 = genotypes[0], genotypes[1]
        all_vals1 = sub_df[sub_df[genotype_col] == g1][metric].dropna().values
        all_vals2 = sub_df[sub_df[genotype_col] == g2][metric].dropna().values

        if len(all_vals1) > 0 and len(all_vals2) > 0:
            # 1. Normality evaluation (Shapiro-Wilk)
            sw1 = sp_stats.shapiro(all_vals1)
            sw2 = sp_stats.shapiro(all_vals2)
            norm1 = sw1.pvalue >= 0.05
            norm2 = sw2.pvalue >= 0.05
            both_normal = norm1 and norm2

            # 2. Homogeneity of variances (Levene's test)
            lev = sp_stats.levene(all_vals1, all_vals2)
            equal_var = lev.pvalue >= 0.05

            # 3. Hypothesis testing
            if both_normal:
                if equal_var:
                    test_name = "Student t-test"
                    stat_res = sp_stats.ttest_ind(all_vals1, all_vals2, equal_var=True)
                else:
                    test_name = "Welch t-test"
                    stat_res = sp_stats.ttest_ind(all_vals1, all_vals2, equal_var=False)
                p_val = stat_res.pvalue
                stat_val = stat_res.statistic
            else:
                test_name = "Mann-Whitney U"
                stat_res = sp_stats.mannwhitneyu(all_vals1, all_vals2, alternative="two-sided")
                p_val = stat_res.pvalue
                stat_val = stat_res.statistic

            # Replicate-level test (on replicate medians)
            meds1 = rep_medians_by_geno.get(g1, [])
            meds2 = rep_medians_by_geno.get(g2, [])
            if len(meds1) >= 3 and len(meds2) >= 3:
                t_rep = sp_stats.ttest_ind(meds1, meds2, equal_var=True)
                p_rep = t_rep.pvalue
            else:
                p_rep = None

            # Asterisk assignment
            if p_val < 0.001:
                stars = "***"
            elif p_val < 0.01:
                stars = "**"
            elif p_val < 0.05:
                stars = "*"
            else:
                stars = "ns"

            if p_val < 0.001:
                p_plot_str = f"{test_name}: p < 0.001 ({stars})"
            elif p_val < 0.05:
                p_plot_str = f"{test_name}: p = {p_val:.4f} ({stars})"
            else:
                p_plot_str = f"{test_name}: p = {p_val:.3f} ({stars})"

            y_max = sub_df[metric].max()
            y_span = y_max - sub_df[metric].min()
            if y_span == 0:
                y_span = 1.0
            bracket_y = y_max + 0.07 * y_span
            text_y = bracket_y + 0.02 * y_span

            ax.plot(
                [0, 0, 1, 1],
                [bracket_y - 0.02 * y_span, bracket_y, bracket_y, bracket_y - 0.02 * y_span],
                color="black",
                linewidth=1.2,
            )
            ax.text(0.5, text_y, p_plot_str, ha="center", va="bottom", fontsize=9.5, fontweight="bold")
            ax.set_ylim(top=bracket_y + 0.16 * y_span)

            stat_report = {
                "comparison": f"{g1} vs {g2}",
                "metric": metric,
                "shapiro_p_g1": sw1.pvalue,
                "shapiro_p_g2": sw2.pvalue,
                "is_normal_g1": norm1,
                "is_normal_g2": norm2,
                "both_normal": both_normal,
                "levene_p": lev.pvalue,
                "equal_variance": equal_var,
                "test_used": test_name,
                "statistic": stat_val,
                "p_value": p_val,
                "stars": stars,
                "n_g1": len(all_vals1),
                "n_g2": len(all_vals2),
                "p_value_replicate_level": p_rep,
            }

            if print_stat_report:
                print(f"==========================================================================")
                print(f"STATISTICAL & NORMALITY REPORT: {g1} vs {g2} [{ylabel}]")
                print(f"==========================================================================")
                print(f"1. Normality Assessment (Shapiro-Wilk test, alpha = 0.05):")
                print(f"   • {g1} (n={len(all_vals1)}): W = {sw1.statistic:.4f}, p = {sw1.pvalue:.4f} -> {'NORMAL (p >= 0.05)' if norm1 else 'NOT NORMAL (p < 0.05)'}")
                print(f"   • {g2} (n={len(all_vals2)}): W = {sw2.statistic:.4f}, p = {sw2.pvalue:.4f} -> {'NORMAL (p >= 0.05)' if norm2 else 'NOT NORMAL (p < 0.05)'}")
                print(f"   • Conclusion: {'Both distributions are normal -> Parametric test valid.' if both_normal else 'At least one distribution is non-normal -> Non-parametric test recommended.'}")
                print(f"2. Homogeneity of Variances (Levene test):")
                print(f"   • Stat = {lev.statistic:.4f}, p = {lev.pvalue:.4f} -> {'Equal variances' if equal_var else 'Unequal variances (heteroscedastic)'}")
                print(f"3. Statistical Test Performed:")
                print(f"   • Test: {test_name}")
                print(f"   • Test Statistic = {stat_val:.4f}")
                print(f"   • P-value = {p_val:.5f} ({stars})")
                print(f"   • Significance code: *** p < 0.001 | ** p < 0.01 | * p < 0.05 | ns p >= 0.05")
                if p_rep is not None:
                    print(f"4. Replicate-Level Test (N={len(meds1)} vs {len(meds2)} replicate medians):")
                    print(f"   • t-test p-value = {p_rep:.4f}")
                print(f"==========================================================================\n")

    # Legend placed OUTSIDE the plot area (top right outside) so it never covers points or brackets
    handles = []
    labels = []
    for rep in all_reps:
        h_rep = plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=palette.get(rep, "#6B7280"),
            markersize=9,
            markeredgecolor="black",
            markeredgewidth=1.2,
        )
        handles.append(h_rep)
        labels.append(f"Replicate {rep}")

    h_larva = plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#9CA3AF", markersize=6)
    h_med = plt.Line2D(
        [0],
        [0],
        marker="o",
        color="w",
        markerfacecolor="#9CA3AF",
        markeredgecolor="black",
        markeredgewidth=1.8,
        markersize=11,
    )
    h_grand = plt.Line2D([0], [0], color="black", linewidth=2.5)

    handles.extend([h_larva, h_med, h_grand])
    labels.extend(["Single larva", "Replicate median", "Mean +/- SEM"])

    if show_legend:
        ax.legend(
            handles,
            labels,
            bbox_to_anchor=(1.04, 1.0),
            loc="upper left",
            frameon=True,
            framealpha=0.9,
            edgecolor="#D1D5DB",
            fontsize=8.5,
        )

    if created_fig:
        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"Saved plot: {save_path}")
        return fig, ax
    return ax


def plot_average_speed_over_time(
    larva_dfs,
    genotypes=None,
    epoch_s=10,
    error_type="sem",
    ax=None,
    palette=None,
    title=None,
    show_legend=True,
    print_stat_report=True,
    save_path=None,
    figsize=(9, 5),
):
    """
    Plot average crawling speed over time for multiple genotypes.
    
    Hierarchy (mean of replicate means):
      1. For each biological replicate (cohort N1, N2, N3...) and each time epoch,
         computes the mean speed across larvae in that replicate:
         v_bar_{G, rep}(t) = mean(speed of larvae in rep at epoch t)
      2. For each genotype G, computes the Grand Mean across biological replicates:
         V_bar_G(t) = mean_{rep}(v_bar_{G, rep}(t))
      3. Computes the error band across biological replicates:
         - Standard Deviation (SD): SD(t) = std(v_bar_{G, rep}(t), ddof=1)
         - Standard Error of the Mean (SEM): SEM(t) = SD(t) / sqrt(N_reps)
      4. Evaluates normality (Shapiro-Wilk) and equal variance (Levene) on the replicate-level
         mean speeds, runs the appropriate hypothesis test (Student's / Welch's t-test or
         Mann-Whitney U), and reports the scientific rationale for choosing SD vs SEM.
      5. Places legends outside the axes to prevent visual obstruction.
    """
    try:
        from scipy import stats as sp_stats
    except ImportError:
        sp_stats = None

    # Parse and organize all larvae by genotype and replicate (cohort)
    larvae_records = []
    max_time_s = 0.0

    for name, df_l in larva_dfs.items():
        file_p = df_l.attrs.get("file_path", name)
        meta = parse_filename_metadata(file_p)
        geno = df_l.attrs.get("genotype") or meta.get("genotype") or "Unknown"
        cohort = meta.get("cohort") or "All"
        
        # Calculate max recording time
        if "Frame" in df_l.columns and "fps" in df_l.columns and len(df_l) > 0:
            t_max = df_l["Frame"].max() / df_l["fps"].iloc[0]
            if t_max > max_time_s:
                max_time_s = t_max

        # Epoch summaries per larva
        ep = summarize_by_epoch(df_l, epoch_s=epoch_s)
        for _, row in ep.iterrows():
            larvae_records.append({
                "genotype": geno,
                "replicate": cohort,
                "larva": Path(name).stem,
                "epoch": int(row["epoch"]),
                "mean_speed": row["mean"],
            })

    if not larvae_records:
        raise ValueError("No epoch data could be extracted from larva_dfs.")

    df_all_epochs = pd.DataFrame(larvae_records)

    # If genotypes not explicitly provided, extract unique genotypes
    if genotypes is None:
        genotypes = sorted(df_all_epochs["genotype"].dropna().unique().tolist())

    sub_epochs = df_all_epochs[df_all_epochs["genotype"].isin(genotypes)].copy()
    if sub_epochs.empty:
        raise ValueError(f"No data found for genotypes: {genotypes}")

    # 1. Compute replicate means per epoch: v_bar_{G, rep}(t)
    rep_epoch_means = (
        sub_epochs.groupby(["genotype", "replicate", "epoch"])["mean_speed"]
        .mean()
        .reset_index()
    )

    # 2. Compute Grand Mean, SD, SEM across replicates per epoch
    grand_stats = (
        rep_epoch_means.groupby(["genotype", "epoch"])["mean_speed"]
        .agg(
            grand_mean="mean",
            sd=lambda x: x.std(ddof=1) if len(x) > 1 else 0.0,
            sem=lambda x: x.sem() if len(x) > 1 else 0.0,
            n_reps="count",
        )
        .reset_index()
    )
    grand_stats["time_s"] = grand_stats["epoch"] * epoch_s

    # 3. Overall replicate averages across entire recording (for statistical testing)
    rep_overall = (
        rep_epoch_means.groupby(["genotype", "replicate"])["mean_speed"]
        .mean()
        .reset_index()
    )

    # Color palette: Purple, Orange, Green (Purple & Orange if 2 items)
    if palette is None:
        default_colors = ["#8B5CF6", "#F97316", "#10B981", "#6366F1", "#EC4899", "#14B8A6"]
        palette = {g: default_colors[i % len(default_colors)] for i, g in enumerate(genotypes)}

    created_fig = False
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize, dpi=300)
        created_fig = True
    else:
        fig = ax.get_figure()

    # Plot curves and shaded error bands
    error_key = error_type.lower()
    for geno in genotypes:
        g_data = grand_stats[grand_stats["genotype"] == geno].sort_values("time_s")
        if g_data.empty:
            continue

        color = palette.get(geno, "#374151")
        time_x = g_data["time_s"].values
        mean_y = g_data["grand_mean"].values
        n_reps_max = int(g_data["n_reps"].max())

        if error_key == "sd":
            err = g_data["sd"].values
            err_label = f"{geno} (mean +/- SD, R={n_reps_max})"
        else:
            err = g_data["sem"].values
            err_label = f"{geno} (mean +/- SEM, R={n_reps_max})"

        ax.plot(
            time_x,
            mean_y,
            label=err_label,
            color=color,
            linewidth=2.2,
            marker="o",
            markersize=3.5,
            zorder=3,
        )

        ax.fill_between(
            time_x,
            mean_y - err,
            mean_y + err,
            color=color,
            alpha=0.18,
            zorder=2,
        )

    # Standardize time axis
    max_t_s = int(round(max_time_s)) if max_time_s > 0 else int(grand_stats["time_s"].max())
    tick_step = 30 if max_t_s >= 120 else (20 if max_t_s >= 60 else 10)
    time_ticks = list(range(0, max_t_s + 1, tick_step))
    if max_t_s not in time_ticks:
        time_ticks.append(max_t_s)

    ax.set_xlim(0, max_t_s)
    ax.set_xticks(time_ticks)
    ax.set_xlabel("Time (s)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Average speed (mm/s)", fontsize=11, fontweight="bold")

    plot_title = title if title else f"Average Speed Over Time ({epoch_s}s epochs, mean +/- {error_key.upper()})"
    ax.set_title(plot_title, fontsize=12, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.3, zorder=1)

    if show_legend:
        ax.legend(
            bbox_to_anchor=(1.04, 1.0),
            loc="upper left",
            frameon=True,
            framealpha=0.9,
            edgecolor="#D1D5DB",
            fontsize=9.5,
        )

    # Statistical Evaluation & Rationale
    stat_summary = {}
    if sp_stats is not None and len(genotypes) == 2:
        g1, g2 = genotypes[0], genotypes[1]
        v1 = rep_overall[rep_overall["genotype"] == g1]["mean_speed"].values
        v2 = rep_overall[rep_overall["genotype"] == g2]["mean_speed"].values

        # Normality (Shapiro-Wilk)
        s1, p_norm1 = sp_stats.shapiro(v1) if len(v1) >= 3 else (1.0, 1.0)
        s2, p_norm2 = sp_stats.shapiro(v2) if len(v2) >= 3 else (1.0, 1.0)

        # Equal variance (Levene)
        l_stat, p_var = sp_stats.levene(v1, v2) if len(v1) >= 3 and len(v2) >= 3 else (0.0, 1.0)

        is_normal = (p_norm1 > 0.05) and (p_norm2 > 0.05)
        equal_var = p_var > 0.05

        if is_normal:
            t_stat, p_val = sp_stats.ttest_ind(v1, v2, equal_var=equal_var)
            test_name = "Two-sample Student's t-test" if equal_var else "Welch's t-test"
        else:
            u_stat, p_val = sp_stats.mannwhitneyu(v1, v2, alternative="two-sided")
            test_name = "Mann-Whitney U test"

        stat_summary = {
            "genotype_1": g1,
            "genotype_2": g2,
            "mean_1": float(np.mean(v1)) if len(v1) > 0 else np.nan,
            "std_1": float(np.std(v1, ddof=1)) if len(v1) > 1 else 0.0,
            "sem_1": float(np.std(v1, ddof=1) / np.sqrt(len(v1))) if len(v1) > 1 else 0.0,
            "n_reps_1": len(v1),
            "shapiro_p_1": float(p_norm1),
            "mean_2": float(np.mean(v2)) if len(v2) > 0 else np.nan,
            "std_2": float(np.std(v2, ddof=1)) if len(v2) > 1 else 0.0,
            "sem_2": float(np.std(v2, ddof=1) / np.sqrt(len(v2))) if len(v2) > 1 else 0.0,
            "n_reps_2": len(v2),
            "shapiro_p_2": float(p_norm2),
            "levene_p": float(p_var),
            "is_normal": is_normal,
            "equal_var": equal_var,
            "test_name": test_name,
            "p_value": float(p_val),
            "error_type_chosen": error_key.upper(),
        }

        if print_stat_report:
            print("=" * 72)
            print(f"  STATISTICAL REPORT: AVERAGE SPEED OVER TIME ({g1} vs {g2})")
            print("=" * 72)
            print(f"Hierarchical Summary (mean of replicate means, N={len(v1)} vs N={len(v2)} biological replicates):")
            print(f"  * {g1:15s}: Mean = {stat_summary['mean_1']:.4f} mm/s | SD = {stat_summary['std_1']:.4f} | SEM = {stat_summary['sem_1']:.4f} | Shapiro-Wilk p = {p_norm1:.4f}")
            print(f"  * {g2:15s}: Mean = {stat_summary['mean_2']:.4f} mm/s | SD = {stat_summary['std_2']:.4f} | SEM = {stat_summary['sem_2']:.4f} | Shapiro-Wilk p = {p_norm2:.4f}")
            print(f"Homogeneity of Variance (Levene's test): p = {p_var:.4f} ({'Equal variance confirmed' if equal_var else 'Unequal variances detected'})")
            norm_str = "Normal distribution (p > 0.05)" if is_normal else "Non-normal distribution (p <= 0.05)"
            print(f"Normality Outcome: {norm_str}")
            print(f"Hypothesis Test Selected: {test_name}")
            sig_mark = "ns" if p_val >= 0.05 else ("*" if p_val >= 0.01 else ("**" if p_val >= 0.001 else "***"))
            print(f"Significance: p = {p_val:.4f} [{sig_mark}]")
            print("-" * 72)
            print("SCIENTIFIC JUSTIFICATION: SD vs SEM")
            print("  - SD (Standard Deviation): Quantifies the direct biological spread / variability")
            print("    between experimental cohorts. Use SD when the objective is to describe the")
            print("    variation inherent to the biological population.")
            print("  - SEM (Standard Error of the Mean = SD / sqrt(N)): Quantifies the precision of the")
            print("    estimated population mean. It directly relates to statistical hypothesis testing")
            print("    (e.g., non-overlapping +/- 1 SEM bands frequently reflect p < 0.05 in parametric tests).")
            print(f"  - Currently plotted shaded band: +/- {error_key.upper()}.")
            print("=" * 72)

    if created_fig:
        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"Saved plot: {save_path}")
        return fig, ax
    return ax


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

