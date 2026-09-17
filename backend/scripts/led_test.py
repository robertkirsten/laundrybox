#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from argus_backend.cli import led_test
from argus_backend.config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chase exactly one red or green pixel at a time across the ARGUS strip."
    )
    parser.add_argument("--env-file", type=Path, help="ARGUS environment file")
    parser.add_argument("--delay", type=float, default=0.08, help="seconds per pixel")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--color", choices=("red", "green", "both"), default="both")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings(_env_file=args.env_file) if args.env_file else Settings()
    led_test(settings, delay_s=args.delay, cycles=args.cycles, color_name=args.color)


if __name__ == "__main__":
    main()
