"""PyInstaller entry point for the pixel-art desktop releases."""

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.__main__ import main


if __name__ == "__main__":
    main()
