from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import TextIO

import serial
import uvicorn

from .backup import backup_database
from .config import Settings
from .database import create_database_engine, create_schema, create_session_factory
from .repository import Repository, ScanLogEntry


def seed(settings: Settings) -> None:
    engine = create_database_engine(settings.database_url)
    try:
        create_schema(engine)
        Repository(create_session_factory(engine), settings).seed_mock_data()
    finally:
        engine.dispose()


def post_debug_message(endpoint: str, message: object, label: str) -> None:
    body = json.dumps({"message": message}).encode()
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        if response.status >= 300:
            raise RuntimeError(f"replay failed at {label}: HTTP {response.status}")


def replay(path: Path, base_url: str, delay_s: float, hold_s: float) -> None:
    endpoint = f"{base_url.rstrip('/')}/api/v1/debug/reports"
    last_message: object | None = None
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            last_message = json.loads(line)
            post_debug_message(endpoint, last_message, f"line {line_number}")
            time.sleep(delay_s)

    deadline = time.monotonic() + hold_s
    while last_message is not None and time.monotonic() < deadline:
        post_debug_message(endpoint, last_message, "hold")
        time.sleep(min(delay_s, 0.25))


def _format_weight(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} g"


def _scan_values(entry: ScanLogEntry) -> tuple[str, str, str, str]:
    return (
        entry.epc or "—",
        entry.garment_name or ("Unbekannt" if entry.epc else "Nicht erkannt"),
        _format_weight(entry.measured_weight_g),
        _format_weight(entry.reference_weight_g),
    )


def _print_scan_table(entries: list[ScanLogEntry], output: TextIO) -> None:
    rows = [_scan_values(entry) for entry in entries]
    headers = ("EPC", "GARMENT", "IST", "SOLL")
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    formatted_headers = "  ".join(
        header.ljust(widths[index]) for index, header in enumerate(headers)
    )
    print(formatted_headers, file=output)
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)), file=output)
    output.flush()


def scan_log(
    settings: Settings,
    *,
    limit: int,
    follow: bool,
    as_csv: bool,
    poll_interval_s: float = 0.5,
) -> None:
    engine = create_database_engine(settings.database_url)
    try:
        repository = Repository(create_session_factory(engine), settings)
        initial = list(reversed(repository.recent_scan_log(limit)))
        seen = {entry.cycle_id for entry in initial}
        writer = csv.writer(sys.stdout) if as_csv else None
        if writer is not None:
            writer.writerow(("EPC", "GARMENT", "IST", "SOLL"))
            writer.writerows(_scan_values(entry) for entry in initial)
            sys.stdout.flush()
        else:
            _print_scan_table(initial, sys.stdout)

        while follow:
            time.sleep(poll_interval_s)
            new_entries = [
                entry
                for entry in reversed(repository.recent_scan_log(100))
                if entry.cycle_id not in seen
            ]
            if not new_entries:
                continue
            seen.update(entry.cycle_id for entry in new_entries)
            if writer is not None:
                writer.writerows(_scan_values(entry) for entry in new_entries)
            else:
                for entry in new_entries:
                    print("  ".join(_scan_values(entry)))
            sys.stdout.flush()
    finally:
        engine.dispose()


def serial_monitor(settings: Settings, *, seconds: float | None, lines: int | None) -> None:
    path = next((path for path in settings.candidate_serial_ports() if path.exists()), None)
    if path is None:
        candidates = ", ".join(str(path) for path in settings.candidate_serial_ports())
        raise RuntimeError(f"Teensy serial device not found ({candidates})")
    deadline = time.monotonic() + seconds if seconds is not None else None
    emitted = 0
    with serial.Serial(path, settings.serial_baud, timeout=0.5) as device:
        print(f"Reading {path} at {settings.serial_baud} baud; exit with Ctrl+C.", file=sys.stderr)
        while deadline is None or time.monotonic() < deadline:
            raw = device.read_until(b"\n", settings.max_serial_line_bytes + 1)
            if not raw:
                continue
            print(raw.decode(errors="replace").rstrip())
            emitted += 1
            if lines is not None and emitted >= lines:
                break


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="argus-backend")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="load settings from this env file instead of ./.env",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="run the FastAPI service")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")

    subparsers.add_parser("seed", help="create the schema and seed mock records")

    replay_parser = subparsers.add_parser("replay", help="replay JSONL through debug ingest")
    replay_parser.add_argument("path", type=Path)
    replay_parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    replay_parser.add_argument("--delay", type=float, default=0.25)
    replay_parser.add_argument(
        "--hold",
        type=float,
        default=0.0,
        help="keep resending the final report for this many seconds",
    )

    backup_parser = subparsers.add_parser("backup", help="create a verified SQLite backup")
    backup_parser.add_argument("destination", type=Path)
    backup_parser.add_argument("--keep", type=int, default=14)

    scans_parser = subparsers.add_parser(
        "scans", help="show the clean EPC/garment/actual/reference scan log"
    )
    scans_parser.add_argument("--last", type=int, default=20)
    scans_parser.add_argument("--follow", action="store_true")
    scans_parser.add_argument("--csv", action="store_true")

    serial_parser = subparsers.add_parser(
        "serial-monitor", help="print raw Teensy lines; the backend must be stopped first"
    )
    serial_parser.add_argument("--seconds", type=float)
    serial_parser.add_argument("--lines", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings(_env_file=args.env_file) if args.env_file else Settings()
    try:
        if args.command == "serve":
            uvicorn.run(
                "argus_backend.api:app",
                host=args.host,
                port=args.port,
                reload=args.reload,
                log_level=settings.log_level.lower(),
            )
        elif args.command == "seed":
            seed(settings)
        elif args.command == "replay":
            replay(args.path, args.base_url, args.delay, args.hold)
        elif args.command == "backup":
            print(backup_database(settings.database_url, args.destination, args.keep))
        elif args.command == "scans":
            scan_log(settings, limit=args.last, follow=args.follow, as_csv=args.csv)
        elif args.command == "serial-monitor":
            serial_monitor(settings, seconds=args.seconds, lines=args.lines)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
