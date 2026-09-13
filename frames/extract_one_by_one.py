import sys
import time
import shutil
import subprocess
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent

def check_ffmpeg() -> bool:
    """Checks if ffmpeg is available on the computer."""
    return shutil.which("ffmpeg") is not None

def process_video(video_path: Path):
    out_dir = DIRECTORY / f"{video_path.stem}_frames"
    out_dir.mkdir(exist_ok=True)

    # Check if frames were already extracted
    existing_frames = list(out_dir.glob("*.png"))
    if existing_frames:
        print(f"  [SKIPPED] This video was already processed previously (folder '{out_dir.name}' has frames).")
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

    print(f"  -> Extracting frames into: {out_dir.name} ... Please wait.")
    try:
        subprocess.run(cmd, check=True)
        print(f"  [SUCCESS] Finished extracting frames for '{video_path.name}'.")
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] FFmpeg failed with error code {e.returncode} while processing '{video_path.name}'.")
    except FileNotFoundError:
        print(f"  [ERROR] FFmpeg was not found on your system! Please make sure FFmpeg is installed and added to PATH.")
    except Exception as e:
        print(f"  [ERROR] Something went wrong with '{video_path.name}': {str(e)}")

def main():
    import argparse
    global DIRECTORY
    parser = argparse.ArgumentParser(
        description="Sequential Video Extractor: Converts .h264 videos into frames one by one."
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
    print("   STEP-BY-STEP VIDEO FRAME EXTRACTOR (ONE BY ONE)")
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

    print(f"Found {total} video(s) ready to be converted into image sequences.")
    print("Processing videos one by one in order...\n")
    print("-" * 75)

    start_time = time.time()
    for idx, vid in enumerate(video_files, 1):
        print(f"\n[Video {idx} of {total}] Processing file: {vid.name}")
        process_video(vid)

    total_time = time.time() - start_time
    print("\n" + "=" * 75)
    print(f"✓ All {total} videos processed successfully in {time.strftime('%H:%M:%S', time.gmtime(total_time))}!")
    print("  Your frames are saved in separate '_frames' folders next to each video.")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    main()
