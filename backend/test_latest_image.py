from __future__ import annotations

import json
import sys
from pathlib import Path

import server


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "premeal"
    if mode not in {"premeal", "frame"}:
        raise SystemExit("Usage: python test_latest_image.py [premeal|frame]")

    images = sorted(Path(server.UPLOAD_DIR).glob("*.jpg"), key=lambda path: path.stat().st_mtime)
    if not images:
        raise SystemExit(f"No jpg images found in {server.UPLOAD_DIR}")

    meal = {"frames": []}
    result = server.analyze_image(images[-1], mode, meal)
    print(f"Image: {images[-1].name}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
