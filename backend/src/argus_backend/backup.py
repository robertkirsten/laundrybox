from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def sqlite_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url.endswith(":memory:"):
        raise ValueError("database backup requires a file-backed SQLite URL")
    return Path(database_url.removeprefix(prefix)).expanduser().resolve()


def backup_database(database_url: str, destination: Path, keep: int = 14) -> Path:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    source_path = sqlite_path(database_url)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target_path = destination / f"argus-{timestamp}.sqlite3"
    temporary_path = destination / f".{target_path.name}.tmp"

    source = sqlite3.connect(source_path)
    target = sqlite3.connect(temporary_path)
    try:
        source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimeError(f"backup integrity check failed: {integrity!r}")
    finally:
        target.close()
        source.close()

    temporary_path.replace(target_path)
    backups = sorted(destination.glob("argus-*.sqlite3"), reverse=True)
    for expired in backups[keep:]:
        expired.unlink()
    return target_path
