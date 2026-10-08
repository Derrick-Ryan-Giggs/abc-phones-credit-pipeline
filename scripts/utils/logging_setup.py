"""Logging setup shared by every script: one format, written to the terminal (stderr) and to logs/<name>.log."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMAT = "%(asctime)s %(levelname)s %(message)s"


def setup_logging(name: str, log_dir: Path | str | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure the root logger (replacing earlier handlers) and return a logger called `name`.

    In Cloud Run the stderr stream goes to Cloud Logging, where ERROR lines can trigger an alert.
    """
    log_dir = Path(log_dir) if log_dir else ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=level, format=FORMAT, force=True,
                        handlers=[logging.FileHandler(log_dir / f"{name}.log"), logging.StreamHandler(sys.stderr)])
    return logging.getLogger(name)
