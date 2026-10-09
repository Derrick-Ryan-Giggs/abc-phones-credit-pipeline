"""Unit tests for scripts/utils: masking, redaction, settings and the Cloud Storage upload helper.

Run:  uv run --extra dev pytest tests/test_masking.py -q
"""
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from utils import bq_client, config, masking  # noqa: E402

CFG = {"gcp": {"project_id": "my-proj", "region": "us-central1", "raw_bucket": "b", "masking_secret": "masking-key", "masking_secret_version": "1"},
       "bigquery": {"dataset_staging": "stg", "dataset_marts": "marts", "location": "us-central1"}, "snapshots": {"expected_dates": ["2025-01-01"]}}


def test_masking_is_stable_keyed_and_fixed_length():
    ids = pd.Series(["recA", "recB", "recA"])
    a, b = masking.Masker(b"key-one")(ids), masking.Masker(b"key-two")(ids)
    assert a[0] == a[2] and a[0] != a[1]                      # same id, same hash
    assert a[0] != b[0]                                        # a different key gives different hashes
    assert all(len(v) == masking.KEY_LENGTH and set(v) <= set("0123456789abcdef") for v in a)
    assert "recA" not in "".join(a)


def test_blank_and_missing_identifiers_stay_null():
    out = masking.Masker(b"k")(pd.Series(["recA", "", None, "  "]))
    assert out.notna().tolist() == [True, False, False, False]


def test_redact_text_removes_emails_phones_and_long_numbers():
    s = pd.Series(["call me on 0712 345 678 or +254 722 111 222", "write to jane.doe@example.com", "id 12345678 here", "all good", None])
    out = masking.redact_text(s)
    assert out[0] == "call me on [phone] or [phone]" and out[1] == "write to [email]"
    assert out[2] == "id [number] here" and out[3] == "all good" and pd.isna(out[4])


def test_masking_key_is_read_from_secret_manager_with_the_pinned_version(monkeypatch):
    seen = {}

    class FakeClient:
        def access_secret_version(self, request):
            seen["name"] = request["name"]
            return types.SimpleNamespace(payload=types.SimpleNamespace(data=b"secret-bytes"))

    fake_sm = types.SimpleNamespace(SecretManagerServiceClient=FakeClient)
    fake_cloud = types.ModuleType("google.cloud")
    fake_cloud.secretmanager = fake_sm
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", fake_sm)
    assert masking.get_masking_key(CFG) == b"secret-bytes"
    assert seen["name"] == "projects/my-proj/secrets/masking-key/versions/1"


def test_config_reports_missing_settings(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("gcp:\n  project_id: x\n")
    with pytest.raises(ValueError, match="gcp.region"):
        config.load_config(f)
    assert config.dataset_ref(CFG, "marts") == "`my-proj.marts`"


def test_render_sql_fills_every_placeholder():
    sql = "CREATE TABLE {{MARTS}}.t {{PARTITION}} AS SELECT * FROM {{STG}}.s"
    out = bq_client.render_sql(sql, CFG)
    assert "{{" not in out and "`my-proj.marts`.t PARTITION BY snapshot_date CLUSTER BY loan_key" in out
    assert "PARTITION" not in bq_client.render_sql(sql, CFG, partition=False)


class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.md5_hash = store.get(name)

    def exists(self):
        return self.name in self.store

    def reload(self):
        self.md5_hash = self.store[self.name]

    def upload_from_filename(self, path):
        self.store[self.name] = bq_client.md5_base64(Path(path))


class FakeBucket:
    def __init__(self):
        self.store = {}

    def blob(self, name):
        return FakeBlob(self.store, name)


def test_upload_is_idempotent_and_detects_changes(tmp_path):
    (tmp_path / "a.csv").write_text("x,y\n1,2\n")
    (tmp_path / "b.xlsx").write_bytes(b"binary")
    (tmp_path / "notes.txt").write_text("ignored")
    (tmp_path / "~$lock.xlsx").write_bytes(b"temp")
    bucket = FakeBucket()
    first = bq_client.upload_raw_files(bucket, tmp_path, "raw/ingest_date=2026-10-07")
    assert first == [("a.csv", "uploaded"), ("b.xlsx", "uploaded")]
    assert bq_client.upload_raw_files(bucket, tmp_path, "raw/ingest_date=2026-10-07") == [("a.csv", "unchanged"), ("b.xlsx", "unchanged")]
    (tmp_path / "a.csv").write_text("x,y\n1,3\n")
    assert bq_client.upload_raw_files(bucket, tmp_path, "raw/ingest_date=2026-10-07")[0] == ("a.csv", "uploaded")
