# recall

`recall` is a personal spaced repetition web app for reviewing markdown cards.
See the [design document](docs/design.md) for the project plan and card format.

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
