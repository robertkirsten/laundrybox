from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
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
    mock_data_path: Path | None = None

    serial_enabled: bool = True
    serial_port: Path = Path("/dev/argus-teensy")
    serial_fallback_port: Path = Path("/dev/ttyACM0")
    serial_baud: int = Field(default=115_200, gt=0)
    serial_read_timeout_s: float = Field(default=0.5, gt=0)
    serial_reconnect_s: float = Field(default=1.0, gt=0)
    serial_stale_after_s: float = Field(default=2.0, gt=0)
    max_serial_line_bytes: int = Field(default=4_096, ge=256, le=1_048_576)

    threshold_g: float = Field(default=3.0, ge=0)
    empty_weight_max_g: float = Field(default=10.0, ge=0)
    min_garment_weight_g: float = Field(default=50.0, gt=0)
    max_garment_weight_g: float = Field(default=1_000.0, gt=0)
    stability_tolerance_g: float = Field(default=2.0, ge=0)
    stability_window_size: int = Field(default=3, ge=2, le=1_000)
    removal_confirm_samples: int = Field(default=3, ge=2, le=1_000)
    minimum_tag_reads: int = Field(default=2, ge=1, le=1_000)
    acquisition_timeout_s: float = Field(default=6.0, gt=0)
    inspection_timeout_s: float = Field(default=30.0, gt=0)
    feedback_display_s: float = Field(default=3.0, gt=0)
    monitor_interval_s: float = Field(default=0.25, gt=0)

    neopixel_enabled: bool = False
    neopixel_count: int = Field(default=60, ge=1, le=1_000)
    # The prototype is powered from the Pi's 5 V rail, so cap brightness at
    # 50%. The LED driver separately enforces that no emitted color can
    # energize more than one RGB channel at a time.
    neopixel_brightness: float = Field(default=0.3, ge=0.0, le=0.5)

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

    @model_validator(mode="after")
    def validate_ranges(self) -> Settings:
        if self.empty_weight_max_g >= self.min_garment_weight_g:
            raise ValueError("empty_weight_max_g must be below min_garment_weight_g")
        if self.min_garment_weight_g >= self.max_garment_weight_g:
            raise ValueError("min_garment_weight_g must be below max_garment_weight_g")
        return self
