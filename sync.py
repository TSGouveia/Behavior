"""
Python utility script to sync and download latest project updates from GitHub (TSGouveia/Behavior).
Keeps local files completely synchronized with the latest GitHub main branch.
"""

import sys
import shutil
import subprocess
from pathlib import Path


def check_git() -> bool:
    """Checks if Git is installed and available in the command line."""
    return shutil.which("git") is not None


def run_git_command(cmd, repo_root):
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root)] + cmd,
            check=True,
            text=True,
            capture_output=True
        )
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else e.stdout.strip()
        return False, error_msg
    except FileNotFoundError:
        return False, "Git executable not found."


def main():
    repo_root = Path(__file__).resolve().parent

    print("=" * 75)
    print("      PROJECT UPDATER & SYNCHRONIZER (TSGouveia/Behavior)")
    print("=" * 75)
    print("This tool will download all latest changes and new files from GitHub.")
    print(f"Project folder:\n  -> {repo_root}\n")

    # Step 0: Ensure Git is available
    if not check_git():
        print("[ERROR] Git is not installed or not recognized on your computer!")
        print("  -> What this means: The updater needs 'git' to download files from GitHub.")
        print("  -> Solution: Please install Git from https://git-scm.com/ and reopen your terminal.\n")
        sys.exit(1)

    # Step 1: Check GitHub connection and fetch latest data
    print("[Step 1 of 2] Checking for updates on GitHub...")
    success, output = run_git_command(["fetch", "origin"], repo_root)

    if not success:
        print("\n[ERROR] Could not connect to GitHub to download updates.")
        print(f"  -> Details: {output}")
        print("  -> What you can check:")
        print("     1. Are you connected to the internet?")
        print("     2. Is GitHub accessible from your network?")
        sys.exit(1)

    print("  [OK] Connected successfully! Found latest version on GitHub.\n")

    # Step 2: Apply the updates locally
    print("[Step 2 of 2] Updating local project files to match GitHub...")
    success, output = run_git_command(["reset", "--hard", "origin/main"], repo_root)

    if success:
        print("\n" + "=" * 75)
        print("[SUCCESS] ALL DONE! Your local project is now 100% up to date.")
        print(f"  Current version state: {output}")
        print("=" * 75 + "\n")
    else:
        print("\n[ERROR] Failed to apply the latest updates to your files.")
        print(f"  -> Details: {output}")
        print("  -> Please make sure no open programs are locking project files.")
        sys.exit(1)


if __name__ == "__main__":
    main()
