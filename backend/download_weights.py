"""
download_weights.py — Render build-time weights downloader.

Downloads Real-ESRGAN model weights from GitHub Releases if not already present.
Run this as part of the Render build command:
    pip install -r requirements.txt && python download_weights.py
"""

import os
import sys
import requests
from pathlib import Path

MODEL_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
MODEL_PATH = WEIGHTS_DIR / "RealESRGAN_x4plus.pth"

CHUNK_SIZE = 8192  # 8 KB chunks for streaming download


def download_weights():
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)

    if MODEL_PATH.exists():
        size_mb = MODEL_PATH.stat().st_size / (1024 * 1024)
        print(f"[weights] Model already present: {MODEL_PATH} ({size_mb:.1f} MB) — skipping download.")
        return

    print(f"[weights] Downloading Real-ESRGAN weights from:\n  {MODEL_URL}")
    print(f"[weights] Destination: {MODEL_PATH}")

    try:
        response = requests.get(MODEL_URL, stream=True, timeout=300)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(MODEL_PATH, "wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        pct = downloaded / total_size * 100
                        mb = downloaded / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)
                        # Print progress every ~10 MB
                        if downloaded % (10 * 1024 * 1024) < CHUNK_SIZE:
                            print(f"[weights]   {mb:.1f} / {total_mb:.1f} MB ({pct:.1f}%)")

        final_size = MODEL_PATH.stat().st_size / (1024 * 1024)
        print(f"[weights] Download complete: {final_size:.1f} MB saved to {MODEL_PATH}")

    except requests.RequestException as e:
        # Remove partial file on failure
        if MODEL_PATH.exists():
            MODEL_PATH.unlink()
        print(f"[weights] ERROR: Failed to download model weights: {e}", file=sys.stderr)
        print("[weights] The backend will fall back to Lanczos high-fidelity upscaling.", file=sys.stderr)
        # Exit 0 so Render build still succeeds — fallback engine handles the missing model gracefully
        sys.exit(0)


if __name__ == "__main__":
    download_weights()
