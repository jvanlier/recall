# recall

`recall` is a personal spaced repetition web app for reviewing markdown cards.
See the [design document](docs/design.md) for the project plan and card format.
The [cards repository guide](docs/cards-repo.md) explains how to set up a
private repository for your decks.

## Run the web app

Set `RECALL_CARDS_DIR` to a cards repository and start the server:

```sh
RECALL_CARDS_DIR=examples/cards uv run recall serve
```

`PORT` defaults to `8000` and `HOST` defaults to `0.0.0.0`. The review log is
stored at `.recall/reviews.jsonl` in the cards repository. Git sync runs on deck
loads, when a session ends, and in the background; set `RECALL_GIT_SYNC=0` to
disable it for local development.

The app vendors htmx **2.0.7** and KaTeX **0.16.22** in
`src/recall/static/`; it does not load front-end dependencies from a CDN.

## Development

The project uses [uv](https://docs.astral.sh/uv/) with Python 3.14:

```sh
uv sync
uv run prek install --hook-type pre-commit --hook-type pre-push
```

Run the tests and all checks with:

```sh
uv run pytest
uv run prek run --all-files
```
