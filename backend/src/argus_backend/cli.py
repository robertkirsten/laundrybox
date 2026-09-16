from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import uvicorn

from .backup import backup_database
from .config import Settings
from .database import create_database_engine, create_schema, create_session_factory
from .repository import Repository


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="argus-backend")
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings()
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
