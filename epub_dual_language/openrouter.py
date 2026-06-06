from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str
    app_name: str = "epub-dual-language"
    site_url: str = "http://localhost"
    timeout_seconds: int = 120
    retries: int = 3


class OpenRouterClient:
    def __init__(self, config: OpenRouterConfig) -> None:
        self.config = config

    def translate_batch(
        self,
        texts: list[str],
        target_language: str,
        source_language: str | None = None,
        translator_notes: bool = False,
    ) -> list[str]:
        if not texts:
            return []

        payload = self._build_payload(
            texts,
            target_language,
            source_language,
            translator_notes,
        )
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.config.site_url,
            "X-Title": self.config.app_name,
        }

        last_error: Exception | None = None
        for attempt in range(1, self.config.retries + 1):
            try:
                response = requests.post(
                    OPENROUTER_URL,
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                translations = parse_translation_response(content)
                if len(translations) != len(texts):
                    raise ValueError(
                        f"Model returned {len(translations)} translations for {len(texts)} inputs."
                    )
                return translations
            except Exception as exc:  # noqa: BLE001 - retry and re-raise with context.
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(2**attempt)

        raise RuntimeError("OpenRouter translation failed after retries.") from last_error

    def _build_payload(
        self,
        texts: list[str],
        target_language: str,
        source_language: str | None,
        translator_notes: bool,
    ) -> dict:
        source = source_language or "the source language"
        note_instruction = (
            "You may add very short translator notes in square brackets, but only for "
            "truly important archaic, culturally specific, historical, or otherwise "
            "hard-to-translate references. Do not explain ordinary sentences, jokes, "
            "or every line. Most translations should have no note."
            if translator_notes
            else "Do not add translator notes or commentary."
        )
        system = (
            "You are a careful literary translator. Preserve meaning, tone, paragraph "
            "boundaries, names, punctuation intent, and inline XHTML tags and attributes "
            "when they appear in the input. Return only valid JSON with a top-level key "
            "named translations."
        )
        user = {
            "source_language": source,
            "target_language": target_language,
            "instructions": (
                "Translate each string independently. Keep the array length and order "
                "exactly the same as the input. Inputs may be XHTML fragments; translate "
                "only human-readable text and preserve the fragment structure. "
                f"{note_instruction}"
            ),
            "texts": texts,
        }
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }


def parse_translation_response(content: str) -> list[str]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

    data = json.loads(cleaned)
    translations = data.get("translations")
    if not isinstance(translations, list) or not all(
        isinstance(item, str) for item in translations
    ):
        raise ValueError("Translation response must contain a string array named translations.")
    return translations
