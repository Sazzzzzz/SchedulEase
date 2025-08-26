#!/usr/bin/env python3
"""
Launcher for SchedulEase executable. Used as Nuitka build entrance only.
Patches runtime paths for onefile and delegates to python.main:main.
"""

# Build command
# nuitka --standalone --onefile --output-dir=dist --output-filename=schedulease.exe --include-data-file=python/tests/test_data.json=tests/test_data.json --follow-imports --plugin-enable=anti-bloat --msvc=latest python/launcher.py

import os
import sys
from pathlib import Path


def _exe_dir() -> Path:
    # Use sys.argv[0] to get original executable path per Nuitka docs
    return Path(os.path.dirname(os.path.abspath(sys.argv[0])))


def _patch_paths() -> None:
    exe_dir = _exe_dir()

    # Ensure the package root is importable. Our package dir is 'python/'.
    pkg_dir = Path(__file__).parent  # .../python
    workspace_root = pkg_dir.parent  # repo root
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))

    # Patch config constants before importing main
    import python.config as config

    data_path = exe_dir / "data"
    config_path = data_path / "config.toml"

    config.SCRIPT_DIR = exe_dir
    config.DATA_PATH = data_path
    config.CONFIG_PATH = config_path


def main() -> None:
    _patch_paths()
    from python.main import main as run

    run()


if __name__ == "__main__":
    main()
