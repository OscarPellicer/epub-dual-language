from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import posixpath
import re
import uuid
import zipfile

from bs4 import BeautifulSoup, Tag
from ebooklib import epub
import ebooklib
from tqdm import tqdm

from .chunking import TextUnit, make_chunks, split_sentences


TRANSLATABLE_TAGS = {"p", "li"}
STYLE_BLOCK = """
.dual-translation {
  margin-top: -0.25em;
}
.dual-style-italic {
  font-style: italic;
}
.dual-style-muted {
  color: #555;
}
.dual-style-italic-muted {
  color: #555;
  font-style: italic;
}
.dual-style-plain {
}
.dual-original-sentence {
  display: inline;
}
.dual-translated-sentence {
  display: inline;
}
""".strip()


TranslateBatch = Callable[[list[str]], list[str]]


def translate_epub(
    input_path: Path,
    output_path: Path,
    translate_batch: TranslateBatch,
    *,
    target_language: str,
    chunking_strategy: str = "tokens",
    max_tokens: int = 1800,
    layout: str = "paragraph",
    translation_style: str = "italic",
    limit_units: int | None = None,
    dry_run: bool = False,
) -> int:
    book = epub.read_epub(str(input_path))
    document_items = list(_spine_documents(book))
    opf_path, zip_base_path = _opf_path_and_base(input_path)

    unit_index: dict[tuple[str, int], Tag] = {}
    units: list[TextUnit] = []
    modified_items: dict[str, BeautifulSoup] = {}

    metadata_replacements: dict[str, BeautifulSoup] = {}
    with zipfile.ZipFile(input_path) as source_epub:
        metadata_replacements[opf_path] = _updated_metadata_soup(
            source_epub,
            opf_path,
            target_language,
        )
        for item in document_items:
            item_zip_path = _zip_item_path(zip_base_path, item.get_name())
            soup = BeautifulSoup(source_epub.read(item_zip_path), "xml")
            item_units = _extract_units(item.get_id(), soup, layout, limit_units, len(units))
            for unit, tag in item_units:
                units.append(unit)
                unit_index[(unit.item_id, unit.unit_id)] = tag
            if item_units:
                modified_items[item_zip_path] = soup
            if limit_units is not None and len(units) >= limit_units:
                break

    chunks = make_chunks(units, chunking_strategy, max_tokens)
    translated_count = 0
    sentence_translations: dict[int, tuple[Tag, list[tuple[str, str]]]] = {}

    progress = tqdm(chunks, desc="Translating chunks", unit="chunk")
    for chunk_number, chunk in enumerate(progress, start=1):
        texts = [unit.text for unit in chunk.units]
        translations = (
            [f"[DRY RUN {chunk_number}.{index}] {text}" for index, text in enumerate(texts, 1)]
            if dry_run
            else translate_batch(texts)
        )
        for unit, translation in zip(chunk.units, translations, strict=True):
            tag = unit_index[(unit.item_id, unit.unit_id)]
            if layout == "sentence":
                tag_key = id(tag)
                if tag_key not in sentence_translations:
                    sentence_translations[tag_key] = (tag, [])
                sentence_translations[tag_key][1].append((unit.text, translation))
            else:
                _insert_paragraph_translation(tag, translation, translation_style)
            translated_count += 1

    for tag, pairs in sentence_translations.values():
        _insert_sentence_translations(tag, pairs, translation_style)

    for soup in modified_items.values():
        _ensure_style(soup)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_epub_with_replacements(
        input_path,
        output_path,
        {**metadata_replacements, **modified_items},
    )
    return translated_count


def _legacy_translate_epub(
    input_path: Path,
    output_path: Path,
    translate_batch: TranslateBatch,
    *,
    chunking_strategy: str = "tokens",
    max_tokens: int = 1800,
    layout: str = "paragraph",
    translation_style: str = "italic",
    limit_units: int | None = None,
    dry_run: bool = False,
) -> int:
    book = epub.read_epub(str(input_path))
    document_items = list(_spine_documents(book))

    unit_index: dict[tuple[str, int], Tag] = {}
    units: list[TextUnit] = []

    for item in document_items:
        soup = BeautifulSoup(item.get_content(), "xml")
        item_units = _extract_units(item.get_id(), soup, layout, limit_units, len(units))
        for unit, tag in item_units:
            units.append(unit)
            unit_index[(unit.item_id, unit.unit_id)] = tag
        item._dual_language_soup = soup  # type: ignore[attr-defined]
        if limit_units is not None and len(units) >= limit_units:
            break

    chunks = make_chunks(units, chunking_strategy, max_tokens)
    translated_count = 0
    sentence_translations: dict[int, tuple[Tag, list[tuple[str, str]]]] = {}

    progress = tqdm(chunks, desc="Translating chunks", unit="chunk")
    for chunk_number, chunk in enumerate(progress, start=1):
        texts = [unit.text for unit in chunk.units]
        translations = (
            [f"[DRY RUN {chunk_number}.{index}] {text}" for index, text in enumerate(texts, 1)]
            if dry_run
            else translate_batch(texts)
        )
        for unit, translation in zip(chunk.units, translations, strict=True):
            tag = unit_index[(unit.item_id, unit.unit_id)]
            if layout == "sentence":
                tag_key = id(tag)
                if tag_key not in sentence_translations:
                    sentence_translations[tag_key] = (tag, [])
                sentence_translations[tag_key][1].append((unit.text, translation))
            else:
                _insert_paragraph_translation(tag, translation, translation_style)
            translated_count += 1

    for tag, pairs in sentence_translations.values():
        _insert_sentence_translations(tag, pairs, translation_style)

    for item in document_items:
        soup = getattr(item, "_dual_language_soup", None)
        if soup is not None:
            _ensure_style(soup)
            item.set_content(str(soup).encode("utf-8"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book)
    return translated_count


def _spine_documents(book: epub.EpubBook):
    item_by_id = {item.get_id(): item for item in book.get_items()}
    for item_ref, _linear in book.spine:
        item = item_by_id.get(item_ref)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
            yield item


def _opf_path_and_base(input_path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(input_path) as source_epub:
        container = BeautifulSoup(source_epub.read("META-INF/container.xml"), "xml")
    rootfile = container.find("rootfile")
    if rootfile is None or not rootfile.get("full-path"):
        raise ValueError("Could not locate EPUB rootfile in META-INF/container.xml.")
    opf_path = rootfile["full-path"]
    return opf_path, posixpath.dirname(opf_path)


def _zip_item_path(zip_base_path: str, item_name: str) -> str:
    return posixpath.normpath(posixpath.join(zip_base_path, item_name))


def _updated_metadata_soup(
    source_epub: zipfile.ZipFile,
    opf_path: str,
    target_language: str,
) -> BeautifulSoup:
    soup = BeautifulSoup(source_epub.read(opf_path), "xml")
    package = soup.find("package")
    metadata = soup.find("metadata")
    title = soup.find("dc:title")
    if title is None:
        title = metadata.find("title") if metadata else None
    if title is None:
        return soup

    original_title = title.get_text(strip=True)
    suffix = f" (Dual {target_language})"
    if f"Dual {target_language}" not in original_title:
        title.clear()
        title.append(f"{original_title}{suffix}")
    _update_title_sort(metadata, suffix)
    _replace_identifiers(soup, package, metadata, original_title, target_language)
    return soup


def _update_title_sort(metadata: Tag | None, suffix: str) -> None:
    if metadata is None:
        return
    for meta in metadata.find_all("meta"):
        name = meta.get("name", "")
        prop = meta.get("property", "")
        if name == "calibre:title_sort" or prop == "calibre:title_sort":
            value = meta.get("content") or meta.get_text(strip=True)
            if suffix not in value:
                if meta.has_attr("content"):
                    meta["content"] = f"{value}{suffix}"
                else:
                    meta.clear()
                    meta.append(f"{value}{suffix}")


def _replace_identifiers(
    soup: BeautifulSoup,
    package: Tag | None,
    metadata: Tag | None,
    original_title: str,
    target_language: str,
) -> None:
    if metadata is None:
        return
    existing_values = [
        identifier.get_text(strip=True)
        for identifier in metadata.find_all("dc:identifier")
        if identifier.get_text(strip=True)
    ]
    fingerprint = "|".join(existing_values) or original_title
    language_slug = _metadata_slug(target_language)
    new_identifier = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"epub-dual-language|{fingerprint}|{language_slug}",
        )
    )

    for identifier in list(metadata.find_all("dc:identifier")):
        identifier.decompose()

    identifier = soup.new_tag("dc:identifier")
    identifier["id"] = "dual-language-identifier"
    identifier["opf:scheme"] = "UUID"
    identifier.string = f"urn:uuid:{new_identifier}"
    metadata.insert(0, identifier)

    source_marker = soup.new_tag("meta")
    source_marker["name"] = "epub-dual-language:edition"
    source_marker["content"] = f"Dual {target_language}"
    identifier.insert_after(source_marker)

    if package is not None:
        package["unique-identifier"] = "dual-language-identifier"


def _metadata_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "target"


def _extract_units(
    item_id: str,
    soup: BeautifulSoup,
    layout: str,
    limit_units: int | None,
    existing_count: int,
) -> list[tuple[TextUnit, Tag]]:
    body = soup.find("body")
    if body is None:
        return []

    pairs: list[tuple[TextUnit, Tag]] = []
    next_unit_id = 0
    for tag in body.find_all(TRANSLATABLE_TAGS):
        if _inside_translatable_parent(tag):
            continue
        visible_text = tag.get_text(" ", strip=True)
        if not visible_text:
            continue
        text = _inner_markup(tag) if layout == "paragraph" else tag.get_text(" ", strip=True)
        text = " ".join(text.split())
        if not text:
            continue

        pieces = split_sentences(text) if layout == "sentence" else [text]
        for piece in pieces:
            if limit_units is not None and existing_count + len(pairs) >= limit_units:
                return pairs
            pairs.append((TextUnit(item_id=item_id, unit_id=next_unit_id, text=piece), tag))
            next_unit_id += 1
    return pairs


def _inside_translatable_parent(tag: Tag) -> bool:
    for parent in tag.parents:
        if not isinstance(parent, Tag) or parent.name == "body":
            return False
        if parent.name in TRANSLATABLE_TAGS:
            return True
    return False


def _insert_paragraph_translation(tag: Tag, translation: str, translation_style: str) -> None:
    translated = tag.__copy__()
    translated.clear()
    translated["class"] = _with_class(
        translated,
        "dual-translation",
        _style_class(translation_style),
    )
    for child in _fragment_children(tag, translation):
        translated.append(child)
    tag.insert_after(translated)


def _insert_sentence_translations(
    tag: Tag,
    pairs: list[tuple[str, str]],
    translation_style: str,
) -> None:
    tag.clear()
    for index, (original, translation) in enumerate(pairs):
        if index:
            tag.append(tag_soup_new_tag(tag, "br", "dual-sentence-break"))
        original_span = tag_soup_new_tag(tag, "span", "dual-original-sentence")
        original_span.string = original
        translated_span = tag_soup_new_tag(tag, "span", "dual-translated-sentence")
        translated_span["class"] = _with_class(
            translated_span,
            "dual-translated-sentence",
            _style_class(translation_style),
        )
        translated_span.string = translation
        tag.append(original_span)
        tag.append(" ")
        tag.append(translated_span)


def tag_soup_new_tag(tag: Tag, name: str, class_name: str) -> Tag:
    soup = tag.find_parent()
    while soup is not None and not isinstance(soup, BeautifulSoup):
        soup = soup.find_parent()
    if soup is None:
        raise ValueError("Could not find document root for tag.")
    new_tag = soup.new_tag(name)
    new_tag["class"] = class_name
    return new_tag


def _inner_markup(tag: Tag) -> str:
    return "".join(str(child) for child in tag.contents)


def _fragment_children(context_tag: Tag, fragment: str) -> list:
    soup = _document_soup(context_tag)
    wrapper = BeautifulSoup(f"<root>{fragment}</root>", "xml")
    root = wrapper.find("root")
    if root is None:
        return [fragment]
    children = []
    for child in list(root.contents):
        parsed = BeautifulSoup(str(child), "xml")
        if parsed.contents:
            children.append(parsed.contents[0])
        else:
            children.append(soup.new_string(str(child)))
    return children


def _document_soup(tag: Tag) -> BeautifulSoup:
    soup = tag.find_parent()
    while soup is not None and not isinstance(soup, BeautifulSoup):
        soup = soup.find_parent()
    if soup is None:
        raise ValueError("Could not find document root for tag.")
    return soup


def _style_class(translation_style: str) -> str:
    return f"dual-style-{translation_style}"


def _with_class(tag: Tag, *class_names: str) -> list[str]:
    existing = tag.get("class", [])
    if isinstance(existing, str):
        existing = [existing]
    return [*existing, *class_names]


def _ensure_style(soup: BeautifulSoup) -> None:
    head = soup.find("head")
    if head is None:
        return
    style = soup.new_tag("style", type="text/css")
    style.string = STYLE_BLOCK
    head.append(style)


def _write_epub_with_replacements(
    input_path: Path,
    output_path: Path,
    replacements: dict[str, BeautifulSoup],
) -> None:
    with zipfile.ZipFile(input_path, "r") as source_epub:
        with zipfile.ZipFile(output_path, "w") as output_epub:
            for info in source_epub.infolist():
                if info.filename in replacements:
                    data = str(replacements[info.filename]).encode("utf-8")
                    output_epub.writestr(info, data)
                else:
                    output_epub.writestr(info, source_epub.read(info.filename))
