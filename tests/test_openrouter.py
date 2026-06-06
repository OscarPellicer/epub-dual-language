from epub_dual_language.openrouter import OpenRouterClient, OpenRouterConfig, parse_translation_response


def test_parse_translation_response() -> None:
    content = '{"translations": ["Hello", "World"]}'

    assert parse_translation_response(content) == ["Hello", "World"]


def test_parse_translation_response_from_fenced_json() -> None:
    content = '```json\n{"translations": ["Hallo"]}\n```'

    assert parse_translation_response(content) == ["Hallo"]


def test_translator_notes_prompt_is_sparse() -> None:
    client = OpenRouterClient(OpenRouterConfig(api_key="test", model="test-model"))

    payload = client._build_payload(  # noqa: SLF001 - prompt contract test.
        ["Grüß Gott"],
        "English",
        "German",
        translator_notes=True,
    )

    instructions = payload["messages"][1]["content"]
    assert "square brackets" in instructions
    assert "truly important" in instructions
    assert "Most translations should have no note" in instructions
