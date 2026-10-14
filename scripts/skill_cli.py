#!/usr/bin/env python3
"""Shared executable entrypoint for all eight repository skills."""

import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
python = root / ".venv" / "bin" / "python"
os.execv(
    str(python if python.exists() else Path(sys.executable)),
    [
        str(python if python.exists() else Path(sys.executable)),
        "-m",
        "career_ops",
        "--workspace",
        str(root),
        *sys.argv[1:],
    ],
)
