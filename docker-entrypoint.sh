#!/bin/sh
set -eu

: "${RECALL_CARDS_DIR:=/cards}"

# Keep git's global config outside the image and writable when the container
# user is changed to match the owner of a bind-mounted cards repository.
export HOME=/tmp/recall-home
mkdir -p "$HOME"
git config --global --add safe.directory "$RECALL_CARDS_DIR"

exec "$@"
