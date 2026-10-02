#!/bin/zsh

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

./Roads-Beneath-the-Shadow "$@"
STATUS=$?

if [[ $STATUS -ne 0 ]]; then
  echo
  echo "The game stopped with an error (code $STATUS)."
  read -r "?Press Return to close..."
fi

exit $STATUS
