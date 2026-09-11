"""
Python utility script to sync and download changes from GitHub (TSGouveia/Behavior).
Forces local repository alignment with the latest GitHub main branch (git fetch origin + git reset --hard origin/main).
"""

import subprocess
import sys
from pathlib import Path


def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, check=True, text=True, capture_output=True)
        if res.stdout:
            print(res.stdout.strip())
        return True
    except subprocess.CalledProcessError as e:
        if e.stdout:
            print(e.stdout.strip())
        if e.stderr:
            print(e.stderr.strip(), file=sys.stderr)
        return False
    except FileNotFoundError:
        print("Error: Git was not found in PATH. Please install Git to continue.", file=sys.stderr)
        return False


def main():
    repo_root = Path(__file__).resolve().parent
    print("=" * 55)
    print("   Force Sync Git (Download) - TSGouveia/Behavior  ")
    print("=" * 55)

    print("\n[1/2] Fetching the latest updates from GitHub (git fetch origin)...")
    fetch_ok = run_cmd(["git", "-C", str(repo_root), "fetch", "origin"])

    if not fetch_ok:
        print("\n[ERROR] Unable to connect to GitHub to check for updates.")
        sys.exit(1)

    print("\n[2/2] Forcing local repository to match GitHub (git reset --hard origin/main)...")
    reset_ok = run_cmd(["git", "-C", str(repo_root), "reset", "--hard", "origin/main"])

    if reset_ok:
        print("\n[OK] Local repository successfully synchronized and up to date with GitHub!")
    else:
        print("\n[WARNING] An issue occurred while updating files.")
        sys.exit(1)


if __name__ == "__main__":
    main()
