"""Tests for markdown card parsing."""

from pathlib import Path

import pytest

from recall.parser import load_repo


def parse_snippet(tmp_path: Path, snippet: str):
    deck = tmp_path / "Deck.md"
    deck.write_text(snippet, encoding="utf-8")
    return load_repo(tmp_path)


@pytest.mark.parametrize(
    ("snippet", "kinds", "fronts", "backs"),
    [
        (
            "Question\n\n?\n\nAnswer\n",
            ["basic"],
            ["Question"],
            ["Answer"],
        ),
        (
            "Front\n\n??\n\nBack\n",
            ["reverse-fwd", "reverse-rev"],
            ["Front", "Back"],
            ["Back", "Front"],
        ),
        (
            "The capital of ==Australia== is ==Canberra==^[city].\n",
            ["cloze", "cloze"],
            [
                "The capital of ==Australia== is ==Canberra==^[city].",
                "The capital of ==Australia== is ==Canberra==^[city].",
            ],
            [
                "The capital of ==Australia== is ==Canberra==^[city].",
                "The capital of ==Australia== is ==Canberra==^[city].",
            ],
        ),
        (
            "perro:::dog\nCapital of France::Paris\n",
            ["reverse-fwd", "reverse-rev", "single-line"],
            ["perro", "dog", "Capital of France"],
            ["dog", "perro", "Paris"],
        ),
    ],
)
def test_card_types(
    tmp_path: Path,
    snippet: str,
    kinds: list[str],
    fronts: list[str],
    backs: list[str],
) -> None:
    result = parse_snippet(tmp_path, snippet)

    assert [card.kind for card in result.cards] == kinds
    assert [card.front for card in result.cards] == fronts
    assert [card.back for card in result.cards] == backs
    assert result.warnings == []


def test_cloze_metadata_and_whole_text(tmp_path: Path) -> None:
    result = parse_snippet(tmp_path, "One ==first== and ==second==^[hint].\n")

    assert [card.cloze_index for card in result.cards] == [0, 1]
    assert [card.cloze_hint for card in result.cards] == [None, "hint"]
    assert all(card.cloze_text == result.cards[0].cloze_text for card in result.cards)
    assert all(card.raw_text == "One first and second." for card in result.cards)


def test_code_fences_do_not_split_or_create_cards(tmp_path: Path) -> None:
    result = parse_snippet(
        tmp_path,
        """```markdown
---
?
==not a cloze==
::not a card
```

---

Question

?

Answer
""",
    )

    assert len(result.cards) == 1
    assert result.cards[0].front == "Question"
    assert result.cards[0].back == "Answer"
    assert result.warnings == []


def test_inline_code_and_math_do_not_create_syntax(tmp_path: Path) -> None:
    result = parse_snippet(
        tmp_path,
        "`left::ignored` and $a==b$ and left::right\n",
    )

    assert len(result.cards) == 1
    assert result.cards[0].front == "`left::ignored` and $a==b$ and left"
    assert result.cards[0].back == "right"
    assert result.warnings == []


def test_blank_lines_are_kept_inside_card_sides(tmp_path: Path) -> None:
    result = parse_snippet(
        tmp_path,
        """A paragraph

A second paragraph

?

First answer paragraph

Second answer paragraph
""",
    )

    assert result.cards[0].front == "A paragraph\n\nA second paragraph"
    assert result.cards[0].back == "First answer paragraph\n\nSecond answer paragraph"


def test_setext_heading_warns_about_missing_separator_blank_line(
    tmp_path: Path,
) -> None:
    result = parse_snippet(tmp_path, "Question\n---\n?\n\nAnswer\n")

    assert [(warning.line, warning.message) for warning in result.warnings] == [
        (2, "missing blank line before thematic break")
    ]


def test_markers_and_comments(tmp_path: Path) -> None:
    result = parse_snippet(
        tmp_path,
        """one::1 <!-- hide -->
two::2 <!-- id: two -->

---

<!-- hide -->
three::3
""",
    )

    assert [card.front for card in result.cards] == ["one", "two", "three"]
    assert [card.hidden for card in result.cards] == [True, False, True]
    assert [card.pinned_id for card in result.cards] == [None, "two", None]
    assert all("<!--" not in card.front for card in result.cards)


def test_commented_out_cards_and_nested_dot_directories_are_ignored(
    tmp_path: Path,
) -> None:
    (tmp_path / ".recall").mkdir()
    (tmp_path / ".recall" / "hidden.md").write_text("x\n?\ny\n", encoding="utf-8")
    (tmp_path / "comment.md").write_text(
        "<!--\nnot a card\n?\nnot an answer\n-->\n", encoding="utf-8"
    )
    (tmp_path / "visible.md").write_text("x\n?\ny\n", encoding="utf-8")

    result = load_repo(tmp_path)

    assert result.decks == ["visible"]
    assert [(card.file, card.front) for card in result.cards] == [
        (Path("visible.md"), "x")
    ]
    assert result.warnings == []
