from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO

from argus_backend.cli import _print_scan_table
from argus_backend.repository import ScanLogEntry


def test_scan_table_contains_only_operator_fields() -> None:
    output = StringIO()
    _print_scan_table(
        [
            ScanLogEntry(
                cycle_id="cycle-1",
                completed_at=datetime(2026, 9, 16, tzinfo=UTC),
                epc="E280689400004031F0E235BE",
                garment_name="Jacke Schwarz",
                measured_weight_g=241.7,
                reference_weight_g=240.0,
            )
        ],
        output,
    )

    rendered = output.getvalue()
    assert "EPC" in rendered
    assert "GARMENT" in rendered
    assert "IST" in rendered
    assert "SOLL" in rendered
    assert "Jacke Schwarz" in rendered
    assert "241.7 g" in rendered
    assert "cycle-1" not in rendered
    assert "2026" not in rendered
