"""Tests for stable card identity."""

from pathlib import Path

from recall.parser import load_repo


def parse_snippet(tmp_path: Path, snippet: str):
    (tmp_path / "Deck.md").write_text(snippet, encoding="utf-8")
    return load_repo(tmp_path)


def test_golden_ids_and_sibling_keys(tmp_path: Path) -> None:
    result = parse_snippet(
        tmp_path,
        """Question

?

Answer

---

la casa
??
the house

---

The capital of ==Australia== is ==Canberra==^[city].
""",
    )

    assert [card.id for card in result.cards] == [
        "289aff12b042",
        "b18f7dad4563:fwd",
        "b18f7dad4563:rev",
        "9bbfb12b3298:c1ef40ce",
        "9bbfb12b3298:b36f06be",
    ]
    assert [card.sibling_key for card in result.cards] == [
        "289aff12b042",
        "b18f7dad4563",
        "b18f7dad4563",
        "9bbfb12b3298",
        "9bbfb12b3298",
    ]


def test_front_whitespace_and_back_edits_keep_id(tmp_path: Path) -> None:
    deck = tmp_path / "Deck.md"
    deck.write_text("The question\n?\nThe first answer\n", encoding="utf-8")
    original = load_repo(tmp_path).cards[0].id

    deck.write_text("  The   question  \n?\nA changed answer\n", encoding="utf-8")

    assert load_repo(tmp_path).cards[0].id == original


def test_front_edit_and_move_change_only_when_expected(tmp_path: Path) -> None:
    deck = tmp_path / "Deck.md"
    deck.write_text("The question\n?\nThe answer\n", encoding="utf-8")
    original = load_repo(tmp_path).cards[0].id

    deck.rename(tmp_path / "Nested.md")
    assert load_repo(tmp_path).cards[0].id == original

    (tmp_path / "Nested.md").write_text(
        "A new question\n?\nThe answer\n", encoding="utf-8"
    )
    assert load_repo(tmp_path).cards[0].id != original


def test_pinned_id_replaces_base_but_keeps_kind_suffix(tmp_path: Path) -> None:
    result = parse_snippet(tmp_path, "Front\n??\nBack\n<!-- id: my-card -->\n")

    assert [card.id for card in result.cards] == ["my-card:fwd", "my-card:rev"]
    assert [card.sibling_key for card in result.cards] == ["my-card", "my-card"]
    assert result.warnings == []


def test_invalid_pinned_id_skips_card(tmp_path: Path) -> None:
    result = parse_snippet(tmp_path, "Front\n?\nBack\n<!-- id: not valid -->\n")

    assert result.cards == []
    assert len(result.warnings) == 1
    assert "invalid pinned ID" in result.warnings[0].message


def test_cloze_ids_follow_deleted_text_not_position(tmp_path: Path) -> None:
    deck = tmp_path / "Deck.md"
    deck.write_text("The ==quick== brown ==fox==.\n", encoding="utf-8")
    original = load_repo(tmp_path)
    ids_by_text = {card.cloze_deleted: card.id for card in original.cards}

    deck.write_text("The ==quick== ==brown== fox.\n", encoding="utf-8")
    updated = load_repo(tmp_path)

    assert updated.cards[0].cloze_deleted == "quick"
    assert updated.cards[0].id == ids_by_text["quick"]
    assert updated.cards[1].cloze_deleted == "brown"
    assert updated.cards[1].id != ids_by_text["fox"]


def test_duplicate_ids_are_skipped_with_all_locations(tmp_path: Path) -> None:
    (tmp_path / "A.md").write_text("Same\n?\nOne\n", encoding="utf-8")
    (tmp_path / "B.md").write_text("Same\n?\nTwo\n", encoding="utf-8")

    result = load_repo(tmp_path)

    assert result.cards == []
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.file == Path("A.md")
    assert "A.md:2" in warning.message
    assert "B.md:2" in warning.message


def test_identical_cloze_deletions_are_duplicates(tmp_path: Path) -> None:
    result = parse_snippet(tmp_path, "==same== and ==same==\n")

    assert result.cards == []
    assert len(result.warnings) == 1
    assert "duplicate card ID" in result.warnings[0].message
