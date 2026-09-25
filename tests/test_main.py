"""Tests for the FastAPI review application."""

from pathlib import Path

from fastapi.testclient import TestClient

from recall.main import Settings, create_app
from recall.parser import load_repo


def app_for(tmp_path: Path, source: str = "Question::Answer\n"):
    (tmp_path / "Deck.md").write_text(source, encoding="utf-8")
    return create_app(Settings(tmp_path))


def test_deck_list_counts_and_healthz(tmp_path: Path) -> None:
    with TestClient(app_for(tmp_path)) as client:
        assert client.get("/healthz").status_code == 200
        response = client.get("/")

    assert response.status_code == 200
    assert "Deck" in response.text
    assert ">0</strong> due" in response.text
    assert ">1</strong> new" in response.text


def test_review_cycle_appends_to_log(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    card = load_repo(tmp_path).cards[0]

    with TestClient(app) as client:
        response = client.get("/review/Deck")
        assert response.status_code == 200
        assert "Question" in response.text
        response = client.post(
            "/review/rate",
            data={"card": card.id, "scope": "Deck", "rating": "3", "ms": "42"},
        )
        assert response.status_code == 200
        response = client.post("/review/done", data={"scope": "Deck"})
        assert "Session complete" in response.text

    assert '"rating": 3' in (tmp_path / ".recall" / "reviews.jsonl").read_text(
        encoding="utf-8"
    )


def test_undo_removes_last_review_and_shows_card_again(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    card = load_repo(tmp_path).cards[0]

    with TestClient(app) as client:
        client.get("/review/Deck")
        client.post(
            "/review/rate",
            data={"card": card.id, "scope": "Deck", "rating": "3", "ms": "42"},
        )
        response = client.post("/review/undo", data={"scope": "Deck"})

    assert response.status_code == 200
    assert "Question" in response.text
    assert not (tmp_path / ".recall" / "reviews.jsonl").read_text(encoding="utf-8")


def test_invalid_card_and_rating_are_rejected(tmp_path: Path) -> None:
    with TestClient(app_for(tmp_path)) as client:
        assert (
            client.post(
                "/review/rate",
                data={"card": "missing", "scope": "Deck", "rating": "3", "ms": "0"},
            ).status_code
            == 400
        )
        card = load_repo(tmp_path).cards[0]
        assert (
            client.post(
                "/review/rate",
                data={"card": card.id, "scope": "Deck", "rating": "5", "ms": "0"},
            ).status_code
            == 400
        )


def test_media_validation(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "present.png").write_bytes(b"png")
    (tmp_path / "notes.txt").write_text("not media", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.png").write_bytes(b"secret")
    outside = tmp_path.parent / "recall-media-outside.png"
    outside.write_bytes(b"outside")
    (tmp_path / "escape.png").symlink_to(outside)

    try:
        with TestClient(app_for(tmp_path)) as client:
            assert client.get("/media/images/present.png").status_code == 200
            assert client.get("/media/notes.txt").status_code == 404
            assert client.get("/media/.hidden/secret.png").status_code == 404
            assert client.get("/media/escape.png").status_code == 404
    finally:
        outside.unlink()
