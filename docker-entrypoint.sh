#!/bin/sh
set -eu

: "${RECALL_CARDS_DIR:=/cards}"
: "${GIT_AUTHOR_NAME:?GIT_AUTHOR_NAME is required}"
: "${GIT_AUTHOR_EMAIL:?GIT_AUTHOR_EMAIL is required}"
: "${GIT_COMMITTER_NAME:?GIT_COMMITTER_NAME is required}"
: "${GIT_COMMITTER_EMAIL:?GIT_COMMITTER_EMAIL is required}"

# Keep git's global config outside the image and writable when the container
# user is changed to match the owner of a bind-mounted cards repository.
export HOME=/tmp/recall-home
mkdir -p "$HOME"
git config --global --add safe.directory "$RECALL_CARDS_DIR"
git config --global user.name "$GIT_AUTHOR_NAME"
git config --global user.email "$GIT_AUTHOR_EMAIL"

exec "$@"
