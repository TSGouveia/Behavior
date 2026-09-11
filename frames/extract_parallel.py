import os
import sys
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Configuration
DIRECTORY = Path(__file__).resolve().parent
MAX_WORKERS = os.cpu_count() or 4

# Thread lock for clean console output
print_lock = Lock()
progress_data = {
    "completed": 0,
    "total": 0,
    "start_time": 0.0,
    "active": set()
}

def render_progress_bar(completed: int, total: int, width: int = 35) -> str:
    if total == 0:
        return "[" + " " * width + "] 0.0%"
    percent = completed / total
    filled = int(round(width * percent))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {percent * 100:5.1f}%"

def update_ui(action_msg: str = None):
    with print_lock:
        completed = progress_data["completed"]
        total = progress_data["total"]
        elapsed = time.time() - progress_data["start_time"]
        
        # Estimate remaining time (ETA)
        if completed > 0:
            rate = elapsed / completed
            eta_seconds = rate * (total - completed)
            eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_seconds))
        else:
            eta_str = "--:--:--"
        
        elapsed_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))
        bar = render_progress_bar(completed, total)
        
        if action_msg:
            print(action_msg)
        
        active_preview = ", ".join(list(progress_data["active"])[:3])
        if len(progress_data["active"]) > 3:
            active_preview += f" (+{len(progress_data['active']) - 3} others)"
        
        # Dynamic status line
        status_line = (
            f"\rProgress: {bar} ({completed}/{total}) | "
            f"Elapsed: {elapsed_str} | ETA: {eta_str} | "
            f"Running: [{active_preview}]"
        )
        sys.stdout.write(status_line.ljust(110))
        sys.stdout.flush()

def process_video(video_path: Path):
    out_dir = DIRECTORY / f"{video_path.stem}_frames"
    out_dir.mkdir(exist_ok=True)

    # Check if frames were already extracted
    existing_frames = list(out_dir.glob("*.png"))
    if existing_frames:
        with print_lock:
            progress_data["completed"] += 1
        update_ui(f"\n[SKIPPED] {video_path.name} (already processed)")
        return

    # Mark as active
    with print_lock:
        progress_data["active"].add(video_path.name)
    update_ui()

    out_pattern = str(out_dir / "frame_%05d.png")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-r", "30",
        "-i", str(video_path),
        "-fps_mode", "passthrough",
        "-pix_fmt", "rgb24",
        out_pattern
    ]

    try:
        subprocess.run(cmd, check=True)
        status_msg = f"\n[OK] {video_path.name}"
    except subprocess.CalledProcessError as e:
        status_msg = f"\n[ERROR] {video_path.name} (code {e.returncode})"
    except Exception as e:
        status_msg = f"\n[ERROR] {video_path.name} ({str(e)})"
    finally:
        with print_lock:
            progress_data["active"].remove(video_path.name)
            progress_data["completed"] += 1
        update_ui(status_msg)

def main():
    import argparse
    global DIRECTORY
    parser = argparse.ArgumentParser(description="Parallel frame extraction using ffmpeg")
    parser.add_argument("--dir", "-d", default=str(DIRECTORY), help="Directory containing .h264 videos (default: script directory)")
    args = parser.parse_args()

    target_dir = Path(args.dir).resolve()
    DIRECTORY = target_dir

    video_files = sorted(list(target_dir.glob("*.h264")))
    total = len(video_files)
    
    if total == 0:
        print(f"No .h264 files found in: {target_dir}")
        return

    progress_data["total"] = total
    progress_data["start_time"] = time.time()

    print("=" * 70)
    print(f" Parallel Video Extractor (FFmpeg)")
    print(f" Total videos: {total}")
    print(f" Concurrent workers: {MAX_WORKERS}")
    print("=" * 70)

    update_ui()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_video, vid) for vid in video_files]
        for f in as_completed(futures):
            pass

    total_time = time.time() - progress_data["start_time"]
    print("\n" + "=" * 70)
    print(f"✓ Completed successfully in {time.strftime('%H:%M:%S', time.gmtime(total_time))}!")
    print("=" * 70)

if __name__ == "__main__":
    main()
