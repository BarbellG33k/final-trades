#!/bin/sh
# Container entrypoint: apply migrations (idempotent), then dispatch command.
set -e

CMD="${1:-serve}"
shift || true

case "$CMD" in
  serve)
    final-trades migrate
    exec final-trades serve
    ;;
  collect)
    final-trades migrate
    exec final-trades collect --once
    ;;
  backfill)
    final-trades migrate
    exec final-trades backfill "$@"
    ;;
  performance)
    final-trades migrate
    exec final-trades performance
    ;;
  coverage-report)
    final-trades migrate
    exec final-trades coverage-report
    ;;
  shell)
    exec /bin/sh
    ;;
  *)
    exec final-trades "$CMD" "$@"
    ;;
esac
