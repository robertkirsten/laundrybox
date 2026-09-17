#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from argus_backend.cli import led_test
from argus_backend.config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fill the ARGUS strip with solid red or green."
    )
    parser.add_argument("--env-file", type=Path, help="ARGUS environment file")
    parser.add_argument(
        "--delay", type=float, default=2.0, help="seconds to display each solid color"
    )
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--color", choices=("red", "green", "both"), default="both")
    parser.add_argument(
        "--brightness",
        type=float,
        help="brightness from 0.0 to 1.0; defaults to ARGUS_NEOPIXEL_BRIGHTNESS",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings(_env_file=args.env_file) if args.env_file else Settings()
    try:
        led_test(
            settings,
            delay_s=args.delay,
            cycles=args.cycles,
            color_name=args.color,
            brightness=args.brightness,
        )
    except ModuleNotFoundError as exc:
        if exc.name in {"board", "neopixel_spi"}:
            raise SystemExit(
                "NeoPixel dependencies are missing. From the backend directory run: "
                "python -m pip install -e ."
            ) from None
        raise


if __name__ == "__main__":
    main()
