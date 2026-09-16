from __future__ import annotations

from pathlib import Path

import pytest

from argus_backend.config import Settings
from argus_backend.database import create_database_engine, create_schema, create_session_factory
from argus_backend.repository import Repository


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'argus-test.sqlite3'}",
        serial_enabled=False,
        enable_debug_ingest=True,
        stability_window_size=3,
        removal_confirm_samples=2,
        minimum_tag_reads=2,
        acquisition_timeout_s=1.0,
        monitor_interval_s=0.01,
    )


@pytest.fixture
def repository(settings: Settings) -> Repository:
    engine = create_database_engine(settings.database_url)
    create_schema(engine)
    factory = create_session_factory(engine)
    repo = Repository(factory, settings)
    repo.seed_mock_data()
    try:
        yield repo
    finally:
        engine.dispose()
