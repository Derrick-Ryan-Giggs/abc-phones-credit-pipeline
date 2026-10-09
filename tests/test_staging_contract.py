"""The schema contracts in sql/01_staging must match what data_cleaning.py really writes.

Needs the staging files from a local run (uv run python scripts/data_cleaning.py --no-load). Skipped if they are not there.
Run:  uv run --extra dev pytest tests/test_staging_contract.py -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import quality_checks as qc  # noqa: E402

pq = pytest.importorskip("pyarrow.parquet")
ARROW_TO_BIGQUERY = {"string": "STRING", "large_string": "STRING", "double": "FLOAT64", "int64": "INT64", "bool": "BOOL", "date32[day]": "DATE"}
CONTRACTS = sorted((ROOT / "sql" / "01_staging").glob("*.sql"))


def test_every_staging_table_has_a_contract_file():
    names = {qc.parse_contract(f.read_text())[0] for f in CONTRACTS if qc.parse_contract(f.read_text())}
    assert names == set(qc.PII_STAGING_TABLES)


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda p: p.stem)
def test_contract_matches_the_staging_file(contract):
    parsed = qc.parse_contract(contract.read_text())
    assert parsed is not None, f"{contract.name} has no CREATE TABLE contract"
    table, expected = parsed
    staged = ROOT / "data" / "staging" / f"{table}.parquet"
    if not staged.exists():
        pytest.skip("run scripts/data_cleaning.py --no-load first")
    schema = pq.read_schema(staged)
    actual = {n: ARROW_TO_BIGQUERY[str(schema.field(n).type)] for n in schema.names}
    assert actual == expected, f"{table}: {set(actual.items()) ^ set(expected.items())}"
