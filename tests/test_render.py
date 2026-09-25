from pathlib import Path

from recall.parser import load_repo
from recall.render import pygments_css, render_card


def parse_snippet(tmp_path: Path, snippet: str, name: str = "Deck.md"):
    deck = tmp_path / name
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text(snippet, encoding="utf-8")
    return load_repo(tmp_path)


def test_basic_card_renders_markdown_and_answer_divider(tmp_path: Path) -> None:
    card = parse_snippet(
        tmp_path,
        "Question with **emphasis**\n?\nAnswer with ~~an old word~~\n",
    ).cards[0]

    rendered = render_card(card)

    assert rendered.front_html == "<p>Question with <strong>emphasis</strong></p>\n"
    assert "<hr>" in rendered.back_html
    assert "<s>an old word</s>" in rendered.back_html


def test_reversible_cards_keep_the_parser_direction(tmp_path: Path) -> None:
    cards = parse_snippet(tmp_path, "front\n??\nback\n").cards

    assert "<p>front</p>" in render_card(cards[0]).front_html
    assert "<p>back</p>" in render_card(cards[1]).front_html


def test_cloze_masks_only_the_selected_deletion(tmp_path: Path) -> None:
    cards = parse_snippet(tmp_path, "The capital of ==Australia== is ==Canberra==^[city].\n").cards

    first = render_card(cards[0])
    second = render_card(cards[1])

    assert '<span class="cloze">[…]</span>' in first.front_html
    assert "is Canberra" in first.front_html
    assert '<mark class="cloze-answer">Australia</mark>' in first.back_html
    assert "city" not in first.back_html
    assert 'Australia is <span class="cloze">[city]</span>' in second.front_html
    assert '<mark class="cloze-answer">Canberra</mark>' in second.back_html


def test_cloze_replacement_is_safe_inside_image_alt_text(tmp_path: Path) -> None:
    cards = parse_snippet(tmp_path, "==![== ==bird== ==](bird.png)==\n").cards

    rendered = render_card(cards[1])

    assert 'alt=" <span' not in rendered.front_html
    assert 'alt=" […] "' in rendered.front_html


def test_cloze_replacement_is_safe_inside_link_labels(tmp_path: Path) -> None:
    card = parse_snippet(tmp_path, "[==hello==](https://example.com)\n").cards[0]

    rendered = render_card(card)

    assert '<a href="https://example.com"><span class="cloze">[…]</span></a>' in rendered.front_html
    assert '<a href="https://example.com"><mark class="cloze-answer">hello</mark></a>' in rendered.back_html


def test_selected_cloze_keeps_reference_definitions(tmp_path: Path) -> None:
    card = parse_snippet(tmp_path, "==[foo][ref]==\n\n[ref]: https://example.com\n").cards[0]

    rendered = render_card(card)

    assert '<a href="https://example.com">foo</a>' in rendered.back_html


def test_math_tables_strikethrough_and_code_are_rendered(tmp_path: Path) -> None:
    card = parse_snippet(
        tmp_path,
        """Price is $a_1 * b_1$
?

| a | b |
|---|---|
| 1 | 2 |

```python
print(1 + 2)
```
~~old~~
""",
    ).cards[0]

    rendered = render_card(card)

    assert '<span class="math inline">a_1 * b_1</span>' in rendered.back_html
    assert "<em>" not in rendered.back_html
    assert "<table>" in rendered.back_html
    assert "<s>old</s>" in rendered.back_html
    assert '<span class="nb">print</span>' in rendered.back_html


def test_images_are_rewritten_and_invalid_paths_are_visible(tmp_path: Path) -> None:
    result = parse_snippet(
        tmp_path,
        """nested question
?
![safe](../images/blue%20flower.svg)
![outside](../../secret.png)
![hidden](../.git/config.png)
""",
        "nested/Deck.md",
    )

    rendered = render_card(result.cards[0])

    assert 'src="/media/images/blue%20flower.svg"' in rendered.back_html
    assert 'src="/media/../' not in rendered.back_html
    assert rendered.back_html.count('class="invalid-image"') == 2
    assert "outside" in rendered.back_html
    assert "hidden" in rendered.back_html


def test_encoded_absolute_image_paths_are_rejected(tmp_path: Path) -> None:
    card = parse_snippet(tmp_path, "question\n?\n![secret](%2Fetc/passwd)\n").cards[0]

    rendered = render_card(card)

    assert 'class="invalid-image"' in rendered.back_html
    assert "/media/" not in rendered.back_html


def test_symlinked_images_are_rejected_when_root_is_available(tmp_path: Path) -> None:
    root = tmp_path / "cards"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not really an image")
    (root / "link.png").symlink_to(outside)
    card = parse_snippet(root, "question\n?\n![secret](link.png)\n").cards[0]

    rendered = render_card(card, root)

    assert 'class="invalid-image"' in rendered.back_html
    assert "/media/" not in rendered.back_html


def test_raw_html_is_escaped_and_pygments_themes_are_available(
    tmp_path: Path,
) -> None:
    card = parse_snippet(tmp_path, "<script>alert(1)</script>\n?\nanswer\n").cards[0]

    rendered = render_card(card)

    assert "&lt;script&gt;" in rendered.front_html
    assert pygments_css("light") != pygments_css("dark")
