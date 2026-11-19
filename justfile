cards_dir := env("RECALL_CARDS_DIR", "examples/cards")
git_sync := env("RECALL_GIT_SYNC", "0")

# Start the web app (defaults to the example cards, without git sync)
serve:
    RECALL_CARDS_DIR={{ quote(cards_dir) }} RECALL_GIT_SYNC={{ git_sync }} uv run recall serve

# Run the tests; extra arguments are passed to pytest
test *args:
    uv run pytest {{ args }}
