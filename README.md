# Total Recall

Total Recall is a personal spaced repetition web app for reviewing markdown cards.
See the [design document](docs/design.md) for the project plan and card format.
The [cards repository guide](docs/cards-repo.md) explains how to set up a
private repository for your decks. The [deployment guide](docs/deployment.md)
explains how to run the app on a home server.

## Run the web app

Start the server on the example cards, with git sync off:

```sh
just serve
```

To use your own cards, set `RECALL_CARDS_DIR` to a cards repository, for
example `RECALL_CARDS_DIR=~/cards RECALL_GIT_SYNC=1 just serve`.

`PORT` defaults to `8000` and `HOST` defaults to `0.0.0.0`. Reviews are stored
in a SQLite database at `RECALL_DB`, which defaults to `.recall/reviews.db` in
the cards repository. The app pulls card edits with
`git pull --ff-only` on deck loads unless `RECALL_GIT_SYNC=0`; `just serve`
sets that by default.

The app vendors htmx **2.0.7** and KaTeX **0.16.22** in
`src/recall/static/`; it does not load front-end dependencies from a CDN.

## Development

The project uses [uv](https://docs.astral.sh/uv/) with Python 3.14:

```sh
uv sync
prek install --hook-type pre-commit --hook-type pre-push
```

Run the tests and all checks with:

```sh
just test
prek run --all-files
```

Arguments after `just test` are passed to pytest, as in `just test -k store`.
