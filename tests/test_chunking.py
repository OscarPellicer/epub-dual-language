from epub_dual_language.chunking import TextUnit, make_chunks, split_sentences


def test_token_chunking_packs_across_spine_item_boundaries() -> None:
    units = [
        TextUnit("chapter-1", 0, "one two three"),
        TextUnit("chapter-1", 1, "four five six"),
        TextUnit("chapter-2", 0, "seven eight"),
    ]

    chunks = make_chunks(units, strategy="tokens", max_tokens=10)

    assert [chunk.item_id for chunk in chunks] == ["mixed"]
    assert [[unit.item_id for unit in chunk.units] for chunk in chunks] == [
        ["chapter-1", "chapter-1", "chapter-2"]
    ]


def test_chapter_chunking_groups_by_item() -> None:
    units = [
        TextUnit("chapter-1", 0, "one"),
        TextUnit("chapter-1", 1, "two"),
        TextUnit("chapter-2", 0, "three"),
    ]

    chunks = make_chunks(units, strategy="chapters", max_tokens=1)

    assert [len(chunk.units) for chunk in chunks] == [2, 1]


def test_split_sentences() -> None:
    assert split_sentences("Hallo Welt. Wie geht es? Gut!") == [
        "Hallo Welt.",
        "Wie geht es?",
        "Gut!",
    ]
