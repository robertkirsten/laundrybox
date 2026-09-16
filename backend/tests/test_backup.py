from __future__ import annotations

import sqlite3
from pathlib import Path

from argus_backend.backup import backup_database
from argus_backend.config import Settings
from argus_backend.repository import Repository


def test_backup_is_consistent_and_readable(
    tmp_path: Path, settings: Settings, repository: Repository
) -> None:
    destination = tmp_path / "backups"
    backup = backup_database(settings.database_url, destination)
    assert backup.is_file()

    connection = sqlite3.connect(backup)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT COUNT(*) FROM garments").fetchone() == (3,)
    finally:
        connection.close()
