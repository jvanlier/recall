"""Tests for the FastAPI review application."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from recall.main import Settings, create_app
from recall.parser import load_repo


def app_for(tmp_path: Path, source: str = "Question::Answer\n"):
    (tmp_path / "Deck.md").write_text(source, encoding="utf-8")
    return create_app(Settings(tmp_path))


def presentation_token(html: str) -> str:
    match = re.search(r'name="presentation" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


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
            data={
                "card": card.id,
                "scope": "Deck",
                "rating": "3",
                "ms": "42",
                "presentation": presentation_token(response.text),
            },
        )
        assert response.status_code == 200
        assert 'data-reviewed="1"' in response.text
        response = client.post("/review/done", data={"scope": "Deck"})
        assert "Session complete" in response.text
        assert "Undo last rating" in response.text

    assert '"rating": 3' in (tmp_path / ".recall" / "reviews.jsonl").read_text(
        encoding="utf-8"
    )


def test_stale_rating_is_rejected_and_new_session_resets_count(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    card = load_repo(tmp_path).cards[0]

    with TestClient(app) as client:
        response = client.get("/review/Deck")
        payload = {
            "card": card.id,
            "scope": "Deck",
            "rating": "3",
            "ms": "42",
            "presentation": presentation_token(response.text),
        }
        assert client.post("/review/rate", data=payload).status_code == 200
        assert client.post("/review/rate", data=payload).status_code == 400
        response = client.get("/review/Deck")

    assert "0 reviewed" in response.text


def test_undo_removes_last_review_and_shows_card_again(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    card = load_repo(tmp_path).cards[0]

    with TestClient(app) as client:
        response = client.get("/review/Deck")
        client.post(
            "/review/rate",
            data={
                "card": card.id,
                "scope": "Deck",
                "rating": "3",
                "ms": "42",
                "presentation": presentation_token(response.text),
            },
        )
        response = client.post("/review/undo", data={"scope": "Deck"})

    assert response.status_code == 200
    assert "Question" in response.text
    assert not (tmp_path / ".recall" / "reviews.jsonl").read_text(encoding="utf-8")


def test_deck_links_encode_url_delimiters(tmp_path: Path) -> None:
    (tmp_path / "C#.md").write_text("Question one::Answer one\n", encoding="utf-8")
    (tmp_path / "Folder?Name.md").write_text(
        "Question two::Answer two\n", encoding="utf-8"
    )

    with TestClient(create_app(Settings(tmp_path))) as client:
        response = client.get("/")
        assert 'href="/review/C%23"' in response.text
        assert 'href="/review/Folder%3FName"' in response.text
        assert client.get("/review/C%23").status_code == 200
        assert client.get("/review/Folder%3FName").status_code == 200


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
    payload = tmp_path / "payload.html"
    payload.write_text("<script>alert(1)</script>", encoding="utf-8")
    (tmp_path / "escape.png").symlink_to(outside)
    (tmp_path / "active.png").symlink_to(payload)
    (tmp_path / "active.svg").write_text(
        "<svg><script>alert(1)</script></svg>", encoding="utf-8"
    )

    try:
        with TestClient(app_for(tmp_path)) as client:
            assert client.get("/media/images/present.png").status_code == 200
            assert client.get("/media/notes.txt").status_code == 404
            assert client.get("/media/.hidden/secret.png").status_code == 404
            assert client.get("/media/escape.png").status_code == 404
            assert client.get("/media/active.png").status_code == 404
            svg = client.get("/media/active.svg")
            assert svg.status_code == 200
            assert svg.headers["content-security-policy"] == "sandbox"
            assert svg.headers["x-content-type-options"] == "nosniff"
    finally:
        outside.unlink()
