"""Settings loader.

All non-secret settings live in config/settings.yaml. Secrets (the masking key) are never stored in files or
environment variables: they are read from GCP Secret Manager (see utils/masking.py).
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "settings.yaml"

REQUIRED = {
    "gcp": ["project_id", "region", "raw_bucket", "masking_secret", "masking_secret_version"],
    "bigquery": ["dataset_staging", "dataset_marts", "location"],
    "snapshots": ["expected_dates"],
}


def load_config(path: Path | str | None = None) -> dict:
    """Read settings.yaml and fail early, with a clear message, if a required setting is missing."""
    path = Path(path) if path else DEFAULT_CONFIG
    cfg = yaml.safe_load(path.read_text()) or {}
    missing = [f"{section}.{key}" for section, keys in REQUIRED.items() for key in keys if key not in (cfg.get(section) or {})]
    if missing:
        raise ValueError(f"{path} is missing required settings: {', '.join(missing)}")
    return cfg


def dataset_id(cfg: dict, layer: str) -> str:
    """Fully qualified dataset id for a layer ('staging' or 'marts'), e.g. my-project.abc_staging."""
    return f"{cfg['gcp']['project_id']}.{cfg['bigquery'][f'dataset_{layer}']}"


def dataset_ref(cfg: dict, layer: str) -> str:
    """The same id wrapped in backticks, ready to drop into SQL (project ids contain dashes)."""
    return f"`{dataset_id(cfg, layer)}`"
