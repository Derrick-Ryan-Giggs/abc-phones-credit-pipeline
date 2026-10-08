"""PII masking.

* Identifiers are replaced by a keyed hash (HMAC-SHA256, first 20 hex characters). The same key is used on every
  table, so a loan keeps the same masked key everywhere and joins still work. Without the key the hashes cannot be
  recomputed or reversed.
* The key lives only in GCP Secret Manager (a pinned version, see config/settings.yaml). It is never logged,
  written to a file or read from an environment variable.
* Free text is redacted: emails, phone numbers and long digit runs are removed.
"""
from __future__ import annotations

import hashlib
import hmac
import re

import pandas as pd

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?254|\b0)[\s-]?[17]\d{2}[\s-]?\d{3}[\s-]?\d{3}")
LONG_DIGITS = r"\b\d{7,}\b"
KEY_LENGTH = 20


def get_masking_key(cfg: dict) -> bytes:
    """Read the masking key from Secret Manager (pinned version)."""
    from google.cloud import secretmanager

    g = cfg["gcp"]
    name = f"projects/{g['project_id']}/secrets/{g['masking_secret']}/versions/{g['masking_secret_version']}"
    client = secretmanager.SecretManagerServiceClient()
    return client.access_secret_version(request={"name": name}).payload.data


def mask_value(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:KEY_LENGTH]


class Masker:
    """Keyed hash of identifiers. Blank values stay null. Only unique values are hashed."""

    def __init__(self, key: bytes) -> None:
        self._key = key

    def __call__(self, s: pd.Series) -> pd.Series:
        cache = {v: mask_value(self._key, v) for v in s.dropna().astype(str).unique() if v.strip() != ""}
        return s.astype(object).map(cache)


def redact_text(s: pd.Series) -> pd.Series:
    """Remove emails, phone numbers and long digit runs from free text (nulls stay null)."""
    out = s.astype(object)
    out = out.str.replace(EMAIL_RE.pattern, "[email]", regex=True)
    out = out.str.replace(PHONE_RE.pattern, "[phone]", regex=True)
    out = out.str.replace(LONG_DIGITS, "[number]", regex=True)
    return out.astype(object)
