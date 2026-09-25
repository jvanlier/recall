#!/usr/bin/env bash
set -euo pipefail

ROUNDS=12
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for ((i=1; i<=ROUNDS; i++)); do
  echo "=== Round $i of $ROUNDS ==="
  started=$SECONDS
  status=0
  pibox --with web,browser --mode json \
    "/skill:implement-autonomous Take exactly one next available open issue from https://github.com/jvanlier/recall/issues and implement it. If you need the recall-cards repo, clone it from https://github.com/jvanlier/recall-cards" \
    | python3 "$SCRIPT_DIR/loop_output.py" || status=$?
  printf '\n=== Round %d elapsed: %ds (exit %d) ===\n' "$i" "$((SECONDS - started))" "$status"
  if ((status != 0)); then exit "$status"; fi
done
