from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re


TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
SENTENCE_RE = re.compile(r"(?<=[.!?;:])\s+(?=[A-ZÄÖÜÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛ0-9\"'“„])")


@dataclass(frozen=True)
class TextUnit:
    item_id: str
    unit_id: int
    text: str


@dataclass(frozen=True)
class TranslationChunk:
    item_id: str
    units: list[TextUnit]


def estimate_tokens(text: str) -> int:
    return max(1, len(TOKEN_RE.findall(text)))


def split_sentences(text: str) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    return [part.strip() for part in SENTENCE_RE.split(text) if part.strip()]


def make_chunks(
    units: Iterable[TextUnit],
    strategy: str,
    max_tokens: int,
) -> list[TranslationChunk]:
    units_by_item: dict[str, list[TextUnit]] = {}
    for unit in units:
        units_by_item.setdefault(unit.item_id, []).append(unit)

    if strategy == "chapters":
        units_by_item: dict[str, list[TextUnit]] = {}
        for unit in units:
            units_by_item.setdefault(unit.item_id, []).append(unit)
        return [
            TranslationChunk(item_id=item_id, units=item_units)
            for item_id, item_units in units_by_item.items()
            if item_units
        ]

    chunks: list[TranslationChunk] = []
    current: list[TextUnit] = []
    current_tokens = 0
    for unit in units:
        unit_tokens = estimate_tokens(unit.text)
        if current and current_tokens + unit_tokens > max_tokens:
            chunks.append(TranslationChunk(item_id=_chunk_item_id(current), units=current))
            current = []
            current_tokens = 0
        current.append(unit)
        current_tokens += unit_tokens
    if current:
        chunks.append(TranslationChunk(item_id=_chunk_item_id(current), units=current))
    return chunks


def _chunk_item_id(units: list[TextUnit]) -> str:
    item_ids = {unit.item_id for unit in units}
    if len(item_ids) == 1:
        return units[0].item_id
    return "mixed"
