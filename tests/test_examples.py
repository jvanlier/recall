from pathlib import Path

from recall.check import check_repo

EXAMPLES = Path(__file__).parents[1] / "examples" / "cards"


def test_example_cards_parse_without_warnings() -> None:
    result = check_repo(EXAMPLES)

    assert result.warnings == []
    assert result.decks == ["Foundations", "Languages/Spanish"]
    assert any(card.hidden for card in result.cards)
    assert any(card.pinned_id == "stable-card-id" for card in result.cards)
    assert any(card.pinned_id == "spanish-cat" for card in result.cards)
