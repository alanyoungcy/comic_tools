from __future__ import annotations

import argparse
from pathlib import Path

from comicpublish.pipeline import generate_comic_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comicpublish",
        description="Generate a comic project bundle and zip it for download.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Generate a comic bundle.")
    generate.add_argument("--title", required=True, help="Comic title.")
    generate.add_argument("--premise", required=True, help="One-line story premise.")
    generate.add_argument("--genre", default="science fantasy", help="Comic genre/style.")
    generate.add_argument("--pages", type=int, default=4, help="Number of pages to scaffold.")
    generate.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build"),
        help="Directory where output files are written.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "generate":
        root = generate_comic_bundle(
            title=args.title,
            premise=args.premise,
            genre=args.genre,
            pages=args.pages,
            output_dir=args.output_dir,
        )
        print(f"Comic bundle written to: {root}")
        print(f"Download archive: {root / 'download' / (root.name + '.zip')}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2

