from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARGUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ARGUS backend"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    json_logs: bool = True

    database_url: str = "sqlite:///./var/argus.sqlite3"
    auto_create_schema: bool = True
    seed_mock_data: bool = True

    serial_enabled: bool = True
    serial_port: Path = Path("/dev/argus-teensy")
    serial_fallback_port: Path = Path("/dev/ttyACM0")
    serial_baud: int = 115_200
    serial_read_timeout_s: float = 0.5
    serial_reconnect_s: float = 1.0
    serial_stale_after_s: float = 2.0
    max_serial_line_bytes: int = 4_096

    threshold_g: float = 3.0
    empty_weight_max_g: float = 10.0
    min_garment_weight_g: float = 50.0
    max_garment_weight_g: float = 1_000.0
    stability_tolerance_g: float = 1.0
    stability_window_size: int = 6
    removal_confirm_samples: int = 4
    minimum_tag_reads: int = 2
    acquisition_timeout_s: float = 10.0
    monitor_interval_s: float = 0.25

    station_code: str = "ARGUS-01"
    operator_number: str = "4471"
    algorithm_version: str = "mvp-1"

    enable_debug_ingest: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )

    def candidate_serial_ports(self) -> tuple[Path, ...]:
        if self.serial_port == self.serial_fallback_port:
            return (self.serial_port,)
        return (self.serial_port, self.serial_fallback_port)
