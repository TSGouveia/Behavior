import sys
import time
import subprocess
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent

def process_video(video_path: Path):
    out_dir = DIRECTORY / f"{video_path.stem}_frames"
    out_dir.mkdir(exist_ok=True)

    # Check if frames were already extracted
    existing_frames = list(out_dir.glob("*.png"))
    if existing_frames:
        print(f"[SKIPPED] {video_path.name} (already processed)")
        return

    out_pattern = str(out_dir / "frame_%05d.png")
    cmd = [
        "ffmpeg",
        "-r", "30",
        "-i", str(video_path),
        "-fps_mode", "passthrough",
        "-pix_fmt", "rgb24",
        out_pattern
    ]

    print(f"[EXTRACTING] {video_path.name} ...")
    try:
        subprocess.run(cmd, check=True)
        print(f"[OK] {video_path.name}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] {video_path.name} (code {e.returncode})")
    except Exception as e:
        print(f"[ERROR] {video_path.name} ({str(e)})")

def main():
    import argparse
    global DIRECTORY
    parser = argparse.ArgumentParser(description="Extract frames one by one using ffmpeg")
    parser.add_argument("--dir", "-d", default=str(DIRECTORY), help="Directory containing .h264 videos (default: script directory)")
    args = parser.parse_args()

    target_dir = Path(args.dir).resolve()
    DIRECTORY = target_dir

    video_files = sorted(list(target_dir.glob("*.h264")))
    total = len(video_files)
    
    if total == 0:
        print(f"No .h264 files found in: {target_dir}")
        return

    print("=" * 70)
    print(f" Single-Process Video Extractor (FFmpeg)")
    print(f" Total videos: {total}")
    print("=" * 70)

    start_time = time.time()
    for idx, vid in enumerate(video_files, 1):
        print(f"\n({idx}/{total}) Processing: {vid.name}")
        process_video(vid)

    total_time = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"✓ Completed successfully in {time.strftime('%H:%M:%S', time.gmtime(total_time))}!")
    print("=" * 70)

if __name__ == "__main__":
    main()
