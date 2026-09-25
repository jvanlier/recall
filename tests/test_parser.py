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


def test_double_question_marker_has_priority_over_single_question(
    tmp_path: Path,
) -> None:
    result = parse_snippet(tmp_path, "Front\n?\nMiddle\n??\nBack\n")

    assert [card.kind for card in result.cards] == ["reverse-fwd", "reverse-rev"]
    assert result.cards[0].front == "Front\n?\nMiddle"
    assert result.cards[0].back == "Back"


def test_cloze_syntax_must_be_a_markdown_mark_token(tmp_path: Path) -> None:
    result = parse_snippet(
        tmp_path,
        """===value===

---

==first

second==
""",
    )

    assert result.cards == []
    assert [warning.line for warning in result.warnings] == [1, 5]


def test_cloze_metadata_and_whole_text(tmp_path: Path) -> None:
    result = parse_snippet(tmp_path, "One ==first== and ==second==^[hint].\n")

    assert [card.cloze_index for card in result.cards] == [0, 1]
    assert [card.cloze_hint for card in result.cards] == [None, "hint"]
    assert all(card.cloze_text == result.cards[0].cloze_text for card in result.cards)
    assert all(card.raw_text == "One first and second." for card in result.cards)


def test_mark_inside_link_label_terminates() -> None:
    from recall.markdown import markdown_it

    tokens = markdown_it().parse("==hello==^[hint with ==symbols==]")

    marks = [t for t in tokens[1].children or [] if t.type == "mark_open"]
    assert len(marks) == 2


def test_cloze_hint_containing_mark_warns(tmp_path: Path) -> None:
    result = parse_snippet(tmp_path, "==hello==^[hint with ==symbols==]\n")

    assert result.cards == []
    assert [warning.line for warning in result.warnings] == [1]


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


def test_inline_masking_follows_markdown_paragraphs_and_escaping(
    tmp_path: Path,
) -> None:
    result = parse_snippet(
        tmp_path,
        """\\`escaped::backtick`

`unmatched

question::answer
""",
    )

    assert [card.front for card in result.cards] == [
        "\\`escaped",
        "question",
    ]
    assert [card.back for card in result.cards] == ["backtick`", "answer"]
    assert result.warnings == []


def test_clozes_can_contain_code_and_math_delimiters(tmp_path: Path) -> None:
    result = parse_snippet(
        tmp_path,
        """==a $x==y$ b==

---

==a `x==y` b==
""",
    )

    assert len(result.cards) == 2
    assert [card.raw_text for card in result.cards] == [
        "a $x==y$ b",
        "a `x==y` b",
    ]
    assert result.warnings == []


@pytest.mark.parametrize("blank", ["\n", " \t\n"])
def test_math_masking_stops_at_blank_lines(tmp_path: Path, blank: str) -> None:
    result = parse_snippet(
        tmp_path, f"Price $5\n{blank}question::answer\n{blank}Price $10\n"
    )

    assert [(card.front, card.back) for card in result.cards] == [
        ("question", "answer")
    ]
    assert result.warnings == []


@pytest.mark.parametrize("deletion", ["`code`", "$x$", "`a` $b$"])
def test_clozes_may_contain_only_code_or_math(tmp_path: Path, deletion: str) -> None:
    result = parse_snippet(tmp_path, f"Use =={deletion}== here.\n")

    assert len(result.cards) == 1
    assert result.cards[0].raw_text == f"Use {deletion} here."
    assert result.warnings == []


@pytest.mark.parametrize(
    "snippet",
    [
        "The ==Aus<!-- ignore -->tralia== capital.\n",
        "The ==Aus<!-- == -->tralia== capital.\n",
    ],
)
def test_comments_inside_clozes_are_ignored(tmp_path: Path, snippet: str) -> None:
    result = parse_snippet(tmp_path, snippet)

    assert len(result.cards) == 1
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
