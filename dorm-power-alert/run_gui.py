from __future__ import annotations

import os
import sys
from pathlib import Path

from app.gui.main import main


def _fix_working_directory_for_frozen_app() -> None:
    """Ensure runtime files (.env/gui_profiles.json/logs) are resolved next to the exe."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        os.chdir(exe_dir)


if __name__ == "__main__":
    _fix_working_directory_for_frozen_app()
    main()
