import os
import sys
import time
import shutil
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

def check_ffmpeg() -> bool:
    """Checks if ffmpeg is available on the computer."""
    return shutil.which("ffmpeg") is not None

def render_progress_bar(completed: int, total: int, width: int = 30) -> str:
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
        
        active_list = list(progress_data["active"])
        if active_list:
            active_preview = ", ".join(active_list[:2])
            if len(active_list) > 2:
                active_preview += f" (+{len(active_list) - 2} more)"
        else:
            active_preview = "Waiting..."
        
        # Dynamic status line
        status_line = (
            f"\rOverall Progress: {bar} ({completed}/{total} videos done) | "
            f"Time elapsed: {elapsed_str} | Estimated time left: {eta_str} | "
            f"Currently converting: [{active_preview}]"
        )
        sys.stdout.write(status_line.ljust(120))
        sys.stdout.flush()

def process_video(video_path: Path):
    out_dir = DIRECTORY / f"{video_path.stem}_frames"
    out_dir.mkdir(exist_ok=True)

    # Check if frames were already extracted
    existing_frames = list(out_dir.glob("*.png"))
    if existing_frames:
        with print_lock:
            progress_data["completed"] += 1
        update_ui(f"\n[SKIPPED] Video '{video_path.name}' was already converted into images previously.")
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
        status_msg = f"\n[SUCCESS] Extracted all frames from '{video_path.name}' into folder '{out_dir.name}'."
    except subprocess.CalledProcessError as e:
        status_msg = f"\n[ERROR] FFmpeg failed while converting '{video_path.name}' (exit code: {e.returncode})."
    except FileNotFoundError:
        status_msg = f"\n[ERROR] FFmpeg was not found on your system. Please make sure FFmpeg is installed and added to PATH."
    except Exception as e:
        status_msg = f"\n[ERROR] Unexpected problem with '{video_path.name}': {str(e)}"
    finally:
        with print_lock:
            progress_data["active"].remove(video_path.name)
            progress_data["completed"] += 1
        update_ui(status_msg)

def main():
    import argparse
    global DIRECTORY
    parser = argparse.ArgumentParser(
        description="Fast Batch Video Extractor: Converts all .h264 videos into individual image frames simultaneously."
    )
    parser.add_argument(
        "--dir", "-d",
        default=str(DIRECTORY),
        help="Folder containing your .h264 videos (default: current script folder)"
    )
    args = parser.parse_args()

    target_dir = Path(args.dir).resolve()
    DIRECTORY = target_dir

    print("=" * 75)
    print("   FAST BATCH VIDEO FRAME EXTRACTOR (PARALLEL MODE)")
    print("=" * 75)

    if not check_ffmpeg():
        print("\n[ERROR] FFmpeg program was not found!")
        print("  -> What this means: Your computer does not recognize the 'ffmpeg' command.")
        print("  -> Solution: Ensure FFmpeg is installed and added to your Windows PATH variables.\n")
        return

    print(f"\nScanning folder for videos:\n  -> {target_dir}")
    video_files = sorted(list(target_dir.glob("*.h264")))
    total = len(video_files)
    
    if total == 0:
        print("\n[INFO] No .h264 video files found in this folder.")
        print("  -> Make sure your video files end with '.h264' and are located in the target folder.")
        return

    progress_data["total"] = total
    progress_data["start_time"] = time.time()

    print(f"Found {total} video(s) to process.")
    print(f"Using {MAX_WORKERS} simultaneous tasks to convert videos quickly.\n")
    print("-" * 75)

    update_ui()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_video, vid) for vid in video_files]
        for f in as_completed(futures):
            pass

    total_time = time.time() - progress_data["start_time"]
    print("\n\n" + "=" * 75)
    print(f"✓ All tasks finished in {time.strftime('%H:%M:%S', time.gmtime(total_time))}!")
    print("  Your frames are saved in separate '_frames' folders next to each video.")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    main()
