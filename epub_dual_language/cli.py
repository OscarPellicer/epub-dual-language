from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from .epub_processor import translate_epub
from .openrouter import OpenRouterClient, OpenRouterConfig


DEFAULT_MODEL = "google/gemini-3-flash-preview"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epub-dual-language",
        description="Create a dual-language EPUB using OpenRouter translations.",
    )
    parser.add_argument("input_epub", type=Path, help="Path to the source EPUB.")
    parser.add_argument(
        "target_language",
        help="Output language to pass to the translation prompt, e.g. English or Spanish.",
    )
    parser.add_argument(
        "--source-language",
        help="Optional source language hint to pass to the prompt.",
    )
    parser.add_argument("--output", type=Path, help="Output EPUB path.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model name.")
    parser.add_argument(
        "--chunking",
        choices=("chapters", "tokens"),
        default="tokens",
        help="Chunk by EPUB spine chapters or by estimated token budget.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=6000,
        help="Estimated max input tokens per translation request for token chunking.",
    )
    parser.add_argument(
        "--layout",
        choices=("paragraph", "sentence"),
        default="paragraph",
        help="How to interleave original and translated text.",
    )
    parser.add_argument(
        "--translation-style",
        choices=("italic", "muted", "italic-muted", "plain"),
        default="italic",
        help="Visual style for translated text in the output EPUB.",
    )
    parser.add_argument(
        "--translator-notes",
        action="store_true",
        help="Allow rare bracketed translator notes for important cultural or archaic references.",
    )
    parser.add_argument(
        "--limit-units",
        type=int,
        help="Translate only the first N paragraphs/list items/sentences for testing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write a sample EPUB without calling OpenRouter.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.input_epub.exists():
        parser.error(f"Input EPUB does not exist: {args.input_epub}")

    output_path = args.output or args.input_epub.with_name(
        f"{args.input_epub.stem}.{args.target_language.lower()}.dual.epub"
    )

    client: OpenRouterClient | None = None
    if not args.dry_run:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            parser.error("OPENROUTER_API_KEY is required in .env or the environment.")
        client = OpenRouterClient(OpenRouterConfig(api_key=api_key, model=args.model))

    def translate_batch(texts: list[str]) -> list[str]:
        if client is None:
            return texts
        return client.translate_batch(
            texts,
            target_language=args.target_language,
            source_language=args.source_language,
            translator_notes=args.translator_notes,
        )

    translated_count = translate_epub(
        args.input_epub,
        output_path,
        translate_batch,
        target_language=args.target_language,
        chunking_strategy=args.chunking,
        max_tokens=args.max_tokens,
        layout=args.layout,
        translation_style=args.translation_style,
        limit_units=args.limit_units,
        dry_run=args.dry_run,
    )

    print(f"Wrote {output_path}")
    print(f"Translated units: {translated_count}")
    print(f"Model: {args.model if not args.dry_run else 'dry-run'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
