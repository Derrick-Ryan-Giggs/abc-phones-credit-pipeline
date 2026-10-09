"""docs/data_dictionary.md must describe every column of every staging table, with no placeholder text.

Run:  uv run --extra dev pytest tests/test_data_dictionary.py -q
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import quality_checks as qc  # noqa: E402

DICTIONARY = (ROOT / "docs" / "data_dictionary.md").read_text()
CONTRACTS = [qc.parse_contract(f.read_text()) for f in sorted((ROOT / "sql" / "01_staging").glob("*.sql"))]


def section(table: str) -> str:
    match = re.search(rf"### `{table}`(.*?)(?=\n### |\n## |\Z)", DICTIONARY, re.S)
    assert match, f"{table} has no section in docs/data_dictionary.md"
    return match.group(1)


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c[0])
def test_every_staging_column_is_described_with_the_right_type(contract):
    table, columns = contract
    text = section(table)
    for name, bq_type in columns.items():
        assert re.search(rf"\| `{name}` \| {bq_type} \| [^|]+ \|", text), f"{table}.{name} ({bq_type}) is missing or has the wrong type"


def test_every_other_table_has_a_section():
    for table in ("int_loan_snapshot_features", "fct_loan_snapshot", "mart_portfolio_metrics", "mart_segment_risk", "mart_nps_credit", "load_audit", "dq_results"):
        assert section(table).strip()


def test_no_column_is_left_with_placeholder_text():
    assert "| ? |" not in DICTIONARY
