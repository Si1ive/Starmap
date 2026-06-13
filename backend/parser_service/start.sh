#!/usr/bin/env sh
set -eu

HOST="${PARSER_SERVICE_HOST:-0.0.0.0}"
PORT="${PARSER_SERVICE_PORT:-8090}"
DEFAULT_PARSER="${PDF_PARSER_SERVICE_DEFAULT:-mineru}"

echo "[parser-service] starting on ${HOST}:${PORT} with default parser=${DEFAULT_PARSER}"

exec uvicorn parser_service.main:app --host "${HOST}" --port "${PORT}"
