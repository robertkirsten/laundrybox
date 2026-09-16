from __future__ import annotations

from pathlib import Path

import pytest

from argus_backend.config import Settings
from argus_backend.repository import Repository, RepositoryError


def test_mock_fixture_csv_is_validated(settings: Settings, repository: Repository) -> None:
    fixtures = repository._load_mock_fixtures()  # type: ignore[attr-defined]
    assert len(fixtures) == 3
    assert fixtures[0].epc == "E28011052000773410000001"
    assert fixtures[0].reference_weight_g == 240.0


def test_invalid_mock_fixture_csv_fails_closed(
    tmp_path: Path, settings: Settings, repository: Repository
) -> None:
    invalid_csv = tmp_path / "invalid.csv"
    invalid_csv.write_text("epc,chute_number\nNOT-HEX,0\n", encoding="utf-8")
    invalid_settings = settings.model_copy(update={"mock_data_path": invalid_csv})
    invalid_repository = Repository(repository._factory, invalid_settings)  # type: ignore[attr-defined]

    with pytest.raises(RepositoryError, match="invalid mock garment CSV"):
        invalid_repository.seed_mock_data()
