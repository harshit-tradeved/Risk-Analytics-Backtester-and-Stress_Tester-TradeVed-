"""
One-time setup: clones the Kronos repo and installs all dependencies.
Run once before starting the service:
    python setup.py
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def run(cmd: list[str], **kwargs):
    print(f">>> {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def main():
    kronos_dir = HERE / "Kronos"

    # 1. Clone Kronos repo if not present
    if not kronos_dir.exists():
        print("\n[1/3] Cloning Kronos repo...")
        run(["git", "clone", "https://github.com/shiyu-coder/Kronos", str(kronos_dir)])
    else:
        print("[1/3] Kronos repo already cloned — pulling latest...")
        run(["git", "-C", str(kronos_dir), "pull"])

    # 2. Install Kronos deps
    print("\n[2/3] Installing Kronos dependencies...")
    run([sys.executable, "-m", "pip", "install", "-r", str(kronos_dir / "requirements.txt")])

    # 3. Install service deps
    print("\n[3/3] Installing service dependencies...")
    run([sys.executable, "-m", "pip", "install", "-r", str(HERE / "requirements.txt")])

    print("\nSetup complete. Start the service with:")
    print("  uvicorn main:app --port 8001")
    print("\nThen in your backtester terminal:")
    print("  set KRONOS_URL=http://localhost:8001   (Windows)")
    print("  export KRONOS_URL=http://localhost:8001  (Linux/Mac)")


if __name__ == "__main__":
    main()
