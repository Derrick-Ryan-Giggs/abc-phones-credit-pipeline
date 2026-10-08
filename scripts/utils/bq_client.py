"""Google Cloud helpers: BigQuery client, SQL placeholder rendering, and idempotent uploads to Cloud Storage.

SQL files use placeholders that are filled in here and nowhere else in new code:
    {{STG}}        the staging dataset         {{MARTS}}      the marts dataset
    {{PARTITION}}  partition and cluster clause for the big fact tables
"""
from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path

from utils.config import dataset_ref

LOG = logging.getLogger("bq_client")
PARTITION_CLAUSE = "PARTITION BY snapshot_date CLUSTER BY loan_key"
RAW_SUFFIXES = (".csv", ".xlsx")


def render_sql(sql: str, cfg: dict, partition: bool = True) -> str:
    out = sql.replace("{{STG}}", dataset_ref(cfg, "staging")).replace("{{MARTS}}", dataset_ref(cfg, "marts"))
    return out.replace("{{PARTITION}}", PARTITION_CLAUSE if partition else "")


def get_bigquery_client(cfg: dict):
    from google.cloud import bigquery

    return bigquery.Client(project=cfg["gcp"]["project_id"], location=cfg["bigquery"]["location"])


def ensure_dataset(client, cfg: dict, layer: str) -> None:
    """Create the dataset if it is missing. An empty dataset costs nothing."""
    from google.cloud import bigquery

    dataset = bigquery.Dataset(f"{cfg['gcp']['project_id']}.{cfg['bigquery'][f'dataset_{layer}']}")
    dataset.location = cfg["bigquery"]["location"]
    client.create_dataset(dataset, exists_ok=True)


def run_sql_file(client, path: Path, cfg: dict, dry_run: bool = False):
    """Render and run one SQL file. With dry_run the query is only validated."""
    from google.cloud import bigquery

    job = client.query(render_sql(path.read_text(), cfg), job_config=bigquery.QueryJobConfig(dry_run=dry_run, use_query_cache=False))
    if not dry_run:
        job.result()
    return job


# ---- Cloud Storage ---------------------------------------------------------
def md5_base64(path: Path) -> str:
    """MD5 of a local file in the same base64 form Cloud Storage reports."""
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()


def upload_if_changed(bucket, local_path: Path, dest_name: str) -> str:
    """Upload a file unless an identical copy is already there. Returns 'uploaded' or 'unchanged'."""
    blob = bucket.blob(dest_name)
    if blob.exists():
        blob.reload()
        if blob.md5_hash == md5_base64(local_path):
            return "unchanged"
    blob.upload_from_filename(str(local_path))
    return "uploaded"


def upload_raw_files(bucket, raw_dir: Path, prefix: str) -> list[tuple[str, str]]:
    """Upload every raw CSV and xlsx file under `prefix` (e.g. raw/ingest_date=2026-10-07). Raw files are only read."""
    files = sorted(p for p in Path(raw_dir).iterdir() if p.is_file() and p.suffix.lower() in RAW_SUFFIXES and not p.name.startswith("~$"))
    results = []
    for f in files:
        status = upload_if_changed(bucket, f, f"{prefix}/{f.name}")
        LOG.info("%-45s %s", f.name, status)
        results.append((f.name, status))
    return results
